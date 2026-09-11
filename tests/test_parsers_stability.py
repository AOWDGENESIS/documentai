# -*- coding: utf-8 -*-
"""Importer für DOCX/TXT/RTF/XLSX/Bilder + Stabilitätstests."""
import os

import pytest

from documentai.core.errors import DocumentDamagedError


def _schreibe(path: str, inhalt: bytes) -> str:
    with open(path, "wb") as fh:
        fh.write(inhalt)
    return path


def test_txt_parser(svc, tmp_path):
    pfad = _schreibe(str(tmp_path / "notiz.txt"), "Hallo Welt\nZweite Zeile".encode())
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert model.source_format == "txt"
    assert "Hallo Welt" in model.pages[0].text


def test_docx_parser(svc, tmp_path):
    docx = pytest.importorskip("docx")
    d = docx.Document()
    d.add_heading("Testdokument", 0)
    d.add_paragraph("Vorname: Max")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Feld", "Wert"
    t.cell(1, 0).text, t.cell(1, 1).text = "Ort", "Osnabrück"
    pfad = str(tmp_path / "test.docx")
    d.save(pfad)
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert model.source_format == "docx"
    assert "Max" in model.pages[0].text and "Osnabrück" in model.pages[0].text


def test_rtf_parser(svc, tmp_path):
    pytest.importorskip("striprtf")
    rtf = r"{\rtf1\ansi Hallo RTF Welt\par zweite Zeile}"
    pfad = _schreibe(str(tmp_path / "doc.rtf"), rtf.encode("ascii"))
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert "Hallo RTF Welt" in model.pages[0].text


def test_xlsx_parser(svc, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Wert"])
    ws.append(["Kunde", "4711"])
    pfad = str(tmp_path / "mappe.xlsx")
    wb.save(pfad)
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert "4711" in model.pages[0].text


def test_bild_parser_ocr_noetig(svc, tmp_path):
    from PIL import Image
    pfad = str(tmp_path / "scan.png")
    Image.new("RGB", (200, 100), "white").save(pfad)
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert model.source_format == "bild"
    assert model.pages[0].needs_ocr is True


def test_unbekanntes_format_klar_gemeldet(svc, tmp_path):
    pfad = _schreibe(str(tmp_path / "x.xyz"), b"bla")
    with pytest.raises(DocumentDamagedError) as info:
        svc.open_document(pfad)
    assert "Kein Importer" in str(info.value.message)


def test_muell_bytes_fuehren_nicht_zu_absturz(svc, tmp_path):
    pfad = _schreibe(str(tmp_path / "muell.pdf"),
                     os.urandom(2048))
    try:
        model, session, engine = svc.open_document(pfad)
    except DocumentDamagedError:
        return                                    # kontrollierter Fehler
    svc.analyze(model, session, engine)           # darf nicht crashen


def test_mehrere_dokumente_gleichzeitig(svc, assets):
    offen = []
    try:
        for pfad in (assets.normal, assets.acro, assets.visual):
            model, session, engine = svc.open_document(pfad)
            offen.append((model, session, engine))
        for model, session, engine in offen:
            svc.analyze(model, session, engine)
        assert len(offen) == 3
        assert sum(len(m.fields) for m, _, _ in offen) > 15
    finally:
        for _, session, _ in offen:
            try:
                session.doc.close()
            except AttributeError:
                pass                              # Nicht-PDF ohne session
            except Exception:
                pass


def test_grosse_datei_bilder(svc, assets):
    model, session, engine = svc.open_document(assets.images)
    svc.analyze(model, session, engine)
    assert model.diagnosis["seiten"] == 3
    for p in model.pages:
        assert p.image_count >= 1
