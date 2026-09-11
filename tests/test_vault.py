# -*- coding: utf-8 -*-
"""Verschlüsselter Datentresor: Sicherheit, Multi-Personen, Extraktion, CLI."""
import os
import sqlite3

import pytest

from documentai import samples
from documentai.engines.semantic import RuleSemanticAnalyzer
from documentai.services.extraction import extract_structured_data
from documentai.services.vault import (SecureVault, VaultError,
                                       VaultLockedError, default_path)

MASTER = "Master!2026_sicher"


@pytest.fixture()
def db_pfad(tmp_path) -> str:
    return str(tmp_path / "secure_vault.db")


@pytest.fixture()
def tresor(db_pfad):
    v = SecureVault.create(MASTER, db_pfad)
    yield v
    v.close()


def _familie(vault: SecureVault) -> tuple[int, int, int]:
    """Beispiel aus der Spezifikation: Administrator, Kim, Amy."""
    ich = vault.add_person("Max Mustermann", "Administrator")
    kim = vault.add_person("Kim Mustermann", "Ehepartnerin")
    amy = vault.add_person("Amy Mustermann", "Tochter")
    vault.set_datum(ich, "vorname", "Max")
    vault.set_datum(ich, "nachname", "Mustermann")
    vault.set_datum(ich, "plz", "49000")
    vault.set_datum(kim, "vorname", "Kim")
    vault.set_datum(kim, "nachname", "Mustermann")
    vault.set_datum(amy, "vorname", "Amy")
    return ich, kim, amy


# ------------------------------------------------------------ Sicherheit
def test_erstellen_und_oeffnen(db_pfad):
    v = SecureVault.create(MASTER, db_pfad)
    v.add_person("Testperson", "Rolle")
    v.save()
    v.close()
    assert os.path.exists(db_pfad)
    v2 = SecureVault.open(MASTER, db_pfad)
    assert len(v2.list_persons()) == 1
    v2.close()


def test_datei_verschluesselt_unklartext(db_pfad, tresor):
    tresor.add_person("Max Mustermann", "ich")
    tresor.set_datum(1, "iban", "DE89370400440532013000")
    tresor.set_datum(1, "geburtsdatum", "01.01.1980")
    tresor.save()
    with open(db_pfad, "rb") as f:      # sauber schließen
        raw = f.read()
    for geheim in (b"Max Mustermann", b"Mustermann",
                   b"DE89370400440532013000", b"01.01.1980",
                   b"SQLite format 3", b"CREATE TABLE", b"persons"):
        assert geheim not in raw, f"Klartext gefunden: {geheim}"


def test_falsches_passwort_abgelehnt(db_pfad, tresor):
    tresor.save()
    with pytest.raises(VaultError):
        SecureVault.open("voellig-falsch", db_pfad)


def test_manipulation_erkannt(db_pfad, tresor):
    tresor.save()
    tresor.close()
    with open(db_pfad, "rb") as f:          # sauber schließen
        data = bytearray(f.read())
    data[-8] ^= 0xFF                       # Byte im Geheimtext kippen
    with open(db_pfad + ".manip", "wb") as f:   # sauber schließen
        f.write(bytes(data))
    with pytest.raises(VaultError):
        SecureVault.open(MASTER, db_pfad + ".manip")


def test_gesperrter_zugriff(db_pfad):
    with pytest.raises(VaultLockedError):
        SecureVault().list_persons()


def test_kurzes_passwort_abgelehnt(db_pfad):
    with pytest.raises(VaultError):
        SecureVault.create("abc", db_pfad)


def test_passwort_wechsel_erhaelt_daten(db_pfad, tresor):
    ich, _, _ = _familie(tresor)
    tresor.save()
    tresor.change_master_password(MASTER, "NeuesPasswort2026!")
    tresor.close()
    with pytest.raises(VaultError):
        SecureVault.open(MASTER, db_pfad)
    v = SecureVault.open("NeuesPasswort2026!", db_pfad)
    assert v.get_data(ich)["vorname"]["wert"] == "Max"
    v.close()


def test_backup_rotation(db_pfad, tresor):
    tresor.add_person("Jemand", "")
    tresor.save()
    assert os.path.exists(db_pfad + ".bak")
    tresor.add_person("Nochmal", "")
    tresor.save()
    v2 = SecureVault.open(MASTER, db_pfad)      # .bak ist älterer Stand
    v2.close()


# ------------------------------------------------------------ Multi-Person
def test_drei_personen_isoliert(db_pfad, tresor):
    ich, kim, amy = _familie(tresor)
    assert [p["name"] for p in tresor.list_persons()] == \
        ["Max Mustermann", "Kim Mustermann", "Amy Mustermann"]
    assert tresor.get_data(ich)["vorname"]["wert"] == "Max"
    assert tresor.get_data(kim)["vorname"]["wert"] == "Kim"
    assert tresor.get_data(amy)["vorname"]["wert"] == "Amy"
    assert "nachname" not in tresor.get_data(amy)


