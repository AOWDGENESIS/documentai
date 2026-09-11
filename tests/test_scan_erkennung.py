# -*- coding: utf-8 -*-
"""Scan-Felderkennung: Rasterstruktur, integrierte OCR und die
pixelgenaue Ersetzung handschriftlicher Einträge."""
import os

import pymupdf
import pytest

from documentai import samples
from documentai.services.tools import tessdata_verzeichnis

HAT_TESSDATA = bool(tessdata_verzeichnis())


def _scan_pfad(tmp_path) -> str:
    return samples.make_scan_handschrift_pdf(str(tmp_path / "scan_hand.pdf"))


def _region_mittelwert(pfad: str, rect) -> float:
    """Mittlere Helligkeit (0=schwarz … 255=weiß) in einem Rechteck."""
    with pymupdf.open(pfad) as doc:
        pix = doc.load_page(0).get_pixmap(
            dpi=200, colorspace=pymupdf.csGRAY,
            clip=pymupdf.Rect(rect))
        daten = pix.samples
        return sum(daten) / max(1, len(daten))


# ======================================================================
# Raster-Struktur
# ======================================================================
def test_struktur_erkennt_linien_kaestchen_und_tinte(tmp_path):
    from documentai.engines.scan_struktur import analysiere
    pfad = _scan_pfad(tmp_path)
    with pymupdf.open(pfad) as doc:
        png = doc.load_page(0).get_pixmap(dpi=200).tobytes("png")
    s = analysiere(png, dpi=200.0)
    assert len(s.linien_h) >= 3                    # drei Feldlinien
    kaestchen = [k for k in s.kasten if k.breite <= 25 and k.hoehe <= 25]
    assert kaestchen, "Kontrollkästchen müssen erkannt werden"
    # Tinte (Handschrift) über der obersten Feldlinie:
    l = sorted(s.linien_h, key=lambda x: x.mitte_y)[0]
    assert s.tinte_bbox(l.x0 + 5, l.y0 - 14, l.x1 - 40, l.y0 - 1) is not None
    # und NICHT dort, wo kein Eintrag steht (rechter Linienbereich frei):
    assert s.tinte_bbox(l.x1 - 120, l.y0 - 12, l.x1 - 5, l.y0 - 1) is None


def test_otsu_trennt_hell_und_dunkel():
    from documentai.engines.scan_struktur import _otsu
    hist = [0] * 256
    for i in range(256):
        hist[i] = 10 if i in (60, 61, 62, 200, 201, 202) else 0
    schwelle = _otsu(hist)
    assert 62 <= schwelle <= 200


# ======================================================================
# Analyse-Pipeline auf dem Handschrift-Scan
# ======================================================================
@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_scan_formular_felder_super_praezise(svc, tmp_path):
    pfad = _scan_pfad(tmp_path)
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    pm = model.pages[0]
    assert pm.ocr_applied and pm.ocr_integriert
    labels = {f.label for f in model.fields}
    assert {"Vorname", "Nachname", "Geburtsdatum"} <= labels
    # Präzision: Feldunterkante liegt auf der gezeichneten Linie (y=103)
    vorname = next(f for f in model.fields if f.label == "Vorname")
    assert abs((vorname.rect.y + vorname.rect.height) - 103.0) <= 2.5
    assert vorname.tinte_rect is not None      # Handschrift lokalisiert
    # Nachname: Tinte liegt vollständig OBERHALB der Linie …
    nachname = next(f for f in model.fields if f.label == "Nachname")
    assert nachname.tinte_rect.y + nachname.tinte_rect.height \
        <= nachname.rect.y + nachname.rect.height + 0.5
    # … Vorname hat Unterlängen: Tinte ragt UNTER die Linie (Band +6,5)
    assert vorname.tinte_rect.y + vorname.tinte_rect.height \
        > vorname.rect.y + vorname.rect.height
    # angehaktes Kästchen als Checkbox mit erkanntem Haken
    haken = [f for f in model.fields if f.field_type == "checkbox"
             and f.value]
    assert haken and haken[0].tinte_rect is not None


