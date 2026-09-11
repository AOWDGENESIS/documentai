# -*- coding: utf-8 -*-
"""Acrobat-inspirierte PDF-Werkzeuge (100 % open source, ohne Lizenzschlüssel):

Markieren/Durchstreichen/Haftnotiz/Freihand (Kommentar-Werkzeuge),
Schwärzen (Redaktion – entfernt Inhalt endgültig), Seiten verwalten
(löschen/extrahieren/zusammenführen), AES-256-Schutz, „Zuletzt geöffnet“.
"""
import os

import pymupdf
import pytest

from documentai import samples
from documentai.core.errors import DocumentAIError
from documentai.engines import annotate
from documentai.engines.pdf_mupdf import MuPdfEngine
from documentai.services import recent


@pytest.fixture()
def session(tmp_path):
    pdf = samples.make_normal_pdf(str(tmp_path / "doc.pdf"))
    engine = MuPdfEngine()
    s = engine.open(pdf)
    yield s
    try:
        s.doc.close()
    except Exception:                                   # noqa: BLE001
        pass


def _text_ohne(session_doc, page=0):
    return session_doc[page].get_text()


# ------------------------------------------------ Kommentar-Werkzeuge
def test_highlight_erzeugt_annotation(session, tmp_path):
    doc = session.doc
    worte = doc[0].get_text("words")
    assert worte, "Test-PDF sollte Text enthalten"
    w = worte[0]
    rect = (w[0], w[1], w[2], w[3])
    n = annotate.markieren(session, 0, [rect], "highlight")
    assert n >= 1
    typen = [a.type[1] for a in doc[0].annots()]
    assert "Highlight" in typen


def test_strikeout_und_underline(session):
    doc = session.doc
    worte = doc[0].get_text("words")
    w = worte[min(2, len(worte) - 1)]
    rect = (w[0] - 2, w[1] - 2, w[2] + 2, w[3] + 2)
    assert annotate.markieren(session, 0, [rect], "strikeout") >= 1
    assert annotate.markieren(session, 0, [rect], "underline") >= 1
    typen = [a.type[1] for a in doc[0].annots()]
    assert "StrikeOut" in typen and "Underline" in typen


def test_haftnotiz(session):
    annotate.haftnotiz(session, 0, 50, 50, "Wichtig: prüfen!")
    typen = [a.type[1] for a in session.doc[0].annots()]
    assert "Text" in typen
    with pytest.raises(DocumentAIError):
        annotate.haftnotiz(session, 0, 50, 50, "   ")


def test_freihand(session):
    annotate.freihand(session, 0, [(100, 100), (200, 120), (300, 150)])
    typen = [a.type[1] for a in session.doc[0].annots()]
    assert "Ink" in typen


def test_markieren_leerer_bereich_gibt_null(session):
    assert annotate.markieren(session, 0,
                              [(1, 1, 2, 2)], "highlight") == 0


# ------------------------------------------------------------ Schwärzen
def test_redaktion_entfernt_text_endgueltig(session, tmp_path):
    doc = session.doc
    worte = doc[0].get_text("words")
    ziel_wort = None
    for w in worte:
        if len(w[4]) >= 4:
            ziel_wort = w
            break
    assert ziel_wort, "brauchen ein Wort mit >= 4 Zeichen"
    rect = (ziel_wort[0] - 1, ziel_wort[1] - 1, ziel_wort[2] + 1,
            ziel_wort[3] + 1)
    n_mark = annotate.redaktion_markieren(session, 0, [rect])
    assert n_mark == 1
    n = annotate.redaktion_anwenden(session)
    assert n >= 1
    assert ziel_wort[4] not in _text_ohne(doc), \
        "Geschwärztes Wort darf nicht mehr im Text sein"


# ------------------------------------------------------- Seiten-Verwaltung
def test_seite_loeschen(session):
    vor = session.doc.page_count
    assert annotate.seite_loeschen(session, [0]) == 1
    assert session.doc.page_count == vor - 1


def test_seite_extrahieren(session, tmp_path):
    ziel = str(tmp_path / "extrakt.pdf")
    annotate.seite_extrahieren(session, 0, ziel)
    with pymupdf.open(ziel) as neu:
        assert neu.page_count == 1


def test_zusammenfuehren(session, tmp_path):
    anderes = samples.make_table_pdf(str(tmp_path / "tabelle.pdf"))
    vor = session.doc.page_count
    n = annotate.zusammenfuehren(session, [anderes])
    assert n == 1
    assert session.doc.page_count > vor


def test_zusammenfuehren_geschuetzt_erkennt(session, tmp_path):
    gesch = samples.make_encrypted_pdf(str(tmp_path / "g.pdf"), "u", "o")
    with pytest.raises(DocumentAIError):
        annotate.zusammenfuehren(session, [gesch])


# ------------------------------------------------------------- Schutz
def test_verschluesselt_speichern(session, tmp_path):
    ziel = str(tmp_path / "geschuetzt.pdf")
    result = annotate.speichern_verschluesselt(session, ziel, "Geheim!2026")
    assert os.path.isfile(ziel)
    assert result["ohne_passwort_gesperrt"] is True
    probe = pymupdf.open(ziel)
    assert probe.needs_pass
    assert probe.authenticate("Geheim!2026")
    probe.close()


def test_kurzes_passwort_abgelehnt(session, tmp_path):
    with pytest.raises(DocumentAIError):
        annotate.speichern_verschluesselt(
            session, str(tmp_path / "x.pdf"), "abc")


# ---------------------------------------------------------- Zuletzt
def test_recent_liste_leeren(tmp_path):
    db = str(tmp_path / "zuletzt.json")
    recent.leeren(db)
    assert recent.laden(db) == []
    recent.merken("/tmp/a.pdf", db)
    recent.merken("/tmp/b.pdf", db)
    recent.merken("/tmp/a.pdf", db)          # Duplikat nach vorn
    liste = recent.laden(db)
    assert liste[0]["pfad"] == "/tmp/a.pdf"
    assert len(liste) == 2
    for i in range(20):
        recent.merken(f"/tmp/x{i}.pdf", db)
    assert len(recent.laden(db)) <= recent.MAX_EINTRAEGE
    recent.leeren(db)
    assert recent.laden(db) == []


def test_recent_kaputte_datei_robust(tmp_path):
    db = tmp_path / "zuletzt.json"
    db.write_text("{kein json", encoding="utf-8")
    assert recent.laden(str(db)) == []