def test_person_loeschen_mit_daten(db_pfad, tresor):
    ich, kim, amy = _familie(tresor)
    tresor.delete_person(kim)
    ids = [p["id"] for p in tresor.list_persons()]
    assert kim not in ids
    assert ich in ids and amy in ids


def test_daten_persistent_über_sperre(db_pfad, tresor):
    ich, _, _ = _familie(tresor)
    tresor.set_datum(ich, "email", "max@example.de", "test", 0.9)
    tresor.save()
    tresor.close()
    v = SecureVault.open(MASTER, db_pfad)
    daten = v.get_data(ich)
    assert daten["email"]["wert"] == "max@example.de"
    assert daten["email"]["quelle"] == "test"
    v.close()


def test_vault_log_ohne_werte(db_pfad, tresor):
    ich, _, _ = _familie(tresor)
    tresor.set_datum(ich, "iban", "DE89370400440532013000")
    eintraege = tresor.log_entries()
    for e in eintraege:
        assert "DE8937" not in e["details"] + e["aktion"]


# ------------------------------------------------------------ Profil/Nutzung
def test_export_profil_befuellt_formular(db_pfad, tresor, assets, svc):
    ich, _, _ = _familie(tresor)
    tresor.set_datum(ich, "geburtsdatum", "01.01.1980")
    tresor.set_datum(ich, "ort", "Musterstadt")
    tresor.set_datum(ich, "strasse", "Musterstraße")
    tresor.save()
    profil = tresor.export_profile(ich)
    model, session, engine = svc.open_document(assets.visual)
    svc.analyze(model, session, engine)
    zuordnungen = svc.prepare_fill(model, profil)
    werte = {z["canonical"]: z["wert"] for z in zuordnungen}
    assert werte.get("vorname") == "Max"
    assert werte.get("geburtsdatum") == "01.01.1980"
    assert werte.get("plz_ort") == "49000 Musterstadt"


# ------------------------------------------------------------ Extraktion
def test_extraktion_aus_formularfeldern(svc, assets):
    model, session, engine = svc.open_document(assets.acro)
    svc.analyze(model, session, engine)
    model.fields[0].value = "Max"
    model.fields[1].value = "Mustermann"
    model.fields[2].value = "01.01.1980"
    props = extract_structured_data(model)
    felder = {p["key"]: p["wert"] for p in props}
    assert felder.get("vorname") == "Max"
    assert felder.get("nachname") == "Mustermann"
    assert felder.get("geburtsdatum") == "01.01.1980"


def test_extraktion_aus_brief(svc, assets):
    """Normaler Brief: Namen/Adresse aus Fließtext erkennen."""
    model, session, engine = svc.open_document(assets.normal)
    svc.analyze(model, session, engine)
    props = extract_structured_data(model)
    felder = {p["key"]: p["wert"] for p in props}
    assert felder.get("vorname") == "Max"
    assert felder.get("nachname") == "Mustermann"
    assert felder.get("plz") == "49000"
    assert felder.get("ort") == "Musterstadt"
    assert "antrag" not in felder.get("vorname", "").lower()  # kein Titel


def test_extraktion_plausibilitaetsfilter(svc, assets):
    model, session, engine = svc.open_document(assets.normal)
    svc.analyze(model, session, engine)
    for p in extract_structured_data(model):
        if p["key"] == "plz":
            assert len(p["wert"]) == 5 and p["wert"].isdigit()


def test_uebernahme_und_dokumentverknuepfung(db_pfad, tresor, svc, assets):
    ich, _, _ = _familie(tresor)
    model, session, engine = svc.open_document(assets.acro)
    svc.analyze(model, session, engine)
    model.fields[0].value = "Max"
    model.fields[1].value = "Mustermann"
    props = extract_structured_data(model)
    doc_id = tresor.add_document("acro.pdf", model.sha256, 1, "pdf", ich)
    n = tresor.adopt_extractions(ich, props, doc_id)
    assert n >= 2
    assert tresor.find_document(model.sha256) == doc_id
    extr = tresor.get_extractions(doc_id)
    assert all(e["geprüft"] for e in extr)
    assert tresor.get_data(ich)["nachname"]["wert"] == "Mustermann"


