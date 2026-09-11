# -*- coding: utf-8 -*-
"""GUI-Panel: lokaler, verschlüsselter Datentresor (Multi-Personen).

Funktionen:
- Tresor erstellen / öffnen (Master-Passwort) / sperren / Passwort ändern
- Personen verwalten (z. B. ich, Partnerin, Kind) mit Stammdaten
- Informationen aus dem aktuell geöffneten Dokument übernehmen
  (Extraktion → Prüfung → Übernahme, inkl. automatischer Personen-Zuordnung)
- Personenprofil für die Formularbefüllung verwenden
- optional Master-Passwort im Windows-Keyring merken (falls `keyring` Paket)
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ..services import profile as profile_service
from ..services import vault as vault_mod
from ..services.extraction import extract_structured_data
from ..services.vault import (SecureVault, VaultError, VaultLockedError,
                              default_path)

KEYRING_OK = False
try:
    import keyring  # noqa: F401
    KEYRING_OK = True
except Exception:
    KEYRING_OK = False

HAEUFIGE_FELDER = ("vorname", "nachname", "geburtsdatum", "strasse",
                   "hausnummer", "plz", "ort", "telefon", "email", "iban",
                   "bic", "kundennummer", "aktenzeichen", "versicherungsnummer",
                   "steuernummer", "personalnummer", "beruf", "firma")


def _safe(fn):
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except VaultError as exc:
            messagebox.showerror("Datentresor", exc.message)
        except Exception as exc:                     # noqa: BLE001
            from ..util import write_error_report
            pfad = write_error_report(exc, action=fn.__name__,
                                      component="vault-panel")
            messagebox.showerror("Datentresor",
                                 f"{getattr(exc, 'message', exc)}\n\n"
                                 f"Fehlerbericht: {pfad}")
    return wrapper


class VaultPanel(ttk.Frame):

    def __init__(self, master, app, view):
        super().__init__(master, padding=6)
        self.app = app
        self.view = view                    # zugehöriger Dokument-Tab
        self._persons: list[dict] = []
        self._active_id: int | None = None
        self._build()

    # ------------------------------------------------------------- Aufbau
    def _build(self) -> None:
        box = ttk.LabelFrame(self, text="Verschlüsselter Datentresor "
                                        "(AES-256, lokal)")
        box.pack(fill=tk.BOTH, expand=True)

        row1 = ttk.Frame(box)
        row1.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(row1, text="Tresor erstellen…",
                   command=self.create_vault).pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Tresor öffnen…",
                   command=self.open_vault).pack(side=tk.LEFT, padx=2)
        self.btn_lock = ttk.Button(row1, text="Sperren", state=tk.DISABLED,
                                   command=self.lock_vault)
        self.btn_lock.pack(side=tk.LEFT, padx=2)
        ttk.Button(row1, text="Passwort ändern…",
                   command=self.change_password).pack(side=tk.LEFT, padx=2)
        self.lbl_status = ttk.Label(row1, text="gesperrt",
                                    foreground="#777")
        self.lbl_status.pack(side=tk.RIGHT, padx=6)

        row2 = ttk.Frame(box)
        row2.pack(fill=tk.X, padx=6, pady=2)
        ttk.Label(row2, text="Person:").pack(side=tk.LEFT)
        self.cmb_person = ttk.Combobox(row2, state="readonly", width=28,
                                       values=["(keine)"])
        self.cmb_person.pack(side=tk.LEFT, padx=4)
        self.cmb_person.bind("<<ComboboxSelected>>", self._on_person_select)
        ttk.Button(row2, text="Anlegen…",
                   command=self.add_person).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="Umbenennen…",
                   command=self.rename_person).pack(side=tk.LEFT, padx=2)
        ttk.Button(row2, text="Löschen",
                   command=self.delete_person).pack(side=tk.LEFT, padx=2)

        columns = ("Feld", "Wert", "Quelle", "Konfidenz", "Aktualisiert")
        self.tree = ttk.Treeview(box, columns=columns, show="headings",
                                 height=8)
        for col, width in zip(columns, (120, 170, 90, 70, 130)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        self.tree.bind("<Double-1>", lambda e: self.set_datum(edit=True))

        row4 = ttk.Frame(box)
        row4.pack(fill=tk.X, padx=6, pady=4)
        ttk.Button(row4, text="Eintrag setzen…",
                   command=self.set_datum).pack(side=tk.LEFT, padx=2)
        ttk.Button(row4, text="Eintrag löschen",
                   command=self.delete_datum).pack(side=tk.LEFT, padx=2)
        ttk.Button(row4, text="Aus Dokument übernehmen…",
                   command=self.import_from_document).pack(side=tk.LEFT,
                                                           padx=2)
        ttk.Button(row4, text="Für Befüllung verwenden",
                   command=self.use_for_filling).pack(side=tk.LEFT, padx=2)
        self.refresh()

    # --------------------------------------------------------- Zustand
    @property
    def vault(self) -> SecureVault | None:
        return getattr(self.app, "vault", None)

    def refresh(self) -> None:
        vault = self.vault
        if vault is None or not vault.unlocked:
            self.lbl_status.configure(
                text=f"gesperrt – {default_path()}", foreground="#777")
            self.btn_lock.configure(state=tk.DISABLED)
            self.cmb_person.set("(keine)")
            self.cmb_person["values"] = ["(keine)"]
            self.tree.delete(*self.tree.get_children())
            self._persons = []
            self._active_id = None
            for child in self.winfo_children():
                pass
            return
        try:
            stats = vault.statistics()
            self.lbl_status.configure(
                text=f"offen – {stats['personen']} Personen, "
                     f"{stats['datenfelder']} Felder, "
                     f"{stats['dokumente']} Dokumente",
                foreground="#1b5e20")
            self.btn_lock.configure(state=tk.NORMAL)
            self._persons = vault.list_persons()
            namen = [f"{p['name']} ({p['rolle']})" if p["rolle"] else
                     p["name"] for p in self._persons] or ["(keine)"]
            self.cmb_person["values"] = namen
            if self._active_id is None and self._persons:
                self._active_id = self._persons[0]["id"]
            idx = next((i for i, p in enumerate(self._persons)
                        if p["id"] == self._active_id), 0)
            if self._persons:
                self.cmb_person.current(min(idx, len(namen) - 1))
            self._load_data()
        except VaultLockedError:
            self.refresh()

    def _load_data(self) -> None:
        self.tree.delete(*self.tree.get_children())
        vault = self.vault
        if vault is None or self._active_id is None:
            return
        try:
            for key, info in vault.get_data(self._active_id).items():
                self.tree.insert("", tk.END, iid=key, values=(
                    key, info["wert"], info["quelle"],
                    f"{round(info['konfidenz'] * 100)} %",
                    info["aktualisiert"]))
        except VaultError:
            pass

    def _on_person_select(self, _event=None) -> None:
        idx = self.cmb_person.current()
        if 0 <= idx < len(self._persons):
            self._active_id = self._persons[idx]["id"]
        self._load_data()

    # --------------------------------------------------------- Tresor
    @_safe
    def create_vault(self) -> None:
        pfad = default_path()
        if os.path.exists(pfad):
            if not messagebox.askyesno(
                    "Datentresor",
                    "Es existiert bereits ein Tresor:\n"
                    f"{pfad}\n\nBeim Neuerstellen werden die vorhandenen "
                    "Daten NICHT gelöscht, aber ein neuer leerer Tresor "
                    "unter diesem Pfad überschreibt die Datei.\nWirklich "
                    "einen NEUEN Tresor anlegen?"):
                return
        pw = simpledialog.askstring("Tresor erstellen",
                                    "Master-Passwort festlegen (min. 4 "
                                    "Zeichen):", show="*")
        if pw is None:
            return
        pw2 = simpledialog.askstring("Tresor erstellen",
                                     "Master-Passwort wiederholen:",
                                     show="*")
        if pw2 is None or pw != pw2:
            messagebox.showwarning("Tresor erstellen",
                                   "Die Eingaben stimmen nicht überein.")
            return
        vault = SecureVault.create(pw, pfad, exist_ok=True)
        self.app.vault = vault
        if KEYRING_OK:
            if messagebox.askyesno("Keyring", "Master-Passwort im "
                                    "Windows-Keyring merken?\n(Andernfalls "
                                    "bei jedem Start eingeben.)"):
                vault_mod.keyring_store_password(pw)
        self._after_mutation()
        messagebox.showinfo("Datentresor",
                            "Verschlüsselter Tresor erstellt:\n"
                            f"{pfad}\n\nAlle Daten liegen ausschließlich "
                            "verschlüsselt (AES-256) auf diesem Rechner.")

    @_safe
    def open_vault(self) -> None:
        pfad = default_path()
        if not os.path.exists(pfad):
            messagebox.showinfo("Datentresor",
                                "Noch kein Tresor vorhanden.\nBitte zuerst "
                                "„Tresor erstellen…“ nutzen.")
            return
        pw = None
        if KEYRING_OK:
            pw = vault_mod.keyring_load_password()
        if pw is None:
            pw = simpledialog.askstring("Tresor öffnen",
                                        "Master-Passwort:", show="*")
            if pw is None:
                return
        try:
            self.app.vault = SecureVault.open(pw, pfad)
        except VaultError as exc:
            if KEYRING_OK and "falsch" in exc.message.lower():
                vault_mod.keyring_delete_password()
                pw = simpledialog.askstring(
                    "Tresor öffnen",
                    "Gespeichertes Passwort war falsch (wurde verworfen).\n"
                    "Master-Passwort:", show="*")
                if pw:
                    self.app.vault = SecureVault.open(pw, pfad)
            else:
                raise
        self._after_mutation()

    @_safe
    def lock_vault(self) -> None:
        if self.vault is not None:
            self.vault.lock()
        self.app.vault = None
        self._after_mutation()

    @_safe
    def change_password(self) -> None:
        vault = self.vault
        if vault is None or not vault.unlocked:
            messagebox.showinfo("Datentresor", "Bitte zuerst öffnen.")
            return
        alt = simpledialog.askstring("Passwort ändern",
                                     "Aktuelles Master-Passwort:", show="*")
        if alt is None:
            return
        neu = simpledialog.askstring("Passwort ändern",
                                     "Neues Master-Passwort:", show="*")
        if neu is None:
            return
        neu2 = simpledialog.askstring("Passwort ändern",
                                      "Neues Passwort wiederholen:",
                                      show="*")
        if neu != neu2:
            messagebox.showwarning("Passwort ändern",
                                   "Die Eingaben stimmen nicht überein.")
            return
        vault.change_master_password(alt, neu)
        if KEYRING_OK:
            vault_mod.keyring_store_password(neu)
        messagebox.showinfo("Datentresor", "Master-Passwort geändert.")

    # --------------------------------------------------------- Personen
    @_safe
    def add_person(self) -> None:
        vault = self.vault
        if vault is None:
            return
        name = simpledialog.askstring("Person anlegen", "Vollständiger Name:")
        if not name or not name.strip():
            return
        rolle = simpledialog.askstring("Person anlegen",
                                       "Rolle (z. B. ich, Partnerin, Kind):")
        pid = vault.add_person(name.strip(), (rolle or "").strip())
        self._active_id = pid
        self._after_mutation()

    @_safe
    def rename_person(self) -> None:
        vault = self.vault
        if vault is None or self._active_id is None:
            return
        person = vault.get_person(self._active_id)
        name = simpledialog.askstring("Person umbenennen", "Neuer Name:",
                                      initialvalue=person["name"])
        if not name:
            return
        rolle = simpledialog.askstring("Person umbenennen", "Neue Rolle:",
                                       initialvalue=person["rolle"])
        vault.rename_person(self._active_id, name, rolle or "")
        self._after_mutation()

    @_safe
    def delete_person(self) -> None:
        vault = self.vault
        if vault is None or self._active_id is None:
            return
        person = vault.get_person(self._active_id)
        if not messagebox.askyesno(
                "Person löschen",
                f"Person „{person['name']}“ samt aller Daten wirklich "
                "löschen?\n(Die Aktion wird protokolliert, Daten sind nach "
                "dem Speichern unwiederbringlich entfernt.)"):
            return
        vault.delete_person(self._active_id)
        vault.save()
        self._active_id = None
        self._after_mutation()

    # --------------------------------------------------------- Daten
    @_safe
    def set_datum(self, edit: bool = False) -> None:
        vault = self.vault
        if vault is None or self._active_id is None:
            messagebox.showinfo("Datentresor",
                                "Bitte zuerst Tresor öffnen und Person "
                                "auswählen.")
            return
        key = ""
        if edit and self.tree.selection():
            key = self.tree.selection()[0]
        if not key:
            dlg = _FieldChooserDialog(self, HAEUFIGE_FELDER)
            self.wait_window(dlg)
            key = dlg.ergebnis
            if not key:
                return
        person = vault.get_person(self._active_id)
        aktuell = vault.get_data(self._active_id).get(key, {}).get("wert", "")
        wert = simpledialog.askstring(
            "Eintrag setzen",
            f"Feld „{key}“ für {person['name']}:", initialvalue=aktuell)
        if wert is None:
            return
        if wert.strip() == "":
            vault.delete_datum(self._active_id, key)
        else:
            vault.set_datum(self._active_id, key, wert, "manuell", 1.0)
        vault.save()
        self._after_mutation()

    @_safe
    def delete_datum(self) -> None:
        vault = self.vault
        sel = self.tree.selection()
        if vault is None or not sel:
            return
        vault.delete_datum(self._active_id, sel[0])
        vault.save()
        self._after_mutation()

    # ------------------------------------------------------ Extraktion
    @_safe
    def import_from_document(self) -> None:
        vault = self.vault
        if vault is None:
            messagebox.showinfo("Datentresor", "Bitte zuerst Tresor öffnen.")
            return
        view = self.app._current()
        if view is None or view.model is None or not view.model.pages:
            messagebox.showinfo("Datentresor",
                                "Bitte zuerst ein Dokument im aktuellen Tab "
                                "analysieren lassen.")
            return
        model = view.model

        def work():
            return extract_structured_data(model)

        def done(proposals):
            if not proposals:
                messagebox.showinfo("Datenextraktion",
                                    "Im aktuellen Dokument wurden keine "
                                    "verwertbaren Personen-Daten erkannt.")
                return
            dlg = _ExtractionReviewDialog(self, vault, proposals)
            self.wait_window(dlg)
            if dlg.ergebnis is None:
                return
            person_id, gewaehlt = dlg.ergebnis
            try:
                doc_id = vault.add_document(
                    model.path, model.sha256, len(model.pages),
                    model.source_format, person_id,
                    "Übernahme per GUI")
                n = vault.adopt_extractions(person_id, gewaehlt, doc_id)
                vault.save()
                self._active_id = person_id
                self._after_mutation()
                messagebox.showinfo(
                    "Datenextraktion",
                    f"{n} Einträge in die verschlüsselte Datenbank "
                    "übernommen.\n(Dokument wurde mit SHA-256 verknüpft "
                    "registriert.)")
            except VaultError as exc:
                messagebox.showerror("Datentresor", exc.message)
        self.app.start_task(work, done)

    # ------------------------------------------------------ Befüllung
    @_safe
    def use_for_filling(self) -> None:
        vault = self.vault
        if vault is None or self._active_id is None:
            return
        profil = vault.export_profile(self._active_id)
        person = vault.get_person(self._active_id)
        # Profil-Tab(s) der geöffneten Dokumente befüllen
        for view in self.app.views:
            for key, var in view.profile_vars.items():
                if key in profil:
                    var.set(profil[key])
        profile_service.save({**profile_service.load(), **profil})
        self.app.set_status(
            f"Profil „{person['name']}“ für Befüllung aktiviert "
            f"({len(profil)} Felder).")

    # --------------------------------------------------------- Interna
    def _after_mutation(self) -> None:
        self.app.vault_changed()


# ----------------------------------------------------------- Dialoge
class _FieldChooserDialog(tk.Toplevel):
    """Auswahl eines kanonischen Feldes (mit freier Eingabe)."""

    def __init__(self, master, felder):
        super().__init__(master)
        self.title("Feld wählen")
        self.ergebnis = ""
        self.var = tk.StringVar()
        ttk.Label(self, text="Feld:").pack(padx=8, pady=(8, 2))
        cmb = ttk.Combobox(self, textvariable=self.var, values=list(felder),
                           width=30)
        cmb.pack(padx=8, pady=2)
        cmb.set(felder[0])
        ttk.Button(self, text="Weiter",
                   command=self._ok).pack(pady=8)
        self.transient(master.winfo_toplevel())
        self.grab_set()
        self.bind("<Return>", lambda e: self._ok())

    def _ok(self):
        self.ergebnis = self.var.get().strip().lower()
        self.destroy()


class _ExtractionReviewDialog(tk.Toplevel):
    """Extraktionsvorschläge prüfen: Person wählen + Felder abhaken."""

    def __init__(self, master, vault: SecureVault, proposals: list[dict]):
        super().__init__(master)
        self.title("Erkannte Daten prüfen und übernehmen")
        self.geometry("720x440")
        self.ergebnis = None            # (person_id, [proposals])
        self.proposals = proposals
        self.vault = vault

        ttk.Label(self, text="1) Person wählen:").pack(anchor=tk.W,
                                                       padx=10, pady=(8, 2))
        self.personen = vault.list_persons()
        self.cmb = ttk.Combobox(self, state="readonly", width=40,
                                values=[p["name"] for p in self.personen]
                                or ["(zuerst Person anlegen)"])
        self.cmb.pack(anchor=tk.W, padx=10)
        # Auto-Zuordnung vorschlagen (§4 Workflow)
        pid, score = vault.match_person(proposals)
        if pid:
            idx = next((i for i, p in enumerate(self.personen)
                        if p["id"] == pid), None)
            if idx is not None:
                self.cmb.current(idx)
                ttk.Label(self, text=f"Automatische Zuordnungsvorschlag: "
                                     f"{self.personen[idx]['name']} "
                                     f"({int(score * 100)} % Übereinstimmung)",
                          foreground="#1b5e20").pack(anchor=tk.W, padx=10)
        elif self.personen:
            self.cmb.current(0)

        ttk.Label(self, text="2) Zu übernehmende Daten (Doppelklick "
                             "zum An-/Abwählen):").pack(anchor=tk.W,
                                                        padx=10, pady=(8, 2))
        columns = ("Übernehmen", "Feld", "Wert", "Quelle", "Konfidenz")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        for col, width in zip(columns, (80, 130, 220, 110, 80)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=width)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)
        for p in proposals:
            self.tree.insert("", tk.END, values=(
                "ja", p["key"], p["wert"][:38], p["quelle"],
                f"{round(p['konfidenz'] * 100)} %"))
        self.tree.bind("<Double-1>", lambda e: self._toggle())

        bar = ttk.Frame(self)
        bar.pack(fill=tk.X, pady=6)
        ttk.Button(bar, text="Alle übernehmen",
                   command=lambda: self._all("ja")).pack(side=tk.LEFT,
                                                         padx=6)
        ttk.Button(bar, text="Keine übernehmen",
                   command=lambda: self._all("nein")).pack(side=tk.LEFT)
        ttk.Button(bar, text="In Datenbank übernehmen",
                   command=self._apply).pack(side=tk.RIGHT, padx=6)
        self.transient(master.winfo_toplevel())
        self.grab_set()

    def _toggle(self) -> None:
        sel = self.tree.selection()
        if sel:
            vals = list(self.tree.item(sel[0], "values"))
            vals[0] = "nein" if vals[0] == "ja" else "ja"
            self.tree.item(sel[0], values=vals)

    def _all(self, state: str) -> None:
        for item in self.tree.get_children():
            vals = list(self.tree.item(item, "values"))
            vals[0] = state
            self.tree.item(item, values=vals)

    def _apply(self) -> None:
        idx = self.cmb.current()
        if not self.personen:
            messagebox.showinfo("Datenextraktion",
                                "Bitte zuerst eine Person im Datentresor "
                                "anlegen.", parent=self)
            return
        person_id = self.personen[idx]["id"]
        gewaehlt = []
        for i, item in enumerate(self.tree.get_children()):
            vals = self.tree.item(item, "values")
            if vals[0] == "ja":
                gewaehlt.append(self.proposals[i])
        if not gewaehlt:
            messagebox.showinfo("Datenextraktion",
                                "Nichts ausgewählt – bitte mindestens ein "
                                "Feld markieren.", parent=self)
            return
        self.ergebnis = (person_id, gewaehlt)
        self.destroy()