@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_integrierte_ocr_ohne_externes_tesseract(svc, tmp_path):
    """Scans bleiben analysierbar, selbst ohne tesseract.exe: die in
    PyMuPDF einkompilierte Engine + mitgelieferte tessdata genügen."""
    from documentai.core import registry
    from documentai.core.interfaces import IOcrEngine
    svc.ocr_engine = None
    try:
        pfad = _scan_pfad(tmp_path)
        model, session, engine = svc.open_document(pfad)
        svc.analyze(model, session, engine)
        assert model.ocr_used is True
        assert model.pages[0].ocr_integriert is True
        assert any("Vorname" in (f.label or "") for f in model.fields)
    finally:
        svc.ocr_engine = registry.resolve(IOcrEngine)


def test_ohne_ocr_noch_immer_feldlinien(svc, tmp_path, monkeypatch):
    """Selbst ganz ohne OCR liefert die Rasterstruktur die Felder mit
    Positions- und Tinten-Erkennung (Beschriftung fehlt dann halt)."""
    from documentai.core import registry
    from documentai.core.interfaces import IOcrEngine
    from documentai.services import tools
    monkeypatch.setattr(tools, "tessdata_verzeichnis", lambda: "")
    svc.ocr_engine = None
    try:
        pfad = _scan_pfad(tmp_path)
        model, session, engine = svc.open_document(pfad)
        svc.analyze(model, session, engine)
        assert model.pages[0].needs_ocr
        mit_tinte = [f for f in model.fields if f.tinte_rect is not None]
        assert len(mit_tinte) >= 3      # 3 beschriebene Linien + Haken
        linien_felder = [f for f in mit_tinte
                         if abs((f.rect.y + f.rect.height) - 103.0) <= 2.5
                         or abs((f.rect.y + f.rect.height) - 135.0) <= 2.5
                         or abs((f.rect.y + f.rect.height) - 167.0) <= 2.5]
        assert len(linien_felder) == 3
    finally:
        svc.ocr_engine = registry.resolve(IOcrEngine)


# ======================================================================
# Korrektur: Handschrift sauber ersetzen
# ======================================================================
@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_korrektur_ersetzt_handschrift_sauber(svc, tmp_path):
    pfad = _scan_pfad(tmp_path)
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    f = next(x for x in model.fields if x.label == "Nachname")
    assert f.tinte_rect is not None
    t = f.tinte_rect
    region = (t.x - 1, t.y - 1, t.x + t.width + 1, t.y + t.height + 0.5)
    vorher = _region_mittelwert(pfad, region)
    assert vorher < 235                  # da ist dunkle Tinte

    # 1) Leer-Korrektur: alter Eintrag muss SAUBER verschwinden
    #    (Produktfluss über save_version: Version 1 = geleert)
    svc.apply_fill(model, session, engine,
                   [{"feld_id": f.id, "wert": ""}])
    v1 = engine.save_version(session, model, "Handschrift entfernt")
    assert _region_mittelwert(v1["pfad"], region) > 250.0

    # 2) Neuer Wert steht anschließend sauber im Feld (Version 2)
    svc.apply_fill(model, session, engine,
                   [{"feld_id": f.id, "wert": "Musterfrau"}])
    v2 = engine.save_version(session, model, "Neuer Wert")
    ziel = v2["pfad"]
    with pymupdf.open(ziel) as doc:
        text = doc.load_page(0).get_text()
    assert "Musterfrau" in text          # neuer Wert steht drin

    # Feldlinie bleibt erhalten: Pixelzeile auf der Linie weiter dunkel
    linie_y = f.rect.y + f.rect.height
    streifen = (f.rect.x + 2, linie_y + 0.3, f.rect.x + 60, linie_y + 1.0)
    assert _region_mittelwert(ziel, streifen) < 150


