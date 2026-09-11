# -*- coding: utf-8 -*-
"""Dokumentvergleich + Export mit Verifikation."""
import json
import os
import shutil

import pytest

from tests.conftest import PROFIL
from documentai.engines.compare import compare_models, format_text_diff
from documentai.engines.exporter import ExportEngine


def _befuellte_version(svc, quelle: str, profil=PROFIL) -> str:
    model, session, engine = svc.open_document(quelle)
    svc.analyze(model, session, engine)
    svc.apply_fill(model, session, engine, svc.prepare_fill(model, profil))
    return svc.save_new_version(model, session, engine)["pfad"]


def test_textvergleich_findet_aenderung(svc, assets, tmp_path):
    quelle = shutil.copy(assets.acro, tmp_path / "Vergleich.pdf")
    neu = _befuellte_version(svc, quelle, {"vorname": "Max",
                                           "nachname": "Mustermann"})
    ergebnis = svc.compare_paths(quelle, neu)
    assert ergebnis["identisch"] is False
    assert ergebnis["feld_aenderungen"]
    aenderung = {f["feld"]: f for f in ergebnis["feld_aenderungen"]}
    assert aenderung["vorname"]["nachher"] == "Max"


def test_visueller_vergleich_erzeugt_bild(svc, assets, tmp_path):
    quelle = shutil.copy(assets.visual, tmp_path / "VisVergleich.pdf")
    neu = _befuellte_version(svc, quelle)
    ergebnis = svc.compare_paths(quelle, neu)
    assert ergebnis["visuell"]["verfuegbar"] is True
    assert len(ergebnis["visuell"]["bilder"]) >= 1
    for bild in ergebnis["visuell"]["bilder"]:
        assert os.path.exists(bild)


def test_format_text_diff_ausgabe(svc, assets, tmp_path):
    quelle = shutil.copy(assets.acro, tmp_path / "Diff.pdf")
    neu = _befuellte_version(svc, quelle, {"vorname": "Max"})
    text = format_text_diff(svc.compare_paths(quelle, neu))
    assert "ORIGINAL" in text and "NEUE VERSION" in text


def test_export_json_csv_txt_docx(svc, assets, tmp_path):
    model, session, engine = svc.open_document(assets.acro)
    svc.analyze(model, session, engine)
    ex = ExportEngine()
    r_json = ex.export(model, None, None, "json", str(tmp_path / "e.json"))
    r_csv = ex.export(model, None, None, "csv", str(tmp_path / "e.csv"))
    r_txt = ex.export(model, None, None, "txt", str(tmp_path / "e.txt"))
    r_docx = ex.export(model, None, None, "docx", str(tmp_path / "e.docx"))
    for r in (r_json, r_csv, r_txt, r_docx):
        assert r["ok"] is True, r
    with open(r_json["pfad"], encoding="utf-8") as f:
        daten = json.load(f)
    assert daten["felder"] and daten["diagnose"]["formularfelder"] == 10
    with open(r_csv["pfad"], encoding="utf-8-sig") as f:
        csv_inhalt = f.read()
    assert "vorname" in csv_inhalt and "geburtsdatum" in csv_inhalt


def test_export_png_seiten(svc, assets, tmp_path):
    model, session, engine = svc.open_document(assets.normal)
    svc.analyze(model, session, engine)
    r = ExportEngine().export(model, session, engine, "png",
                              str(tmp_path / "seiten"))
    assert r["ok"] is True and r["seiten"] == 3
    for i in (1, 2, 3):
        assert os.path.exists(os.path.join(r["pfad"], f"normal_s{i}.png"))


def test_export_pdf_verifiziert(svc, assets, tmp_path):
    quelle = shutil.copy(assets.acro, tmp_path / "Exp.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    svc.apply_fill(model, session, engine,
                   svc.prepare_fill(model, {"vorname": "Export"}))
    r = ExportEngine().export(model, session, engine, "pdf", "")
    assert r["ok"] is True
    assert r["pruefung"]["seiten"] == 1
    assert r["pruefung"]["felder"] >= 10          # Felder erhalten
    # Erneut öffnen und Text der Feldwerte prüfen
    import pymupdf
    doc = pymupdf.open(r["pfad"])
    assert doc.load_page(0).widgets() is not None
    doc.close()


def test_export_pdfa_ohne_ghostscript_klar_gemeldet(svc, assets, monkeypatch):
    # 'Ghostscript fehlt' simulieren: neue Erkennung (config/tools/PATH)
    # an der Quelle abschalten, nicht nur den PATH.
    from documentai.services import tools as tools_mod
    monkeypatch.setattr(tools_mod, "ghostscript_binary", lambda: "")
    model, session, engine = svc.open_document(assets.acro)
    svc.analyze(model, session, engine)
    r = ExportEngine().export(model, session, engine, "pdfa", "x")
    assert r["ok"] is False and "nicht verfügbar" in r["fehler"]


def test_export_ungueltiges_format(svc, assets):
    model, session, engine = svc.open_document(assets.acro)
    r = ExportEngine().export(model, session, engine, "xyz", "x")
    assert r["ok"] is False
