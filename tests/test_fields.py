# -*- coding: utf-8 -*-
"""Felderkennung: AcroForm, visuelle Felder, Semantik, Synonyme."""
from documentai.engines.semantic import (RuleSemanticAnalyzer,
                                         match_canonical, normalize)


def test_acroform_felder_vollstaendig(svc, assets):
    model, session, engine = svc.open_document(assets.acro)
    svc.analyze(model, session, engine)
    by_name = {f.name: f for f in model.fields}
    for name in ("vorname", "nachname", "geburtsdatum", "strasse", "plz",
                 "ort", "email", "einwilligung", "anrede", "unterschrift"):
        assert name in by_name, f"Feld {name} fehlt"
    assert by_name["einwilligung"].field_type == "checkbox"
    assert by_name["anrede"].field_type == "dropdown"
    assert by_name["anrede"].options == ["Herr", "Frau", "Diverse"]
    assert by_name["unterschrift"].field_type == "signatur"
    assert by_name["vorname"].required is True
    assert by_name["strasse"].required is False


def test_visuelle_felder_unterstriche(svc, assets):
    model, session, engine = svc.open_document(assets.visual)
    svc.analyze(model, session, engine)
    labels = {f.label for f in model.fields}
    for erwartet in ("Vorname", "Nachname", "Geburtsdatum", "Straße",
                     "PLZ / Ort", "E-Mail", "IBAN", "Telefon"):
        assert erwartet in labels, f"{erwartet} nicht erkannt in {labels}"
    felder = [f for f in model.fields if f.label == "Geburtsdatum"]
    assert felder[0].field_type == "datum"
    assert felder[0].rect is not None and felder[0].rect.width > 100


def test_checkboxen_visuell(svc, assets):
    model, session, engine = svc.open_document(assets.visual)
    svc.analyze(model, session, engine)
    checkboxen = [f for f in model.fields if f.field_type == "checkbox"]
    labels = {f.label for f in checkboxen}
    assert "Ja" in labels and "Nein" in labels


def test_semantik_synonyme_de_en():
    faelle = {
        "Geburtsdatum:": "geburtsdatum",
        "Date of Birth": "geburtsdatum",
        "DOB": "geburtsdatum",
        "geboren am": "geburtsdatum",
        "geb.": "geburtsdatum",
        "Vorname": "vorname",
        "First Name": "vorname",
        "Nachname": "nachname",
        "Surname": "nachname",
        "PLZ": "plz",
        "ZIP Code": "plz",
        "Postleitzahl": "plz",
        "E-Mail": "email",
        "E-Mail Adresse": "email",
        "IBAN": "iban",
        "Telefon": "telefon",
        "Phone": "telefon",
        "Kunden-Nr.": "kundennummer",
        "Aktenzeichen": "aktenzeichen",
        "Unterschrift": "unterschrift",
        "Signature": "unterschrift",
        "Straße": "strasse",
        "Street": "strasse",
        "Ort": "ort",
        "City": "ort",
    }
    for label, erwartet in faelle.items():
        canon, conf = match_canonical(label)
        assert canon == erwartet, f"{label!r} → {canon} (erwartet {erwartet})"
        assert conf >= 0.84


def test_plz_ort_kombiniert(svc, assets):
    model, session, engine = svc.open_document(assets.visual)
    svc.analyze(model, session, engine)
    feld = [f for f in model.fields if f.label == "PLZ / Ort"][0]
    assert feld.canonical == "plz_ort"


def test_freitext_parsing_beispiel_anforderung():
    sa = RuleSemanticAnalyzer()
    ergebnis = sa.parse_freeform_lines([
        "Max", "Mustermann", "01.01.1980",
        "Musterstraße 10", "49000 Musterstadt", "max@example.de",
    ])
    assert ergebnis["vorname"] == "Max"
    assert ergebnis["nachname"] == "Mustermann"
    assert ergebnis["geburtsdatum"] == "01.01.1980"
    assert ergebnis["strasse"] == "Musterstraße"
    assert ergebnis["hausnummer"] == "10"
    assert ergebnis["plz"] == "49000"
    assert ergebnis["ort"] == "Musterstadt"
    assert ergebnis["email"] == "max@example.de"


def test_profil_zuordnung_mit_kombinierten_feldern(svc, assets):
    model, session, engine = svc.open_document(assets.visual)
    svc.analyze(model, session, engine)
    sa = RuleSemanticAnalyzer()
    zu = sa.match_profile(model.fields, {
        "vorname": "Max", "nachname": "Mustermann", "plz": "49000",
        "ort": "Musterstadt"})
    plz_ort = [z for z in zu if z["canonical"] == "plz_ort"]
    assert plz_ort and plz_ort[0]["wert"] == "49000 Musterstadt"
    assert plz_ort[0]["pruefen"] is True       # Benutzer soll bestätigen


def test_normalize():
    assert normalize("E-Mail Adresse:") == "e mail adresse"
    assert normalize("Straße") == "strasse"
    assert normalize("  Vorname  ") == "vorname"
