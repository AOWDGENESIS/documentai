# -*- coding: utf-8 -*-
"""Formularbefüllung: AcroForm, Overlay, Checkbox, neue Versionen, Audit."""
import os
import shutil

import pymupdf
import pytest

from tests.conftest import PROFIL
from documentai.core.models import file_sha256


def _feldwerte(pdf_path: str) -> dict:
    doc = pymupdf.open(pdf_path)
    werte = {}
    for pno in range(doc.page_count):
        for w in doc.load_page(pno).widgets():
            werte[w.field_name] = w.field_value
    doc.close()
    return werte


def test_acroform_befuellen_und_version(svc, assets, tmp_path):
    quelle = shutil.copy(assets.acro, tmp_path / "Antrag.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)

    zuordnungen = svc.prepare_fill(model, PROFIL)
    namen = {z["canonical"] for z in zuordnungen}
    assert {"vorname", "nachname", "geburtsdatum", "plz", "ort",
            "email"} <= namen
    svc.apply_fill(model, session, engine, zuordnungen)
    assert model.edited is True

    result = svc.save_new_version(model, session, engine)
    assert result["pruefung"]["ok"] is True
    assert result["pruefung"]["seiten"] == 1

    werte = _feldwerte(result["pfad"])
    assert werte["vorname"] == "Max"
    assert werte["nachname"] == "Mustermann"
    assert werte["geburtsdatum"] == "01.01.1980"
    assert werte["plz"] == "49000"
    assert file_sha256(str(quelle)) == model.sha256    # Original unangetastet


def test_checkbox_setzen(svc, assets, tmp_path):
    quelle = shutil.copy(assets.acro, tmp_path / "Check.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    feld = [f for f in model.fields if f.name == "einwilligung"][0]
    svc.apply_fill(model, session, engine,
                   [{"feld_id": feld.id, "wert": True}])
    result = svc.save_new_version(model, session, engine)
    assert bool(_feldwerte(result["pfad"])["einwilligung"]) is True


def test_visuelles_formular_overlay(svc, assets, tmp_path):
    quelle = shutil.copy(assets.visual, tmp_path / "Visuell.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    svc.apply_fill(model, session, engine, svc.prepare_fill(model, PROFIL))
    result = svc.save_new_version(model, session, engine)
    text = pymupdf.open(result["pfad"]).load_page(0).get_text()
    for wert in ("Max", "Mustermann", "01.01.1980", "Musterstraße",
                 "49000 Musterstadt", "max@example.de"):
        assert wert in text, wert


def test_druckversion_v3(svc, assets, tmp_path):
    quelle = shutil.copy(assets.acro, tmp_path / "V.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    svc.apply_fill(model, session, engine,
                   svc.prepare_fill(model, {"vorname": "Anna"}))
    r2 = svc.save_new_version(model, session, engine)
    svc.apply_fill(model, session, engine,
                   svc.prepare_fill(model, {"vorname": "Beate"}))
    r3 = svc.save_new_version(model, session, engine)
    assert "_v2_bearbeitet" in r2["pfad"] and "_v3_bearbeitet" in r3["pfad"]


def test_audit_nachvollziehbar(svc, assets, tmp_path):
    quelle = shutil.copy(assets.acro, tmp_path / "Audit.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    svc.apply_fill(model, session, engine,
                   svc.prepare_fill(model, {"vorname": "Max"}))
    svc.save_new_version(model, session, engine)
    aktionen = [a.action for a in model.audit]
    for erwartet in ("Dokument geöffnet", "Felder erkannt",
                     "Feld geändert", "Neue PDF-Version erzeugt",
                     "PDF-Struktur geprüft"):
        assert erwartet in aktionen, (erwartet, aktionen)
    # Audit-Datei existiert und enthält Zeitstempel
    from documentai.core.audit import audit_path_for
    pfad = audit_path_for(model.name)
    assert os.path.exists(pfad)
    with open(pfad, encoding="utf-8") as f:
        inhalt = f.read()
    assert "Neue PDF-Version erzeugt" in inhalt


def test_sonderzeichen_und_umlaute(svc, assets, tmp_path):
    quelle = shutil.copy(assets.acro, tmp_path / "Umlaute.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    sonderzeilen = "ÄÖÜäöüß Є活血 – „„“ “ ¾ ㋡"
    svc.apply_fill(model, session, engine,
                   [{"feld_id": f.id, "wert": sonderzeilen}
                    for f in model.fields
                    if f.field_type == "text"][:3])
    result = svc.save_new_version(model, session, engine)
    werte = _feldwerte(result["pfad"])
    assert sonderzeilen in list(werte.values())


def test_langer_text_autoschrumpf(svc, assets, tmp_path):
    quelle = shutil.copy(assets.visual, tmp_path / "Lang.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    lang = "Supercalifragilisticexpialidocious " * 3
    svc.apply_fill(model, session, engine,
                   [{"feld_id": f.id, "wert": lang}
                    for f in model.fields if f.label == "Vorname"])
    result = svc.save_new_version(model, session, engine)
    text = pymupdf.open(result["pfad"]).load_page(0).get_text()
    assert "Supercalifragilistic" in text       # Text wurde platziert
