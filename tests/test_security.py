# -*- coding: utf-8 -*-
"""Sicherheit: Passwörter, Berechtigungen, Signaturen, Originale."""
import os
import shutil

import pymupdf
import pytest

from documentai.core.errors import (OperationNotAllowedError,
                                    PasswordRequiredError,
                                    WrongPasswordError)
from documentai.core.models import file_sha256
from documentai.engines.signatures import SignatureAnalyzer
from documentai.services import versioning


def test_passwort_geschuetzt_ohne_passwort(svc, assets):
    with pytest.raises(PasswordRequiredError):
        svc.open_document(assets.encrypted)


def test_falsches_passwort(svc, assets):
    with pytest.raises((WrongPasswordError, PasswordRequiredError)):
        svc.open_document(assets.encrypted, password="falsch")


def test_richtiges_passwort_oeffnet(svc, assets):
    model, session, engine = svc.open_document(assets.encrypted,
                                               password="user123")
    svc.analyze(model, session, engine)
    d = model.diagnosis
    assert d["verschluesselt"] is True
    assert d["text_vorhanden"] is True
    assert d["bearbeitung_erlaubt"] is False      # MODIFY entzogen
    assert d["drucken_erlaubt"] is True


def test_signaturfeld_erkannt(svc, assets):
    model, session, engine = svc.open_document(assets.acro)
    svc.analyze(model, session, engine)
    assert model.signature_info["vorhanden"] is True
    entry = model.signature_info["eintraege"][0]
    assert entry["feld"] == "unterschrift"
    assert "Leeres Signaturfeld" in entry["status"]


def test_signaturinfo_in_zusammenfassung(svc, assets):
    model, session, engine = svc.open_document(assets.acro)
    svc.analyze(model, session, engine)
    assert any("Signatur" in z for z in model.summary_lines())


def test_original_wird_nie_ueberschrieben(svc, assets, tmp_path):
    quelle = shutil.copy(assets.visual, tmp_path / "Formular.pdf")
    sha_vorher = file_sha256(str(quelle))
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    svc.apply_fill(model, session, engine,
                   svc.prepare_fill(model, {"vorname": "Test"}))
    result = svc.save_new_version(model, session, engine)
    neu = result["pfad"]
    assert os.path.abspath(neu) != os.path.abspath(str(quelle))
    assert "_v2_bearbeitet" in neu
    assert file_sha256(str(quelle)) == sha_vorher


def test_versionen_durchnummeriert(svc, assets, tmp_path):
    quelle = shutil.copy(assets.visual, tmp_path / "Versionierung.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    p2 = versioning.next_version_path(str(quelle))
    assert p2.endswith("Versionierung_v2_bearbeitet.pdf")
    with open(p2, "wb") as fh:
        fh.write(b"platzhalter")
    p3 = versioning.next_version_path(str(quelle))
    assert p3.endswith("Versionierung_v3_bearbeitet.pdf")


def test_backup_wird_angelegt(svc, assets, tmp_path):
    quelle = shutil.copy(assets.visual, tmp_path / "Backup.pdf")
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    pfad = versioning.backup_original(model)
    assert pfad and os.path.exists(pfad)
    assert file_sha256(pfad) == model.sha256


def test_guard_original():
    with pytest.raises(OperationNotAllowedError):
        versioning.guard_original("a.pdf", "a.pdf")


def test_gesperrtes_dokument_nur_analyse(svc, assets):
    """Bei fehlender Berechtigung: Analyse ok, keine Änderung erzwungen."""
    model, session, engine = svc.open_document(assets.encrypted,
                                               password="user123")
    svc.analyze(model, session, engine)
    assert model.diagnosis["bearbeitung_erlaubt"] is False
    # Analyse und Anzeige funktionieren trotzdem:
    assert model.diagnosis["text_vorhanden"] is True