def test_automatische_personenzuordnung(db_pfad, tresor, svc, assets):
    """Spec §4: Extraktion wird der richtigen Person zugeordnet."""
    ich, kim, amy = _familie(tresor)
    proposals = [{"key": "vorname", "wert": "Kim", "konfidenz": 0.9},
                 {"key": "nachname", "wert": "Mustermann",
                  "konfidenz": 0.9}]
    pid, score = tresor.match_person(proposals)
    assert pid == kim
    assert score >= 0.5
    # Und Amy:
    proposals_amy = [{"key": "vorname", "wert": "Amy", "konfidenz": 0.9}]
    pid2, _ = tresor.match_person(proposals_amy)
    assert pid2 == amy


def test_kein_match_bei_fremddaten(db_pfad, tresor):
    _familie(tresor)
    proposals = [{"key": "vorname", "wert": "Fremd", "konfidenz": 0.9}]
    pid, score = tresor.match_person(proposals)
    assert pid is None or score < 0.5


# ------------------------------------------------------------ Statistik/Format
def test_statistik(db_pfad, tresor):
    _familie(tresor)
    stats = tresor.statistics()
    assert stats["personen"] == 3
    assert stats["datenfelder"] >= 6


def test_kein_tresor_vorhanden(db_pfad):
    with pytest.raises(VaultError):
        SecureVault.open(MASTER, db_pfad + "/nicht_da.db")


def test_doppelter_create_schuetzt(db_pfad, tresor):
    tresor.save()
    with pytest.raises(VaultError):
        SecureVault.create(MASTER, db_pfad)


def test_standardpfad_im_portablen_data_ordner():
    pfad = default_path()
    assert pfad.endswith("secure_vault.db")
    assert os.sep + "data" + os.sep in pfad


# ------------------------------------------------------------ CLI
def test_cli_datenbank_roundtrip(db_pfad, svc, tmp_path, capsys, monkeypatch):
    """Kompletter CLI-Ablauf: erstellen → Personen → Daten → Import."""
    import DocumentAI as cli
    brief = samples.make_normal_pdf(str(tmp_path / "Brief.pdf"))

    def run(*argv):
        monkeypatch.setattr("sys.argv", ["DocumentAI.py"] + list(argv))
        rc = cli.main()
        out = capsys.readouterr().out
        return rc, out

    rc, out = run("--cli", "datenbank", "erstellen", "--db", db_pfad,
                  "--passwort", MASTER, "--neues-passwort", MASTER)
    assert rc == 0 and "erstellt" in out

    rc, out = run("--cli", "datenbank", "person-anlegen", "--db", db_pfad,
                  "--passwort", MASTER, "--name", "Max Mustermann",
                  "--rolle", "Administrator (ich)")
    assert rc == 0 and "Person angelegt" in out

    rc, out = run("--cli", "datenbank", "person-anlegen", "--db", db_pfad,
                  "--passwort", MASTER, "--name", "Kim Mustermann",
                  "--rolle", "Ehepartnerin")
    assert rc == 0

    rc, out = run("--cli", "datenbank", "daten-setzen", "--db", db_pfad,
                  "--passwort", MASTER, "--person", "1",
                  "--key", "plz", "--wert", "49000")
    assert rc == 0 and "Gespeichert" in out

    rc, out = run("--cli", "datenbank", "daten-anzeigen", "--db", db_pfad,
                  "--passwort", MASTER, "--person", "Max Mustermann")
    assert rc == 0 and "49000" in out

    # Import aus Brief mit automatischer Zuordnung (Freigabe per Flag)
    rc, out = run("--cli", "datenbank", "import", "--db", db_pfad,
                  "--passwort", MASTER, "--datei", brief, "--freigabe",
                  "--person", "1")
    assert rc == 0 and "übernommen" in out

    rc, out = run("--cli", "datenbank", "statistik", "--db", db_pfad,
                  "--passwort", MASTER)
    assert rc == 0 and "personen" in out

    rc, out = run("--cli", "datenbank", "personen", "--db", db_pfad,
                  "--passwort", MASTER)
    assert "Max Mustermann" in out and "Kim Mustermann" in out

    # Falsches Passwort über CLI:
    rc, out = run("--cli", "datenbank", "personen", "--db", db_pfad,
                  "--passwort", "falsch")
    assert rc == 4            # Fehlerbericht-Pfad


def test_freitext_name_heuristik_robust():
    sa = RuleSemanticAnalyzer()
    ergebnis = sa.parse_freeform_lines(
        ["Max", "Mustermann", "01.01.1980", "Musterstraße 10",
         "49000 Musterstadt", "max@example.de"])
    assert ergebnis["vorname"] == "Max"
    assert ergebnis["nachname"] == "Mustermann"
    # Titel/Floskeln werden NICHT als Namen fehlinterpretiert
    ergebnis2 = sa.parse_freeform_lines(["Antrag auf Wohngeld",
                                         "Sehr geehrte Damen und Herren"])
    assert "vorname" not in ergebnis2 or \
        ergebnis2["vorname"].lower() not in ("antrag", "sehr")
