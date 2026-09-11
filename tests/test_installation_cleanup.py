# -*- coding: utf-8 -*-
"""Auto-Aufräumen bei jeder Installation (Nutzerregel 10.09.2026):
alte Desktop-Verknüpfungen und alte Installationsordner werden
automatisch beseitigt – eigene Daten werden vorher gerettet.

Diese Tests prüfen die Logik aus winenv/installer-src/install_tail.py
direkt (plattformneutral). Unter Wine/Labor liegt die Datei nicht im
Container → Tests überspringen dort."""
import importlib.util
import os
import sys

import pytest

HIER = os.path.dirname(os.path.abspath(__file__))
INSTALL_TAIL = os.path.join(HIER, "..", "..", "winenv",
                            "installer-src", "install_tail.py")

if not os.path.exists(INSTALL_TAIL):
    it = None                          # Labor/Wine: Datei nicht vorhanden
else:
    _spec = importlib.util.spec_from_file_location(
        "install_tail", INSTALL_TAIL)
    it = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(it)

requires_it = pytest.mark.skipif(it is None,
                                 reason="install_tail.py nicht im Container")


def _install_anlegen(basis, name, mit_daten=True):
    """Kleiner Fake-Installationsordner (gleiche Signatur wie echt)."""
    pfad = os.path.join(basis, name)
    os.makedirs(os.path.join(pfad, "DocumentAI", "documentai"),
                exist_ok=True)
    offen = os.path.join(pfad, "DocumentAI-starten.bat")
    with open(offen, "w") as f:
        f.write("@echo off\n")
    if mit_daten:
        for rel in ("data/tresor.dat", "config/einstellungen.ini"):
            d = os.path.join(pfad, "DocumentAI", rel)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            with open(d, "w") as f:
                f.write("geheim: " + name)
    return pfad


@requires_it
def test_alte_verknuepfungen_werden_geloescht(tmp_path):
    desk = tmp_path / "Desktop"
    desk.mkdir()
    for name in ("DocumentAI.lnk", "DocumentAI 1.4.2.lnk",
                 "DocumentAI 1.5.0.lnk", "Anderes Programm.lnk"):
        (desk / name).write_text("x")
    (desk / "Unterordner").mkdir()
    (desk / "Unterordner" / "DocumentAI.lnk").write_text("x")
    weg = it._verknuepfungen_aufraeumen([str(desk)])
    assert len(weg) == 3
    rest = sorted(p.name for p in desk.iterdir())
    assert rest == ["Anderes Programm.lnk", "Unterordner"]
    # im Unterordner wird NICHT gelöscht (nur Desktop-Ebene)
    assert (desk / "Unterordner" / "DocumentAI.lnk").exists()


@requires_it
def test_installationserkennung(tmp_path):
    gut = _install_anlegen(str(tmp_path), "echt")
    assert it._ist_installation(gut)
    # nur Starter, kein App-Ordner -> keine Installation
    halb = tmp_path / "halb"
    halb.mkdir()
    (halb / "DocumentAI-starten.bat").write_text("x")
    assert not it._ist_installation(str(halb))
    assert not it._ist_installation(str(tmp_path))
    assert not it._ist_installation("")


@requires_it
def test_loeschschutz(tmp_path, monkeypatch):
    monkeypatch.setenv("WINDIR", str(tmp_path / "Windows"))
    ziel = str(tmp_path / "neu")
    os.makedirs(ziel)
    assert not it._sicher_zu_loeschen(ziel, ziel)             # Ziel selbst
    assert not it._sicher_zu_loeschen(str(tmp_path), ziel)    # Elternordner
    assert not it._sicher_zu_loeschen(os.path.join(ziel, "x"), ziel)
    assert not it._sicher_zu_loeschen(str(tmp_path / "Windows"), ziel)
    assert not it._sicher_zu_loeschen("C:\\", ziel)            # Laufwerk
    alt = str(tmp_path / "alte-installation")
    os.makedirs(alt)
    assert it._sicher_zu_loeschen(alt, ziel)