@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_korrektur_entfernt_haken_in_kaestchen(svc, tmp_path):
    pfad = _scan_pfad(tmp_path)
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    f = next(x for x in model.fields
             if x.field_type == "checkbox" and x.value)
    assert f.tinte_rect is not None
    svc.apply_fill(model, session, engine,
                   [{"feld_id": f.id, "wert": False}])
    ziel = engine.save_version(session, model, "Haken entfernt")["pfad"]
    # Inneres des Kästches ist jetzt weiß …
    innen = (f.rect.x + 2, f.rect.y + 2,
             f.rect.x + f.rect.width - 2, f.rect.y + f.rect.height - 2)
    assert _region_mittelwert(ziel, innen) > 240
    # … aber der Rand des Kästchens steht weiterhin dunkel.
    rand = (f.rect.x, f.rect.y + 0.1,
            f.rect.x + f.rect.width, f.rect.y + 0.9)
    assert _region_mittelwert(ziel, rand) < 150


@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_scan_uebersteht_mehrere_versionen(svc, tmp_path):
    """Regression: Nach dem Speichern einer Version durfte eine weitere
    Redaktion das Seitenbild nie entfernen (Scan bleibt Scan)."""
    pfad = _scan_pfad(tmp_path)
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    textfeld = next(x for x in model.fields if x.label == "Vorname")
    for wert in ("", "Anna"):
        svc.apply_fill(model, session, engine,
                       [{"feld_id": textfeld.id, "wert": wert}])
        ergebnis = engine.save_version(session, model, "Korrektur")
        assert ergebnis["pruefung"]["ok"]
    letzte = session.saved_versions[-1]
    with pymupdf.open(letzte) as doc:
        assert doc.load_page(0).get_images(full=True), \
            "Seitenbild darf nach mehreren Versionen nicht verschwinden"
        assert "Anna" in doc.load_page(0).get_text()


@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_unterlaengen_unter_der_linie_werden_entfernt(svc, tmp_path):
    """Handschrift reicht oft UNTER die Feldlinie (g, j, p, ß …).
    Die Korrektur muss beide Seiten säubern – die Linie selbst und
    die darunterliegende Zeile dürfen nicht beschädigt werden."""
    pfad = _scan_pfad(tmp_path)
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    f = next(x for x in model.fields if x.label == "Vorname")
    linie = f.rect.y + f.rect.height
    band_unten = (f.rect.x + 52, linie + 1.2, f.rect.x + 68, linie + 5.3)
    assert _region_mittelwert(pfad, band_unten) < 240   # da ist Tinte

    svc.apply_fill(model, session, engine, [{"feld_id": f.id, "wert": ""}])
    ziel = engine.save_version(session, model, "Unterlängen entfernt")["pfad"]
    # Unterlängen sauber entfernt …
    assert _region_mittelwert(ziel, band_unten) > 250.0
    # … Linie bleibt …
    linien_streifen = (f.rect.x + 2, linie + 0.45, f.rect.x + 60, linie + 0.85)
    assert _region_mittelwert(ziel, linien_streifen) < 150
    # … und die Nachname-Zeile darunter bleibt unangetastet.
    nachname = next(x for x in model.fields if x.label == "Nachname")
    assert nachname.tinte_rect is not None
    nt = nachname.tinte_rect
    region_n = (nt.x - 1, nt.y - 1, nt.x + nt.width + 1, nt.y + nt.height)
    assert _region_mittelwert(ziel, region_n) < 235


@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_mehrseitiger_scan_erkennt_felder_auf_allen_seiten(svc, tmp_path):
    pfad = _scan_pfad(tmp_path)
    doppel = str(tmp_path / "scan_2seiten.pdf")
    with pymupdf.open(pfad) as doc:
        with pymupdf.open() as out:
            out.insert_pdf(doc)
            out.insert_pdf(doc)
            out.save(doppel, deflate=True)
    model, session, engine = svc.open_document(doppel)
    svc.analyze(model, session, engine)
    assert len(model.pages) == 2
    for pno in (0, 1):
        assert model.pages[pno].ocr_applied
        mit_tinte = [f for f in model.fields
                     if f.page == pno and f.tinte_rect is not None]
        assert len(mit_tinte) >= 3, f"Seite {pno + 1}: Felder fehlen"
    # verschiedene Seiten bleiben verschiedene Felder (kein Dedupe-Fehler)
    ids = [f.id for f in model.fields]
    assert len(ids) == len(set(ids))
