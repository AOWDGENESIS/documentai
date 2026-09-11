# -*- coding: utf-8 -*-
"""PDF-Diagnose über alle Dokumentklassen hinweg."""
import pytest

from documentai.core.errors import (DocumentDamagedError,
                                    PasswordRequiredError)


def test_normales_pdf(svc, assets):
    model, session, engine = svc.open_document(assets.normal)
    svc.analyze(model, session, engine)
    d = model.diagnosis
    assert d["seiten"] == 3
    assert d["text_vorhanden"] is True
    assert d["format"] == "PDF"
    assert d["bearbeitung_erlaubt"] is True


def test_leeres_pdf(svc, assets):
    model, session, engine = svc.open_document(assets.empty)
    svc.analyze(model, session, engine)
    assert model.diagnosis["seiten"] == 1
    assert model.diagnosis["text_vorhanden"] is False


def test_beschaedigtes_pdf_kontrolliert(svc, assets):
    """Beschädigte Datei darf NIE abstürzen – kontrollierter Fehler."""
    try:
        model, session, engine = svc.open_document(assets.corrupted)
        svc.analyze(model, session, engine)
        assert model.diagnosis["seiten"] == 0
    except DocumentDamagedError:
        pass                                     # ebenso korrekt


def test_viele_seiten(svc, assets):
    model, session, engine = svc.open_document(assets.many)
    svc.analyze(model, session, engine)
    assert model.diagnosis["seiten"] == 120
    assert len(model.pages) == 120
    assert model.pages[0].text.startswith("Seite 1")


def test_pdf_mit_bildern(svc, assets):
    model, session, engine = svc.open_document(assets.images)
    svc.analyze(model, session, engine)
    assert model.diagnosis["bilder"] is True
    assert model.diagnosis["text_vorhanden"] is False


def test_gescanntes_pdf_ocr_noetig(svc, assets):
    model, session, engine = svc.open_document(assets.scanned)
    svc.analyze(model, session, engine)
    assert model.diagnosis["ocr_noetig"] is True
    assert model.pages[0].needs_ocr is True
    assert any(i.code == "OCR_FEHLT" for i in model.issues) or \
        model.ocr_used


def test_metadaten_und_header(svc, assets):
    model, session, engine = svc.open_document(assets.normal)
    svc.analyze(model, session, engine)
    assert "PDF" in model.diagnosis["pdf_version"]


def test_sha_wird_ermittelt(svc, assets):
    model, _, _ = svc.open_document(assets.normal)
    assert len(model.sha256) == 64


def test_passwort_geschuetzt_ohne_passwort(svc, assets):
    with pytest.raises(PasswordRequiredError):
        svc.open_document(assets.encrypted)


def test_wiederholtes_oeffnen_schliessen(svc, assets):
    for _ in range(5):
        model, session, engine = svc.open_document(assets.normal)
        assert session is not None
        session.doc.close()
