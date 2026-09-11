# -*- coding: utf-8 -*-
"""GUI-Klickfolge-Tests (Nutzerfund 03.09.2026):

„testet alles bis ins kleinste Detail – jeden Klick, jeden Reiter“.

Deckt ab:
* alle 7 Reiter vorhanden & wählbar (der „Daten“-Reiter war bei 360 px
  Panelbreite hinter dem Reiter-Überlauf unsichtbar!)
* jeder Knopf im Fenster überlebt einen Klick (mit Abbrech-Antworten)
* komplette Nutzerreise für einen SCAN (Bild-PDF ohne Textebene):
  Öffnen → Analyse/OCR → Felder → Profildaten → „Autom. befüllen“ →
  Zuordnung → „Neue Version“ → Werte wirklich im PDF.
"""
import os
import shutil
import sys
from conftest import app_schliessen
import time

import pytest

tkinter = pytest.importorskip("tkinter")

HAVE_DISPLAY = (os.environ.get("DISPLAY") or sys.platform.startswith("win"))
TESSERACT_DA = bool(shutil.which("tesseract"))

REITER_ERWARTET = ["Analyse", "Felder", "Validierung", "Daten", "Audit",
                   "Tresor 🔒", "Vergleich"]


def _pump(app, bedingung, sekunden=20):
    """Tk-Ereignisschleife pumpen, bis Bedingung wahr wird."""
    frist = time.time() + sekunden
    while time.time() < frist:
        app.root.update()
        if bedingung():
            return True
        time.sleep(0.05)
    return False


def _knopftexte(widget):
    """Alle ttk/tk-Buttons unter widget als {text: button} sammeln."""
    import tkinter.ttk as ttk
    out = {}
    for w in widget.winfo_children():
        if isinstance(w, (ttk.Button, tkinter.Button)):
            out[w.cget("text")] = w
        out.update(_knopftexte(w))
    return out


def _toplevels(app):
    """ALLE Toplevel-Fenster – auch solche, die an einem View hängen."""
    def _sammln(w):
        out = []
        for c in w.winfo_children():
            if isinstance(c, tkinter.Toplevel):
                out.append(c)
            out.extend(_sammln(c))
        return out
    return _sammln(app.root)


def _app_neu():
    """DocumentAIApp erzeugen – mit Wiederholung.

    Wine-Tcl-Eigenheit (nur Labor): beim mehrfachen Anlegen/Zerstören von
    Tk-Instanzen im selben Prozess scheitert gelegentlich das Lesen von
    init.tcl („couldn't read file … : Success“). Auf echtem Windows nicht
    beobachtet; ein gc+Sleep+Neuerstellen behebt es im Labor zuverlässig.
    """
    import gc
    from documentai.gui.app import DocumentAIApp
    for versuch in range(3):
        try:
            return DocumentAIApp()
        except Exception:
            gc.collect()
            time.sleep(0.4)
    return DocumentAIApp()


