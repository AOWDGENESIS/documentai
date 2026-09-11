# -*- coding: utf-8 -*-
"""Grafische Oberfläche von DocumentAI (tkinter, deutsch, lokal).

Aufbau:
┌────────────────────────────────────────────────────────────┐
│ Werkzeugleiste                                             │
├───────────────┬────────────────────────┬───────────────────┤
│ Seitenliste   │   PDF-Viewer (Canvas)  │ Eigenschaften /   │
│ + Felder      │   Zoom, Suche, Klick   │ Analyse, Felder,  │
│               │   auf Element          │ Validierung, …    │
├───────────────┴────────────────────────┴───────────────────┤
│ Status: ✓ Analyse ✓ Felder ⚠ Hinweise ✓ PDF gültig         │
└────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from collections import deque
from tkinter import filedialog, messagebox, simpledialog, ttk

from .. import __version__ as APP_VERSION
from .. import config as config_mod
from ..bilder import symbole
from .theme import farben, norm as thema_norm
from ..core import audit as audit_mod
from ..core.errors import PasswordRequiredError
from ..core.models import FieldModel, PageModel, Rect4
from ..engines import annotate
from ..engines.exporter import ExportEngine
from ..engines.signatures import SignatureAnalyzer
from ..services import profile as profile_service
from ..services import recent
from ..services.analysis import AnalysisService
from ..util import write_error_report

try:
    from PIL import Image, ImageTk
    PIL_OK = True
except Exception:
    PIL_OK = False


def safe(fn):
    """Fehler niemals abstürzen lassen – immer Bericht + Dialog."""
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:
            path = write_error_report(exc, action=fn.__name__,
                                      component="gui")
            try:
                messagebox.showerror(
                    "DocumentAI – Fehler",
                    f"{getattr(exc, 'message', exc)}\n\n"
                    f"Fehlerbericht: {path}")
            except Exception:
                raise
    return wrapper


class DocumentView(ttk.Frame):
    """Ein geöffnetes Dokument (Tab) mit Viewer + Inspector."""

    def __init__(self, master, app, path):
        super().__init__(master)
        self.app = app
        self.service = app.service
        self.path = path
        self.model = None
        self.session = None
        self.engine = None
        self.current_page = 0
        self.zoom = 1.0
        self.show_fields = tk.BooleanVar(value=True)
        self.photo = None
        self.field_items: dict[str, int] = {}      # canvas-id -> field-id
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.search_hits: list = []
        # PDF-Werkzeuge (Acrobat-inspiriert): Interaktionsmodus der Ansicht
        self.mode = "normal"      # normal|highlight|strikeout|sticky|ink|redact
        self.redact_rects: list[tuple[int, tuple]] = []   # (Seite, PDF-Rect)
        self._rubber = None       # Gummiband-Rechteck (Canvas-ID)
        self._ink_pts: list[tuple[float, float]] = []
        self._ink_item = None
        # Acrobat-Bedienung: Schiene + Panels + Thumbnails + Navbar
        self._rail_active = "werkzeuge"
        self._thumb_photos: list = []
        self._thumb_ids: dict[int, int] = {}
        self._build()
        self._open(path)

    # ------------------------------------------------------------ Aufbau
    def _build(self):
        außen = ttk.Frame(self, style="View.TFrame")
        außen.pack(fill=tk.BOTH, expand=True)

        # ---------- Icon-Schiene links (Acrobat-Navigationsschiene) ----
        rail = tk.Frame(außen, background="#26282e", width=52)
        rail.pack(side=tk.LEFT, fill=tk.Y)
        rail.pack_propagate(False)
        self.rail = rail
        self._rail_buttons: dict[str, tk.Button] = {}
        schiene = (
            ("werkzeuge", "⚒", "Werkzeuge"),
            ("seiten", "▤", "Seiten"),
            ("lesezeichen", "🔖", "Zeichen"),
            ("kommentare", "💬", "Komment."),
            ("anhaenge", "📎", "Anlagen"),
        )
        for key, zeichen, kurz in schiene:
            kasten = tk.Frame(rail, background="#26282e")
            kasten.pack(fill=tk.X, pady=(2, 0))
            b = tk.Button(kasten, text=zeichen, bd=0, relief=tk.FLAT,
                          background="#26282e", foreground="#c9cdd4",
                          activebackground="#1473e6", activeforeground="white",
                          font=("", 15), padx=2, pady=1,
                          command=lambda k=key: self._panel_zeigen(k))
            b.pack()
            tk.Label(kasten, text=kurz, background="#26282e",
                     foreground="#8b909a", font=("", 7)).pack()
            self._rail_buttons[key] = b

        # ---------- Panel links (Inhalt je Schienen-Knopf) -------------
        self.panel = tk.Frame(außen, background="#ffffff", width=236,
                              highlightbackground="#d9dce1",
                              highlightthickness=1)
        self.panel.pack(side=tk.LEFT, fill=tk.Y)
        self.panel.pack_propagate(False)

        # unsichtbare Datenliste (Seiten-Auswahlmodell, stabil für
        # Skripte/Tests); die Thumbnail-Ansicht arbeitet darauf.
        # Wichtig: NICHT im Panel selbst – der Panel-Wechsel räumt auf.
        self.page_list = tk.Listbox(außen, exportselection=False,
                                    width=14, height=2)
        # Acrobat-Standard: beim Öffnen sofort die SEITEN-Miniaturen
        # zeigen (Nutzerwunsch: „Seiten müssen immer sauber als
        # Miniaturansicht zu erkennen sein“). Werkzeuge über die
        # Schiene bzw. die Kopfleisten-Knöpfe.
        self._panel_zeigen("seiten")

        # ---------- Mitte: Navigationsleiste + Canvas ------------------
        mitte = ttk.Frame(außen, style="Mitte.TFrame")
        mitte.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        navbar = tk.Frame(mitte, background="#ffffff",
                          highlightbackground="#d9dce1", highlightthickness=1)
        navbar.pack(side=tk.TOP, fill=tk.X)
        self.navbar = navbar
        tk.Button(navbar, text="◀", bd=0, relief=tk.FLAT,
                  background="#ffffff", foreground="#1f2430",
                  activebackground="#eef1f5", padx=6, pady=3,
                  command=self._seite_zurueck).pack(side=tk.LEFT,
                                                    padx=(6, 0))
        self.nav_seite = tk.Entry(navbar, width=5, justify=tk.CENTER,
                                  relief=tk.FLAT, background="#f1f3f6")
        self.nav_seite.pack(side=tk.LEFT, padx=2, pady=3)
        self.nav_seite.bind("<Return>", self._seite_gehe)
        self.nav_von = tk.Label(navbar, background="#ffffff",
                                foreground="#5a6472", text="von 1")
        self.nav_von.pack(side=tk.LEFT, padx=(0, 8))
        tk.Button(navbar, text="▶", bd=0, relief=tk.FLAT,
                  background="#ffffff", foreground="#1f2430",
                  activebackground="#eef1f5", padx=6, pady=3,
                  command=self._seite_vor).pack(side=tk.LEFT)
        tk.Frame(navbar, width=1, background="#d9dce1"
                  ).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        tk.Button(navbar, text="−", bd=0, relief=tk.FLAT, background="#ffffff",
                  foreground="#1f2430", activebackground="#eef1f5", padx=8,
                  pady=3, command=lambda: self.zoom_by(1 / 1.25)
                  ).pack(side=tk.LEFT)
        self.nav_zoom = tk.Label(navbar, text="100 %", background="#ffffff",
                                 foreground="#1f2430", width=5)
        self.nav_zoom.pack(side=tk.LEFT)
        tk.Button(navbar, text="＋", bd=0, relief=tk.FLAT, background="#ffffff",
                  foreground="#1f2430", activebackground="#eef1f5", padx=6,
                  pady=3, command=lambda: self.zoom_by(1.25)
                  ).pack(side=tk.LEFT)
        tk.Frame(navbar, width=1, background="#d9dce1"
                  ).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        tk.Button(navbar, text="↻", bd=0, relief=tk.FLAT, background="#ffffff",
                  foreground="#1f2430", activebackground="#eef1f5", padx=8,
                  pady=3, font=("", 12), command=self._rotate_page
                  ).pack(side=tk.LEFT)
        tk.Button(navbar, text="◧", bd=0, relief=tk.FLAT, background="#ffffff",
                  foreground="#1f2430", activebackground="#eef1f5", padx=8,
                  pady=3, font=("", 12), command=self._fit_breite
                  ).pack(side=tk.LEFT)
        ttk.Checkbutton(navbar, text="Felder", style="Nav.TCheckbutton",
                        variable=self.show_fields,
                        command=self._render_page).pack(side=tk.LEFT,
                                                        padx=8)
        tk.Frame(navbar, width=1, background="#d9dce1"
                  ).pack(side=tk.LEFT, fill=tk.Y, padx=6)
        # Hell/Dunkel-Umschalter (Nutzerwunsch 10.09.2026)
        self.app._thema_knopf = tk.Button(
            navbar, bd=0, relief=tk.FLAT, background="#ffffff",
            foreground="#1f2430", activebackground="#eef1f5", padx=8,
            pady=3, font=("", 13), command=self.app._thema_wechseln)
        self.app._thema_knopf.pack(side=tk.LEFT)
        self.app._thema_symbol_setzen()

        # Werkzeug-Banner über dem Seitenbereich: erscheint nur, wenn
        # ein Werkzeug aktiv ist (Pack-Position über after=navbar
        # stabil gehalten)
        self.werkzeug_banner = tk.Frame(mitte, background="#fff8e1",
                                        highlightthickness=0)
        self._banner_aktualisieren()

        center = ttk.Frame(mitte, style="Mitte.TFrame")
        center.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(
            center, background=farben(
                getattr(self.app, "thema_modus", "hell"))["canvas"],
            highlightthickness=0, width=560)
        vbar = ttk.Scrollbar(center, orient=tk.VERTICAL,
                             command=self.canvas.yview)
        hbar = ttk.Scrollbar(center, orient=tk.HORIZONTAL,
                             command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set,
                              xscrollcommand=hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        center.rowconfigure(0, weight=1)
        center.columnconfigure(0, weight=1)
        self.canvas.bind("<Button-1>", self._on_canvas_click)
        self.canvas.bind("<B1-Motion>", self._on_canvas_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_canvas_release)
        self.canvas.bind("<Escape>", lambda e: self.set_mode("normal"))
        self.canvas.bind("<Double-Button-1>",
                         self._on_canvas_doppelklick)
        self.canvas.bind_all("<Control-d>",
                             lambda e: self.app._current_eigenschaften())
        # Mausrad: Windows/macOS melden <MouseWheel> (+/-120), Linux
        # Button-4/5 - ein Handler für alles (Scrollen + Blättern)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", self._on_wheel)
        self.canvas.bind("<Button-5>", self._on_wheel)

        # ---------- rechts: Eigenschaften + Tabs ----------------------
        right = ttk.Frame(außen, width=430, style="Seite.TFrame")
        right.pack(side=tk.RIGHT, fill=tk.Y, padx=(4, 0))
        self.inspector = ttk.LabelFrame(right, text="Eigenschaften")
        self.inspector_prop = {}
        for i, key in enumerate(("Element", "Typ", "Wert", "Quelle",
                                 "Konfidenz", "Status")):
            ttk.Label(self.inspector, text=key + ":").grid(
                row=i, column=0, sticky=tk.W, padx=6, pady=1)
            var = tk.StringVar(value="–")
            ttk.Label(self.inspector, textvariable=var, wraplength=230
                      ).grid(row=i, column=1, sticky=tk.W, padx=4, pady=1)
            self.inspector_prop[key] = var
        self.btn_edit = ttk.Button(self.inspector, text="Bearbeiten",
                                   command=self._edit_selected,
                                   state=tk.DISABLED)
        self.btn_edit.grid(row=6, column=0, columnspan=2, sticky=tk.W,
                           padx=6, pady=4)
        self.inspector.pack(fill=tk.X, padx=4, pady=4)

        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Analyse-Tab
        self.txt_analysis = tk.Text(self.tabs, width=44, wrap=tk.WORD,
                                    state=tk.DISABLED, height=8)
        self.tabs.add(self.txt_analysis, text="Analyse")

        # Felder-Tab
        frame_f = ttk.Frame(self.tabs)
        cols = ("Beschriftung", "Typ", "Wert", "Pflicht")
        self.tree_fields = ttk.Treeview(frame_f, columns=cols, show="headings")
        for col, width in zip(cols, (140, 70, 150, 40)):
            self.tree_fields.heading(col, text=col)
            self.tree_fields.column(col, width=width)
        self.tree_fields.pack(fill=tk.BOTH, expand=True)
        self.tree_fields.bind("<Double-1>", lambda e: self._edit_selected())
        self.tree_fields.bind("<<TreeviewSelect>>", self._on_field_select)
        self.tree_fields.bind("<Delete>",
                              lambda e: self._feld_loeschen_gewaehlt())
        fuss_f = ttk.Frame(frame_f)
        fuss_f.pack(fill=tk.X, pady=2)
        ttk.Button(fuss_f, text="Feld entfernen",
                   style="Werk.TButton",
                   command=self._feld_loeschen_gewaehlt
                   ).pack(side=tk.LEFT, padx=2)
        ttk.Label(fuss_f, text="Entf-Taste wirkt auch (nur eigene/erkannte "
                  "Felder, keine AcroForm-Felder).",
                  foreground="#5a6472").pack(side=tk.LEFT, padx=6)
        self.tabs.add(frame_f, text="Felder")

        # Validierungs-Tab
        frame_v = ttk.Frame(self.tabs)
        vcols = ("!", "Meldung", "Feld")
        self.tree_issues = ttk.Treeview(frame_v, columns=vcols,
                                        show="headings")
        self.tree_issues.heading("!", text="")
        self.tree_issues.column("!", width=26)
        self.tree_issues.heading("Meldung", text="Meldung")
        self.tree_issues.column("Meldung", width=260)
        self.tree_issues.heading("Feld", text="Feld")
        self.tree_issues.column("Feld", width=90)
        self.tree_issues.pack(fill=tk.BOTH, expand=True)
        bar = ttk.Frame(frame_v)
        ttk.Button(bar, text="Problem anzeigen",
                   command=self._show_issue).pack(side=tk.LEFT, padx=3,
                                                  pady=3)
        ttk.Button(bar, text="Automatisch korrigieren",
                   command=self._autofix_issue).pack(side=tk.LEFT, padx=3)
        bar.pack(fill=tk.X)
        self.tabs.add(frame_v, text="Validierung")

        # Daten-Tab (Profil)
        frame_d = ttk.Frame(self.tabs)
        self.profile_vars: dict[str, tk.StringVar] = {}
        from ..services.profile import PROFILE_TEMPLATE
        for i, (key, value) in enumerate(PROFILE_TEMPLATE.items()):
            ttk.Label(frame_d, text=key.replace("_", " ").capitalize()
                      ).grid(row=i // 2, column=(i % 2) * 2, sticky=tk.W,
                             padx=4, pady=2)
            var = tk.StringVar(value=value)
            entry = ttk.Entry(frame_d, textvariable=var, width=16)
            entry.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=4, pady=2)
            self.profile_vars[key] = var
        bar_d = ttk.Frame(frame_d)
        ttk.Button(bar_d, text="Profil speichern",
                   command=self._save_profile).pack(side=tk.LEFT, padx=3,
                                                    pady=4)
        ttk.Button(bar_d, text="Profil importieren…",
                   command=self._import_profile).pack(side=tk.LEFT)
        bar_d.grid(row=10, column=0, columnspan=4)
        self.tabs.add(frame_d, text="Daten")

        # Audit-Tab
        self.txt_audit = tk.Text(self.tabs, width=44, wrap=tk.WORD,
                                 state=tk.DISABLED)
        self.tabs.add(self.txt_audit, text="Audit")

        # Datenbank-Tab (verschlüsselter Datentresor, app-global geteilt)
        from .vault_panel import VaultPanel
        self.vault_panel = VaultPanel(self.tabs, self.app, self)
        self.tabs.add(self.vault_panel, text="Tresor 🔒")

        # Vergleich-Tab
        frame_c = ttk.Frame(self.tabs)
        ttk.Button(frame_c, text="Version zum Vergleich wählen…",
                   command=self._compare).pack(pady=6)
        self.txt_compare = tk.Text(frame_c, wrap=tk.WORD, state=tk.DISABLED)
        self.txt_compare.pack(fill=tk.BOTH, expand=True)
        self.tabs.add(frame_c, text="Vergleich")

        right.pack_propagate(False)

    # --------------------------------------------------------- Öffnen
    @safe
    def _open(self, path: str) -> None:
        password = None
        for _ in range(3):
            try:
                self.model, self.session, self.engine = \
                    self.service.open_document(path, password)
                break
            except PasswordRequiredError:
                password = simpledialog.askstring(
                    "Passwort erforderlich",
                    "Dieses Dokument ist passwortgeschützt.\n\nBitte das "
                    "erforderliche Passwort eingeben\n(der Schutz wird "
                    "niemals umgangen):", show="*")
                if password is None:
                    self.destroy()
                    return
        else:
            messagebox.showerror("DocumentAI", "Passwort nicht korrekt.")
            self.destroy()
            return
        self.app.set_status("Analysiere Dokument …")
        self.app.start_task(
            lambda: self.service.analyze(self.model, self.session,
                                         self.engine,
                                         progress=self.app.progress_cb),
            self._after_analyze)

    def _after_analyze(self, result=None) -> None:
        if not self.model.fields and not getattr(self, "_hint_felder", False):
            self._hint_felder = True       # nur einmal pro Dokument melden
            if any(p.needs_ocr for p in self.model.pages):
                self.app.set_status(
                    "Hinweis: keine Felder erkannt – OCR prüfen "
                    "(Selbstdiagnose) oder Felder selbst markieren.")
        self.page_list.delete(0, tk.END)
        for p in self.model.pages:
            self.page_list.insert(tk.END, f"Seite {p.number + 1}")
        if self.model.signature_info.get("vorhanden"):
            antwort = messagebox.askyesno(
                "Digitale Signatur erkannt",
                "Dieses Dokument enthält eine digitale Signatur.\n\n"
                "Eine Änderung kann die bestehende Signatur ungültig "
                "machen.\n\nWeiterarbeiten und später eine NEUE bearbeitete "
                "Version erstellen?\n(Das Original bleibt in jedem Fall "
                "unverändert.)",
                icon="warning")
            if not antwort:
                self.app.set_status("Signiertes Dokument – nur Ansicht.")
        self.refresh_all()
        self._render_page()
        seite = getattr(self, "_neu_einladen_seite", None)
        if seite is not None:
            del self._neu_einladen_seite
            if self.model.pages:
                self._seite_waehlen(min(seite, len(self.model.pages) - 1))
        self.app.set_status("Bereit.")

    # ------------------------------------------------ Neu einlesen
    @safe
    def neu_einlesen(self) -> None:
        """Dokument neu einlesen: Datei frisch von der Platte laden und
        komplett neu analysieren (z. B. nach äußeren Änderungen oder um
        die Felderkennung erneut laufen zu lassen)."""
        if self.session is None or self.model is None:
            self.app.set_status("Kein Dokument offen.")
            return
        # Die Sitzung spiegelt ggf. bereits eine gespeicherte Version
        # (nach „Neue Version erstellen“) – dann genau DIE neu laden,
        # nicht das Original (Stand vor den Änderungen).
        pfad = getattr(self.session, "quelle", None) or self.model.path
        passwort = getattr(self.session, "password", "") or None
        if self.model.edited:
            ok = messagebox.askyesno(
                "Dokument neu einlesen",
                "Die aktuellen Änderungen sind noch nicht als neue Version "
                "gespeichert.\n\nBeim Neu einlesen gehen sie verloren "
                "(das Original auf der Platte bleibt unberührt).\n\n"
                "Trotzdem neu einlesen?",
                icon="warning")
            if not ok:
                self.app.set_status("Neu einlesen abgebrochen.")
                return
        self._neu_einladen_seite = self.current_page
        ur_pfad = self.model.path          # Versionierungs-Anker (Original)
        try:
            self.session.doc.close()
        except Exception:
            pass
        try:
            self.model, self.session, self.engine = \
                self.service.open_document(pfad, passwort)
        except Exception:
            messagebox.showerror(
                "Dokument neu einlesen",
                "Die Datei konnte nicht neu gelesen werden:\n"
                + str(pfad))
            self.destroy()
            return
        # Versionsketten bleiben am Original verankert (Dokument_v3_
        # bearbeitet.pdf statt Dokument_v2_bearbeitet_v2_bearbeitet.pdf)
        self.model.path = ur_pfad
        try:
            from ..core.models import file_sha256
            if os.path.exists(ur_pfad):
                self.model.sha256 = file_sha256(ur_pfad)
        except Exception:
            pass
        self._hint_felder = False
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.app.set_status("Lese Dokument neu ein …")
        self.app.start_task(
            lambda: self.service.analyze(self.model, self.session,
                                         self.engine,
                                         progress=self.app.progress_cb),
            self._after_analyze)

    def _feld_loeschen_gewaehlt(self) -> None:
        """Entfernt das in der Felder-Liste gewählte Feld."""
        auswahl = self.tree_fields.selection()
        if not auswahl or self.model is None:
            return
        f = self.model.field_by_id(auswahl[0])
        if f is None:
            return
        if f.source == "acroform":
            self.app.set_status("AcroForm-Felder gehören zum Dokument "
                                "und können hier nicht entfernt werden.")
            return
        if self.feld_entfernen(f):
            self.refresh_all()
            self._render_page()
            self.app.set_status(f"✓ Feld entfernt: {f.label or f.name}")

    def _unterschrift_einfuegen(self, rect, bild_pfad: str) -> None:
        """Fügt ein Unterschrifts-Bild im Rechteck ein (Proportionen
        bleiben erhalten – wie ein echtes Stempel-Bild)."""
        import os as _os
        try:
            annotate.bild_einfuegen(self.session, self.current_page,
                                    rect, bild_pfad)
            self.model.edited = True
            audit_mod.log(self.model, "Unterschrift eingefügt",
                          _os.path.basename(bild_pfad)[:40])
            self.app.set_status("✓ Unterschrift eingefügt – „Neue "
                                "Version“ speichert sie.")
        except Exception as exc:                    # noqa: BLE001
            messagebox.showerror("Unterschrift", str(exc))

    # ------------------------------------------------ Formular-Werkzeuge
    def textfeld_einfuegen(self, rect, seite: int | None = None):
        """Setzt ein manuelles Textfeld (Acrobat „Textfeld hinzufügen“).
        rect: PDF-Rechteck (pymupdf.Rect oder Rect4). Klick ohne Zug
        ergibt ein Standardfeld (180×16 pt)."""
        if self.model is None:
            return None
        # WICHTIG: Der GUI-Weg liefert ein TUPLE (x0, y0, x1, y1) –
        # Tupel haben KEINE Attribute. Der alte Code crashete hier mit
        # "'tuple' object has no attribute 'x'" und zeigte nur einen
        # Fehlerdialog: Das Werkzeug wirkete „kaputt“ (Nutzerfund
        # 09.09.2026). Reihenfolge: Tuple (iterierbar) → pymupdf.Rect
        # → Rect4.
        try:
            x0, y0, x1, y1 = (float(v) for v in rect)   # Tuple/Liste
        except (TypeError, ValueError):
            try:
                x0, y0 = float(rect.x0), float(rect.y0)  # pymupdf.Rect
                x1, y1 = float(rect.x1), float(rect.y1)
            except AttributeError:                       # Rect4
                x0, y0 = rect.x, rect.y
                x1, y1 = rect.x + rect.width, rect.y + rect.height
        if x1 - x0 < 6 and y1 - y0 < 6:            # nur geklickt
            # Acrobat-Auto-Platzierung: Klick neben/unter ein Label →
            # Feld sitzt exakt auf der nächsten Formular-Linie („just
            # above the baseline“), nicht irgendwo im Leeren.
            x0, x1, y0, y1 = self._klick_auf_linie(x0, y0)
            if x1 - x0 < 6:
                x1, y1 = x0 + 180, y0 + 16
        x1, y1 = max(x1, x0 + 24), max(y1, y0 + 12)
        pno = self.current_page if seite is None else seite
        n = 1 + sum(1 for f in self.model.fields
                    if f.source == "manuell")
        slug = f"textfeld_{n}"
        f = FieldModel(
            id=f"manuell::{pno}::{slug}", name=slug,
            label=f"Textfeld {n}", field_type="text",
            page=pno,
            rect=Rect4(x0, y0, x1 - x0, y1 - y0),
            source="manuell", confidence=1.0)
        for other in self.model.fields:
            if other.page == pno and other.rect and not (
                    x1 < other.rect.x
                    or other.rect.x + other.rect.width < x0
                    or y1 < other.rect.y
                    or other.rect.y + other.rect.height < y0):
                # Acrobat: Klick auf eine Linie, auf der schon ein Feld
                # liegt, ÖFFNET dieses Feld (siehe Aufrufer).
                self._overlap_feld = other
                self.app.set_status(
                    "Hier liegt schon ein Feld – es wurde zum "
                    "Ausfüllen geöffnet.")
                return None
        self.model.fields.append(f)
        audit_mod.log(self.model, "Textfeld eingefügt",
                      f"Seite {pno + 1}, {f.label}")
        return f

    def feld_entfernen(self, f: FieldModel) -> bool:
        """Entfernt ein manuell/visuell erkanntes Feld (AcroForm-Felder
        gehören zum Dokument und bleiben). Ausstehende Overlay-Einträge
        für das Feld werden mit entfernt."""
        if f is None or f.source == "acroform" or self.model is None:
            return False
        if f in self.model.fields:
            self.model.fields.remove(f)
        if self.session is not None and f.rect is not None:
            self.session.pending_overlays = [
                ov for ov in self.session.pending_overlays
                if not (ov.get("page") == f.page
                        and ov.get("rect") == f.rect)]
        self.undo_stack = [a for a in self.undo_stack
                           if a.get("feld") != f.id]
        self.redo_stack = [a for a in self.redo_stack
                           if a.get("feld") != f.id]
        audit_mod.log(self.model, "Feld entfernt", f.label or f.name)
        return True

    def felder_automatisch(self) -> None:
        """Textfelder automatisch erkennen (OCR nachholen + Detektor)."""
        if self.model is None or self.session is None:
            self.app.set_status("Kein Dokument offen.")
            return
        vorher = len(self.model.fields)
        self.app.set_status("Erkenne Formularfelder …")

        def fertig(_result=None) -> None:
            neu = len(self.model.fields) - vorher
            self.refresh_all()
            self._render_page()
            if neu > 0:
                self.app.set_status(
                    f"✓ {neu} Feld(er) automatisch erkannt – Gesamt "
                    f"{len(self.model.fields)}.")
            else:
                self.app.set_status(
                    "Keine weiteren Felder gefunden – ggf. Textfeld von "
                    "Hand einfügen.")

        self.app.start_task(
            lambda: self.service.felder_automatisch_erkennen(
                self.model, self.session, self.engine),
            fertig)

    # --------------------------------------------------------- Ansicht
    def refresh_all(self) -> None:
        model = self.model
        # Analyse
        self.txt_analysis.configure(state=tk.NORMAL)
        self.txt_analysis.delete("1.0", tk.END)
        lines = ["Dokumentanalyse", "───────────────"]
        lines += model.summary_lines()
        lines.append("")
        lines.append("Schutzstatus: " +
                     SignatureAnalyzer.protection_summary(model))
        lines.append(f"Audit-Einträge: {len(model.audit)}")
        self.txt_analysis.insert("1.0", "\n".join(lines))
        self.txt_analysis.configure(state=tk.DISABLED)
        # Felder
        self.tree_fields.delete(*self.tree_fields.get_children())
        for f in model.fields:
            wert = "" if f.value is None else str(f.value)
            self.tree_fields.insert("", tk.END, iid=f.id,
                                    values=(f.label or f.name, f.field_type,
                                            wert[:28],
                                            "*" if f.required else ""))
        # Validierung
        self.tree_issues.delete(*self.tree_issues.get_children())
        icons = {"fehler": "✗", "warnung": "⚠", "hinweis": "ℹ"}
        for issue in model.issues:
            fld = model.field_by_id(issue.field_id)
            label = (fld.label if fld else "") or ""
            self.tree_issues.insert(
                "", tk.END,
                values=(icons[issue.severity], issue.message[:70], label))
        # Audit
        self.txt_audit.configure(state=tk.NORMAL)
        self.txt_audit.delete("1.0", tk.END)
        for entry in model.audit[-200:]:
            self.txt_audit.insert(tk.END,
                                  f"{entry.timestamp}  {entry.action}"
                                  + (f" – {entry.details}"
                                     if entry.details else "") + "\n")
        self.txt_audit.see(tk.END)
        self.txt_audit.configure(state=tk.DISABLED)
        self._update_statusbar()

    def _update_statusbar(self) -> None:
        counts = self.model.issue_counts()
        parts = ["✓ Analyse"]
        parts.append(f"✓ {len(self.model.fields)} Felder")
        warns = counts["fehler"] + counts["warnung"]
        parts.append(f"⚠ {warns} Hinweise" if warns else "✓ keine Probleme")
        pdf_ok = not self.model.diagnosis.get("beschaedigte_objekte")
        parts.append("✓ PDF gültig" if pdf_ok else "⚠ Strukturprobleme")
        if self.model.edited:
            parts.append("● ungespeicherte Änderungen")
        self.app.set_status("   ".join(parts))

    def _on_page_select(self, _event=None) -> None:
        sel = self.page_list.curselection()
        if sel:
            self.current_page = sel[0]
            self._render_page()

    # ---------------- Acrobat-Panels (Schiene links) ------------------
    def _panel_zeigen(self, key: str) -> None:
        """Linkes Panel auf Schienen-Knopf umschalten (Akrobat: Seiten,
        Lesezeichen, Kommentare, Anhänge, Alle Werkzeuge)."""
        self._rail_active = key
        for k, b in self._rail_buttons.items():
            b.configure(
                background="#1473e6" if k == key else "#26282e",
                foreground="white" if k == key else "#c9cdd4")
        for kind in self.panel.winfo_children():
            kind.destroy()
        kopf = tk.Label(self.panel, text={
            "werkzeuge": "Alle Werkzeuge", "seiten": "Seiten",
            "lesezeichen": "Lesezeichen", "kommentare": "Kommentare",
            "anhaenge": "Anhänge"}[key], background="#ffffff",
            foreground="#1f2430", font=("", 10, "bold"), anchor=tk.W)
        kopf.pack(fill=tk.X, padx=10, pady=(10, 4))
        {"werkzeuge": self._werkzeuge_panel,
         "seiten": self._seiten_panel,
         "lesezeichen": self._lesezeichen_panel,
         "kommentare": self._kommentare_panel,
         "anhaenge": self._anhaenge_panel}[key]()

    def _panel_gruppe(self, titel: str) -> ttk.Frame:
        """Gruppen-Überschrift im Werkzeuge-Panel (Acrobat-Kategorien)."""
        ttk.Label(self.panel, text=titel, style="Gruppe.TLabel"
                  ).pack(fill=tk.X, padx=10, pady=(8, 1))
        kasten = ttk.Frame(self.panel, style="Weiss.TFrame")
        kasten.pack(fill=tk.X, padx=6)
        return kasten

    # Symbol je Werkzeug-Text (Nutzerwunsch 10.09.2026: „Symbole
    # passend zum Objekt“) – lokal mit PIL gezeichnet, Offline.
    _SYMBOL_MAP = {
        "Auswählen": "auswaehlen", "Schwenken (Hand)": "schwenken",
        "Begrenzungsrahmen anzeigen": "bbox", "Textfeld einfügen": "textfeld",
        "Felder automatisch erkennen": "textfeld",
        "Feld entfernen": "seite_loeschen", "Feld verschieben": "verschieben",
        "Unterschrift wählen…": "signatur", "Kreuz setzen": "kreuz",
        "Häkchen setzen": "haekchen", "Punkt setzen": "punkt",
        "Umrunden": "umranden", "Durchstreichen (Zeichen)": "durchstreichen",
        "Markieren": "markieren", "Unterstreichen": "unterstreichen",
        "Durchstreichen": "durchstreichen", "Haftnotiz": "haftnotiz",
        "Datei anhängen…": "anhang", "Freihand zeichnen": "feder",
        "Linie": "linie", "Pfeil": "pfeil", "Kreis": "kreis",
        "Rechteck": "rechteck", "Polygon": "polygon",
        "Verbundene Linien": "polylinien", "Kommentarwolke": "wolke",
        "Textlegende": "legende", "Objekte messen": "messen",
        "Text einfügen": "text", "Bild einfügen…": "bild",
        "Verknüpfung hinzufügen…": "link", "Wasserzeichen…": "wasserzeichen",
        "Kopf-/Fußzeile…": "kopffuss", "Bates-Nummerierung…": "bates",
        "Hintergrundfarbe…": "hintergrund", "Schwärzen": "schwaerzen",
        "Schwärzen anwenden": "schwaerzen", "Suchen & schwärzen…": "schwaerzen",
        "Geschützt speichern": "schloss", "Signieren…": "signatur",
        "Zertifizierte Kopie…": "schild", "Seite löschen": "seite_loeschen",
        "Extrahieren…": "textdatei", "Seite verschieben…": "verschieben",
        "Zuschneiden…": "rechteck", "Seiten drehen…" : "drehen",
        "Leerseite einfügen": "textdatei", "Aus PDF einfügen…": "zusammenfuehren",
        "Dokument neu einlesen": "drehen", "Zusammenführen…": "zusammenfuehren",
        "Optimieren (komprimieren)": "schloss", "Formular abflachen": "rechteck",
        "Als Bilder exportieren…": "bild",
        "Aus Bildern… (PDF erstellen)": "bild", "Drucken": "drucker",
        "Stempel": "stempel", "Lesezeichen hinzufügen": "legende",
        "In Word (.docx)": "word", "In Excel (.xlsx)": "excel",
        "In PowerPoint (.pptx)": "powerpoint", "Als Text (.txt)": "textdatei",
        "Als RTF…": "textdatei", "Export… (alle Formate)": "textdatei",
    }

    def _panel_knopf(self, kasten, text, cmd):
        b = ttk.Button(kasten, text=text, style="Werk.TButton",
                       command=cmd)
        symbol = self._SYMBOL_MAP.get(text)
        if symbol:
            try:
                from PIL import ImageTk
                bild = symbole.symbol_bild(symbol, "#3b7dd8", 18)
                if bild is not None:
                    schluessel = "panel:" + symbol
                    self.app._thema_bilder[schluessel] = ImageTk.PhotoImage(
                        bild, master=self.app.root)
                    b.configure(image=self.app._thema_bilder[schluessel],
                                compound=tk.LEFT, anchor=tk.W)
            except Exception:
                pass
        b.pack(fill=tk.X, pady=0, padx=2, ipady=1)
        b.bind("<Enter>", lambda e, t=text:
               self.app.set_status("Werkzeug: " + t))
        b.bind("<Leave>", lambda e: self.app.set_status(""))

    def _werkzeuge_panel(self) -> None:
        """Acrobat „Alle Werkzeuge“-Katalog (Screenshots 09.09.2026):
        alle Elemente der Acrobat-Pro-Leiste – komplett lokal, ohne
        Abo-/Cloud-Knöpfe („Sparen mit…“, „Kostenlos testen“, KI-)."""
        a = self.app
        for titel, knoepfe in (
            ("Ansicht", (
                ("Auswählen", a._current_auswaehlen),
                ("Schwenken (Hand)", a._current_schwenken),
                ("Feld verschieben", a._current_feld_verschieben),
                ("Begrenzungsrahmen anzeigen", a._begrenzungsrahmen),
            )),
            ("Formular ausfüllen", (
                ("Textfeld einfügen", lambda: self.set_mode(
                    "normal" if self.mode == "textfeld" else "textfeld")),
                ("Felder automatisch erkennen", a._current_felder_auto),
                ("Feld entfernen", a._current_feld_entfernen),
                ("Unterschrift wählen…", a._current_unterschrift),
                ("Kreuz setzen", lambda: self.set_zeichen("kreuz")),
                ("Häkchen setzen", lambda: self.set_zeichen("haekchen")),
                ("Punkt setzen", lambda: self.set_zeichen("punkt")),
                ("Umrunden", lambda: self.set_zeichen("umranden")),
                ("Durchstreichen (Zeichen)",
                 lambda: self.set_zeichen("durchstreichen")),
            )),
            ("Kommentieren & Markieren", (
                ("Markieren", lambda: self.set_mode("highlight")),
                ("Unterstreichen", a._current_unterstreichen),
                ("Durchstreichen", lambda: self.set_mode("strikeout")),
                ("Haftnotiz", lambda: self.set_mode("sticky")),
                ("Datei anhängen…", a._current_anhang),
            )),
            ("Zeichnen & Formen", (
                ("Freihand zeichnen", lambda: self.set_mode("ink")),
                ("Linie", lambda: self.set_form("linie")),
                ("Pfeil", lambda: self.set_form("pfeil")),
                ("Kreis", lambda: self.set_form("kreis")),
                ("Rechteck", lambda: self.set_form("rechteck")),
                ("Polygon", lambda: self.set_polyform("polygon")),
                ("Verbundene Linien",
                 lambda: self.set_polyform("polylinie")),
                ("Kommentarwolke", lambda: self.set_polyform("wolke")),
                ("Textlegende", lambda: self.set_polyform("legende")),
                ("Objekte messen", a._current_messen),
            )),
            ("Inhalt hinzufügen", (
                ("Text einfügen", lambda: self.set_mode("text")),
                ("Bild einfügen…", a._current_bild),
                ("Verknüpfung hinzufügen…", a._current_link),
                ("Wasserzeichen…", a._current_wasserzeichen),
                ("Kopf-/Fußzeile…", a._current_kopf_fuss),
                ("Bates-Nummerierung…", a._current_bates),
                ("Hintergrundfarbe…", a._current_hintergrund),
            )),
            ("Schützen & Signieren", (
                ("Schwärzen", lambda: self.set_mode("redact")),
                ("Schwärzen anwenden", a._current_apply_redact),
                ("Suchen & schwärzen…", a._current_suchschwarz),
                ("Geschützt speichern", a._current_encrypt),
                ("Signieren…", a._current_signieren),
                ("Zertifizierte Kopie…", a._current_zertifikat),
            )),
            ("Seiten organisieren", (
                ("Seite löschen", a._current_delete_page),
                ("Extrahieren…", a._current_extract_page),
                ("Seite verschieben…", a._current_move_page),
                ("Zuschneiden…", a._current_zuschneiden),
                ("Seiten drehen…", a._current_drehen),
                ("Leerseite einfügen", a._current_leerseite),
                ("Aus PDF einfügen…", a._current_aus_pdf),
            )),
            ("Konvertieren", (
                ("In Word (.docx)", lambda: a._konvertieren("docx")),
                ("In Excel (.xlsx)", lambda: a._konvertieren("xlsx")),
                ("In PowerPoint (.pptx)", lambda: a._konvertieren("pptx")),
                ("Als Text (.txt)", lambda: a._konvertieren("txt")),
                ("Als RTF…", lambda: a._konvertieren("rtf")),
                ("Export… (alle Formate)", a._current_export),
            )),
            ("Dokument & Ausgabe", (
                ("Dokument neu einlesen", a._current_neu_einlesen),
                ("Zusammenführen…", a._current_merge),
                ("Optimieren (komprimieren)", a._current_optimieren),
                ("Formular abflachen", a._current_flatten),
                ("Als Bilder exportieren…", a._current_als_bilder),
                ("Aus Bildern… (PDF erstellen)", a._aus_bildern),
                ("Drucken", a._current_drucken),
            )),
            ("Auszeichnen & Stempel", (
                ("Stempel", lambda: self.set_mode("stempel")),
                ("Lesezeichen hinzufügen", a._current_lesezeichen),
            )),
        ):
            kasten = self._panel_gruppe(titel)
            for text, cmd in knoepfe:
                self._panel_knopf(kasten, text, cmd)

    def _seiten_panel(self) -> None:
        """Seiten-Miniaturen (Acrobat-Seitenbereich) + Optionen."""
        croll = ttk.Frame(self.panel, style="Weiss.TFrame")
        croll.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self.thumbs = tk.Canvas(croll, background="#ffffff",
                                highlightthickness=0)
        sbar = ttk.Scrollbar(croll, orient=tk.VERTICAL,
                             command=self.thumbs.yview)
        self.thumbs.configure(yscrollcommand=sbar.set)
        self.thumbs.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sbar.pack(side=tk.RIGHT, fill=tk.Y)
        # Mausrad auf der Miniatur-Leiste (Windows + Linux)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.thumbs.bind(seq, self._thumbs_rad)
        self._thumbnails_zeichnen()
        unten = ttk.Frame(self.panel, style="Weiss.TFrame")
        unten.pack(fill=tk.X, padx=8, pady=6)
        ttk.Checkbutton(unten, text="Felder markieren",
                        style="Nav.TCheckbutton", variable=self.show_fields,
                        command=self._render_page).pack(anchor=tk.W)
        ttk.Button(unten, text="Seite rotieren", style="Werk.TButton",
                   command=self._rotate_page).pack(fill=tk.X, pady=2)

    def _thumbs_rad(self, event) -> None:
        """Mausrad über der Miniatur-Leiste: Liste scrollen."""
        num = getattr(event, "num", 0)
        if num == 4:
            delta = 120
        elif num == 5:
            delta = -120
        else:
            delta = getattr(event, "delta", 0) or 0
        if delta:
            self.thumbs.yview_scroll(-3 if delta > 0 else 3, "units")

    def _thumbnails_zeichnen(self) -> None:
        """Miniaturen: sauber im Seitenverhältnis, exakt umrandet,
        anklickbar und per Drag & Drop neu anordnbar (Acrobat-Seiten)."""
        if not hasattr(self, "thumbs") or self.session is None:
            return
        import io
        from PIL import Image, ImageTk
        c = self.thumbs
        c.delete("all")
        self._thumb_photos.clear()
        self._thumb_ids.clear()
        self._thumb_slots = []
        breite_max = c.winfo_width()
        ziel_b = min(190.0, max(130.0, (breite_max - 34) if breite_max > 60
                                else 190.0))
        y = 10
        seiten = self.model.pages if self.model else []
        for nr in range(len(seiten)):
            pm = seiten[nr]
            b, h = 130, 184
            foto = None
            try:
                dpi = max(16, min(50, int(ziel_b / (pm.width or 595) * 72)))
                png = self.engine.render_page(self.session, nr, dpi)
                img = Image.open(io.BytesIO(png))
                foto = ImageTk.PhotoImage(img)
                b, h = img.size
            except Exception:
                pass
            x0 = 14
            if foto:
                cid = c.create_image(x0, y, anchor=tk.NW, image=foto)
                self._thumb_photos.append(foto)
            else:
                cid = c.create_rectangle(x0, y, x0 + b, y + h,
                                         outline="#c9cdd4")
            tid = c.create_text(x0 + b / 2, y + h + 12, text=f"{nr + 1}",
                                fill="#5a6472", font=("", 9))
            aktiv = nr == self.current_page
            # Rahmen EXAKT um die Seite (folgt dem Seitenverhältnis)
            c.create_rectangle(x0 - 3, y - 3, x0 + b + 3, y + h + 3,
                               outline="#1473e6" if aktiv else "#d9dce1",
                               width=2 if aktiv else 1)
            for tag in (cid, tid):
                c.tag_bind(tag, "<ButtonPress-1>",
                           lambda e, n=nr: self._thumb_drag_start(e, n))
            self._thumb_ids[nr] = cid
            self._thumb_slots.append(y + h / 2)
            y += h + 30
        c.configure(scrollregion=(0, 0, max(220, ziel_b + 24), y + 8))
        c.bind("<B1-Motion>", self._thumb_drag_move)
        c.bind("<ButtonRelease-1>", self._thumb_drag_end)

    # ------------------------------------------------ Miniatur-Drag
    def _thumb_drag_start(self, event, nr: int) -> None:
        self._thumb_drag = {"von": nr,
                            "y0": self.thumbs.canvasy(event.y)}

    def _thumb_ziel_index(self, y: float) -> int:
        slots = getattr(self, "_thumb_slots", [])
        if not slots:
            return 0
        best, abstand = 0, 1e9
        for i, sy in enumerate(slots):
            d = abs(sy - y)
            if d < abstand:
                best, abstand = i, d
        return best

    def _thumb_drag_move(self, event) -> None:
        drag = getattr(self, "_thumb_drag", None)
        if not drag:
            return
        y = self.thumbs.canvasy(event.y)
        self.thumbs.delete("drag_marke")
        ziel = self._thumb_ziel_index(y)
        slots = getattr(self, "_thumb_slots", [])
        if ziel < len(slots):
            ym = slots[ziel] - 60
            self.thumbs.create_line(8, ym, 210, ym, fill="#1473e6",
                                    width=3, arrow=tk.LAST,
                                    tags="drag_marke")

    def _thumb_drag_end(self, event) -> None:
        drag = getattr(self, "_thumb_drag", None)
        self._thumb_drag = None
        self.thumbs.delete("drag_marke")
        if not drag:
            return
        y = self.thumbs.canvasy(event.y)
        if abs(y - drag["y0"]) < 16:            # Klick, kein Ziehen
            self._seite_waehlen(drag["von"])
            return
        ziel = self._thumb_ziel_index(y)
        if ziel != drag["von"]:
            self._seiten_vertauschen(drag["von"], ziel)

    # ------------------------------------------------ Seite verschieben
    def _seiten_vertauschen(self, von: int, zu: int) -> None:
        """Verschiebt eine Seite an eine neue Position (Miniatur-Drag)
        und hält Modell, Felder, Overlays, Tabellen und Nummern synchron."""
        if self.session is None or not self.model:
            return
        n = len(self.model.pages)
        if not (0 <= von < n and 0 <= zu < n) or von == zu:
            return
        alte_nummern = {id(pm): pm.number for pm in self.model.pages}
        reihenfolge = list(range(n))
        reihenfolge.insert(zu, reihenfolge.pop(von))
        try:
            self.session.doc.select(reihenfolge)
        except Exception as exc:                # noqa: BLE001
            messagebox.showerror("Seite verschieben", str(exc))
            return
        objekte = list(self.model.pages)
        seite = objekte.pop(von)
        objekte.insert(zu, seite)
        self.model.pages[:] = objekte
        abbildung = {}
        for i, pm in enumerate(objekte):
            abbildung[alte_nummern[id(pm)]] = i
            pm.number = i
        for f in self.model.fields:
            f.page = abbildung.get(f.page, f.page)
        for t in self.model.tables:
            t.page = abbildung.get(t.page, t.page)
        for ov in self.session.pending_overlays:
            ov["page"] = abbildung.get(ov.get("page"), ov.get("page"))
        self.redact_rects = [(abbildung.get(p, p), r)
                             for p, r in self.redact_rects]
        # Tabellen-Caches der Sitzung sind jetzt falsch nummeriert
        self.session._tables_cache = None
        self.session._tables_cache_all = None
        self.current_page = abbildung.get(self.current_page, 0)
        self.model.edited = True
        audit_mod.log(self.model, "Seite neu angeordnet",
                      f"Seite {von + 1} → Position {zu + 1}")
        self.page_list.delete(0, tk.END)
        for p in self.model.pages:
            self.page_list.insert(tk.END, f"Seite {p.number + 1}")
        self._seite_waehlen(self.current_page)
        self._thumbnails_zeichnen()
        self._nav_aktualisieren()
        self._render_page()
        self.app.set_status(f"✓ Seite {von + 1} auf Position {zu + 1} "
                            "verschoben – „Neue Version“ speichert.")

    def _seite_waehlen(self, nr: int) -> None:
        self.page_list.selection_clear(0, tk.END)
        self.page_list.selection_set(nr)
        self._on_page_select()

    def _lesezeichen_panel(self) -> None:
        """PDF-Lesezeichen (Inhaltsverzeichnis) – Acrobat-Äquivalent."""
        kasten = ttk.Frame(self.panel, style="Weiss.TFrame")
        kasten.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        cols = ("Titel", "Seite")
        self.tree_bm = ttk.Treeview(kasten, columns=cols, show="headings",
                                    height=14)
        self.tree_bm.heading("Titel", text="Titel")
        self.tree_bm.column("Titel", width=150)
        self.tree_bm.heading("Seite", text="Seite")
        self.tree_bm.column("Seite", width=45)
        self.tree_bm.pack(fill=tk.BOTH, expand=True)
        self.tree_bm.bind("<Double-1>", self._lesezeichen_springen)
        bar = ttk.Frame(self.panel, style="Weiss.TFrame")
        bar.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(bar, text="Lesezeichen hinzufügen",
                   style="Werk.TButton",
                   command=self.app._current_lesezeichen).pack(
                       fill=tk.X, pady=1)
        ttk.Button(bar, text="Löschen", style="Werk.TButton",
                   command=self._lesezeichen_loeschen).pack(fill=tk.X,
                                                            pady=1)
        self._lesezeichen_fuellen()

    def _lesezeichen_fuellen(self) -> None:
        if not hasattr(self, "tree_bm") or self.session is None:
            return
        self.tree_bm.delete(*self.tree_bm.get_children())
        from ..engines import annotate
        for bm in annotate.lesezeichen_lesen(self.session):
            self.tree_bm.insert("", tk.END, values=(
                "   " * (bm["ebene"] - 1) + bm["titel"], bm["seite"] + 1))

    def _lesezeichen_springen(self, _e=None) -> None:
        sel = self.tree_bm.selection()
        if sel:
            seite = int(self.tree_bm.item(sel[0], "values")[1]) - 1
            self._seite_waehlen(seite)

    def _lesezeichen_loeschen(self) -> None:
        sel = self.tree_bm.selection()
        if sel and self.session is not None:
            from ..engines import annotate
            annotate.lesezeichen_loeschen(self.session,
                                          self.tree_bm.index(sel[0]))
            self.model.edited = True
            self._lesezeichen_fuellen()

    def _kommentare_panel(self) -> None:
        """Alle Markierungen/Notizen listen (Acrobat-Kommentarliste)."""
        kasten = ttk.Frame(self.panel, style="Weiss.TFrame")
        kasten.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        cols = ("Seite", "Typ", "Text")
        self.tree_comm = ttk.Treeview(kasten, columns=cols, show="headings",
                                      height=16)
        for col, breite in zip(cols, (40, 80, 90)):
            self.tree_comm.heading(col, text=col)
            self.tree_comm.column(col, width=breite)
        self.tree_comm.pack(fill=tk.BOTH, expand=True)
        self.tree_comm.bind("<Double-1>", self._kommentar_springen)
        self._kommentare_fuellen()

    def _kommentare_fuellen(self) -> None:
        if not hasattr(self, "tree_comm") or self.session is None:
            return
        self.tree_comm.delete(*self.tree_comm.get_children())
        from ..engines import annotate
        for k in annotate.kommentare_lesen(self.session):
            self.tree_comm.insert("", tk.END, values=(
                k["seite"] + 1, k["typ"], (k["text"] or "")[:28]))

    def _kommentar_springen(self, _e=None) -> None:
        sel = self.tree_comm.selection()
        if sel:
            seite = int(self.tree_comm.item(sel[0], "values")[0]) - 1
            self._seite_waehlen(seite)

    def _anhaenge_panel(self) -> None:
        """Eingebettete Dateien (Acrobat-Anlagenbereich)."""
        kasten = ttk.Frame(self.panel, style="Weiss.TFrame")
        kasten.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        cols = ("Name", "Größe")
        self.tree_att = ttk.Treeview(kasten, columns=cols, show="headings",
                                     height=16)
        self.tree_att.heading("Name", text="Name")
        self.tree_att.column("Name", width=140)
        self.tree_att.heading("Größe", text="Größe")
        self.tree_att.column("Größe", width=60)
        self.tree_att.pack(fill=tk.BOTH, expand=True)
        self._anhaenge_fuellen()
        ttk.Button(kasten, text="Anhang extrahieren…", style="Werk.TButton",
                   command=self._anhang_speichern).pack(fill=tk.X, pady=4)
        ttk.Button(kasten, text="Anhang einbetten…", style="Werk.TButton",
                   command=self.app._current_anhang).pack(fill=tk.X)

    def _anhaenge_fuellen(self) -> None:
        if not hasattr(self, "tree_att") or self.session is None:
            return
        self.tree_att.delete(*self.tree_att.get_children())
        from ..engines import annotate
        for a in annotate.anhaenge_lesen(self.session):
            self.tree_att.insert("", tk.END, values=(
                a["name"], f"{a['bytes'] // 1024} KB"))

    def _anhang_speichern(self) -> None:
        sel = self.tree_att.selection()
        if not sel or self.session is None:
            return
        name = self.tree_att.item(sel[0], "values")[0]
        ziel = filedialog.asksaveasfilename(initialfile=name)
        if ziel:
            from ..engines import annotate
            annotate.anhang_extrahieren(self.session, name, ziel)
            self.app.set_status("Anhang gespeichert: " + ziel)

    # ---------------- Navbar-Aktionen ---------------------------------
    def _seite_zurueck(self) -> None:
        self._seite_waehlen(max(0, self.current_page - 1))

    # ------------------------------------------------ Mausrad
    def _on_wheel(self, event) -> None:
        """Mausrad wie Acrobat: innerhalb der Seite scrollen; am oberen
        Ende zurück-, am unteren Ende weiterblättern. Ist die ganze
        Seite sichtbar, blättert das Rad sofort um."""
        if not self.model or not self.model.pages:
            return
        num = getattr(event, "num", 0)
        if num == 4:
            delta = 120
        elif num == 5:
            delta = -120
        else:
            delta = getattr(event, "delta", 0) or 0
        if delta == 0:
            return
        schritt = -1 if delta > 0 else 1        # -1 = hoch/zurück
        self.canvas.update_idletasks()
        y0, y1 = self.canvas.yview()
        am_anfang = y0 <= 0.001
        am_ende = y1 >= 0.999
        if (schritt < 0 and am_anfang) or (schritt > 0 and am_ende):
            ziel = self.current_page + schritt
            if 0 <= ziel < len(self.model.pages):
                self._seite_waehlen(ziel)
            return
        self.canvas.yview_scroll(3 * schritt, "units")

    def _seite_vor(self) -> None:
        letzte = len(self.model.pages) - 1 if self.model else 0
        self._seite_waehlen(min(letzte, self.current_page + 1))

    def _seite_gehe(self, _e=None) -> None:
        try:
            nr = int(self.nav_seite.get()) - 1
        except ValueError:
            return
        if self.model and 0 <= nr < len(self.model.pages):
            self._seite_waehlen(nr)

    def _fit_breite(self) -> None:
        """Auf Fensterbreite einpassen (Acrobat „An Breite anpassen“)."""
        if self.session is None:
            return
        basis = self.engine.render_page(self.session, self.current_page, 72)
        import io
        from PIL import Image
        breit_px = Image.open(io.BytesIO(basis)).size[0]
        ziel = max(0.4, min(4.0, (self.canvas.winfo_width() - 24)
                            / breit_px))
        self.zoom = ziel
        self._render_page()

    def _nav_aktualisieren(self) -> None:
        self.nav_seite.delete(0, tk.END)
        self.nav_seite.insert(0, str(self.current_page + 1))
        self.nav_von.configure(
            text=f"von {len(self.model.pages) if self.model else 1}")
        self.nav_zoom.configure(text=f"{int(self.zoom * 100)} %")

    @safe
    def _render_page(self) -> None:
        _rubber_coords = None            # Band eines Zuges retten (u.)
        if (self.session is None or self.engine is None
                or not self.model.pages or not PIL_OK):
            self.canvas.delete("all")
            self.canvas.create_text(
                30, 30, anchor=tk.NW, fill="white",
                text=(self.model.pages[0].text[:4000] if self.model.pages
                      else "(kein Inhalt)"),
                font=("Consolas", 10))
            return
        dpi = int(150 * self.zoom)
        png = self.engine.render_page(self.session, self.current_page, dpi)
        import io
        img = Image.open(io.BytesIO(png))
        self.photo = ImageTk.PhotoImage(img)
        # Rubber-Band eines laufenden Zuges retten (FocusOut-Commits
        # rendern zwischendurch neu – das Band darf nicht verschwinden)
        if getattr(self, "_rubber", None) is not None:
            _rubber_coords = self.canvas.coords(self._rubber)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, img.size[0], img.size[1]))
        self.field_items.clear()
        if self.show_fields.get():
            scale = dpi / 72.0
            for f in self.model.fields:
                if f.page != self.current_page or not f.rect:
                    continue
                color = ("#1e88e5" if f.source == "acroform" else "#43a047")
                x0 = f.rect.x * scale
                y0 = f.rect.y * scale
                x1 = (f.rect.x + f.rect.width) * scale
                y1 = (f.rect.y + f.rect.height) * scale
                cid = self.canvas.create_rectangle(
                    x0, y0, x1, y1, outline=color, dash=(4, 3), width=2)
                self.field_items[cid] = f.id
                # eingetippter Wert SOFORT im Feld zeigen (Acrobat-Feeling)
                wert = f.value
                if wert not in (None, "", False):
                    txt = ("✓" if f.field_type == "checkbox" and wert
                           else str(wert))
                    fs = max(8, min(13, (y1 - y0) * 0.62))
                    self.canvas.create_text(
                        x0 + 3, (y0 + y1) / 2, anchor=tk.W, text=txt,
                        font=("Segoe UI", int(fs)), fill="#0d47a1",
                        width=max(30, x1 - x0 - 6))
        for (x0, y0, x1, y1) in self.search_hits:
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#ff1744",
                                         width=3)
        # Vorschau: markierte Schwärz-Bereiche (endgültig erst beim Anwenden)
        scale2 = (150 * self.zoom) / 72.0
        for (pg_nr, (rx0, ry0, rx1, ry1)) in self.redact_rects:
            if pg_nr != self.current_page:
                continue
            self.canvas.create_rectangle(
                rx0 * scale2, ry0 * scale2, rx1 * scale2, ry1 * scale2,
                fill="#b71c1c", stipple="gray50", outline="#b71c1c", width=2)
        if _rubber_coords and len(_rubber_coords) == 4 and \
                getattr(self, "_rubber", None) is not None:
            self.canvas.coords(self._rubber, *_rubber_coords)
            self.canvas.tag_raise(self._rubber)
        if getattr(self, "_bbox_an", False):
            self._bbox_zeichnen(dpi)
        self._nav_aktualisieren()
        self._thumbnails_aktualisieren()

    def _bbox_zeichnen(self, dpi: int | None = None) -> None:
        """Begrenzungsrahmen anzeigen (Acrobat „Bearbeiten“): Rahmen um
        Textblöcke (blau), Bilder (grün) und Grafiken (orange)."""
        self.canvas.delete("bbox")
        if self.session is None:
            return
        scale = ((dpi if dpi is not None else int(150 * self.zoom))
                 / 72.0)
        seite = self.session.doc.load_page(self.current_page)
        try:
            for b in seite.get_text("blocks"):
                x0, y0, x1, y1 = b[:4]
                self.canvas.create_rectangle(
                    x0 * scale, y0 * scale, x1 * scale, y1 * scale,
                    outline="#1565c0", width=1, dash=(3, 2), tags="bbox")
            info = seite.get_text("dict")
            for blk in info.get("blocks", []):
                if blk.get("type") == 1:               # Bild
                    x0, y0, x1, y1 = blk["bbox"]
                    self.canvas.create_rectangle(
                        x0 * scale, y0 * scale, x1 * scale, y1 * scale,
                        outline="#2e7d32", width=2, tags="bbox")
            for d in seite.get_drawings():
                r = d.get("rect")
                if r is not None and r.width > 2 and r.height > 2:
                    self.canvas.create_rectangle(
                        r.x0 * scale, r.y0 * scale,
                        r.x1 * scale, r.y1 * scale,
                        outline="#ef6c00", width=1, dash=(2, 3),
                        tags="bbox")
        except Exception:                               # noqa: BLE001
            pass

    # ---------------------------------------------------- Interaktion
    def _on_canvas_click(self, event) -> None:
        if not self.model:
            return
        if self.mode != "normal":
            self._tool_down(event)
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        scale = (150 * self.zoom) / 72.0
        px, py = cx / scale, cy / scale
        # Feld getroffen? → DIREKT hineinschreiben (Acrobat „Fill & Sign“)
        for f in self.model.fields:
            if f.page == self.current_page and f.rect and \
                    f.rect.contains(px, py):
                self._inspect(f)
                if f.read_only:
                    return
                if f.field_type == "checkbox":
                    alt = f.value
                    self._set_field_value(f, not bool(f.value))
                    self.undo_stack.append({"feld": f.id, "alt": alt,
                                            "neu": not bool(alt)})
                    self.redo_stack.clear()
                    self._autosave()
                    self.refresh_all()
                    self._render_page()
                else:
                    self._inline_edit(f)
                return
        page = self.model.pages[self.current_page]
        for w in page.words:
            if w.rect.contains(px, py):
                self._inspect_word(w)
                return
        for key in self.inspector_prop:
            self.inspector_prop[key].set("–")
        self.btn_edit.configure(state=tk.DISABLED)

    # ------------------------------- Direkt ins Feld schreiben
    def _inline_edit(self, f) -> None:
        """Öffnet ein Eingabefeld DIREKT über dem PDF-Feld (Acrobat-
        Verhalten: reinlesen, tippen, Enter – fertig)."""
        self._inline_close()
        if self.session is None or not f.rect:
            return
        scale = (150 * self.zoom) / 72.0
        vx = self.canvas.canvasx(0)
        vy = self.canvas.canvasy(0)
        x0 = f.rect.x * scale - vx
        y0 = f.rect.y * scale - vy
        breite = max(70, (f.rect.width) * scale)
        hoehe = max(18, (f.rect.height) * scale)
        var = tk.StringVar(value="" if f.value is None else str(f.value))
        entry = ttk.Entry(self.canvas, textvariable=var)
        self._inline_entry = (entry, f, var)
        entry.place(x=max(2, x0), y=max(2, y0), width=breite, height=hoehe)
        entry.focus_set()
        entry.select_range(0, tk.END)
        entry.bind("<Return>", lambda _e: self._inline_commit())
        # Esc in der Eingabe beendet NUR die Eingabe (Acrobat: „remove
        # focus"), nicht gleich das ganze Werkzeug – „break" stoppt das
        # Aufsteigen zum Fenster-Handler.
        def _esc_nur_eingabe(_e):
            self._inline_close()
            return "break"
        entry.bind("<Escape>", _esc_nur_eingabe)
        entry.bind("<FocusOut>", lambda _e: self._inline_commit())
        entry.bind("<Tab>",
                   lambda _e: (self._inline_commit(), self._inline_next(f)))
        self.app.set_status(
            f"Feld „{f.label or f.name}“: eintippen, Enter übernimmt "
            "(Esc bricht ab, Tab springt weiter).")

    def _inline_commit(self) -> None:
        eintrag = getattr(self, "_inline_entry", None)
        if not eintrag:
            return
        entry, f, var = eintrag
        self._inline_entry = None
        neu = var.get()
        entry.destroy()
        alt = f.value
        if neu == ("" if alt is None else str(alt)):
            return                       # nichts geändert
        from ..core import audit as audit_mod
        self._set_field_value(f, neu)
        self.undo_stack.append({"feld": f.id, "alt": alt, "neu": neu})
        self.redo_stack.clear()
        audit_mod.log(self.model, "Feld direkt ausgefüllt",
                      f'"{f.label or f.name}"')
        self._autosave()
        self.refresh_all()
        self._render_page()
        self.app.set_status(
            f"„{f.label or f.name}“ = {neu!r} übernommen – mit „Neue "
            "Version“ endgültig speichern.")

    def _inline_close(self) -> None:
        eintrag = getattr(self, "_inline_entry", None)
        if eintrag:
            self._inline_entry = None
            try:
                eintrag[0].destroy()
            except Exception:
                pass

    def _inline_next(self, aktuelles) -> None:
        """Tab: nächstes ausfüllbares Feld derselben Seite (von oben)."""
        kandidaten = sorted(
            (x for x in self.model.fields
             if x.page == self.current_page and x.rect
             and x.field_type not in ("checkbox",) and not x.read_only),
            key=lambda x: (x.rect.y, x.rect.x))
        ids = [x.id for x in kandidaten]
        if aktuelles.id in ids:
            i = ids.index(aktuelles.id)
            naechster = kandidaten[(i + 1) % len(kandidaten)] \
                if kandidaten else None
        else:
            naechster = kandidaten[0] if kandidaten else None
        if naechster is not None:
            self._inspect(naechster)
            self._inline_edit(naechster)

    def _thumbnails_aktualisieren(self) -> None:
        """Thumbnail-Rahmen + offene Panels auf neuem Stand halten."""
        if self._rail_active == "seiten" and hasattr(self, "thumbs"):
            self._thumbnails_zeichnen()
        elif self._rail_active == "kommentare" and hasattr(self, "tree_comm"):
            self._kommentare_fuellen()
        elif self._rail_active == "lesezeichen" and hasattr(self, "tree_bm"):
            self._lesezeichen_fuellen()
        elif self._rail_active == "anhaenge" and hasattr(self, "tree_att"):
            self._anhaenge_fuellen()

    # ------------------------------- PDF-Werkzeuge (Acrobat-inspiriert)
    def set_form(self, art: str) -> None:
        """Zeichenform wählen (Linie/Pfeil/Kreis/Rechteck) und Werkzeug
        aktivieren (Acrobat „Zeichnen“-Palette)."""
        self._form_art = art
        self.set_mode("normal" if self.mode == "form" and
                      getattr(self, "_form_art_alt", "") == art else "form")
        self._form_art_alt = art

    def set_polyform(self, art: str) -> None:
        """Mehrpunkt-Zeichenform wählen (Polygon/Verbundene Linien/
        Kommentarwolke/Textlegende) – Acrobat „Zeichnen“-Palette.
        Klick = Punkt setzen, Doppelklick = Form fertigen."""
        self._poly_art = art
        self.set_mode("normal" if self.mode == "polyform" and
                      getattr(self, "_poly_art_alt", "") == art
                      else "polyform")
        self._poly_art_alt = art

    def _on_canvas_doppelklick(self, event) -> None:
        if self.mode == "polyform":
            self._polyform_abschliessen()

    def _poly_punkt_hinzu(self, pos: tuple) -> None:
        """Klick im Mehrpunkt-Modus: Punkt merken + Vorschau zeichnen."""
        if not hasattr(self, "_poly_punkte"):
            self._poly_punkte = []
        if self._poly_punkte and \
                abs(self._poly_punkte[-1][0] - pos[0]) < 3 and \
                abs(self._poly_punkte[-1][1] - pos[1]) < 3:
            return                          # Doppelklick-Duplikat ignorieren
        self._poly_punkte.append(pos)
        self.canvas.create_oval(pos[0] - 3, pos[1] - 3, pos[0] + 3,
                                pos[1] + 3, fill="#e53935",
                                outline="#e53935", tags="poly_form")
        if len(self._poly_punkte) >= 2:
            (x0, y0), (x1, y1) = self._poly_punkte[-2:]
            self.canvas.create_line(x0, y0, x1, y1, fill="#e53935",
                                    width=2, tags="poly_form")

    def _polyform_abschliessen(self) -> None:
        """Doppelklick: gesammelte Punkte als Form ins PDF zeichnen."""
        punkte = list(getattr(self, "_poly_punkte", []))
        art = getattr(self, "_poly_art", "polygon")
        self._poly_aufraeumen()
        if len(punkte) < 2:
            self.app.set_status("Zu wenige Punkte – Form abgebrochen.")
            self.set_mode("normal")
            return
        if art == "legende":
            self.set_mode("normal")
            return                          # Legende läuft über Dialog
        pdf_pts = [self._pdf_pt(*p) for p in punkte]
        try:
            annotate.polyform_zeichnen(self.session, self.current_page,
                                       art, pdf_pts)
        except Exception as exc:                    # noqa: BLE001
            messagebox.showerror("Zeichnen", str(exc))
            return
        self.model.edited = True
        audit_mod.log(self.model, "Form gezeichnet",
                      f"{art}, {len(pdf_pts)} Punkte, Seite "
                      f"{self.current_page + 1}")
        self.app.set_status(f"✓ {art} mit {len(pdf_pts)} Punkten "
                            "gezeichnet – „Neue Version“ speichert sie.")
        self.set_mode("normal")
        self._render_page()

    def _poly_aufraeumen(self) -> None:
        self.canvas.delete("poly_form")
        self._poly_punkte = []

    def _verschiebe_greifen(self, pos: tuple) -> None:
        """Feld unter dem Cursor finden und Greifpunkt merken."""
        self.canvas.delete("verschiebe_rahmen")
        self._verschiebe_item = None
        scale = (150 * self.zoom) / 72.0
        feld = None
        for f in self.model.fields:
            if f.page != self.current_page or not f.rect:
                continue
            x0 = f.rect.x * scale
            y0 = f.rect.y * scale
            x1 = (f.rect.x + f.rect.width) * scale
            y1 = (f.rect.y + f.rect.height) * scale
            if x0 - 4 <= pos[0] <= x1 + 4 and y0 - 4 <= pos[1] <= y1 + 4:
                feld = f
                break
        if feld is None:
            self.app.set_status("Kein Feld an dieser Stelle – Feld "
                                "anklicken und ziehen.")
            return
        self._verschiebe_item = feld
        self._verschiebe_x0, self._verschiebe_y0 = x0, y0
        self._verschiebe_x1, self._verschiebe_y1 = x1, y1
        self.canvas.create_rectangle(
            x0, y0, x1, y1, outline="#1473e6", width=3,
            dash=(6, 3), tags="verschiebe_rahmen")

    def _verschiebe_loserlassen(self, x: float, y: float) -> None:
        """Ziehen beendet: Feld an die neue Position setzen."""
        feld = getattr(self, "_verschiebe_item", None)
        self.canvas.delete("verschiebe_rahmen")
        self._verschiebe_item = None
        if feld is None or feld.rect is None:
            return
        scale = (150 * self.zoom) / 72.0
        dx = (x - self._start[0]) / scale
        dy = (y - self._start[1]) / scale
        if abs(dx) < 0.5 and abs(dy) < 0.5:
            return                       # nur angeklickt, nicht gezogen
        feld.rect = Rect4(
            max(2.0, feld.rect.x + dx), max(2.0, feld.rect.y + dy),
            feld.rect.width, feld.rect.height)
        self.model.edited = True
        audit_mod.log(self.model, "Feld verschoben",
                      f"„{feld.label}“ → Seite "
                      f"{self.current_page + 1}, x={feld.rect.x:.0f}, "
                      f"y={feld.rect.y:.0f}")
        self.app.set_status(f"✓ Feld „{feld.label}“ verschoben – mit "
                            "„Neue Version“ speichern.")
        self._render_page()

    def _poly_legende(self, anker: tuple, kasten: tuple) -> None:
        """Textlegende: Dialog → Zeigerlinie + Textkasten (Acrobat
        „Textlegende“ aus der Zeichnen-Palette)."""
        text = simpledialog.askstring(
            "Textlegende", "Beschriftungstext:", parent=self.canvas)
        p0 = self._pdf_pt(*anker)
        p1 = self._pdf_pt(*kasten)
        self._poly_aufraeumen()
        if not text:
            self.set_mode("normal")
            return
        try:
            annotate.polyform_zeichnen(self.session, self.current_page,
                                       "legende", [p0, p1], text=text)
        except Exception as exc:                    # noqa: BLE001
            messagebox.showerror("Textlegende", str(exc))
            return
        self.model.edited = True
        audit_mod.log(self.model, "Textlegende", text[:40])
        self.app.set_status("✓ Textlegende eingefügt.")
        self.set_mode("normal")
        self._render_page()

    def set_zeichen(self, zeichen: str) -> None:
        """Füllzeichen wählen (Kreuz/Häkchen/Punkt/Umrunden/Durch-
        streichen) – Acrobat „Text eingeben“-Palette."""
        self._zeichen_art = zeichen
        self.set_mode("normal" if self.mode == "zeichen" and
                      getattr(self, "_zeichen_art_alt", "") == zeichen
                      else "zeichen")
        self._zeichen_art_alt = zeichen

    def _klick_auf_linie(self, x: float, y: float) -> tuple:
        """Nächste horizontale Formular-Linie beim Klickpunkt suchen.
        Liefert (x0, x1, y0, y1) eines Feldes, das mit seiner Unterkante
        EXAKT auf der Linie sitzt; ohne Linie den Klick unverändert."""
        if self.session is None:
            return (x, x, y, y)
        try:
            drawings = self.session.doc.load_page(
                self.current_page).get_drawings()
        except Exception:
            return (x, x, y, y)
        best = None
        for d in drawings:
            for item in d.get("items", []):
                if item[0] != "l":
                    continue
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) >= 1.5:
                    continue
                ly = min(p1.y, p2.y)
                lx0, lx1 = min(p1.x, p2.x), max(p1.x, p2.x)
                if not (lx0 - 30 <= x <= lx1 + 10):
                    continue
                abstand = abs(ly - y)
                if abstand <= 22 and (best is None or abstand < best[0]):
                    best = (abstand, lx0, lx1, ly)
        if best is None:
            return (x, x, y, y)
        _, lx0, lx1, ly = best
        feld_x0 = max(lx0 + 1, x - 2)
        feld_x1 = min(max(feld_x0 + 40, lx1 - 1), feld_x0 + 420)
        return (feld_x0, feld_x1, ly - 12.0, ly)

    def set_mode(self, modus: str) -> None:
        """Interaktionsmodus der Ansicht (normal|highlight|strikeout|
        sticky|ink|redact)."""
        if getattr(self, "mode", "normal") == "polyform" \
                and modus != "polyform":
            self._poly_aufraeumen()
        self.mode = modus
        self.canvas.configure(cursor=("crosshair" if modus != "normal"
                                      else "arrow"))
        self._banner_aktualisieren()
        texte = {"highlight": "Markieren: Bereich mit der Maus ziehen "
                              "(Esc beendet).",
                 "strikeout": "Durchstreichen: Bereich ziehen (Esc beendet).",
                 "sticky": "Haftnotiz: Punkt anklicken (Esc beendet).",
                 "ink": "Zeichnen: Linie ziehen (Esc beendet).",
                 "redact": "Schwärzen: Bereiche ziehen, dann „Schwärzen "
                           "anwenden“ (Esc beendet).",
                 "text": "Text einfügen: Rahmen aufziehen, Text eingeben "
                         "(Esc beendet).",
                 "textfeld": "Textfeld einfügen: Rahmen aufziehen (Klick = "
                             "Standardgröße), Text eingeben (Esc beendet).",
                 "stempel": "Stempel: Rahmen aufziehen, Art wählen "
                            "(Esc beendet).",
                 "sign_ink": "Unterschreiben: Unterschrift mit der Maus "
                             "zeichnen (Esc beendet).",
                 "sign_img": "Unterschrift-Bild: Rahmen aufziehen, Bild "
                             "wählen (Esc beendet).",
                 "polyform": "Form: Punkte anklicken, Doppelklick "
                             "beendet (Esc bricht ab).",
                 "feld_bewegen": "Feld verschieben: Feld anklicken und "
                                 "ziehen (Esc beendet).",
                 "normal": "Werkzeug beendet."}
        self.app.set_status(texte.get(modus, ""))

    _BANNER_TEXTE = {
        "textfeld": "Textfeld-Werkzeug: Auf eine Formular-Linie klicken "
                    "setzt das Feld direkt auf die Linie – oder Rahmen "
                    "aufziehen. Esc beendet.",
        "underline": "Unterstreichen: Textbereich ziehen. Esc beendet.",
        "form": "Form zeichnen: Linie/Kreis/Rechteck mit der Maus "
                "aufziehen. Esc beendet.",
        "zeichen": "Füllzeichen: Auf die Stelle klicken, an die das "
                   "Zeichen soll. Esc beendet.",
        "bild": "Bild einfügen: Rahmen aufziehen, dann Bilddatei wählen. "
                "Esc beendet.",
        "link": "Verknüpfung: Rahmen aufziehen, dann Ziel-Adresse "
                "eingeben. Esc beendet.",
        "polyform": "Mehrpunkt-Form: Punkte nacheinander anklicken, "
                    "Doppelklick beendet. Esc bricht ab.",
        "feld_bewegen": "Feld verschieben: Feld anklicken und mit der "
                        "Maus an die richtige Stelle ziehen. Esc "
                        "beendet – die Position wird mit „Neue Version“ "
                        "gespeichert.",
        "messen": "Messen: Linie zwischen zwei Punkten ziehen – der "
                  "Abstand erscheint in der Statusleiste. Esc beendet.",
        "schwenken": "Schwenken: Seite mit gedrückter Maustaste "
                     "verschieben. Esc beendet.",
        "text": "Text einfügen: Rahmen aufziehen oder klicken.",
        "highlight": "Markieren: Bereich ziehen. Esc beendet.",
        "strikeout": "Durchstreichen: Bereich ziehen. Esc beendet.",
        "sticky": "Haftnotiz: Punkt anklicken. Esc beendet.",
        "ink": "Zeichnen: Linie ziehen. Esc beendet.",
        "redact": "Schwärzen: Bereiche ziehen. Esc beendet.",
        "stempel": "Stempel: Rahmen aufziehen. Esc beendet.",
        "sign_ink": "Unterschreiben: mit der Maus zeichnen. Esc beendet.",
        "sign_img": "Unterschrift-Bild: Rahmen aufziehen. Esc beendet.",
    }

    def _banner_aktualisieren(self) -> None:
        """Sichtbares Werkzeug-Banner über der Seite: Der Modus muss
        erkennbar sein UND beendbar (Esc/Knopf) – sonst ist man im
        Werkzeug „gefangen“ (Nutzerfund 09.09.2026). Das Banner ist
        permanent gepackt und wird über die Höhe ein-/ausgeblendet
        (Tk-Pack-Reihenfolge bleibt dadurch stabil)."""
        banner = getattr(self, "werkzeug_banner", None)
        if banner is None:
            return
        if self.mode == "normal":
            for kind in banner.winfo_children():
                kind.destroy()
            banner.pack_forget()
            return
        for kind in banner.winfo_children():
            kind.destroy()
        T = farben(getattr(self.app, "thema_modus", "hell"))
        banner.configure(highlightthickness=1,
                         highlightbackground=T["banner_rand"],
                         background=T["banner_bg"])
        text = self._BANNER_TEXTE.get(self.mode, "Werkzeug aktiv.")
        tk.Label(banner, text="🛠 " + text, background=T["banner_bg"],
                 foreground=T["banner_fg"], font=("", 10, "bold"),
                 anchor=tk.W
                 ).pack(side=tk.LEFT, fill=tk.X, expand=True,
                        padx=10, pady=3)
        tk.Button(banner, text="Fertig (Esc)", relief=tk.FLAT,
                  background=T["banner_bg"], foreground=T["banner_fg"],
                  activebackground=T["banner_aktiv"], font=("", 10, "bold"),
                  command=lambda: self.set_mode("normal")
                  ).pack(side=tk.RIGHT, padx=8, pady=3)
        banner.pack(side=tk.TOP, fill=tk.X, after=self.navbar)

    def _tool_down(self, event) -> None:
        # Offene Inline-Eingabe sauber beenden, damit kein FocusOut-
        # Commit das Rubber-Band zwischendurch wegwischt.
        if getattr(self, "_inline_entry", None):
            self._inline_commit()
        self._start = (self.canvas.canvasx(event.x),
                       self.canvas.canvasy(event.y))
        if self.mode in ("ink", "sign_ink"):
            self._ink_pts = [self._pdf_pt(*self._start)]
            self._ink_canvas = [self._start]
            self._ink_item = None
        elif self.mode == "feld_bewegen":
            self._verschiebe_greifen(self._start)
        elif self.mode == "polyform":
            self._poly_punkt_hinzu(self._start)
        elif self.mode == "schwenken":
            self.canvas.scan_mark(event.x, event.y)
        elif self.mode == "messen":
            self.canvas.delete("mess_linie")
            self.canvas.create_line(
                *self._start, *self._start, fill="#00897b", width=2,
                dash=(4, 3), tags="mess_linie")
        elif self.mode in ("highlight", "strikeout", "redact", "textfeld",
                          "text", "stempel", "sign_img", "underline",
                          "form", "bild", "link"):
            # SICHTBARES Zieh-Rechteck für jedes Rahmen-Werkzeug –
            # ohne Feedback wirkt das Werkzeug „tot“ (Nutzerfund
            # 09.09.2026: „das Einfügen von Textfeldern funktioniert
            # nicht“ – es fehlte jede Rückmeldung beim Ziehen).
            farbe = {"textfeld": "#1473e6", "text": "#1473e6",
                     "stempel": "#7b1fa2", "sign_img": "#00897b",
                     "underline": "#f2a600", "form": "#e53935",
                     "bild": "#2e7d32", "link": "#0d47a1"
                     }.get(self.mode, "#e53935")
            self._rubber = self.canvas.create_rectangle(
                *self._start, *self._start, outline=farbe, width=2,
                dash=(5, 4))

    def _on_canvas_drag(self, event) -> None:
        if self.mode == "normal" or not self.model:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if self.mode == "schwenken":
            self.canvas.scan_dragto(event.x, event.y, gain=1)
            return
        if self.mode == "messen":
            self.canvas.coords("mess_linie", *self._start, x, y)
            return
        if self.mode == "feld_bewegen" and \
                getattr(self, "_verschiebe_item", None) is not None:
            dx, dy = x - self._start[0], y - self._start[1]
            self.canvas.coords(
                "verschiebe_rahmen",
                self._verschiebe_x0 + dx, self._verschiebe_y0 + dy,
                self._verschiebe_x1 + dx, self._verschiebe_y1 + dy)
            return
        if self.mode in ("ink", "sign_ink") and self._ink_pts:
            self._ink_canvas.append((x, y))
            self._ink_pts.append(self._pdf_pt(x, y))
            self._pdf_drag_line()
        elif self._rubber is not None:
            self.canvas.coords(self._rubber, *self._start, x, y)

    def _pdf_drag_line(self) -> None:
        if self._ink_item is not None:
            self.canvas.delete(self._ink_item)
        pts: list[float] = []
        for (px, py) in getattr(self, "_ink_canvas", []):
            pts.extend([px, py])
        if len(pts) >= 4:
            self._ink_item = self.canvas.create_line(
                *pts, fill="#e53935", width=3, capstyle="round",
                smooth=True)

    def _on_canvas_release(self, event) -> None:
        if self.mode == "normal" or not self.model:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        modus, start = self.mode, self._start
        if self._rubber is not None:
            self.canvas.delete(self._rubber)
            self._rubber = None
        if self._ink_item is not None and modus != "ink":
            self.canvas.delete(self._ink_item)
            self._ink_item = None
        try:
            if modus in ("highlight", "strikeout"):
                rect = self._pdf_rect(start, (x, y))
                n = annotate.markieren(self.session, self.current_page,
                                       [rect],
                                       "highlight" if modus == "highlight"
                                       else "strikeout")
                if n:
                    self.model.edited = True
                    audit_mod.log(self.model,
                                  "Markiert" if modus == "highlight"
                                  else "Durchgestrichen",
                                  f"Seite {self.current_page + 1}")
                    self.app.set_status(f"✓ {n} Markierung(en) gesetzt – "
                                        "„Neue Version“ speichert sie.")
            elif modus == "sticky":
                px, py = self._pdf_pt(x, y)
                text = simpledialog.askstring(
                    "Haftnotiz", "Notiztext:", parent=self.canvas)
                if text:
                    annotate.haftnotiz(self.session, self.current_page,
                                       px, py, text)
                    self.model.edited = True
                    audit_mod.log(self.model, "Haftnotiz",
                                  f"Seite {self.current_page + 1}")
            elif modus == "polyform" and \
                    getattr(self, "_poly_art", "") == "legende" and \
                    len(getattr(self, "_poly_punkte", [])) >= 2:
                self._poly_legende(start, (x, y))
            elif modus == "feld_bewegen":
                self._verschiebe_loserlassen(x, y)
            elif modus == "ink":
                if self._ink_item is not None:
                    self.canvas.delete(self._ink_item)
                    self._ink_item = None
                annotate.freihand(self.session, self.current_page,
                                  self._ink_pts)
                self.model.edited = True
            elif modus == "redact":
                rect = self._pdf_rect(start, (x, y))
                self.redact_rects.append((self.current_page, rect))
                self.app.set_status(
                    f"Schwärzen: {len(self.redact_rects)} Bereich(e) "
                    "markiert – „Schwärzen anwenden“ entfernt den Inhalt "
                    "endgültig (neue Version).")
            elif modus == "text":
                rect = self._pdf_rect(start, (x, y))
                text = simpledialog.askstring(
                    "Text einfügen", "Text:", parent=self.canvas)
                if text:
                    annotate.text_einfuegen(self.session,
                                            self.current_page, rect, text)
                    self.model.edited = True
                    audit_mod.log(self.model, "Text eingefügt", text[:40])
            elif modus == "textfeld":
                gezogen = (abs(x - start[0]) >= 6
                           or abs(y - start[1]) >= 6)
                if not gezogen:
                    # Acrobat Fill & Sign: „Click on any field where
                    # you'd like the text to begin and start typing“ –
                    # ein Klick IN ein bestehendes Feld öffnet dieses
                    # direkt zum Weitertippen (kein neues Feld, kein
                    # Überlappungs-Streit).
                    px, py = self._pdf_pt(*start)
                    treffer = next(
                        (f for f in self.model.fields
                         if f.page == self.current_page and f.rect
                         and f.rect.contains(px, py, pad=3)), None)
                    if treffer is not None and not treffer.read_only:
                        self._inspect(treffer)
                        self._inline_edit(treffer)
                        self.app.set_status(
                            f"ℹ Feld „{treffer.label or treffer.name}“ "
                            "geöffnet – direkt eintippen.")
                        return
                rect = self._pdf_rect(start, (x, y))
                f = self.textfeld_einfuegen(rect)
                if f is None and not gezogen:
                    # Klick neben/innerhalb eines bestehenden Feldes:
                    # dieses öffnen statt ablehnen (Acrobat: Klick heißt
                    # bearbeiten). Erst das Überlappungs-Feld aus
                    # textfeld_einfuegen, dann der Klick-Punkt.
                    treffer = getattr(self, "_overlap_feld", None)
                    self._overlap_feld = None
                    if treffer is None:
                        px, py = self._pdf_pt(*start)
                        treffer = next(
                            (f2 for f2 in self.model.fields
                             if f2.page == self.current_page and f2.rect
                             and f2.rect.contains(px, py, pad=3)
                             and not f2.read_only), None)
                    if treffer is not None:
                        self._inspect(treffer)
                        self._inline_edit(treffer)
                        return
                if f is not None:
                    self.refresh_all()
                    self._render_page()
                    # Acrobat Fill & Sign: Klick setzt das Feld, getippt
                    # wird DIREKT am Ort (kein modaler Dialog). Esc oder
                    # Klick außerhalb beendet die Eingabe.
                    self._inline_edit(f)
                    self.app.set_status(
                        "✓ Textfeld gesetzt – jetzt direkt eintippen "
                        "(Enter übernimmt, Esc beendet).")
            elif modus == "underline":
                rect = self._pdf_rect(start, (x, y))
                n = annotate.markieren(self.session, self.current_page,
                                       [rect], art="underline")
                if n:
                    self.model.edited = True
                    audit_mod.log(self.model, "Unterstrichen",
                                  f"Seite {self.current_page + 1}")
                    self.app.set_status(
                        f"✓ {n}× unterstrichen – „Neue Version“ "
                        "speichert.")
            elif modus == "form":
                art = getattr(self, "_form_art", "linie")
                annotate.form_zeichnen(
                    self.session, self.current_page, art,
                    self._pdf_pt(*start), self._pdf_pt(x, y))
                self.model.edited = True
                audit_mod.log(self.model, "Form gezeichnet",
                              f"{art.capitalize()}, Seite "
                              f"{self.current_page + 1}")
                self.app.set_status(
                    f"✓ {art.capitalize()} gezeichnet – „Neue Version“ "
                    "speichert.")
            elif modus == "zeichen":
                if abs(x - start[0]) < 6 and abs(y - start[1]) < 6:
                    px, py = self._pdf_pt(*start)
                    zeichen = getattr(self, "_zeichen_art", "haekchen")
                    annotate.fuell_zeichen(self.session, self.current_page,
                                           px, py, zeichen)
                    self.model.edited = True
                    audit_mod.log(self.model, "Füllzeichen gesetzt",
                                  f"{zeichen}, Seite "
                                  f"{self.current_page + 1}")
                    self.app.set_status(
                        f"✓ {zeichen.capitalize()} gesetzt – „Neue "
                        "Version“ speichert.")
            elif modus == "bild":
                rect = self._pdf_rect(start, (x, y))
                pfad = filedialog.askopenfilename(
                    title="Bild wählen",
                    filetypes=[("Bilder", "*.png *.jpg *.jpeg *.bmp")])
                if pfad:
                    annotate.bild_einfuegen(self.session,
                                            self.current_page, rect, pfad)
                    self.model.edited = True
                    audit_mod.log(self.model, "Bild eingefügt",
                                  f"Seite {self.current_page + 1}")
                    self.app.set_status(
                        "✓ Bild eingefügt – „Neue Version“ speichert.")
            elif modus == "link":
                rect = self._pdf_rect(start, (x, y))
                ziel = simpledialog.askstring(
                    "Verknüpfung", "Ziel-Adresse (URL oder E-Mail):",
                    parent=self.canvas)
                if ziel:
                    annotate.link_hinzufuegen(self.session,
                                              self.current_page, rect, ziel)
                    self.model.edited = True
                    audit_mod.log(self.model, "Verknüpfung hinzugefügt",
                                  ziel[:40])
                    self.app.set_status(
                        f"✓ Verknüpfung auf {ziel[:40]} – „Neue Version“ "
                        "speichert.")
            elif modus == "messen":
                import math
                p0 = self._pdf_pt(*start)
                p1 = self._pdf_pt(x, y)
                dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
                cm = dist / 72.0 * 2.54
                self.canvas.delete("mess_linie")
                self.app.set_status(
                    f"Abstand: {dist:.1f} pt = {cm:.2f} cm "
                    f"({dist / 72:.2f} Zoll)")
            elif modus == "stempel":
                rect = self._pdf_rect(start, (x, y))
                art = simpledialog.askstring(
                    "Stempel",
                    "Art wählen: geprueft, vertraulich, entwurf, final,\n"
                    "freigegeben, kopie – oder eigener Text:", parent=self)
                if art:
                    art = art.strip().lower()
                    if art in annotate.STAMPS:
                        annotate.stempel(self.session, self.current_page,
                                         rect, art)
                    else:
                        annotate.stempel_text(self.session,
                                              self.current_page,
                                              rect, art.upper())
                    self.model.edited = True
                    audit_mod.log(self.model, "Stempel", art)
            elif modus == "sign_ink":
                if self._ink_item is not None:
                    self.canvas.delete(self._ink_item)
                    self._ink_item = None
                annotate.freihand_dick(self.session, self.current_page,
                                       self._ink_pts, breite=2.2)
                self.model.edited = True
                audit_mod.log(self.model, "Unterschrift gezeichnet",
                              f"Seite {self.current_page + 1}")
            elif modus == "sign_img":
                rect = self._pdf_rect(start, (x, y))
                bild = getattr(self, "_signatur_bild", None)
                if not bild:
                    bild = filedialog.askopenfilename(
                        title="Unterschrift-Bild wählen",
                        filetypes=[("Bilder", "*.png *.jpg *.jpeg")])
                else:
                    self._signatur_bild = None
                if bild:
                    self._unterschrift_einfuegen(rect, bild)
        except Exception as exc:                        # noqa: BLE001
            messagebox.showerror("Werkzeug", str(exc))
        self._render_page()

    def _pdf_pt(self, cx: float, cy: float) -> tuple[float, float]:
        scale = (150 * self.zoom) / 72.0
        return cx / scale, cy / scale

    def _pdf_rect(self, p0: tuple, p1: tuple) -> tuple:
        x0, y0 = self._pdf_pt(*p0)
        x1, y1 = self._pdf_pt(*p1)
        return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))

    @safe
    def apply_redactions(self) -> None:
        """Alle Schwärz-Bereiche anwenden und als NEUE Version speichern."""
        if self.session is None or not self.redact_rects:
            messagebox.showinfo("Schwärzen",
                                "Keine Schwärz-Bereiche markiert – zuerst "
                                "mit dem Werkzeug „Schwärzen“ Bereiche "
                                "ziehen.")
            return
        if not messagebox.askyesno(
                "Schwärzen anwenden",
                f"{len(self.redact_rects)} Bereich(e) endgültig schwärzen?\n"
                "Der Inhalt darunter wird entfernt und als NEUE Version "
                "gespeichert (Original bleibt unverändert)."):
            return
        for page, rect in self.redact_rects:
            annotate.redaktion_markieren(self.session, page, [rect])
        n = annotate.redaktion_anwenden(self.session)
        self.redact_rects.clear()
        self.model.edited = True
        audit_mod.log(self.model, "Geschwärzt (Redaktion)",
                      f"{n} Bereich(e)")
        self.save_version()

    @safe
    def delete_page(self) -> None:
        if self.session is None:
            return
        nr = self.current_page
        if not messagebox.askyesno(
                "Seite löschen", f"Seite {nr + 1} wirklich löschen?\n"
                "Gespeichert wird ausschließlich über „Neue Version“ "
                "(Original bleibt unverändert)."):
            return
        if annotate.seite_loeschen(self.session, [nr]) == 0:
            return
        if 0 <= nr < len(self.model.pages):
            self.model.pages.pop(nr)
        self.current_page = min(self.current_page,
                                max(0, len(self.model.pages) - 1))
        self.model.edited = True
        audit_mod.log(self.model, "Seite gelöscht", f"Seite {nr + 1}")
        self.refresh_all()

    @safe
    def extract_page(self) -> None:
        if self.session is None:
            return
        ziel = filedialog.asksaveasfilename(
            title="Seite extrahieren",
            defaultextension=".pdf",
            initialfile=f"Seite_{self.current_page + 1}.pdf",
            filetypes=[("PDF", "*.pdf")])
        if not ziel:
            return
        annotate.seite_extrahieren(self.session, self.current_page, ziel)
        audit_mod.log(self.model, "Seite extrahiert", ziel)
        self.app.set_status(f"✓ Seite {self.current_page + 1} extrahiert: "
                            f"{ziel}")

    @safe
    def merge_pdfs(self) -> None:
        if self.session is None:
            return
        pfade = filedialog.askopenfilenames(
            title="PDF-Dateien zum Zusammenführen auswählen",
            filetypes=[("PDF", "*.pdf")])
        if not pfade:
            return
        n = annotate.zusammenfuehren(self.session, list(pfade))
        while len(self.model.pages) < self.session.doc.page_count:
            self.model.pages.append(
                PageModel(number=len(self.model.pages)))
        self.model.edited = True
        audit_mod.log(self.model, "Zusammengeführt", f"{n} Datei(en)")
        self.refresh_all()
        self.app.set_status(f"✓ {n} Datei(en) angehängt – „Neue Version“ "
                            "speichert das Ergebnis.")

    @safe
    def save_encrypted(self) -> None:
        """AES-256-geschützte neue Version erzeugen (Acrobat „Schützen“)."""
        if self.session is None:
            return
        win = tk.Toplevel(self.app.root)
        win.title("Geschützte PDF-Datei erzeugen")
        ttk.Label(win, text="Passwort (min. 4 Zeichen):").grid(
            row=0, column=0, padx=8, pady=6, sticky=tk.W)
        var1 = tk.StringVar()
        var2 = tk.StringVar()
        ttk.Entry(win, textvariable=var1, show="*").grid(
            row=0, column=1, padx=8, pady=6)
        ttk.Label(win, text="Passwort wiederholen:").grid(
            row=1, column=0, padx=8, pady=6, sticky=tk.W)
        ttk.Entry(win, textvariable=var2, show="*").grid(
            row=1, column=1, padx=8, pady=6)
        ttk.Button(win, text="Erzeugen", command=win.destroy).grid(
            row=2, column=0, columnspan=2, pady=8)
        win.transient(self.app.root)
        win.grab_set()
        win.wait_window()
        pw = var1.get()
        if not pw or pw != var2.get():
            messagebox.showwarning("Schutz", "Passwörter fehlen oder "
                                   "stimmen nicht überein.")
            return
        from ..services.versioning import next_version_path
        ziel = next_version_path(self.path, suffix="_geschuetzt")
        result = annotate.speichern_verschluesselt(self.session, ziel, pw)
        audit_mod.log(self.model, "Geschützt gespeichert (AES-256)", ziel)
        messagebox.showinfo(
            "Geschützte PDF-Datei erzeugt",
            f"Datei: {result['pfad']}\n\n"
            f" Ohne Passwort gesperrt: "
            f"{'ja' if result['ohne_passwort_gesperrt'] else 'NEIN – prüfen!'}"
            "\nOriginal bleibt unverändert.")

    def _inspect(self, f: FieldModel) -> None:
        p = self.inspector_prop
        p["Element"].set(f.label or f.name)
        p["Typ"].set(f.field_type + (" (Pflicht)" if f.required else ""))
        p["Wert"].set("" if f.value is None else str(f.value))
        p["Quelle"].set(f.source)
        p["Konfidenz"].set(f"{round(f.confidence * 100, 1)} %")
        status = []
        if f.read_only:
            status.append("schreibgeschützt")
        if f.original_value != f.value:
            status.append("geändert")
        p["Status"].set(", ".join(status) or "unverändert")
        self.btn_edit.configure(state=tk.NORMAL
                                if not f.read_only else tk.DISABLED)
        self.selected_field = f

    def _inspect_word(self, w) -> None:
        p = self.inspector_prop
        p["Element"].set(f'Text: "{w.text}"')
        p["Typ"].set("Text")
        p["Wert"].set(w.text)
        p["Quelle"].set("OCR" if w.confidence < 100 else "Dokument")
        p["Konfidenz"].set(f"{round(w.confidence, 1)} %")
        p["Status"].set("")
        self.btn_edit.configure(state=tk.DISABLED)

    def _on_field_select(self, _event=None) -> None:
        sel = self.tree_fields.selection()
        if sel:
            f = self.model.field_by_id(sel[0])
            if f:
                self._inspect(f)
                if f.page != self.current_page:
                    self.current_page = f.page
                    self.page_list.selection_clear(0, tk.END)
                    self.page_list.selection_set(f.page)
                    self._render_page()

    @safe
    def _edit_selected(self) -> None:
        f = getattr(self, "selected_field", None)
        if f is None or self.session is None:
            return
        if f.field_type == "checkbox":
            new = not bool(f.value)
        else:
            new = simpledialog.askstring(
                "Feld bearbeiten",
                f'{f.label or f.name} ({f.field_type}):\n\nNeuer Wert:',
                initialvalue="" if f.value is None else str(f.value))
            if new is None:
                return
        old = f.value
        self._set_field_value(f, new)
        self.undo_stack.append({"feld": f.id, "alt": old, "neu": new})
        self.redo_stack.clear()
        audit_mod.log(self.model, "Feld geändert (manuell)",
                      f'"{f.label or f.name}"')
        self._autosave()
        self.refresh_all()
        self._render_page()

    def _set_field_value(self, f: FieldModel, value) -> None:
        f.value = value
        if f.source == "acroform" and self.engine is not None:
            self.engine.fill_fields(self.session, {f.id: value})
        elif self.engine is not None and f.rect is not None:
            ersetze = bool(getattr(f, "tinte_rect", None)) or \
                bool(f.original_value)
            linie = None
            if getattr(f, "linie_y1", 0.0):
                linie = (f.linie_y0, f.linie_y1)
            self.engine.queue_overlay(self.session, f.page, f.rect, value,
                                      f.field_type, f.font_size,
                                      ersetze=ersetze,
                                      tinte=getattr(f, "tinte_rect", None),
                                      linie=linie)
        self.model.edited = True

    @safe
    def undo(self) -> None:
        if not self.undo_stack:
            self.app.set_status("Nichts zum Rückgängigmachen.")
            return
        action = self.undo_stack.pop()
        f = self.model.field_by_id(action["feld"])
        if f is not None:
            self._set_field_value(f, action["alt"])
            if f.source != "acroform" and self.session is not None:
                self.session.pending_overlays = [
                    ov for ov in self.session.pending_overlays
                    if not (ov["page"] == f.page and ov["rect"] == f.rect
                            and ov["value"] == action["neu"])]
            if f.source == "acroform":
                self.redo_stack.append(action)
            else:
                self.redo_stack.append(action)
        self.refresh_all()
        self._render_page()
        self.app.set_status("Rückgängig: "
                            + (f.label if f else action["feld"]))

    @safe
    def redo(self) -> None:
        if not self.redo_stack:
            return
        action = self.redo_stack.pop()
        self.undo_stack.append(action)
        f = self.model.field_by_id(action["feld"])
        if f is not None:
            self._set_field_value(f, action["neu"])
        self.refresh_all()
        self._render_page()

    def _autosave(self) -> None:
        import json
        from ..paths import cache_dir
        from ..util import slugify
        try:
            path = os.path.join(
                cache_dir(), f"autosave_{slugify(self.model.name)}.json")
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.model.to_dict(), fh, ensure_ascii=False)
        except OSError:
            pass

    # ---------------------------------------------------- Aktionen
    @safe
    def auto_fill(self) -> None:
        prof = {k: v.get() for k, v in self.profile_vars.items()}
        # Falls Datentresor offen: Personendaten (geprüfte Daten) vorziehen
        vault = getattr(self.app, "vault", None)
        if vault is not None and vault.unlocked:
            pid = self.app.vault_person_waehlen()
            if pid is not None:
                prof = {**prof, **vault.export_profile(pid)}
        profile_service.save(prof)
        assignments = self.service.prepare_fill(self.model, prof)
        if not assignments:
            self.tabs.select(3)              # Reiter „Daten“ direkt öffnen
            if not self.model.fields:
                messagebox.showinfo(
                    "Automatische Befüllung",
                    "Es wurden noch keine ausfüllbaren Felder erkannt.\n\n"
                    "Bei Scans: „Analysieren“ laufen lassen (OCR liest das "
                    "Formular) oder Felder mit dem Haken „Felder markieren“ "
                    "selbst aufziehen.\n\n"
                    "Ihre Profildaten pflegen Sie im jetzt geöffneten "
                    "Reiter „Daten“.")
            else:
                messagebox.showinfo(
                    "Automatische Befüllung",
                    "Keine passenden Felder für die Profildaten gefunden.\n\n"
                    "Der Reiter „Daten“ ist jetzt geöffnet – dort Namen, "
                    "Anschrift, IBAN u. a. eintragen; gefundenen Feldern "
                    "können Sie auch einzeln über „Bearbeiten“ einen Wert "
                    "geben.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("Zuordnung prüfen und bestätigen")
        dlg.geometry("760x420")
        dlg.transient(self.winfo_toplevel())
        cols = ("Übernehmen", "Feld", "Wert", "Konfidenz", "Hinweis")
        tree = ttk.Treeview(dlg, columns=cols, show="headings")
        for col, width in zip(cols, (70, 190, 190, 80, 160)):
            tree.heading(col, text=col)
            tree.column(col, width=width)
        tree.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        for a in assignments:
            tree.insert("", tk.END, values=(
                "ja", a["feld"], str(a["wert"])[:34],
                f"{round(a['konfidenz'] * 100)} %",
                "bitte prüfen" if a["pruefen"] else ""))
        tree.bind("<Double-1>", lambda e: _toggle(tree))
        bar = ttk.Frame(dlg)
        bar.pack(fill=tk.X, pady=4)

        def _toggle(tree):
            sel = tree.selection()
            if sel:
                vals = list(tree.item(sel[0], "values"))
                vals[0] = "nein" if vals[0] == "ja" else "ja"
                tree.item(sel[0], values=vals)

        def _apply():
            chosen = []
            for item in tree.get_children():
                vals = tree.item(item, "values")
                if vals[0] == "ja":
                    idx = tree.index(item)
                    chosen.append(assignments[idx])
            dlg.destroy()
            if not chosen:
                self.app.set_status("Befüllung abgebrochen.")
                return
            self.service.apply_fill(self.model, self.session, self.engine,
                                    chosen)
            for a in chosen:
                self.undo_stack.append({"feld": a["feld_id"],
                                        "alt": None, "neu": a["wert"]})
            self.redo_stack.clear()
            self.refresh_all()
            self._render_page()
            self._autosave()
            messagebox.showinfo(
                "Automatische Befüllung",
                f"{len(chosen)} Felder befüllt.\n\nBitte prüfen und dann "
                "über „Neue Version erzeugen“ speichern.\nDas Original "
                "bleibt unverändert.")

        ttk.Button(bar, text="Alle übernehmen",
                   command=lambda: _all("ja")).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Keine übernehmen",
                   command=lambda: _all("nein")).pack(side=tk.LEFT)
        ttk.Button(bar, text="Zuordnung übernehmen", command=_apply
                   ).pack(side=tk.RIGHT, padx=4)

        def _all(state):
            for item in tree.get_children():
                vals = list(tree.item(item, "values"))
                vals[0] = state
                tree.item(item, values=vals)

    @safe
    def validate_now(self) -> None:
        from ..core.interfaces import IValidationEngine
        from ..core import registry
        registry.bootstrap()
        validator = registry.resolve(IValidationEngine)
        self.model.issues = validator.validate(self.model, self.session)
        audit_mod.log(self.model, "Validierung durchgeführt")
        self.refresh_all()
        counts = self.model.issue_counts()
        self.app.set_status(
            f"Validierung: {counts['fehler']} Fehler, "
            f"{counts['warnung']} Warnungen")
        self.tabs.select(2)

    @safe
    def _show_issue(self) -> None:
        sel = self.tree_issues.selection()
        if not sel:
            return
        idx = self.tree_issues.index(sel[0])
        issue = self.model.issues[idx]
        f = self.model.field_by_id(issue.field_id)
        if f is not None:
            if f.page != self.current_page:
                self.current_page = f.page
            self._render_page()
            self._inspect(f)
            self.tabs.select(1)
        else:
            messagebox.showinfo("Problem", issue.message +
                                ("\nVorschlag: " + issue.suggestion
                                 if issue.suggestion else ""))

    @safe
    def _autofix_issue(self) -> None:
        sel = self.tree_issues.selection()
        if not sel:
            return
        idx = self.tree_issues.index(sel[0])
        issue = self.model.issues[idx]
        from ..core import registry
        from ..core.interfaces import IValidationEngine
        validator = registry.resolve(IValidationEngine)
        if issue.auto_fix and validator.autofix(issue, self.model):
            audit_mod.log(self.model, "Automatisch korrigiert",
                          issue.code)
            self.model.issues = validator.validate(self.model, self.session)
            self.refresh_all()
            self.app.set_status("Automatisch korrigiert: " + issue.code)
        else:
            messagebox.showinfo(
                "Automatische Korrektur",
                "Für dieses Problem ist keine automatische Korrektur "
                "verfügbar.\n" + (issue.suggestion or ""))

    @safe
    def save_version(self) -> None:
        if self.session is None or self.engine is None:
            messagebox.showinfo("Version",
                                "Für dieses Format ist keine PDF-Version "
                                "möglich.")
            return
        result = self.service.save_new_version(self.model, self.session,
                                               self.engine)
        ok = result["pruefung"]["ok"]
        audit_mod.log(self.model, "Version gespeichert")
        self.refresh_all()
        if ok:
            messagebox.showinfo(
                "Neue Version erzeugt",
                f"Datei: {result['pfad']}\n\n"
                f"Verifikation: {result['pruefung']['seiten']} Seiten, "
                "Struktur OK.\nDas Original wurde nicht verändert.")
        else:
            messagebox.showwarning(
                "Neue Version erzeugt – mit Warnungen",
                f"Datei: {result['pfad']}\n\n"
                + "\n".join(result["pruefung"]["probleme"]))

    @safe
    def export(self) -> None:
        fmt = self.app.ask_export_format()
        if not fmt:
            return
        if fmt == "pdf":
            self.save_version()
            return
        base = os.path.splitext(self.model.path)[0]
        dest = filedialog.asksaveasfilename(
            initialdir=os.path.dirname(base),
            initialfile=os.path.basename(base) + "_export",
            defaultextension="." + fmt if fmt != "png" else "",
            filetypes=[(fmt.upper(), "*." + fmt)])
        if not dest:
            return
        result = ExportEngine().export(self.model, self.session, self.engine,
                                       fmt, dest)
        if result.get("ok"):
            messagebox.showinfo("Export",
                                f"Export erstellt:\n{result.get('pfad', dest)}")
        else:
            messagebox.showerror("Export",
                                 f"Fehlgeschlagen:\n{result.get('fehler')}")

    @safe
    def _compare(self) -> None:
        other = filedialog.askopenfilename(
            title="Vergleichsversion wählen",
            filetypes=[("Dokumente", "*.pdf *.txt *.docx *.rtf *.xlsx")])
        if not other:
            return
        self.app.set_status("Vergleiche …")

        def work():
            from ..engines.compare import compare_models, format_text_diff
            model_b, session_b, engine_b = self.service.open_document(other)
            self.service.analyze(model_b, session_b, engine_b)
            result = compare_models(self.model, model_b, self.session,
                                    session_b, self.engine)
            return format_text_diff(result), result

        def done(res):
            text, result = res
            self.txt_compare.configure(state=tk.NORMAL)
            self.txt_compare.delete("1.0", tk.END)
            self.txt_compare.insert("1.0", text)
            self.txt_compare.configure(state=tk.DISABLED)
            self.tabs.select(5)
            self.app.set_status("Vergleich abgeschlossen.")
        self.app.start_task(work, done)

    @safe
    def _rotate_page(self) -> None:
        if self.session is None:
            return
        self.engine.rotate_page(self.session, self.current_page, 90)
        self.model.edited = True
        audit_mod.log(self.model, "Seite rotiert",
                      f"Seite {self.current_page + 1}")
        self._render_page()

    @safe
    def _save_profile(self) -> None:
        prof = {k: v.get() for k, v in self.profile_vars.items()}
        profile_service.save(prof)
        self.app.set_status("Profil gespeichert (data\\profil.json).")

    @safe
    def _import_profile(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("Profil", "*.json *.csv"), ("Alle", "*.*")])
        if not path:
            return
        prof = profile_service.import_file(path)
        for key, var in self.profile_vars.items():
            var.set(prof.get(key, ""))
        profile_service.save({**prof})
        self.app.set_status("Profil importiert.")

    # ---------------------------------------------------- Suche/Zoom
    @safe
    def search(self, term: str) -> None:
        if not term:
            return
        self.search_hits = []
        scale = (150 * self.zoom) / 72.0
        page = self.model.pages[self.current_page]
        for w in page.words:
            if term.lower() in w.text.lower():
                self.search_hits.append((w.rect.x * scale, w.rect.y * scale,
                                         (w.rect.x + w.rect.width) * scale,
                                         (w.rect.y + w.rect.height) * scale))
        total = sum(1 for p in self.model.pages for w in p.words
                    if term.lower() in w.text.lower())
        self._render_page()
        self.app.set_status(f"Suche „{term}“: {len(self.search_hits)} Treffer "
                            f"auf Seite {self.current_page + 1}, "
                            f"{total} im Dokument.")

    def zoom_by(self, factor: float) -> None:
        self.zoom = min(4.0, max(0.4, self.zoom * factor))
        self.search_hits = []
        self._render_page()
        self.app.set_status(f"Zoom: {int(self.zoom * 100)} %")


class DocumentAIApp:
    def __init__(self):
        self.root = tk.Tk()
        # Versionsnummer IMMER sichtbar (Titelleiste + Taskleiste):
        # Der Nutzerfund 09.09.2026 zeigte einen Test gegen die ALTE
        # Version – ohne Anzeige sind Installations-Stände nicht
        # unterscheidbar.
        self.root.title(f"DocumentAI {APP_VERSION} – "
                        "Dokumentenintelligenz")
        self.root.geometry("1440x900")
        # Feder-Icon für Fenster + Taskbar (lokale Datei, kein Netz)
        self._icon_bild = None
        try:
            from PIL import Image, ImageTk
            _pfad = os.path.join(os.path.dirname(__file__), "..",
                                 "bilder", "feder_256.png")
            self._icon_bild = ImageTk.PhotoImage(file=_pfad,
                                                 master=self.root)
            self.root.iconphoto(True, self._icon_bild)
        except Exception:
            pass
        self.service = AnalysisService()
        self.thema_modus = thema_norm(
            config_mod.get("design.modus", "hell"))
        self._thema_bilder: dict[str, object] = {}
        self._thema_knöpfe: list = []
        self.vault = None                     # verschlüsselter Datentresor
        self.tasks: queue.Queue = queue.Queue()
        self._progress_events: deque = deque()
        self.views: list[DocumentView] = []
        self._build()
        self.root.after(120, self._poll_tasks)
        self.root.after(400, self._startup_selfcheck)

    # ------------------------------------------------------------ Aufbau
    def _build(self) -> None:
        self._stil()

        # ---------- Menüleiste (Acrobat-klassisch) ----------------------
        menue = tk.Menu(self.root)
        datei = tk.Menu(menue, tearoff=0)
        datei.add_command(label="Öffnen …", accelerator="Strg+O",
                          command=self.open_file)
        datei.add_command(label="Ordner öffnen …",
                          accelerator="Strg+Umschalt+O",
                          command=self.open_folder)
        datei.add_command(label="Zuletzt benutzte …",
                          command=self._recent_dialog)
        datei.add_separator()
        datei.add_command(label="Neue Version speichern", accelerator="Strg+S",
                          command=self._current_save)
        datei.add_command(label="Export …", command=self._current_export)
        datei.add_command(label="Als Text speichern …",
                          command=lambda: self._konvertieren("txt"))
        datei.add_command(label="In Word, Excel oder PowerPoint "
                                "konvertieren …",
                          command=self._konvertieren_dialog)
        datei.add_command(label="Dokumenteigenschaften …",
                          accelerator="Strg+D",
                          command=self._current_eigenschaften)
        datei.add_command(label="Drucken …", accelerator="Strg+P",
                          command=self._current_drucken)
        datei.add_separator()
        datei.add_command(label="Beenden", command=self.root.destroy)
        menue.add_cascade(label="Datei", menu=datei)

        bearb = tk.Menu(menue, tearoff=0)
        bearb.add_command(label="Automatisch befüllen", accelerator="Strg+B",
                          command=self._current_auto_fill)
        bearb.add_command(label="Validieren", command=self._current_validate)
        bearb.add_command(label="Rückgängig", accelerator="Strg+Z",
                          command=self._current_undo)
        bearb.add_command(label="Wiederholen", accelerator="Strg+Y",
                          command=self._current_redo)
        bearb.add_command(label="Vergleich …", command=self._current_compare)
        menue.add_cascade(label="Dokument", menu=bearb)

        ansicht = tk.Menu(menue, tearoff=0)
        ansicht.add_command(label="Zoom +", accelerator="Strg++",
                            command=lambda: self._zoom(1.25))
        ansicht.add_command(label="Zoom −", accelerator="Strg+-",
                            command=lambda: self._zoom(1 / 1.25))
        ansicht.add_command(label="Nächste Seite",
                            command=self._seite_naechste)
        ansicht.add_command(label="Vorherige Seite",
                            command=self._seite_vorherige)
        ansicht.add_separator()
        ansicht.add_command(label="Datentresor 🔒",
                            command=self.vault_person_waehlen)
        ansicht.add_command(label="Selbstdiagnose",
                            command=self.run_selfcheck)
        menue.add_cascade(label="Ansicht", menu=ansicht)
        # ACHTUNG: Menü wird NICHT als klassische Leiste montiert
        # („root.config(menu=…)“ verursacht unter Wine/Tk einen
        # Geometrie-Deadlock, sobald Inhalte gepackt sind – 04.09.2026
        # per 12-stufigem Bisect eingegrenzt, siehe Testbericht §19).
        # Stattdessen: Hamburger-Knopf „≡“ in der Kopfzeile (wie das
        # neue Acrobat, das keine klassische Menüleiste mehr hat).
        self._hauptmenue = menue

        # ---------- dunkle Kopfleiste: Logo + Tabs + Schnellzugriff -----
        kopf = tk.Frame(self.root, background="#26282e")
        kopf.pack(fill=tk.X)
        tk.Button(kopf, text="≡", bd=0, relief=tk.FLAT,
                  background="#26282e", foreground="white",
                  activebackground="#3a3d44", activeforeground="white",
                  font=("", 13), padx=8, pady=3,
                  command=self._menue_zeigen
                  ).pack(side=tk.LEFT, padx=(8, 0), pady=7)
        # Feder-Logo in der Kopfleiste: azurblau, transparenter
        # Hintergrund direkt auf dem dunklen Kopfband (Nutzerwunsch
        # 09.09.2026: Feder in Azurblau mit transparentem Hintergrund)
        self._logo_bild = None
        try:
            from PIL import Image, ImageTk
            _feder = os.path.join(os.path.dirname(__file__), "..",
                                  "bilder", "feder_64.png")
            self._logo_bild = ImageTk.PhotoImage(file=_feder, master=kopf)
            tk.Label(kopf, image=self._logo_bild, background="#26282e"
                     ).pack(side=tk.LEFT, padx=(10, 4))
        except Exception:
            pass                # ohne Bild bleibt der Schriftzug allein
        tk.Label(kopf, text="DocumentAI", background="#26282e",
                 foreground="white", font=("", 11, "bold")
                 ).pack(side=tk.LEFT, padx=(0, 16))
        self.tableiste = tk.Frame(kopf, background="#26282e")
        self.tableiste.pack(side=tk.LEFT, fill=tk.Y)

        self.search_var = tk.StringVar()
        entry = ttk.Entry(kopf, textvariable=self.search_var, width=20,
                          style="Kopf.TEntry")
        entry.pack(side=tk.RIGHT, padx=(6, 8), pady=7)
        entry.bind("<Return>", lambda e: self._search())
        # Schnellzugriff (Acrobat-Symbolleiste): Textfeld von Hand +
        # automatische Felderkennung - sofort sichtbar, nicht versteckt
        ttk.Button(kopf, text="Felderkennung ⚡", style="Kopf.TButton",
                   command=self._current_felder_auto
                   ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(kopf, text="Textfeld einfügen", style="Kopf.TButton",
                   command=self._current_textfeld
                   ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(kopf, text="Autom. befüllen", style="Kopf.TButton",
                   command=self._current_auto_fill
                   ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(kopf, text="Rückgängig", style="Kopf.TButton",
                   command=self._current_undo
                   ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(kopf, text="Drucken", style="Kopf.TButton",
                   command=self._current_drucken
                   ).pack(side=tk.RIGHT, padx=2)
        ttk.Button(kopf, text="Neue Version", style="Akzent.TButton",
                   command=self._current_save
                   ).pack(side=tk.RIGHT, padx=(2, 10))

        # ---------- Inhaltsbereich (Views) ------------------------------
        self.content = tk.Frame(self.root, background="#f5f5f7")
        self.content.pack(fill=tk.BOTH, expand=True)

        self.progress = ttk.Progressbar(self.root, mode="determinate",
                                        length=280)
        self.progress.pack(fill=tk.X, side=tk.BOTTOM, padx=6, pady=(0, 2))
        self.status = tk.Label(self.root, text="Bereit – Dokument öffnen "
                                    "über „Datei → Öffnen“. Alles lokal, "
                                    "keine Cloud.", background="#26282e",
                               foreground="#c9cdd4", anchor=tk.W, pady=3,
                               padx=8)
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

        # ---------- Tastaturkurzbefehle (Acrobat-Gewohnheiten) ----------
        self.root.bind("<Control-o>", lambda e: self.open_file())
        self.root.bind("<Control-O>", lambda e: self.open_folder())
        self.root.bind("<Control-s>", lambda e: self._current_save())
        self.root.bind("<Control-p>", lambda e: self._current_drucken())
        self.root.bind("<Control-b>", lambda e: self._current_auto_fill())
        self.root.bind("<Escape>", self._esc_alle)
        self.root.bind("<Control-z>", lambda e: self._current_undo())
        self.root.bind("<Control-y>", lambda e: self._current_redo())
        self.root.bind("<Control-plus>", lambda e: self._zoom(1.25))
        self.root.bind("<Control-minus>", lambda e: self._zoom(1 / 1.25))

    # --------------------------------------------------------- Tasks
    def start_task(self, work, done) -> None:
        result: dict = {}

        def runner():
            try:
                result["wert"] = work()
                result["ok"] = True
            except Exception as exc:               # noqa: BLE001
                result["fehler"] = exc
                result["ok"] = False

        threading.Thread(target=runner, daemon=True).start()

        def poll():
            if "ok" in result:
                if result["ok"]:
                    done(result["wert"])
                else:
                    self._task_error(result["fehler"])
                return
            self.root.after(120, poll)
        self.root.after(120, poll)

    def _task_error(self, exc) -> None:
        path = write_error_report(exc, action="Hintergrundaufgabe",
                                  component="gui")
        messagebox.showerror("DocumentAI – Fehler",
                             f"{getattr(exc, 'message', exc)}\n\n"
                             f"Fehlerbericht: {path}")

    def progress_cb(self, current, total) -> None:
        # Thread-sicher: kann aus Analyse-Threads gerufen werden.
        # Tk-Aufrufe sind aus Nebenthreads unzulässig (unter Windows
        # Deadlock-Gefahr) – daher nur Daten ablegen; die GUI wird
        # ausschließlich im Hauptthread über _poll_tasks aktualisiert.
        self._progress_events.append((current, total))

    def set_status(self, text: str) -> None:
        self.status.configure(text=text)

    # ------------------------------------------------ Hell/Dunkel-Design
    def _thema_wechseln(self) -> None:
        """Zwischen hellem und dunklem Design umschalten (Nutzerwunsch
        10.09.2026). Wahl wird gespeichert und beim Start wieder
        angewendet."""
        self._thema_anwenden("dunkel" if self.thema_modus == "hell"
                             else "hell")

    def _thema_anwenden(self, modus: str) -> None:
        self.thema_modus = thema_norm(modus)
        try:
            config_mod.set("design.modus", self.thema_modus)
        except Exception:
            pass
        T = farben(self.thema_modus)
        self._stil()

        # alte Palette -> neue Palette (Walker für tk.*-Widgets)
        mapa = {"#ffffff": T["panel"], "#26282e": T["kopf"],
                "#f5f5f7": T["seite"], "#eceef2": T["mitte"],
                "#d9dce1": T["trenner"], "#fff8e1": T["banner_bg"],
                "#eef1f5": T["knopf_aktiv"], "#3a3d44": T["kopf_knopf"]}
        fgmap = {"#1f2430": T["text"], "#c9cdd4": T["schine_text"],
                 "#8b909a": T["schine_kurz"], "#7a5c00": T["banner_fg"],
                 "#ffffff": "#ffffff"}

        def _walk(w):
            try:
                for kind in w.winfo_children():
                    _walk(kind)
            except Exception:
                return
            try:
                klasse = w.winfo_class()
                if klasse in ("Frame", "Button", "Label"):
                    bg = str(w.cget("background"))
                    if bg in mapa:
                        w.configure(background=mapa[bg])
                    if klasse in ("Button", "Label"):
                        fg = str(w.cget("foreground"))
                        if fg in fgmap:
                            w.configure(foreground=fgmap[fg])
                        if klasse == "Button":
                            ab = str(w.cget("activebackground"))
                            if ab in mapa:
                                w.configure(activebackground=mapa[ab])
                elif klasse == "Entry":
                    w.configure(background=T["panel"],
                                foreground=T["text"],
                                insertbackground=T["text"])
                elif klasse == "Text":
                    w.configure(background=T["kasten"],
                                foreground=T["text"],
                                insertbackground=T["text"])
                elif klasse == "Treeview":
                    w.configure(background=T["kasten"],
                                foreground=T["text"],
                                fieldbackground=T["kasten"])
            except Exception:
                pass

        _walk(self.root)
        try:
            self.content.configure(background=T["seite"])
            self.status.configure(background=T["kopf"],
                                  foreground=T["schine_text"])
            self.werkzeug_banner.configure(
                highlightbackground=T["banner_rand"])
            self._thema_symbol_setzen()
        except Exception:
            pass
        for view in self.views:
            try:
                view.canvas.configure(background=T["canvas"])
                view._banner_aktualisieren()
                view._render_page()
            except Exception:
                pass
        self.set_status(f"Design: {'dunkel' if self.thema_modus == 'dunkel' else 'hell'}")

    def _thema_symbol_setzen(self) -> None:
        """Umschalter-Knopf zeigt das GEGENTEILIGE Symbol an."""
        try:
            from PIL import ImageTk
            name = "sonne" if self.thema_modus == "dunkel" else "mond"
            farbe = "#f5c542" if name == "sonne" else "#9db4ff"
            bild = symbole.symbol_bild(name, farbe, 18)
            if bild is not None:
                self._thema_bilder["wechsel"] = ImageTk.PhotoImage(
                    bild, master=self.root)
                self._thema_knopf.configure(
                    image=self._thema_bilder["wechsel"], text="",
                    width=34, height=30)
                self._thema_knopf._thema_bild = \
                    self._thema_bilder["wechsel"]
            else:
                self._thema_knopf.configure(
                    text="◐", image="", width=34, height=30)
        except Exception:
            self._thema_knopf.configure(text="◐", image="")

    def _poll_tasks(self) -> None:
        # Fortschrittsereignisse aus Arbeitsthreads im Hauptthread anwenden
        while self._progress_events:
            current, total = self._progress_events.popleft()
            self.progress.configure(maximum=total, value=current)
        self.root.after(120, self._poll_tasks)

    # -------------------------------------------------------- Aktionen
    @safe
    def open_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Dokument öffnen",
            filetypes=[("Unterstützte Dokumente",
                        "*.pdf *.docx *.txt *.rtf *.xlsx *.png *.jpg"),
                       ("PDF", "*.pdf"), ("Alle Dateien", "*.*")])
        if path:
            self.add_document(path)

    @safe
    def open_folder(self) -> None:
        folder = filedialog.askdirectory(title="Ordner mit Dokumenten öffnen")
        if not folder:
            return
        docs = sorted(f for f in os.listdir(folder)
                      if f.lower().endswith((".pdf", ".docx", ".txt", ".rtf",
                                             ".xlsx")))
        if not docs:
            messagebox.showinfo("Ordner", "Keine unterstützten Dokumente "
                                          "gefunden.")
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Dokumente im Ordner")
        lb = tk.Listbox(dlg, selectmode=tk.MULTIPLE, width=70)
        for d in docs:
            lb.insert(tk.END, d)
        lb.pack(padx=8, pady=8)

        def _open_sel():
            chosen = [docs[i] for i in lb.curselection()]
            dlg.destroy()
            for name in chosen[:8]:
                self.add_document(os.path.join(folder, name))
        ttk.Button(dlg, text="Öffnen", command=_open_sel).pack(pady=6)

    def add_document(self, path: str) -> None:
        view = DocumentView(self.content, self, path)
        view.pack(in_=self.content, fill=tk.BOTH, expand=True)
        self.views.append(view)
        self._ansicht_wechseln(view)
        self._tab_band_aktualisieren()

    def _ansicht_wechseln(self, view: DocumentView) -> None:
        """Aktiven Dokument-Tab zeigen (Acrobat: Tabs in der Kopfzeile)."""
        self.view_aktiv = view
        self.root.title(f"{os.path.basename(view.path)} – "
                        f"DocumentAI {APP_VERSION}")
        for v in self.views:
            v.pack_forget()
        view.pack(in_=self.content, fill=tk.BOTH, expand=True)
        self._tab_band_aktualisieren()
        if view.model:
            view._update_statusbar()

    def _tab_band_aktualisieren(self) -> None:
        """Tab-Knöpfe (Dokumentname + ✕) in der dunklen Kopfzeile."""
        for alt_label in self.tableiste.winfo_children():
            alt_label.destroy()
        for v in self.views:
            aktiv = v is getattr(self, "view_aktiv", None)
            kasten = tk.Frame(self.tableiste,
                              background="#1473e6" if aktiv else "#26282e")
            kasten.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 2), pady=4)
            tab_knopf = tk.Button(
                kasten, text=os.path.basename(v.path)[:24],
                bd=0, relief=tk.FLAT,
                background="#1473e6" if aktiv else "#26282e",
                foreground="white" if aktiv else "#c9cdd4",
                activebackground="#3a3d44", activeforeground="white",
                padx=10, pady=4,
                command=lambda vv=v: self._ansicht_wechseln(vv))
            tab_knopf.pack(side=tk.LEFT)
            # Tabs per Drag neu anordnen (Acrobat: Ziehen in der Leiste)
            tab_knopf.bind(
                "<ButtonPress-1>",
                lambda e, vv=v: setattr(self, "_tab_drag",
                                        {"view": vv, "x0": e.x_root}))
            tab_knopf.bind(
                "<ButtonRelease-1>",
                lambda e, vv=v: self._tab_drag_ende(e, vv))
            tk.Button(kasten, text="✕", bd=0, relief=tk.FLAT,
                      background="#1473e6" if aktiv else "#26282e",
                      foreground="white" if aktiv else "#8b909a",
                      activebackground="#b71c1c", activeforeground="white",
                      padx=4, pady=4,
                      command=lambda vv=v: self._ansicht_schliessen(vv)
                      ).pack(side=tk.LEFT)

    def _ansicht_schliessen(self, view: DocumentView) -> None:
        """Dokument-Tab schließen – ungespeicherte Änderungen nachfragen."""
        if view.model and view.model.edited:
            if not messagebox.askyesno(
                    "Schließen",
                    "Es gibt ungespeicherte Änderungen. Trotzdem "
                    "schließen?"):
                return
        try:
            view.destroy()
        except Exception:
            pass
        if view in self.views:
            self.views.remove(view)
        if getattr(self, "view_aktiv", None) is view:
            self.view_aktiv = self.views[0] if self.views else None
            if self.view_aktiv:
                self._ansicht_wechseln(self.view_aktiv)
            else:
                self.set_status("Alle Dokumente geschlossen. Datei → "
                                "Öffnen … (Strg+O)")
                self.root.title(f"DocumentAI {APP_VERSION} – "
                                "Dokumentenintelligenz")
                self._tab_band_aktualisieren()
        else:
            self._tab_band_aktualisieren()

    def _current(self) -> DocumentView | None:
        return getattr(self, "view_aktiv", None)

    def _zoom(self, faktor: float) -> None:
        if (v := self._current()):
            v.zoom_by(faktor)

    def _seite_naechste(self) -> None:
        if (v := self._current()):
            v._seite_vor()

    def _seite_vorherige(self) -> None:
        if (v := self._current()):
            v._seite_zurueck()

    # -------------------------------------------------- Datentresor
    def vault_changed(self) -> None:
        """Benachrichtigt alle Tabs über Tresor-Änderungen."""
        for view in self.views:
            try:
                view.vault_panel.refresh()
            except Exception:
                pass

    def vault_person_waehlen(self):
        """Dialog: Person aus dem Tresor wählen (None = nur Profil-Tab)."""
        if self.vault is None or not self.vault.unlocked:
            return None
        personen = self.vault.list_persons()
        if not personen:
            return None
        dlg = tk.Toplevel(self.root)
        dlg.title("Person für Befüllung wählen")
        ttk.Label(dlg, text="Welche Person soll für die automatische "
                            "Befüllung verwendet werden?").pack(padx=12,
                                                               pady=(10, 4))
        var = tk.StringVar()
        werte = [f"{p['name']} ({p['rolle']})" if p["rolle"] else p["name"]
                 for p in personen] + ["Nur Profil-Tab (manuelle Daten)"]
        cmb = ttk.Combobox(dlg, textvariable=var, values=werte,
                           state="readonly", width=36)
        cmb.current(0)
        cmb.pack(padx=12, pady=4)
        ergebnis: list = []

        def _ok():
            ergebnis.append(cmb.current())
            dlg.destroy()
        ttk.Button(dlg, text="OK", command=_ok).pack(pady=8)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.wait_window()
        if not ergebnis or ergebnis[0] >= len(personen):
            return None
        return personen[ergebnis[0]]["id"]

    def _current_auto_fill(self) -> None:
        if (v := self._current()):
            v.auto_fill()

    def _current_validate(self) -> None:
        if (v := self._current()):
            v.validate_now()

    def _current_save(self) -> None:
        if (v := self._current()):
            v.save_version()

    # --- PDF-Werkzeuge an den aktiven Tab durchreichen ---------------
    def _tool_mode(self, modus: str) -> None:
        if (v := self._current()):
            v.set_mode(modus)

    # ═══════════════════ Extras (Acrobat-Pro, komplett lokal) ═════════
    def _ansicht_oder_info(self) -> DocumentView | None:
        """Aktive Ansicht oder Informationsdialog, wenn nichts offen."""
        v = self._current()
        if v is None or v.session is None or v.model is None:
            messagebox.showinfo(
                "Werkzeuge", "Bitte zuerst ein PDF-Dokument öffnen – "
                "die Werkzeuge arbeiten auf dem geöffneten Dokument.")
            return None
        return v

    def _current_wasserzeichen(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        text = simpledialog.askstring(
            "Wasserzeichen", "Text des Wasserzeichens:",
            initialvalue="KOPIE")
        if not text:
            return
        from ..engines import annotate
        n = annotate.wasserzeichen(v.session, text)
        v.model.edited = True
        audit_mod.log(v.model, "Wasserzeichen", text[:40])
        v._render_page()
        self.set_status(f"✓ Wasserzeichen auf {n} Seite(n) – „Neue "
                        "Version“ speichert es.")

    def _current_kopf_fuss(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        kopf = simpledialog.askstring("Kopfzeile", "Kopfzeilentext "
                                      "(leer = keine):") or ""
        fuss = simpledialog.askstring("Fußzeile", "Fußzeilentext "
                                  "(leer = keine):") or ""
        seitenzahl = messagebox.askyesno("Seitenzahlen",
                                         "Seitenzahlen hinzufügen?")
        bates = ""
        if messagebox.askyesno("Bates", "Bates-Nummerierung statt "
                               "Fußzeile? (Kanzlei-Standard)"):
            bates = simpledialog.askstring("Bates", "Präfix:",
                                           initialvalue="AKTE") or ""
        from ..engines import annotate
        n = annotate.kopf_fusszeile(v.session, kopf, fuss, seitenzahl, bates)
        v.model.edited = True
        audit_mod.log(v.model, "Kopf-/Fußzeile",
                      f"{kopf!r}/{fuss!r}/S={seitenzahl}/B={bates}")
        v._render_page()
        self.set_status(f"✓ Kopf-/Fußzeilen auf {n} Seite(n) gesetzt.")

    def _current_suchschwarz(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        begriff = simpledialog.askstring(
            "Suchen & schwärzen", "Diesen Text überall suchen und "
            "ENDGÜLTIG entfernen:", initialvalue="")
        if not begriff:
            return
        if not messagebox.askyesno(
                "Suchen & schwärzen",
                f"Jedes Vorkommen von „{begriff}“ auf allen Seiten "
                "endgültig entfernen? Es wird eine neue Version erzeugt."):
            return
        from ..engines import annotate
        from ..services import versioning
        n = annotate.suchen_und_schwaerzen(v.session, begriff)
        if n:
            versioning.backup_original(v.model)
            res = v.engine.save_version(v.session, v.model,
                                        "Suchen & schwärzen")
            v.session.saved_versions.append(res["pfad"])
            v._render_page()
            self.set_status(f"✓ {n} Vorkommen von „{begriff}“ entfernt → "
                            + res["pfad"])
        else:
            self.set_status(f"Kein Vorkommen von „{begriff}“ gefunden.")

    def _current_signieren(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Signieren (lokal, ohne Cloud)")
        dlg.geometry("440x220")
        dlg.configure(background="#ffffff")
        ttk.Label(dlg, text="Wie möchten Sie unterschreiben?",
                  font=("Segoe UI", 11, "bold")).pack(pady=(14, 4))
        ttk.Label(dlg, text="Alles lokal – keine Cloud, kein Konto, das "
                  "Zertifikat verlässt Ihren Rechner nie.",
                  foreground="#5a6472").pack()

        def zeichnen():
            dlg.destroy()
            from .signatur_pad import SignaturPad
            import tempfile

            def uebernehmen(png_bytes):
                with tempfile.NamedTemporaryFile(
                        suffix=".png", delete=False) as tmp:
                    tmp.write(png_bytes)
                    v._signatur_bild = tmp.name
                v.set_mode("sign_img")

            def speichern(name, png_bytes):
                from ..services import unterschriften
                pfad = unterschriften.speichern(name, png_bytes)
                return pfad.split(os.sep)[-1]

            SignaturPad(self.root, uebernehmen, speichern)

        def gespeichert():
            dlg.destroy()
            self._unterschrift_auswaehlen(v)

        def bild():
            dlg.destroy()
            v.set_mode("sign_img")

        def digital():
            dlg.destroy()
            try:
                from ..services import signing, versioning
                versioning.backup_original(v.model)
                ziel = versioning.next_version_path(v.model.path,
                                                    suffix="_signiert")
                signing.digital_signieren(v.session, ziel)
                v.session.saved_versions.append(ziel)
                audit_mod.log(v.model, "Digital signiert", ziel)
                info = signing.signatur_info(ziel)
                messagebox.showinfo(
                    "Digitale Signatur",
                    f"Signiert (PAdES) und gespeichert:\n{ziel}\n\n"
                    f"Prüfung: {info.get('status')}\n"
                    f"{info.get('detail', '')[:180]}")
                self.set_status("✓ Digital signiert: " + ziel)
            except Exception as exc:                  # noqa: BLE001
                messagebox.showerror("Signieren",
                                     "Digitale Signatur fehlgeschlagen:\n"
                                     + str(exc))

        bar = ttk.Frame(dlg)
        bar.pack(pady=12)
        ttk.Button(bar, text="✍ Mit Stift/Maus zeichnen",
                   style="Werk.TButton",
                   command=zeichnen).pack(side=tk.LEFT, padx=4)
        from ..services import unterschriften as _us
        _n = len(_us.liste())
        ttk.Button(bar, text=f"🗂 Gespeicherte Unterschrift… ({_n})",
                   style="Werk.TButton",
                   command=gespeichert).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="Bild einfügen", style="Werk.TButton",
                   command=bild).pack(side=tk.LEFT, padx=4)
        ttk.Button(dlg, text="🔐 Digitale Signatur", style="Akzent.TButton",
                   command=digital).pack(pady=2)
        ttk.Button(dlg, text="Abbrechen", style="Werk.TButton",
                   command=dlg.destroy).pack(pady=4)

    def _unterschrift_auswaehlen(self, v) -> None:
        """Auswahl gespeicherter Unterschriften (Acrobat-Stil: Vorschau,
        wiederverwenden, löschen). Mehrfach gespeicherte Unterschriften
        bleiben lokal im Konfigurationsordner."""
        from ..services import unterschriften
        eintraege = unterschriften.liste()
        dlg = tk.Toplevel(self.root)
        dlg.title("Gespeicherte Unterschriften")
        dlg.geometry("460x330")
        dlg.configure(background="#ffffff")
        if not eintraege:
            ttk.Label(dlg, text="Noch keine Unterschriften gespeichert.\n\n"
                      "Im Signieren-Dialog „Mit Stift/Maus zeichnen“ "
                      "wählen,\nzeichnen und dort „Für Wiederverwendung "
                      "speichern“.", foreground="#5a6472"
                      ).pack(pady=30)
            ttk.Button(dlg, text="Schließen", style="Werk.TButton",
                       command=dlg.destroy).pack()
            return
        ttk.Label(dlg, text="Gespeicherte Unterschriften (lokal):",
                  font=("Segoe UI", 11, "bold")).pack(pady=(10, 4))
        box = ttk.Frame(dlg)
        box.pack(fill=tk.BOTH, expand=True, padx=12)
        liste = tk.Listbox(box, width=28, activestyle="dotbox")
        liste.pack(side=tk.LEFT, fill=tk.Y)
        vorschau = tk.Canvas(box, width=180, height=120,
                             background="#ffffff", highlightthickness=1,
                             highlightbackground="#d8dce4")
        vorschau.pack(side=tk.LEFT, padx=8, fill=tk.Y)
        foto = [None]

        def zeigen(_e=None):
            sel = liste.curselection()
            if not sel:
                return
            pfad = eintraege[sel[0]]["pfad"]
            try:
                from PIL import Image, ImageTk
                img = Image.open(pfad).convert("RGBA")
                hintergrund = Image.new("RGBA", img.size,
                                        (255, 255, 255, 255))
                komposit = Image.alpha_composite(hintergrund, img)
                komposit.thumbnail((170, 110))
                foto[0] = ImageTk.PhotoImage(komposit)
                vorschau.delete("all")
                vorschau.create_image(90, 60, image=foto[0])
            except Exception:
                vorschau.delete("all")
                vorschau.create_text(90, 60, text="keine Vorschau",
                                     fill="#9aa2b4")

        for eintrag in eintraege:
            liste.insert(tk.END,
                         f'{eintrag["name"]}  ({eintrag["datum"]})')
        liste.selection_set(0)
        liste.bind("<<ListboxSelect>>", zeigen)
        zeigen()

        def verwenden():
            sel = liste.curselection()
            if sel:
                v._signatur_bild = eintraege[sel[0]]["pfad"]
                dlg.destroy()
                v.set_mode("sign_img")

        def loeschen():
            sel = liste.curselection()
            if not sel:
                return
            name = eintraege[sel[0]]["name"]
            if messagebox.askyesno(
                    "Unterschrift löschen",
                    f'Gespeicherte Unterschrift "{name}" wirklich '
                    "löschen?"):
                unterschriften.loeschen(name)
                dlg.destroy()
                self._unterschrift_auswaehlen(v)

        leiste = ttk.Frame(dlg)
        leiste.pack(pady=8)
        ttk.Button(leiste, text="✍ Verwenden", style="Akzent.TButton",
                   command=verwenden).pack(side=tk.LEFT, padx=4)
        ttk.Button(leiste, text="🗑 Löschen", style="Werk.TButton",
                   command=loeschen).pack(side=tk.LEFT, padx=4)
        ttk.Button(leiste, text="Schließen", style="Werk.TButton",
                   command=dlg.destroy).pack(side=tk.LEFT, padx=4)

    def _current_move_page(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        von = simpledialog.askinteger(
            "Seite verschieben", "Welche Seite? (1-"
            f"{v.model.pages and len(v.model.pages)})",
            parent=self.root, minvalue=1, maxvalue=len(v.model.pages))
        if von is None:
            return
        nach = simpledialog.askinteger(
            "Seite verschieben", f"Seite {von} EINFÜGEN VOR welche "
            "Seite? (0 = ganz nach vorn)", parent=self.root,
            minvalue=0, maxvalue=len(v.model.pages))
        if nach is None:
            return
        from ..engines import annotate
        try:
            annotate.seite_verschieben(v.session, von - 1, nach - 1)
            v.model.edited = True
            audit_mod.log(v.model, "Seite verschoben", f"{von} → {nach}")
            v.refresh_all()
            v._render_page()
            self.set_status(f"✓ Seite {von} vor Position {nach} "
                            "verschoben – „Neue Version“ speichert.")
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror("Seite verschieben", str(exc))

    def _current_drehen(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        von = simpledialog.askinteger("Seiten drehen", "Von Seite:",
                                      parent=self.root, minvalue=1,
                                      maxvalue=len(v.model.pages),
                                      initialvalue=1)
        if von is None:
            return
        bis = simpledialog.askinteger("Seiten drehen", "Bis Seite:",
                                      parent=self.root, minvalue=von,
                                      maxvalue=len(v.model.pages),
                                      initialvalue=von)
        if bis is None:
            return
        grad = simpledialog.askinteger("Seiten drehen", "Grad (90/180/270):",
                                       parent=self.root, minvalue=90,
                                       maxvalue=270, initialvalue=90)
        from ..engines import annotate
        n = annotate.seiten_drehen(v.session, von - 1, bis - 1, grad or 90)
        v.model.edited = True
        audit_mod.log(v.model, "Seiten gedreht", f"{von}–{bis} um {grad}°")
        v._render_page()
        self.set_status(f"✓ {n} Seite(n) gedreht – „Neue Version“ speichert.")

    def _current_leerseite(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        pos = simpledialog.askinteger(
            "Leerseite einfügen", "Einfügen VOR welche Seite? "
            f"(1-{len(v.model.pages)}, 0 = ans Ende)", parent=self.root,
            minvalue=0, maxvalue=len(v.model.pages))
        if pos is None:
            return
        from ..engines import annotate
        annotate.leerseite_einfuegen(v.session, pos)
        v.model.edited = True
        audit_mod.log(v.model, "Leerseite eingefügt", f"vor {pos}")
        v.refresh_all()
        v._render_page()
        self.set_status("✓ Leere Seite eingefügt – „Neue Version“ speichert.")

    def _current_aus_pdf(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        quelle = filedialog.askopenfilename(
            title="PDF wählen, dessen Seiten eingefügt werden",
            filetypes=[("PDF", "*.pdf")])
        if not quelle:
            return
        pos = simpledialog.askinteger(
            "Aus PDF einfügen", f"Einfügen VOR welche Seite? "
            f"(1-{len(v.model.pages)}, 0 = ans Ende)", parent=self.root,
            minvalue=0, maxvalue=len(v.model.pages))
        if pos is None:
            return
        from ..engines import annotate
        try:
            n = annotate.seite_einfuegen_aus_pdf(v.session, quelle, pos)
            v.model.edited = True
            audit_mod.log(v.model, "Seiten aus PDF eingefügt", quelle)
            v.refresh_all()
            v._render_page()
            self.set_status(f"✓ {n} Seite(n) aus {os.path.basename(quelle)} "
                            "eingefügt – „Neue Version“ speichert.")
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror("Aus PDF einfügen", str(exc))

    def _current_zuschneiden(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        mm = simpledialog.askfloat(
            "Zuschneiden", "Rand ringsum abtrennen (in Millimeter):",
            parent=self.root, minvalue=0.0, maxvalue=100.0,
            initialvalue=5.0)
        if mm is None:
            return
        pt = mm * 72 / 25.4
        from ..engines import annotate
        try:
            alle = messagebox.askyesno(
                "Zuschneiden", "Alle Seiten zuschneiden? (Nein = nur "
                f"Seite {v.current_page + 1})")
            if alle:
                for i in range(len(v.model.pages)):
                    annotate.zuschneiden(v.session, i, (pt, pt, pt, pt))
            else:
                annotate.zuschneiden(v.session, v.current_page,
                                     (pt, pt, pt, pt))
            v.model.edited = True
            audit_mod.log(v.model, "Zugeschnitten", f"{mm} mm")
            v._render_page()
            self.set_status(f"✓ {mm} mm Rand abgetrennt – „Neue Version“ "
                            "speichert.")
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror("Zuschneiden", str(exc))

    def _current_hintergrund(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        wahl = simpledialog.askstring(
            "Hintergrundfarbe", "Farbe wählen: blau, grau, grün, gelb, "
            "rosa – oder leer lassen zum Deaktivieren:")
        farben = {"blau": (0.92, 0.95, 1.0), "grau": (0.93, 0.93, 0.94),
                  "grün": (0.92, 0.97, 0.92), "gelb": (0.99, 0.98, 0.90),
                  "rosa": (0.99, 0.94, 0.96)}
        from ..engines import annotate
        if wahl is None:
            return
        wahl = wahl.strip().lower()
        if wahl in farben:
            annotate.hintergrund(v.session, farben[wahl])
            v.model.edited = True
            audit_mod.log(v.model, "Hintergrundfarbe", wahl)
            v._render_page()
            self.set_status(f"✓ Hintergrundfarbe „{wahl}“ hinterlegt – "
                            "„Neue Version“ speichert.")
        else:
            self.set_status("Hintergrund: unbekannte Farbe – blau/grau/"
                            "grün/gelb/rosa sind verfügbar.")

    def _current_lesezeichen(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        titel = simpledialog.askstring(
            "Lesezeichen", f"Titel für Seite {v.current_page + 1}:",
            initialvalue=f"Seite {v.current_page + 1}")
        if not titel:
            return
        from ..engines import annotate
        annotate.lesezeichen_hinzufuegen(v.session, titel, v.current_page)
        v.model.edited = True
        audit_mod.log(v.model, "Lesezeichen", titel)
        v._panel_zeigen("lesezeichen")
        self.set_status(f"✓ Lesezeichen „{titel}“ gesetzt – „Neue "
                        "Version“ speichert es.")

    def _konvertieren_dialog(self) -> None:
        """Acrobat-Menü „In Word, Excel oder PowerPoint konvertieren“:
        kleines Auswahl-Fenster, dann direkt speichern."""
        fenster = tk.Toplevel(self.root)
        fenster.title("Dokument konvertieren")
        fenster.geometry("360x220")
        fenster.transient(self.root)
        rahmen = ttk.Frame(fenster, padding=14)
        rahmen.pack(fill=tk.BOTH, expand=True)
        ttk.Label(rahmen, text="Zielformat wählen:",
                  font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 8))
        for fmt, name in (("docx", "Microsoft Word (.docx)"),
                          ("xlsx", "Microsoft Excel (.xlsx)"),
                          ("pptx", "Microsoft PowerPoint (.pptx)"),
                          ("rtf", "Rich Text Format (.rtf)"),
                          ("txt", "Textdatei (.txt)")):
            ttk.Button(rahmen, text=name,
                       command=lambda f=fmt: (fenster.destroy(),
                                              self._konvertieren(f))
                       ).pack(fill=tk.X, pady=2)

    def _current_feld_verschieben(self) -> None:
        """Erkannte Felder mit der Maus verschieben (Nutzerwunsch
        10.09.2026: erkannte Textfelder neu positionieren)."""
        view = self._current()
        if view is None or view.model is None:
            messagebox.showinfo(
                "Feld verschieben",
                "Bitte zuerst ein Dokument öffnen.")
            return
        view.set_mode("feld_bewegen" if view.mode != "feld_bewegen"
                      else "normal")

    def _begrenzungsrahmen(self) -> None:
        """Acrobat „Begrenzungsrahmen anzeigen“: Objektgrenzen der
        aktuellen Seite ein-/ausblenden (Text/Bild/Grafik)."""
        view = self._current()
        if view is None or view.session is None:
            messagebox.showinfo("Begrenzungsrahmen",
                                "Bitte zuerst ein Dokument öffnen.")
            return
        view._bbox_an = not getattr(view, "_bbox_an", False)
        if view._bbox_an:
            view._bbox_zeichnen()
            self.set_status("Begrenzungsrahmen AN: blau = Text, "
                            "grün = Bilder, orange = Grafik.")
        else:
            view.canvas.delete("bbox")
            self.set_status("Begrenzungsrahmen aus.")

    def _konvertieren(self, fmt: str) -> None:
        """Acrobat „Konvertieren“: PDF nach Word/Excel/PowerPoint/
        Text/RTF – komplett lokal."""
        view = self._current()
        if view is None or view.model is None:
            messagebox.showinfo("Konvertieren",
                                "Bitte zuerst ein Dokument öffnen.")
            return
        von = view.model.name or "dokument"
        endungen = {"docx": ".docx", "xlsx": ".xlsx", "pptx": ".pptx",
                    "txt": ".txt", "rtf": ".rtf"}
        ziel = filedialog.asksaveasfilename(
            defaultextension=endungen[fmt],
            initialfile=os.path.splitext(von)[0] + endungen[fmt],
            filetypes=[({"docx": "Word-Dokument", "xlsx": "Excel-Tabelle",
                         "pptx": "PowerPoint-Präsentation",
                         "txt": "Textdatei",
                         "rtf": "Rich Text Format"}[fmt],
                        "*" + endungen[fmt])])
        if not ziel:
            return
        from ..engines.exporter import ExportEngine
        ergebnis = ExportEngine().export(view.model, view.session,
                                         view.engine, fmt, ziel)
        if ergebnis.get("ok"):
            audit_mod.log(view.model, "Konvertiert",
                          f"{fmt.upper()}: {os.path.basename(ziel)}")
            messagebox.showinfo(
                "Konvertieren",
                "✓ Gespeichert:\n" + ziel)
            self.set_status(f"✓ Konvertiert nach {fmt.upper()}: " + ziel)
        else:
            messagebox.showerror("Konvertieren",
                                 ergebnis.get("fehler", "Fehlgeschlagen."))

    def _current_zertifikat(self) -> None:
        """Acrobat „Zertifizierte Kopie speichern“: schreibgeschützte,
        versiegelte Kopie (AES-256) – lesbar für alle, änderbar für
        niemanden."""
        view = self._current()
        if view is None or view.session is None:
            messagebox.showinfo("Zertifizierte Kopie",
                                "Bitte zuerst ein Dokument öffnen.")
            return
        von = view.model.name or "dokument.pdf"
        ziel = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            initialfile=os.path.splitext(von)[0] + "_zertifiziert.pdf",
            filetypes=[("PDF", "*.pdf")])
        if not ziel:
            return
        try:
            from ..engines import annotate
            info = annotate.zertifizierte_kopie(view.session, ziel)
        except Exception as exc:                        # noqa: BLE001
            messagebox.showerror("Zertifizierte Kopie", str(exc))
            return
        audit_mod.log(view.model, "Zertifizierte Kopie",
                      os.path.basename(ziel))
        messagebox.showinfo(
            "Zertifizierte Kopie",
            "✓ Versiegelte Kopie gespeichert:\n" + ziel +
            "\n\nSie ist für jeden lesbar und druckbar, aber "
            "schreibgeschützt (AES-256).")
        self.set_status("✓ Zertifizierte Kopie: " + ziel)

    def _current_eigenschaften(self) -> None:
        """Acrobat „Datei > Dokumenteigenschaften“ (Strg+D): Metadaten
        ansehen und bearbeiten – Titel, Autor, Thema, Schlagwörter."""
        view = self._current()
        if view is None or view.session is None:
            messagebox.showinfo("Dokumenteigenschaften",
                                "Bitte zuerst ein Dokument öffnen.")
            return
        from ..engines import annotate
        md = annotate.metadaten_lesen(view.session)
        fenster = tk.Toplevel(self.root)
        fenster.title("Dokumenteigenschaften – " +
                      (view.model.name or "Dokument"))
        fenster.geometry("480x430")
        fenster.transient(self.root)
        rahmen = ttk.Frame(fenster, padding=14)
        rahmen.pack(fill=tk.BOTH, expand=True)
        felder = {}
        for schluessel, label, vorbelegt in (
                ("title", "Titel:", md.get("title", "")),
                ("author", "Autor:", md.get("author", "")),
                ("subject", "Thema:", md.get("subject", "")),
                ("keywords", "Schlagwörter:", md.get("keywords", ""))):
            ttk.Label(rahmen, text=label).pack(anchor=tk.W, pady=(6, 0))
            var = tk.StringVar(value=vorbelegt or "")
            ttk.Entry(rahmen, textvariable=var, width=62).pack(
                fill=tk.X)
            felder[schluessel] = var
        info = ttk.LabelFrame(rahmen, text="Allgemein", padding=8)
        info.pack(fill=tk.X, pady=10)
        groesse = "?"
        try:
            groesse = f"{os.path.getsize(view.model.path) / 1024:.0f} KB"
        except OSError:
            pass
        for text in (f"Dokument:  {view.model.name or '?'}",
                     f"Seiten:  {md.get('seiten', '?')}",
                     f"Größe:  {groesse}",
                     f"PDF-Producer:  {md.get('producer') or '?'}",
                     f"Verschlüsselt:  "
                     f"{'ja' if md.get('verschluesselt') else 'nein'}"):
            ttk.Label(info, text=text).pack(anchor=tk.W)

        def _speichern() -> None:
            try:
                annotate.metadaten_setzen(
                    view.session,
                    titel=felder["title"].get(),
                    autor=felder["author"].get(),
                    thema=felder["subject"].get(),
                    schlagworte=felder["keywords"].get())
                view.model.edited = True
                audit_mod.log(view.model, "Eigenschaften bearbeitet",
                              felder["title"].get()[:40] or "(ohne Titel)")
                self.set_status("✓ Dokumenteigenschaften gespeichert "
                                "(mit „Neue Version“ sichern).")
            except Exception as exc:                    # noqa: BLE001
                messagebox.showerror("Dokumenteigenschaften", str(exc))
                return
            fenster.destroy()

        ttk.Button(rahmen, text="Speichern", command=_speichern).pack(
            side=tk.RIGHT, padx=(0, 6))
        ttk.Button(rahmen, text="Schließen",
                   command=fenster.destroy).pack(side=tk.RIGHT)
        fenster.grab_set()

    def _current_optimieren(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        from ..engines import annotate
        from ..services import versioning
        import os
        versioning.backup_original(v.model)
        ziel = versioning.next_version_path(v.model.path,
                                            suffix="_optimiert")
        erg = annotate.optimieren(v.session, ziel)
        v.session.saved_versions.append(ziel)
        audit_mod.log(v.model, "Optimiert", erg["pfad"])
        alt = os.path.getsize(v.model.path)
        self.set_status(f"✓ Optimiert: {alt/1024:.0f} KB → "
                        f"{erg['bytes']/1024:.0f} KB → {ziel}")

    def _current_flatten(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        from ..engines import annotate
        n = annotate.formular_abflachen(v.session, v.model)
        v.model.edited = True
        audit_mod.log(v.model, "Formular abgeflacht", f"{n} Felder")
        v.refresh_all()
        v._render_page()
        self.set_status(f"✓ {n} Formularfeld(er) zu festem Inhalt gemacht "
                        "– „Neue Version“ speichert.")

    def _current_anhang(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        pfade = filedialog.askopenfilenames(
            title="Datei(en) als PDF-Anhang einbetten")
        if not pfade:
            return
        from ..engines import annotate
        for pfad in pfade:
            annotate.anhang_einbetten(v.session, pfad)
        v.model.edited = True
        audit_mod.log(v.model, "Anhang eingebettet", f"{len(pfade)} Datei(en)")
        v._panel_zeigen("anhaenge")
        self.set_status(f"✓ {len(pfade)} Anhang/Anhänge eingebettet – "
                        "„Neue Version“ speichert.")

    def _current_als_bilder(self) -> None:
        v = self._ansicht_oder_info()
        if not v:
            return
        ordner = filedialog.askdirectory(title="Ordner für PNG-Export")
        if not ordner:
            return
        from ..engines import annotate
        pfade = annotate.export_als_bilder(v.session, ordner)
        self.set_status(f"✓ {len(pfade)} Seite(n) als PNG exportiert → "
                        + ordner)
        messagebox.showinfo("Als Bilder exportiert",
                            f"{len(pfade)} PNG-Datei(en) liegen in:\n"
                            + ordner)

    def _current_drucken(self) -> None:
        v = self._current()
        if v is None or v.model is None:
            return
        import os
        pfad = v.model.path
        try:
            os.startfile(pfad, "print")       # nur Windows
            self.set_status("Druckauftrag übergeben für: " + pfad)
        except AttributeError:
            messagebox.showinfo(
                "Drucken", "Direktdrucken ist nur unter Windows "
                "verfügbar. Bitte PDF öffnen und von dort drucken:\n"
                + pfad)
        except OSError:
            # keine Druck-Zuordnung (z. B. frisches Windows) → PDF im
            # Standard-Viewer öffnen, Nutzer druckt von dort (Strg+P)
            try:
                os.startfile(pfad)
                self.set_status("Kein Drucker verknüpft – PDF zum "
                                "Drucken geöffnet: " + pfad)
            except OSError as exc:
                messagebox.showinfo(
                    "Drucken", "PDF bitte im Viewer öffnen und mit "
                    "Strg+P drucken:\n" + pfad + "\n\n(" + str(exc)
                    + ")")

    def _aus_bildern(self) -> None:
        bilder = filedialog.askopenfilenames(
            title="Bilder wählen (JPEG/PNG → PDF)",
            filetypes=[("Bilder", "*.png *.jpg *.jpeg")])
        if not bilder:
            return
        ziel = filedialog.asksaveasfilename(
            title="PDF speichern unter", defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")])
        if not ziel:
            return
        from ..engines import annotate
        try:
            annotate.bilder_zu_pdf(list(bilder), ziel)
            self.set_status("✓ PDF aus Bildern erstellt: " + ziel)
            if messagebox.askyesno("Fertig", "PDF erstellt:\n" + ziel +
                                   "\n\nJetzt öffnen?"):
                self.add_document(ziel)
        except Exception as exc:                      # noqa: BLE001
            messagebox.showerror("Aus Bildern erstellen", str(exc))

    def _current_apply_redact(self) -> None:
        if (v := self._current()):
            v.apply_redactions()

    def _current_neu_einlesen(self) -> None:
        if (v := self._current()):
            v.neu_einlesen()

    def _current_felder_auto(self) -> None:
        if (v := self._current()):
            v.felder_automatisch()

    # ------------------------- neue Acrobat-Werkzeuge (09.09.2026)
    def _current_auswaehlen(self) -> None:
        """Auswählen (Acrobat-Werkzeugsleiste): Normalmodus – klicken,
        Felder treffen, weiterarbeiten."""
        if (v := self._current()):
            v.set_mode("normal")

    def _current_schwenken(self) -> None:
        """Schwenken (Acrobat-Hand-Werkzeug): Seite bei gedrückter
        Maustaste verschieben."""
        if (v := self._current()):
            v.set_mode("schwenken")

    def _current_unterstreichen(self) -> None:
        if (v := self._current()):
            v.set_mode("underline")

    def _current_messen(self) -> None:
        """Objekte messen (Acrobat): Abstand zwischen zwei Punkten."""
        if (v := self._current()):
            v.set_mode("messen")

    def _current_bild(self) -> None:
        if (v := self._current()):
            v.set_mode("bild")

    def _current_link(self) -> None:
        if (v := self._current()):
            v.set_mode("link")

    def _current_bates(self) -> None:
        """Bates-Nummerierung: fortlaufende Nummer auf jede Seite
        (Acrobat „Bates-Nummerierung“) – lokal statt Cloud."""
        v = self._current()
        if v is None or v.session is None:
            return
        praefix = simpledialog.askstring(
            "Bates-Nummerierung",
            "Präfix (leer = keiner):", parent=self.root) or ""
        if praefix is None:
            return
        start = simpledialog.askinteger(
            "Bates-Nummerierung", "Startnummer:", initialvalue=1,
            minvalue=0, parent=self.root)
        if start is None:
            return
        suffix = simpledialog.askstring(
            "Bates-Nummerierung",
            "Suffix (leer = keiner):", parent=self.root) or ""
        from ..engines import annotate as _annotate
        n = _annotate.bates_nummerierung(v.session, praefix=praefix,
                                         start=start, suffix=suffix)
        v.model.edited = True
        audit_mod.log(v.model, "Bates-Nummerierung",
                      f"{n} Seiten, Start {start}")
        self.set_status(f"✓ {n} Seiten nummeriert – „Neue Version“ "
                        "speichert.")

    def _current_textfeld(self) -> None:
        """Kopfleisten-Knopf „Textfeld einfügen“: erster Klick aktiviert,
        zweiter Klick beendet das Werkzeug (Acrobat-Schalter)."""
        if (v := self._current()):
            v.set_mode("normal" if v.mode == "textfeld" else "textfeld")

    def _current_feld_entfernen(self) -> None:
        """In der Felder-Liste ausgewähltes eigenes/erkanntes Feld
        entfernen (gleicher Weg wie Entf-Taste)."""
        if (v := self._current()):
            v._feld_loeschen_gewaehlt()

    def _current_unterschrift(self) -> None:
        if (v := self._current()):
            self._unterschrift_auswaehlen(v)

    def _esc_alle(self, _event=None) -> None:
        """Esc beendet überall: erst die Inline-Eingabe, dann das
        Werkzeug – niemand darf im Modus gefangen sein."""
        v = self._current()
        if v is None:
            return
        if getattr(v, "_inline_entry", None):
            v._inline_close()
        v.set_mode("normal")

    def _tab_drag_ende(self, event, view) -> None:
        """Tab-Ziehen: über 60 px horizontal = eine Position tauschen."""
        drag = getattr(self, "_tab_drag", None)
        self._tab_drag = None
        if not drag or drag.get("view") is not view:
            return
        dx = event.x_root - drag["x0"]
        if abs(dx) < 60:
            return                       # normaler Klick (Command läuft)
        try:
            idx = self.views.index(view)
        except ValueError:
            return
        neu = idx + (1 if dx > 0 else -1)
        if 0 <= neu < len(self.views):
            self.views.insert(neu, self.views.pop(idx))
            self._tab_band_aktualisieren()

    def _current_delete_page(self) -> None:
        if (v := self._current()):
            v.delete_page()

    def _current_extract_page(self) -> None:
        if (v := self._current()):
            v.extract_page()

    def _current_merge(self) -> None:
        if (v := self._current()):
            v.merge_pdfs()

    def _current_encrypt(self) -> None:
        if (v := self._current()):
            v.save_encrypted()

    def _recent_dialog(self) -> None:
        """„Zuletzt geöffnet“ – Acrobat-Startseite, aber rein lokal."""
        win = tk.Toplevel(self.root)
        win.title("Zuletzt geöffnete Dokumente")
        liste = recent.laden()
        lb = tk.Listbox(win, width=72, height=min(12, max(4, len(liste))))
        for eintrag in liste:
            lb.insert(tk.END, f"{eintrag.get('zeit', '')}   "
                              f"{eintrag['pfad']}")
        lb.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

        def _oeffnen(_event=None):
            sel = lb.curselection()
            if sel:
                pfad = liste[sel[0]]["pfad"]
                win.destroy()
                if os.path.isfile(pfad):
                    self.add_document(pfad)
                else:
                    messagebox.showinfo("Zuletzt", "Datei existiert nicht "
                                       f"mehr:\n{pfad}")

        ttk.Button(win, text="Öffnen", command=_oeffnen).pack(
            side=tk.LEFT, padx=10, pady=8)

        def _leeren():
            recent.leeren()
            lb.delete(0, tk.END)
            self.set_status("Liste „Zuletzt“ geleert.")

        ttk.Button(win, text="Liste leeren", command=_leeren).pack(
            side=tk.LEFT, pady=8)
        lb.bind("<Double-Button-1>", _oeffnen)
        win.transient(self.root)
        win.grab_set()

    def _current_export(self) -> None:
        if (v := self._current()):
            v.export()

    def _current_compare(self) -> None:
        if (v := self._current()):
            v._compare()

    def _current_undo(self) -> None:
        if (v := self._current()):
            v.undo()

    def _current_redo(self) -> None:
        if (v := self._current()):
            v.redo()

    def _zoom(self, factor: float) -> None:
        if (v := self._current()):
            v.zoom_by(factor)

    def _search(self) -> None:
        if (v := self._current()):
            v.search(self.search_var.get())

    def ask_export_format(self) -> str | None:
        win = tk.Toplevel(self.root)
        win.title("Export-Format")
        var = tk.StringVar(value="pdf")
        for fmt, name in (("pdf", "PDF (neue Version)"),
                          ("txt", "Text (.txt)"), ("json", "JSON (Struktur)"),
                          ("csv", "CSV (Felder/Tabellen)"),
                          ("docx", "Word (.docx)"), ("png", "Bilder (PNG)"),
                          ("pdfa", "PDF/A (falls Ghostscript)")):
            ttk.Radiobutton(win, text=name, value=fmt,
                            variable=var).pack(anchor=tk.W, padx=12, pady=2)
        ttk.Button(win, text="Exportieren",
                   command=win.destroy).pack(pady=8)
        win.transient(self.root)
        win.grab_set()
        win.wait_window()
        return var.get()

    # ----------------------------------------------------- Selbstdiagnose
    def _startup_selfcheck(self) -> None:
        from ..selftest import has_failures, run_selftest
        checks = run_selftest(quick=True)
        if has_failures(checks):
            self.set_status("⚠ Selbstdiagnose fand Probleme – Details über "
                            "„Selbstdiagnose“.")
        else:
            warns = sum(1 for c in checks if c["status"] == "warnung")
            self.set_status(f"Bereit. Selbstdiagnose: OK ({warns} "
                            "optionale Hinweise).")

    @safe
    def run_selfcheck(self) -> None:
        from ..selftest import format_checks, run_selftest

        def work():
            return format_checks(run_selftest())

        def done(text):
            win = tk.Toplevel(self.root)
            win.title("Selbstdiagnose")
            txt = tk.Text(win, width=90, height=26, font=("Consolas", 10))
            txt.insert("1.0", text)
            txt.pack(padx=8, pady=8)
        self.set_status("Selbstdiagnose läuft …")
        self.start_task(work, done)

    # ------------------------------------------------------------- Run
    def run(self) -> None:
        self.root.mainloop()

    # ------------------------------------------------ Hamburger-Menü
    def _ueber_dialog(self) -> None:
        """Über-Dialog: Version prominently – Installations-Stände sind
        damit sofort unterscheidbar (Acrobat: Hilfe → Über)."""
        messagebox.showinfo(
            f"Über DocumentAI {APP_VERSION}",
            f"DocumentAI {APP_VERSION}\n\n"
            "Lokal & offline · portabel · Open Source\n"
            "Keine Cloud, keine Telemetrie.\n\n"
            "Neueste Version im Installer-ZIP des jeweiligen "
            "Lieferstands.")

    def _menue_zeigen(self) -> None:
        """Acrobat-Stil: ≡ öffnet das Menü als Blatt unter der Kopfzeile
        (das neue Acrobat nutzt keine klassische Menüleiste mehr)."""
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)                  # randloses Blatt
        win.configure(background="#ffffff")
        eintraege = (
            ("Öffnen … (Strg+O)", self.open_file),
            ("Ordner öffnen …", self.open_folder),
            ("Zuletzt benutzte …", self._recent_dialog),
            None,
            ("Neue Version speichern (Strg+S)", self._current_save),
            ("Export …", self._current_export),
            ("Drucken … (Strg+P)", self._current_drucken),
            None,
            ("Automatisch befüllen (Strg+B)", self._current_auto_fill),
            ("Validieren", self._current_validate),
            ("Rückgängig (Strg+Z)", self._current_undo),
            ("Wiederholen (Strg+Y)", self._current_redo),
            ("Vergleich …", self._current_compare),
            None,
            ("Datentresor 🔒", self.vault_person_waehlen),
            ("Selbstdiagnose", self.run_selfcheck),
            None,
            None,
            (f"Über DocumentAI {APP_VERSION}", self._ueber_dialog),
            ("Beenden", self.root.destroy),
        )
        for e in eintraege:
            if e is None:
                tk.Frame(win, height=1, background="#d9dce1"
                         ).pack(fill=tk.X, padx=10, pady=2)
            else:
                text, cmd = e
                tk.Button(win, text=text, bd=0, relief=tk.FLAT,
                          background="#ffffff", foreground="#1f2430",
                          activebackground="#e8f1fd",
                          activeforeground="#1473e6", anchor=tk.W,
                          font=("", 10), padx=14, pady=5,
                          command=lambda c=cmd: (win.destroy(), c())
                          ).pack(fill=tk.X)
        win.update_idletasks()
        x = self.root.winfo_rootx() + 10
        y = self.root.winfo_rooty() + 52
        win.geometry(f"+{x}+{y}")
        # Klick daneben schließt das Blatt
        self.root.bind_all("<Button-1>",
                           lambda e: win.destroy()
                           if e.window != int(win.frame(), 16) else None,
                           add="+")

    # ---------------------------------------------------- Gestaltung
    def _stil(self) -> None:
        """Acrobat-Look: dunkle Kopfzeile (#26282e), Adobe-Blau-Akzent
        (#1473e6), helle Werkzeugflächen – mit try/except, falls ein
        Tk-Theme fehlt (dann greifen die Standardfarben)."""
        try:
            stil = ttk.Style(self.root)
            try:
                stil.theme_use("clam")
            except Exception:
                pass                       # Fallback: Standard-Theme
            T = farben(self.thema_modus)
            F_KOPF, F_SEITE, F_HELLE = T["kopf"], T["seite"], T["panel"]
            F_AKZENT, F_TEXT, F_GRAU = T["akzent"], T["text"], T["grau"]
            stil.configure("TFrame", background=F_SEITE)
            stil.configure("View.TFrame", background=F_SEITE)
            stil.configure("Mitte.TFrame", background="#eceef2")
            stil.configure("Seite.TFrame", background=F_SEITE)
            stil.configure("Weiss.TFrame", background=F_HELLE)
            stil.configure("Gruppe.TLabel", background=F_HELLE,
                           foreground=F_AKZENT, font=("", 8, "bold"))
            # Werkzeug-Knöpfe (Panel): flach, weiß
            stil.configure("Werk.TButton", background=F_HELLE,
                           foreground=F_TEXT, borderwidth=0,
                           focuscolor=F_HELLE, padding=(4, 2))
            stil.map("Werk.TButton",
                     background=[("active", T["knopf_aktiv"]),
                                 ("pressed", T["knopf_druck"])])
            # Kopfzeilen-Knöpfe: dunkler Grund, helle Schrift
            stil.configure("Kopf.TButton", background=T["kopf_knopf"],
                           foreground="white", borderwidth=0,
                           padding=(8, 4))
            stil.map("Kopf.TButton",
                     background=[("active", T["kopf_aktiv"]),
                                 ("pressed", T["kopf"])])
            # Akzent-Knopf („Neue Version“): Adobe-Blau
            stil.configure("Akzent.TButton", background=F_AKZENT,
                           foreground="white", borderwidth=0,
                           font=("", 9, "bold"), padding=(10, 4))
            stil.map("Akzent.TButton",
                     background=[("active", T["akzent_aktiv"]),
                                 ("pressed", T["akzent_druck"]),
                                 ("disabled", "#9db8dd")])
            # Navbar-Checkbutton auf weißem Grund
            stil.configure("Nav.TCheckbutton", background=F_HELLE,
                           foreground=F_TEXT)
            stil.map("Nav.TCheckbutton", background=[("active", F_HELLE)])
            # dunkles Suchfeld in der Kopfzeile
            stil.configure("Kopf.TEntry", fieldbackground="#3a3d44",
                           foreground="white", bordercolor="#4a4e57",
                           insertcolor="white")
            # Rechte Reiter (Analysen): weiß mit blauem aktiven Balken
            stil.configure("TNotebook", background=F_SEITE, borderwidth=0)
            stil.configure("TNotebook.Tab", background=F_HELLE,
                           foreground=F_TEXT, padding=(10, 5),
                           borderwidth=0)
            stil.map("TNotebook.Tab",
                     background=[("selected", F_HELLE)],
                     foreground=[("selected", F_AKZENT),
                                 ("active", F_GRAU)])
            # Inspector/Eigenschaften
            stil.configure("TLabelframe", background=F_HELLE,
                           bordercolor="#d9dce1")
            stil.configure("TLabelframe.Label", background=F_HELLE,
                           foreground=F_TEXT)
            stil.configure("TLabel", background=F_SEITE, foreground=F_TEXT)
            stil.configure("Weiss.TLabel", background=F_HELLE,
                           foreground=F_TEXT)
            stil.configure("TButton", padding=(6, 3))
            # Statusleiste (tk.Label direkt eingefärbt)
            self.status_fg = T["schine_text"]
        except Exception:
            pass                           # Design ist optional, Funktion
                                             # muss niemals daran scheitern
                  # muss niemals daran scheitern
