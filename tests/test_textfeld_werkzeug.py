# -*- coding: utf-8 -*-
"""Textfeld einfügen (manuell + automatisch) und Feld entfernen."""
import os
import sys
import time

import pymupdf
import pytest

from conftest import app_schliessen

tkinter = pytest.importorskip("tkinter")

HAVE_DISPLAY = (os.environ.get("DISPLAY") or
                sys.platform.startswith("win"))

from documentai import samples
from documentai.services.tools import tessdata_verzeichnis

HAT_TESSDATA = bool(tessdata_verzeichnis())


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


def _pump(app, bedingung, frist_s=30):
    frist = time.time() + frist_s
    while time.time() < frist:
        app.root.update()
        if bedingung():
            return True
        time.sleep(0.05)
    return False


# ======================================================================
# Service: automatische Feld-Erkennung
# ======================================================================
@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_felder_automatisch_auf_scan(svc, tmp_path):
    """Scans ohne erkannte Felder bekommen per Knopfdruck Felder."""
    pfad = samples.make_scan_handschrift_pdf(str(tmp_path / "scan.pdf"))
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert model.fields                    # Analyse findet schon Felder
    # Neu-Analyse über den Service-Weg darf keine Duplikate erzeugen
    neu = svc.felder_automatisch_erkennen(model, session, engine)
    ids = [f.id for f in model.fields]
    assert len(ids) == len(set(ids)), "keine doppelten Feld-IDs"
    assert neu >= 0


@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_felder_automatisch_ohne_erkennung(svc, tmp_path, monkeypatch):
    """Seiten OHNE Worte (OCR abgeschaltet) -> Nachanalyse holt die
    integrierte OCR nach und findet die Felder doch."""
    from documentai.services import tools
    monkeypatch.setattr(tools, "tessdata_verzeichnis", lambda: "")
    svc.ocr_engine = None
    try:
        pfad = samples.make_scan_handschrift_pdf(str(tmp_path / "s2.pdf"))
        model, session, engine = svc.open_document(pfad)
        svc.analyze(model, session, engine)
        assert not model.pages[0].ocr_applied
    finally:
        from documentai.core import registry
        from documentai.core.interfaces import IOcrEngine
        svc.ocr_engine = registry.resolve(IOcrEngine)
    monkeypatch.undo()
    neu = svc.felder_automatisch_erkennen(model, session, engine)
    assert neu >= 3, "Nachanalyse muss Felder nachliefern"
    assert any(f.tinte_rect is not None for f in model.fields)


# ======================================================================
# GUI: manuelles Textfeld
# ======================================================================
@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_textfeld_manuell_einfuegen_fuellen_speichern(svc, assets, tmp_path):
    """Kern-Nutzerreise: Feld von Hand setzen -> Text eingeben ->
    neue Version -> Text steht im PDF."""
    import shutil
    pfad = str(tmp_path / "leer.pdf")
    # Absichtliches Dokument ohne erkennbare Felder: Fließtext ohne
    # Beschriftungs-Zeichen (kein Doppelpunkt, kein bekanntes Label,
    # keine Lücke) – Auto-Erkennung muss leer bleiben.
    doc = pymupdf.open()
    seite = doc.new_page()
    seite.insert_text((50, 100), "Beliebiger Fließtext dieser Zeile",
                      fontsize=12)
    doc.save(pfad)
    doc.close()

    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _pump(app, lambda: view.model is not None
                     and view.model.pages)
        assert not [f for f in view.model.fields
                    if f.source != "acroform"]
        f = view.textfeld_einfuegen(pymupdf.Rect(120, 88, 320, 104))
        assert f is not None and f.source == "manuell"
        assert f.rect.width == pytest.approx(200, abs=1)
        # Überlappung verbieten (Acrobat-Verhalten: kein Doppel-Feld)
        assert view.textfeld_einfuegen(pymupdf.Rect(130, 90, 300, 102)) \
            is None
        # Klick ohne Zug -> Standardgröße
        g = view.textfeld_einfuegen(pymupdf.Rect(50, 200, 52, 202))
        assert g is not None and g.rect.width == pytest.approx(180, abs=1)
        view._set_field_value(f, "Meine Notiz")
        ergebnis = app.service.save_new_version(view.model, view.session,
                                                view.engine)
        with pymupdf.open(ergebnis["pfad"]) as doc:
            assert "Meine Notiz" in doc.load_page(0).get_text()
        assert any(a.action == "Textfeld eingefügt"
                   for a in view.model.audit)
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_feld_entfernen_mit_overlay(svc, assets, tmp_path):
    """Feld entfernen: weg aus Liste, Overlay-Eintrag mit weg."""
    import shutil
    pfad = str(tmp_path / "leer2.pdf")
    doc = pymupdf.open()
    doc.new_page()
    doc.save(pfad)
    doc.close()
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _pump(app, lambda: view.model is not None
                     and view.model.pages)
        f = view.textfeld_einfuegen(pymupdf.Rect(100, 100, 300, 116))
        assert f is not None
        view._set_field_value(f, "Weg damit")
        assert view.session.pending_overlays
        assert view.feld_entfernen(f) is True
        assert f not in view.model.fields
        assert not view.session.pending_overlays
        # AcroForm-Felder dürfen NICHT entfernt werden
        from documentai.core.models import FieldModel
        acro = FieldModel(id="acro::0::x", name="x", source="acroform")
        view.model.fields.append(acro)
        assert view.feld_entfernen(acro) is False
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_werkzeugknopffe_ohne_dokument_harmlos():
    app = _app_neu()
    try:
        app.root.update()
        app._current_felder_auto()
        app.root.update()
    finally:
        app_schliessen(app)