def _scan_pdf(pfad: str) -> str:
    """Bild-PDF ohne Textebene bauen (Simulation gescannter Antrag)."""
    import pymupdf
    tmp = pymupdf.open()
    s = tmp.new_page(width=595, height=842)
    for text, y in (("Antrag auf Leistung (Simulation)", 60),
                    ("Vorname ______________________", 140),
                    ("Nachname _____________________", 170),
                    ("Strasse ______________________", 200),
                    ("PLZ _______ Ort ______________", 230),
                    ("IBAN ________________________", 260),
                    ("Telefon ______________________", 290)):
        s.insert_text((50, y), text, fontsize=12)
    png = s.get_pixmap(dpi=200).tobytes("png")
    scan = pymupdf.open()
    ss = scan.new_page(width=595, height=842)
    ss.insert_image(ss.rect, stream=png)
    scan.save(pfad)
    return pfad


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_alle_reiter_vorhanden_und_waehlbar(svc, assets):
    """Der Daten-Reiter muss existieren UND direkt anwählbar sein."""
    app = _app_neu()
    try:
        app.add_document(assets.visual)
        assert _pump(app, lambda: app._current() is not None and
                     app._current().model is not None and
                     app._current().model.pages)
        tabs = app._current().tabs
        namen = [tabs.tab(t, "text") for t in tabs.tabs()]
        assert namen == REITER_ERWARTET, f"Reiter abweichend: {namen}"
        for i in range(len(namen)):            # jeder einzeln anwählbar
            tabs.select(i)
            app.root.update()
            assert int(tabs.index(tabs.select())) == i
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_jeder_knopf_ueberlebt_abbruch(svc, assets, monkeypatch):
    """Klick auf JEDEN Button (Antworten = Abbrechen) darf nichts kaputt
    machen – kein Crash, kein hängender Dialog."""
    from tkinter import (filedialog, messagebox, simpledialog)
    antworten = {"infos": [], "fehler": []}
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **k: "")
    monkeypatch.setattr(filedialog, "askopenfilenames", lambda **k: ())
    monkeypatch.setattr(filedialog, "askdirectory", lambda **k: "")
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **k: "")
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(messagebox, "askokcancel", lambda *a, **k: False)
    monkeypatch.setattr(messagebox, "showinfo",
                        lambda *a, **k: antworten["infos"].append(a))
    monkeypatch.setattr(messagebox, "showerror",
                        lambda *a, **k: antworten["fehler"].append(a))
    monkeypatch.setattr(messagebox, "showwarning",
                        lambda *a, **k: None)
    monkeypatch.setattr(simpledialog, "askstring", lambda *a, **k: None)
    monkeypatch.setattr(simpledialog, "askinteger", lambda *a, **k: None)
    monkeypatch.setattr(simpledialog, "askfloat", lambda *a, **k: None)
    # Modale Fenster dürfen den Test nicht blockieren
    monkeypatch.setattr(tkinter.Misc, "wait_window",
                        lambda self, w=None: None)
    monkeypatch.setattr(tkinter.Misc, "grab_set", lambda self: None)

    app = _app_neu()
    try:
        app.add_document(assets.visual)
        assert _pump(app, lambda: app._current() is not None and
                     app._current().model is not None and
                     app._current().model.pages), "Analyse hängt"
        # Alle Knöpfe der HAUTFENSTER-Ebenen: Toolbar + Werkzeuge +
        # linkes Panel + Reiter + Inspector des aktiven Views
        app.root.update()
        klicke = dict(_knopftexte(app.root))
        view = app._current()
        klicke.update(_knopftexte(view))
        klicke.update(_knopftexte(view.tabs))
        klicke.update(_knopftexte(view.inspector))
        assert len(klicke) >= 25, f"unerwartet wenige Knöpfe: {klicke}"
        for text, btn in klicke.items():
            if not btn.winfo_exists():
                continue        # Tab-✕/Panel-Wechsel dürfen Knöpfe entfernen
            vor_toplevels = set(map(str, _toplevels(app)))
            try:
                btn.invoke()
            except Exception as exc:                      # noqa: BLE001
                pytest.fail(f"Knopf {text!r} crasht: {exc}")
            app.root.update()
            # Dialog-Fenster, die dabei aufgingen, wieder schließen
            for tl in _toplevels(app):
                if str(tl) not in vor_toplevels:
                    tl.destroy()
        assert not antworten["fehler"], \
            f"Fehlerdialoge bei Abbruch-Klicks: {antworten['fehler']}"
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
@pytest.mark.skipif(not TESSERACT_DA and not any(
    os.path.isdir(os.path.join(basis, "tools", "tesseract"))
    for basis in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  os.path.dirname(os.path.dirname(          # App-Root (Installer)
                      os.path.dirname(os.path.abspath(__file__)))))),
    reason="Tesseract nicht verfügbar (Scan-Test übersprungen)")
