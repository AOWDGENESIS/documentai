# -*- coding: utf-8 -*-
"""Felderkennung auf echten Anmeldeformularen (Nutzerfund
10.09.2026, Screenshot-Vergleich mit 0_Anmeldeformular…): Gitter-
tabellen, Vier-Label-Zeilen, Doppel-Doppelpunkt-Zeilen, Rechteck-
Checkboxen, Seitenrahmen, Unterschriftslinien mit Label darunter
und die Typ-Fallen „Bisherige Schule“/„Bushaltestelle“."""
import pytest

from documentai import samples
from documentai.engines.field_detector import VisualFieldDetector
from documentai.engines.semantic import infer_type


@pytest.fixture(scope="module")
def anmelde(svc, tmp_path_factory):
    pdf = samples.make_anmelde_formular_pdf(
        str(tmp_path_factory.mktemp("anmelde") / "anmelde.pdf"))
    m, s, e = svc.open_document(pdf)
    svc.analyze(m, s, e)
    return m


def _labels(m, typ=None):
    return [f.label for f in m.fields
            if typ is None or f.field_type == typ]


# ---- Typ-Fallen (Wortgrenzen) --------------------------------------
def test_typ_fallen_keine_fehlgriffe():
    assert infer_type("Bisherige Schule") == "text"      # nicht „bis“->datum
    assert infer_type("Einstieg Bushaltestelle") == "text"  # nicht „tel“
    assert infer_type("Telefon / Notfallkontakte") == "telefon"
    assert infer_type("Telefonnummer") == "telefon"      # Kompositum
    assert infer_type("Hausnummer") == "zahl"
    assert infer_type("Geburtsdatum") == "datum"
    assert infer_type("Geburtsort") == "text"


# ---- Scheinfelder ---------------------------------------------------
def test_keine_felder_aus_seitenrahmen_oder_zierlinien(anmelde):
    """Der Seitenrahmen (545 pt breit) und Zierlinien ohne Label in
    Linienhöhe dürfen KEINE Felder erzeugen (vormals „Feld 10/11“)."""
    seitenbreit = [f for f in anmelde.fields
                   if f.rect and f.rect.width > 400]
    assert not seitenbreit, \
        [f.label for f in seitenbreit]
    assert not [l for l in _labels(anmelde) if l.startswith("Feld ")]


# ---- Vier-Label-Zeile ----------------------------------------------
def test_vier_label_zeile_vollstaendig(anmelde):
    labels = set(_labels(anmelde))
    for erwartet in ("Name", "Vorname", "Geburtsort"):
        assert erwartet in labels


# ---- Doppel-Doppelpunkt-Zeile --------------------------------------
def test_gleichzeitig_gestellte_labels_bleiben_getrennt(anmelde):
    labels = set(_labels(anmelde))
    assert "Staatsangehörigkeit" in labels
    assert "Religion" in labels
    assert "Staatsangehörigkeit Religion" not in labels


# ---- Rechteck-Checkboxen: Optionen getrennt ------------------------
def test_checkbox_optionen_verschmelzen_nicht(anmelde):
    cbs = _labels(anmelde, "checkbox")
    assert "gemeinsam" in cbs and "Mutter" in cbs and "Vater" in cbs
    assert "gemeinsam Mutter" not in cbs and "Mutter Vater" not in cbs
    assert "gemeinsamMutter" not in cbs


# ---- Typen auf dem Formular ----------------------------------------
def test_typen_stimmen(anmelde):
    nach_label = {f.label: f.field_type for f in anmelde.fields}
    assert nach_label.get("Telefon / Notfallkontakte") == "telefon"
    assert nach_label.get("E-Mail-Adressen") == "email"
    assert nach_label.get("Bisherige Schule") == "text"
    assert nach_label.get("Einstieg Bushaltestelle") == "text"


# ---- Unterschrift unter der Linie ----------------------------------
def test_unterschrift_unter_der_linie(anmelde):
    """Die Signaturlinie trägt ihre Beschriftung UNTER sich – das
    Feld muss als signatur erkannt werden (vormals „Feld 3“)."""
    sigs = [f for f in anmelde.fields if f.field_type == "signatur"]
    assert any("Unterschrift" in (f.label or "") for f in sigs)


# ---- Abgleich mit dem echten Nutzer-PDF (Struktur, ohne Daten) ------
def test_struktur_des_echten_nutzerformulars():
    """Der Nutzer-Screenshot zeigte 35 erkannte Felder mit Fehlern;
    nach den Fixes erkennt die Struktur (Nachbau ohne personen-
    bezogene Daten) die Kern-Label sauber."""
    import pymupdf
    import tempfile, os
    from documentai.services.analysis import AnalysisService
    svc = AnalysisService()
    tmp = tempfile.mkdtemp()
    pdf = samples.make_anmelde_formular_pdf(os.path.join(tmp, "n.pdf"))
    m, s, e = svc.open_document(pdf)
    svc.analyze(m, s, e)
    labels = set(_labels(m))
    kern = ["Name", "Vorname", "Geburtsort", "Anschrift",
            "Staatsangehörigkeit", "Religion",
            "Telefon / Notfallkontakte", "E-Mail-Adressen",
            "Bisherige Schule", "Einstieg Bushaltestelle",
            "gemeinsam", "Mutter", "Vater",
            "Unterschrift Erziehungsberechtigte"]
    fehlt = [k for k in kern if k not in labels]
    assert not fehlt, fehlt
