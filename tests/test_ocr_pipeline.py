# -*- coding: utf-8 -*-
"""OCR-Pipeline: Fake-Engine (Schnittstellentest) + echte OCR falls vorhanden."""
import shutil
import subprocess

import pytest

from documentai.core.models import Rect4, Word


class FakeOcrEngine:
    """Simuliert Tesseract für die Pipeline (Positionen + Konfidenz)."""

    name = "Fake-OCR (Test)"
    priority = 200

    @staticmethod
    def is_available() -> bool:
        return True

    def ocr_page(self, png_bytes: bytes, language: str = "deu+eng"):
        worter = []
        zeilen = [
            ("Anmeldeformular", 50, 45, 88),
            ("Vorname:", 50, 92, 48),
            ("________", 140, 92, 300),
            ("Nachname:", 50, 122, 55),
            ("________", 140, 122, 300),
            ("Geburtsdatum:", 50, 152, 78),
            ("________", 140, 152, 300),
            ("Ja", 68, 349, 12),
            ("Nein", 158, 349, 20),
            ("☐", 50, 343, 10),
            ("☐", 140, 343, 10),
        ]
        for text, x, y, breite in zeilen:
            worter.append(Word(text=text, rect=Rect4(x, y, breite, 10),
                               confidence=92.5 if text != "☐" else 70.0))
        return worter


def test_ocr_pipeline_mit_fake_engine(svc, assets):
    svc.ocr_engine = FakeOcrEngine()
    try:
        model, session, engine = svc.open_document(assets.scanned)
        svc.analyze(model, session, engine)
        assert model.ocr_used is True
        assert model.pages[0].ocr_applied is True
        labels = {f.label for f in model.fields}
        assert "Vorname" in labels and "Geburtsdatum" in labels
        glyphs = [f for f in model.fields if f.field_type == "checkbox"]
        assert len(glyphs) >= 1                    # ☐ aus OCR erkannt
        # niedrige Konfidenz wird gemeldet (☐ hat 70 %, Rest 92 %)
        assert all(isinstance(w.confidence, float)
                   for w in model.pages[0].words)
    finally:
        from documentai.core import registry
        from documentai.core.interfaces import IOcrEngine
        svc.ocr_engine = registry.resolve(IOcrEngine)


def test_ocr_nicht_verfuegbar_degradiert_sauber(svc, assets, monkeypatch):
    from documentai.services import tools
    # Auch die integrierte OCR (tessdata) wegmocken -> echter Notlauf
    monkeypatch.setattr(tools, "tessdata_verzeichnis", lambda: "")
    svc.ocr_engine = None
    try:
        model, session, engine = svc.open_document(assets.scanned)
        svc.analyze(model, session, engine)
        assert model.ocr_used is False
        assert model.pages[0].needs_ocr is True
        assert any(i.code == "OCR_FEHLT" for i in model.issues)
    finally:
        from documentai.core import registry
        from documentai.core.interfaces import IOcrEngine
        svc.ocr_engine = registry.resolve(IOcrEngine)


def test_tesseract_verfuegbarkeit_korrekt_ermittelt():
    """Verfügbarkeit folgt der portablen Erkennung (config → tools/ → PATH)."""
    from documentai.engines.ocr import TesseractOcrEngine
    from documentai.services.tools import tesseract_binary
    assert TesseractOcrEngine.is_available() == bool(tesseract_binary())


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract fehlt")
def test_echte_ocr_erkennung(svc, tmp_path):
    """Echter OCR-Test – läuft nur, wenn Tesseract installiert ist."""
    from documentai import samples
    pfad = samples.make_scanned_pdf(str(tmp_path / "ocr_test.pdf"))
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert model.ocr_used is True
    assert any("Vorname" in (f.label or "") for f in model.fields)