def test_nutzerreise_scan_formular_ausfuellen(svc, tmp_path, monkeypatch):
    """KOMPLETTE Reise: Scan öffnen → OCR-Felder → „Autom. befüllen“ →
    Zuordnung bestätigen → „Neue Version“ → Werte im Ergebnis-PDF."""
    import pymupdf
    from tkinter import messagebox
    from documentai.gui.app import DocumentAIApp

    infos = []
    monkeypatch.setattr(messagebox, "showinfo",
                        lambda *a, **k: infos.append((a, k)) or "ok")
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)

    pfad = _scan_pdf(str(tmp_path / "antrag-scan.pdf"))
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        def _analyse_fertig():
            m = view.model
            return (m is not None and m.pages and
                    any("Validierung" in str(getattr(e, "action", ""))
                        for e in m.audit))
        assert _pump(app, _analyse_fertig, sekunden=60), \
            "Analyse (inkl. OCR) wurde nicht fertig"
        assert view.model.fields, (
            "Scan: Felder wurden nicht erkannt – Lücken-Regel defekt?")
        assert any(f.canonical == "vorname" for f in view.model.fields)

        # Profildaten eintragen (Reiter „Daten“-Felder des Views)
        werte = {"vorname": "Anna", "nachname": "Beispiel",
                 "ort": "Hasbergen", "plz": "49170"}
        for k, v in werte.items():
            view.profile_vars[k].set(v)

        # Werkzeugleisten-Knopf „Autom. befüllen“ wirklich klicken
        knoepfe = _knopftexte(app.root)
        assert "Autom. befüllen" in knoepfe
        knoepfe["Autom. befüllen"].invoke()

        def _dlg_da():
            return any("Zuordnung" in (w.title() or "")
                       for w in _toplevels(app))
        assert _pump(app, _dlg_da, sekunden=15), "Zuordnungsdialog fehlt"

        # Im Zuordnungsdialog: alle übernehmen + bestätigen
        dlg = [w for w in _toplevels(app)
               if "Zuordnung" in (w.title() or "")][-1]
        dlg_knoepfe = _knopftexte(dlg)
        assert "Alle übernehmen" in dlg_knoepfe
        dlg_knoepfe["Alle übernehmen"].invoke()
        dlg_knoepfe["Zuordnung übernehmen"].invoke()
        app.root.update()

        assert any("Felder befüllt" in str(a) for a, _k in infos), infos
        gefuellt = [f for f in view.model.fields if f.value]
        assert gefuellt, "keine Feldwerte nach Befüllung"

        # „Neue Version“ klicken → Datei muss die Werte enthalten
        versionen_vorher = len(view.session.saved_versions)
        _knopftexte(app.root)["Neue Version"].invoke()
        app.root.update()
        assert len(view.session.saved_versions) > versionen_vorher
        datei = view.session.saved_versions[-1]
        text = pymupdf.open(datei)[0].get_text()
        assert "Anna" in text and "Beispiel" in text, \
            f"Werte fehlen im Ergebnis-PDF: {text[:80]!r}"

        # Rückgängig-Knopf arbeitet die Undo-Liste ab (stürzt nicht ab)
        _knopftexte(app.root)["Rückgängig"].invoke()
        app.root.update()
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_auto_fill_ohne_felder_oeffnet_daten_reiter(svc, assets, monkeypatch):
    """Nutzerfund: Verweis auf Reiter „Daten“ – dieser muss sich selbst
    öffnen und die Meldung muss weiterhelfen."""
    from tkinter import messagebox
    from documentai.gui.app import DocumentAIApp

    infos = []
    monkeypatch.setattr(messagebox, "showinfo",
                        lambda *a, **k: infos.append(str(a)) or "ok")
    app = _app_neu()
    try:
        app.add_document(assets.visual)
        assert _pump(app, lambda: app._current() is not None and
                     app._current().model is not None and
                     app._current().model.pages, sekunden=60)
        view = app._current()
        view.model.fields = []                  # „nichts erkannt“ erzwingen
        view.auto_fill()
        app.root.update()
        assert int(view.tabs.index(view.tabs.select())) == 3, \
            "Daten-Reiter wurde nicht automatisch geöffnet"
        assert infos and "Daten" in infos[0], infos
    finally:
        app_schliessen(app)
