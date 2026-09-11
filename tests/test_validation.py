# -*- coding: utf-8 -*-
"""Validierungs-Engine: Syntax, Plausibilität, Rechenfehler, Autokorrektur."""
import pytest

from documentai.core.models import DocumentModel, FieldModel, Rect4
from documentai.engines.validator import Validator, iban_checksum_ok


def _model_mit_feldern(felder: list[FieldModel]) -> DocumentModel:
    m = DocumentModel(path="test.pdf")
    m.diagnosis.update({"seiten": 1, "text_vorhanden": True})
    m.fields = felder
    return m


def _feld(**kwargs) -> FieldModel:
    base = dict(id="f1", name="f1", label="Feld", field_type="text")
    base.update(kwargs)
    return FieldModel(**base)


def test_email_ungueltig():
    m = _model_mit_feldern([_feld(field_type="email", value="kein-email")])
    issues = Validator().validate(m)
    assert any(i.code == "EMAIL_UNGUELTIG" for i in issues)


def test_email_gueltig():
    m = _model_mit_feldern([_feld(field_type="email", value="max@example.de")])
    assert not [i for i in Validator().validate(m)
                if i.code == "EMAIL_UNGUELTIG"]


def test_plz():
    m = _model_mit_feldern([_feld(field_type="plz", value="4900")])
    assert any(i.code == "PLZ_UNGUELTIG" for i in Validator().validate(m))
    m = _model_mit_feldern([_feld(field_type="plz", value="49000")])
    assert not [i for i in Validator().validate(m)
                if i.code == "PLZ_UNGUELTIG"]


def test_iban_pruefsumme():
    assert iban_checksum_ok("DE89370400440532013000") is True
    assert iban_checksum_ok("DE89370400440532013001") is False
    m = _model_mit_feldern([
        _feld(field_type="iban", value="DE89 3704 0044 0532 0130 00")])
    issues = Validator().validate(m)
    assert any(i.code == "IBAN_LEERZEICHEN" for i in issues)
    assert not any(i.code == "IBAN_PRUEFSUMME" for i in issues)


def test_datum():
    faelle = [
        ("32.13.1980", "DATUM_FORMAT"),
        ("1980-01-01", "DATUM_FORMAT"),          # ISO = ungewöhnlich (Hinweis)
        ("01.01.1980", None),
        ("01.01.2200", "DATUM_ZUKUNFT"),
    ]
    for wert, code in faelle:
        m = _model_mit_feldern([_feld(field_type="datum", canonical="datum",
                                      value=wert)])
        codes = [i.code for i in Validator().validate(m)]
        assert (code in codes) == (code is not None), (wert, codes)


def test_geburtsdatum_unplausibel():
    m = _model_mit_feldern([_feld(field_type="datum",
                                  canonical="geburtsdatum",
                                  value="01.01.2200")])
    assert any(i.code == "DATUM_UNPLAUSIBEL" for i in Validator().validate(m))


def test_pflichtfeld_fehlt():
    m = _model_mit_feldern([_feld(required=True, value=None)])
    assert any(i.code == "PFLICHT_FEHLT" for i in Validator().validate(m))


def test_text_ueberlauf():
    f = _feld(value="Ein sehr langer Text der nicht passen wird",
              rect=Rect4(0, 0, 60, 12))
    m = _model_mit_feldern([f])
    issues = Validator().validate(m)
    assert any(i.code == "TEXT_ZU_LANG" for i in issues)
    # Autokorrektur: Schrift verkleinern
    issue = [i for i in issues if i.auto_fix][0]
    assert Validator().autofix(issue, m) is True
    assert f.font_size < 10.0


def test_autofix_datum_normalisieren():
    m = _model_mit_feldern([_feld(field_type="datum", value="1980-01-01")])
    issue = [i for i in Validator().validate(m) if i.auto_fix][0]
    assert Validator().autofix(issue, m) is True
    assert m.fields[0].value == "01.01.1980"


def test_rechenfehler_tabelle(svc, assets):
    model, session, engine = svc.open_document(assets.table_err)
    svc.analyze(model, session, engine)
    assert any(i.code == "RECHENFEHLER" for i in model.issues)


def test_tabelle_korrekt_kein_rechenfehler(svc, assets):
    model, session, engine = svc.open_document(assets.table_ok)
    svc.analyze(model, session, engine)
    assert not any(i.code == "RECHENFEHLER" for i in model.issues)
    assert len(model.tables) == 1
    assert "Menge" in model.tables[0].header


def test_moegliche_fehlzuordnung():
    felder = [
        _feld(id="a", name="a", label="Vorname", canonical="vorname",
              value="Muster"),
        _feld(id="b", name="b", label="Nachname", canonical="nachname",
              value="Muster"),
    ]
    issues = Validator().validate(_model_mit_feldern(felder))
    assert any(i.code == "MOEGLICHE_FEHLZUORDNUNG" for i in issues)


def test_tabellen_header_mit_none_crasht_nicht(monkeypatch):
    """Regression (Nutzerfund 03.09.2026): 'NoneType' has no 'lower'.

    Echte PDFs (z. B. Anträge) können Tabellen mit leeren/verbundenen
    Zellen enthalten; find_tables lieferte im Header-Fallback-Pfad rohe
    None-Zellen → Validierung/Analyse crashte beim Vergleich.
    """
    from documentai.core.models import (DocumentModel, PageModel, Rect4,
                                        TableData)
    from documentai.engines import pdf_mupdf as pdf_mod
    from documentai.engines.validator import Validator

    def fake_find_tables(self, session):
        return [TableData(page=0,
                          bbox=Rect4(x=0, y=0, width=200, height=40),
                          header=[None, "Menge", "Einzelpreis", "Summe"],
                          rows=[["Posten", "2", "3,50", "7,00"],
                                [None, None, None, None]])]

    monkeypatch.setattr(pdf_mod.MuPdfEngine, "find_tables",
                        fake_find_tables)
    m = DocumentModel(name="antrag", path="antrag.pdf")
    m.pages = [PageModel(number=0)]
    issues = Validator().validate(m)      # darf KEIN AttributeError werfen
    assert isinstance(issues, list)
