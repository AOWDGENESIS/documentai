# -*- coding: utf-8 -*-
"""End-to-End: kompletter Ablauf wie in der Anforderung beschrieben.

Analysieren → Verstehen → Struktur erkennen → Bearbeitbarkeit feststellen →
Felder erkennen → Daten zuordnen → Benutzer prüfen lassen (simuliert) →
Änderungen durchführen → validieren → neue Version erzeugen →
Ergebnis verifizieren.
"""
import os
import shutil

import pymupdf

from tests.conftest import PROFIL


def test_kompletter_ablauf_visuelles_formular(svc, assets, tmp_path):
    quelle = shutil.copy(assets.visual, tmp_path / "Anmeldung.pdf")

    # 1) Analysieren
    model, session, engine = svc.open_document(str(quelle))
    svc.analyze(model, session, engine)
    assert model.diagnosis["text_vorhanden"] is True

    # 2) Struktur & Bearbeitbarkeit
    assert model.diagnosis["bearbeitung_erlaubt"] is True
    assert model.signature_info.get("vorhanden") is False

    # 3) Felder erkennen (visuell) + Semantik
    canons = {f.canonical for f in model.fields}
    assert {"vorname", "nachname", "geburtsdatum", "plz_ort", "iban",
            "email"} <= canons

    # 4) Daten zuordnen
    zuordnungen = svc.prepare_fill(model, PROFIL)
    assert zuordnungen

    # 5) "Benutzer prüfen" (CLI/GUI-Rückfrage simuliert: alle bestätigt)
    # 6) Änderungen durchführen
    ergebnis = svc.apply_fill(model, session, engine, zuordnungen)
    assert ergebnis["overlay"] >= 5

    # 7) Validieren – Pflichtfelder jetzt gefüllt
    from documentai.core import registry
    from documentai.core.interfaces import IValidationEngine
    validator = registry.resolve(IValidationEngine)
    model.issues = validator.validate(model, session)
    assert not [i for i in model.issues if i.code == "PFLICHT_FEHLT"]

    # 8) Neue Version erzeugen + verifizieren
    res = svc.save_new_version(model, session, engine)
    assert res["pruefung"]["ok"] is True

    # 9) Ergebnis verifizieren: Werte wirklich im Dokument
    text = pymupdf.open(res["pfad"]).load_page(0).get_text()
    for wert in PROFIL.values():
        if wert and wert not in ("10",):         # Hausnummer separat
            assert wert in text or wert == "10", wert

    # 10) Original unverändert + Backup + Audit
    from documentai.core.models import file_sha256
    assert file_sha256(str(quelle)) == model.sha256
    aktionen = [a.action for a in model.audit]
    assert "Neue PDF-Version erzeugt" in aktionen


def test_kompletter_ablauf_acroform_mehrere_dokumente(svc, assets, tmp_path):
    """Ein Profil, viele Dokumente."""
    quelldateien = [shutil.copy(assets.acro, tmp_path / "A.pdf"),
                    shutil.copy(assets.acro, tmp_path / "B.pdf")]
    versionen = []
    for quelle in quelldateien:
        model, session, engine = svc.open_document(quelle)
        svc.analyze(model, session, engine)
        svc.apply_fill(model, session, engine,
                       svc.prepare_fill(model, PROFIL))
        versionen.append(svc.save_new_version(model, session,
                                              engine)["pfad"])
    assert all(os.path.exists(v) for v in versionen)
    werte = {}
    for v in versionen:
        doc = pymupdf.open(v)
        for w in doc.load_page(0).widgets():
            werte[w.field_name] = w.field_value
        doc.close()
    assert werte["vorname"] == "Max" and werte["plz"] == "49000"