@requires_it
def test_alte_installationen_finden(tmp_path, monkeypatch):
    up = tmp_path / "up"; la = tmp_path / "la"
    (up / "Downloads").mkdir(parents=True)
    (la / "Programs").mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(up))
    monkeypatch.setenv("LOCALAPPDATA", str(la))
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("PUBLIC", raising=False)

    alt1 = _install_anlegen(str(up), "DocumentAI")            # direkt im Profil
    alt2 = _install_anlegen(str(up / "Downloads"),
                            "DocumentAI-Installer-v8")        # alter Installer
    alt2_app = os.path.join(alt2, "App")
    os.makedirs(alt2_app, exist_ok=True)
    # App/ im Installer ist die eigentliche alte Installation:
    os.makedirs(os.path.join(alt2_app, "DocumentAI"))
    with open(os.path.join(alt2_app, "DocumentAI-starten.bat"), "w") as f:
        f.write("x")
    alt3 = _install_anlegen(str(tmp_path), "markierte-alt")
    it._marker_schreiben(alt3)

    ziel = str(tmp_path / "neu-Ziel" / "Installation")
    os.makedirs(os.path.dirname(ziel))
    gefunden = it._alte_installationen_finden(ziel)
    assert alt1 in gefunden
    assert alt2_app in gefunden
    assert alt3 in gefunden
    assert ziel not in gefunden
    # Marker-Ordner (nur installation.txt) ist KEINE Installation:
    assert str(la / "DocumentAI") not in gefunden


@requires_it
def test_altlasten_beseitigen_retten_und_loeschen(tmp_path, monkeypatch):
    up = tmp_path / "up"; la = tmp_path / "la"
    up.mkdir(); (la / "Programs").mkdir(parents=True)
    monkeypatch.setenv("USERPROFILE", str(up))
    monkeypatch.setenv("LOCALAPPDATA", str(la))
    monkeypatch.delenv("OneDrive", raising=False)
    monkeypatch.delenv("OneDriveConsumer", raising=False)
    monkeypatch.delenv("PUBLIC", raising=False)

    alt = _install_anlegen(str(up), "DocumentAI")
    _install_anlegen(str(la / "Programs"), "Programs-Alt")   # 2. Altlast
    # Marker zeigt auf die WICHTIGSTE (jüngste) Installation:
    it._marker_schreiben(alt)
    unbeteiligt = _install_anlegen(str(tmp_path), "nein", mit_daten=False)
    # "nein" liegt neben dem Ziel-Elternordner? nein: Ziel woanders,
    # aber Signatur stimmt -> wuerde gefunden, wenn im Suchbereich.
    # Es liegt direkt in tmp_path (= Suchbereich nur bei Ziel daneben):
    ziel = str(tmp_path / "Ziel" / "App")
    os.makedirs(ziel)

    staging = str(tmp_path / "staging")
    os.makedirs(staging)
    lnks, ordner = it._altlasten_beseitigen(ziel, staging)

    assert not os.path.exists(alt)                     # Altlast gelöscht
    assert os.path.exists(unbeteiligt)                 # nicht im Suchbereich
    # gerettete Daten der Markierung (erste Fundstelle gewinnt):
    gerettet = os.path.join(staging, "data", "tresor.dat")
    assert os.path.exists(gerettet)
    with open(gerettet) as f:
        assert "DocumentAI" in f.read()
    assert isinstance(lnks, list) and isinstance(ordner, list)


@requires_it
def test_marker_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert it._marker_lesen() == ""
    os.makedirs(tmp_path / "neu")
    it._marker_schreiben(str(tmp_path / "neu"))
    assert it._marker_lesen() == str(tmp_path / "neu")
    # Pfad, der nicht mehr existiert, wird ignoriert:
    it._marker_schreiben(str(tmp_path / "weg"))
    assert it._marker_lesen() == ""


@requires_it
def test_daten_wiederherstellen_ohne_ueberschreiben(tmp_path):
    von = tmp_path / "von"; nach = tmp_path / "nach"
    (von / "data").mkdir(parents=True)
    (nach / "data").mkdir(parents=True)
    (von / "data" / "a.txt").write_text("alt")
    (von / "data" / "b.txt").write_text("alt")
    (nach / "data" / "a.txt").write_text("NEU")
    n = it._daten_wiederherstellen(str(von), str(nach),
                                   ueberschreiben=False)
    assert n == 1
    assert (nach / "data" / "a.txt").read_text() == "NEU"
    assert (nach / "data" / "b.txt").read_text() == "alt"
