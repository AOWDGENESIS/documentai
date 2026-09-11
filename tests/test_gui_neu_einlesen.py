# -*- coding: utf-8 -*-
"""GUI: Dokument neu einlesen (frisch von der Platte + Neu-Analyse)."""
import os
import sys
import time

import pytest

from conftest import app_schliessen

tkinter = pytest.importorskip("tkinter")

HAVE_DISPLAY = (os.environ.get("DISPLAY") or
                sys.platform.startswith("win"))


def _app_neu():
    import gc
    from documentai.gui.app import DocumentAIApp
    for _ in range(3):
        try:
            return DocumentAIApp()
        except Exception:
            gc.collect()
            time.sleep(0.4)
    return DocumentAIApp()


def _warte_auf(app, view, bedingung, frist_s=30):
    frist = time.time() + frist_s
    while time.time() < frist:
        app.root.update()
        if bedingung():
            return True
        time.sleep(0.05)
    return False


def _analyse_fertig(view) -> bool:
    """Analyse REALLY abgeschlossen (Audit-Reihenfolge ist deterministisch,
    aber Felder stehen schon vor dem letzten Log-Eintrag)."""
    m = view.model
    return bool(m and m.pages and m.fields and not m.edited
                and m.audit and m.audit[-1].action == "Analyse abgeschlossen")


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_dokument_neu_einlesen_laedt_und_analysiert_neu(svc, assets,
                                                         tmp_path,
                                                         monkeypatch):
    import shutil
    from tkinter import messagebox
    pfad = str(tmp_path / "formular.pdf")
    shutil.copy(assets.visual, pfad)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: None)
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert view is not None
        assert _warte_auf(app, view, lambda: _analyse_fertig(view))
        n_felder = len(view.model.fields)
        assert n_felder >= 5
        # In-Memory-Änderung simulieren (zählt als ungespeichert)
        view.model.edited = True
        view._seite_waehlen(0)
        view.neu_einlesen()
        assert _warte_auf(app, view, lambda: _analyse_fertig(view))
        # Neu analyse: gleiche Feldzahl, Modell frisch, Seite erhalten
        assert len(view.model.fields) == n_felder
        assert view.model.audit[-1].action == "Analyse abgeschlossen"
        assert view.current_page == 0
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_knopf_dokument_neu_einlesen_vorhanden_ohne_dokument():
    app = _app_neu()
    try:
        app.root.update()
        # Ohne Dokument muss der Knopf harmlos sein (kein Absturz)
        app._current_neu_einlesen()
        app.root.update()
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_neu_einlesen_nach_version_laedt_gespeicherten_stand(svc, assets,
                                                             tmp_path,
                                                             monkeypatch):
    """Nach „Neue Version" zeigt die Sitzung die gespeicherte Datei.
    „Neu einlesen" muss DIESEN Stand laden (nicht das Original) und
    die Versionskette am Original verankern."""
    import shutil
    from tkinter import messagebox
    pfad = str(tmp_path / "formular.pdf")
    shutil.copy(assets.visual, pfad)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: None)
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _warte_auf(app, view,
                          lambda: view.model is not None
                          and bool(view.model.fields))
        f = next(x for x in view.model.fields if x.label == "Vorname")
        view._set_field_value(f, "Anna")
        view.model.edited = True
        ergebnis = app.service.save_new_version(view.model, view.session,
                                                view.engine)
        assert ergebnis["pfad"].endswith("_v2_bearbeitet.pdf")
        assert getattr(view.session, "quelle", "") == ergebnis["pfad"]
        view.neu_einlesen()
        assert _warte_aof_fallback(app, view)
        # Gespeicherter Stand sichtbar: Anna steht im Dokument
        assert view.session.quelle.endswith("_v2_bearbeitet.pdf")
        # Versions-Anker bleibt das Original: nächste Version = v3
        view._set_field_value(f, "Berta")
        view.model.edited = True
        ergebnis2 = app.service.save_new_version(view.model, view.session,
                                                 view.engine)
        assert ergebnis2["pfad"].endswith("_v3_bearbeitet.pdf"), \
            "Versionskette muss am Original verankert bleiben"
    finally:
        app_schliessen(app)


def _warte_aof_fallback(app, view):
    import time as _t
    frist = _t.time() + 30
    while _t.time() < frist:
        app.root.update()
        if _analyse_fertig(view):
            return True
        _t.sleep(0.05)
    return False


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_neu_einlesen_liest_externe_aenderung(svc, assets, tmp_path,
                                              monkeypatch):
    """Kernzweck: Datei wurde außen verändert – Neu einlesen zeigt
    den neuen Inhalt."""
    import shutil
    from tkinter import messagebox
    pfad = str(tmp_path / "formular.pdf")
    shutil.copy(assets.visual, pfad)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: None)
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _warte_auf(app, view,
                          lambda: view.model is not None
                          and bool(view.model.pages))
        assert len(view.model.pages) == 1
        # Extern: Seite 2 anhängen (gleicher Pfad)
        import pymupdf
        with pymupdf.open(pfad) as doc:
            with pymupdf.open() as out:
                out.insert_pdf(doc)
                out.new_page()
                out.save(pfad + ".neu", deflate=True)
        import os as _os
        _os.replace(pfad + ".neu", pfad)
        view.neu_einlesen()
        assert _warte_auf(app, view,
                          lambda: view.model is not None
                          and len(view.model.pages) == 2)
    finally:
        app_schliessen(app)
