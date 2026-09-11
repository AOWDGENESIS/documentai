# -*- coding: utf-8 -*-
"""Tabellen-Felderkennung: mehrere Felder in Rastern (Acrobat
„Prepare Form“-Auto-Detect) – Nutzerfund 09.09.2026: „es wurde ein
einziges Textfeld erkannt, aber die anderen wurden ignoriert“."""
from documentai import samples
from documentai.core.models import Rect4, Word
from documentai.engines.field_detector import VisualFieldDetector


# ======================================================================
# Formular-Raster: jede leere Zelle wird ein Feld
# ======================================================================
def test_formular_raster_erkennt_alle_leeren_zellen(svc, tmp_path):
    pfad = samples.make_leerfelder_tabelle_pdf(str(tmp_path / "raster.pdf"))
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    labels = [f.label for f in
              sorted(model.fields, key=lambda f: f.rect.y)]
    assert labels == ["Name", "Vorname", "Geburtsdatum",
                      "Staatsangehörigkeit", "Straße und Hausnummer",
                      "PLZ", "Ort", "Telefon"], \
        "Alle 8 leeren Zellen müssen Felder mit Zeilen-Label werden"
    assert len(model.fields) == 8


def test_formular_raster_feldtypen(svc, tmp_path):
    """Semantik greift auch in Rastern: Geburtsdatum → datum,
    PLZ → plz, Telefon → telefon."""
    pfad = samples.make_leerfelder_tabelle_pdf(str(tmp_path / "raster.pdf"))
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    by_label = {f.label: f for f in model.fields}
    assert by_label["Geburtsdatum"].field_type == "datum"
    assert by_label["PLZ"].field_type == "plz"
    assert by_label["Telefon"].field_type == "telefon"
    assert by_label["Geburtsdatum"].required is True


def test_formular_raster_mehrseitig(svc, tmp_path):
    """Dasselbe Raster auf zwei Seiten: Felder bleiben pro Seite
    erhalten (mehrzeilige/mehrfach-Formulare)."""
    import pymupdf
    pfad = samples.make_leerfelder_tabelle_pdf(str(tmp_path / "raster.pdf"))
    doc = pymupdf.open(pfad)
    doc.fullcopy_page(0)                      # Seite 1 = Kopie von Seite 0
    doc.save(str(tmp_path / "raster2.pdf"), garbage=3, deflate=True)
    doc.close()
    model, session, engine = svc.open_document(str(tmp_path / "raster2.pdf"))
    svc.analyze(model, session, engine)
    pro_seite = {0: 0, 1: 0}
    for f in model.fields:
        pro_seite[f.page] = pro_seite.get(f.page, 0) + 1
    assert pro_seite[0] == 8 and pro_seite[1] == 8, \
        f"beide Seiten brauchen je 8 Felder, nicht {pro_seite}"


# ======================================================================
# Datentabellen dürfen KEINE Wildfelder werfen
# ======================================================================
def test_datentabelle_keine_wildfelder(svc, assets):
    """Kostenübersicht (fast alle Zellen gefüllt) ist eine Datentabelle
    und gehört nicht in die Eingabemaske."""
    model, session, engine = svc.open_document(assets.table_ok)
    svc.analyze(model, session, engine)
    assert model.fields == [], \
        f"Datentabelle darf keine Felder werfen: {model.fields}"


def test_leerer_tabellenrand_keine_etiketten_zeugnis(svc, assets):
    """Das Gitter einer Tabelle zieht oft eine leere Schlusszeile –
    deren Zellen dürfen keine Labels von weiter oben erben."""
    model, session, engine = svc.open_document(assets.table_err)
    svc.analyze(model, session, engine)
    labels = {f.label for f in model.fields}
    assert not labels & {"C", "1", "135,50", "130,00"}, \
        f"Schlussrand-Zellen mit alten Werten als Label: {labels}"


# ======================================================================
# Label-Suche in breiten Labelspalten (Unit-Ebene)
# ======================================================================
def test_zellen_label_links_breite_spalte():
    """Labelspalten sind oft breiter als das 90-pt-Fenster der
    Unterstrich-Erkennung – hier: 115 pt Abstand."""
    det = VisualFieldDetector()
    zelle = Rect4(200.0, 80.0, 220.0, 22.0)
    words = [
        Word("Name", Rect4(55.0, 85.0, 30.0, 10.0)),
        Word("Vorname", Rect4(55.0, 107.0, 42.0, 10.0)),
    ]
    assert det._zellen_label_links(words, zelle) == "Name"


def test_zellen_label_links_sammelt_phrase():
    det = VisualFieldDetector()
    zelle = Rect4(200.0, 80.0, 220.0, 22.0)
    words = [
        Word("Straße", Rect4(55.0, 85.0, 28.0, 10.0)),
        Word("und", Rect4(86.0, 85.0, 20.0, 10.0)),
        Word("Hausnummer", Rect4(108.0, 85.0, 55.0, 10.0)),
    ]
    assert det._zellen_label_links(words, zelle) == "Straße und Hausnummer"


def test_zellen_label_links_ignoriert_zeile_darueber():
    det = VisualFieldDetector()
    zelle = Rect4(200.0, 124.0, 220.0, 22.0)
    words = [
        Word("Name", Rect4(55.0, 85.0, 30.0, 10.0)),      # 2 Bänder höher
        Word("PLZ", Rect4(55.0, 129.0, 22.0, 10.0)),      # eigene Zeile
    ]
    assert det._zellen_label_links(words, zelle) == "PLZ"


# ======================================================================
# Lücken-Erkennung auf Digital-PDFs (Textebene, kein Scan)
# ======================================================================
def _text_pdf(pfad, zeilen):
    import pymupdf
    doc = pymupdf.open()
    seite = doc.new_page()
    for i, text in enumerate(zeilen):
        seite.insert_text((50, 100 + i * 25), text, fontsize=12)
    doc.save(pfad, garbage=3, deflate=True)
    doc.close()
    return pfad


def test_digital_label_mit_leerer_zeile_wird_feld(svc, tmp_path):
    """„Notizen:“ allein am Zeilenanfang + große Lücke = Eingabefeld
    (Acrobat Fill&Sign-Prinzip, Nutzerwunsch 09.09.2026)."""
    pfad = _text_pdf(str(tmp_path / "notiz.pdf"), ["Notizen:"])
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    labels = [f.label for f in model.fields]
    assert "Notizen" in labels, f"Notizen-Feld erwartet: {labels}"


def test_digital_gefuellte_zeile_kein_feld(svc, tmp_path):
    """Bereits ausgefüllte Zeilen dürfen KEIN Feld über dem Wert legen
    (sonst überklebt die Maske den Inhalt)."""
    pfad = _text_pdf(str(tmp_path / "gefuellt.pdf"),
                     ["Telefon: 030 12345678"])
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert model.fields == [], \
        f"gefüllte Zeile darf kein Feld werfen: {model.fields}"


def test_digital_fliesstext_kein_feld(svc, tmp_path):
    """Normaler Fließtext (keine Beschriftung) bleibtfelderlos."""
    pfad = _text_pdf(str(tmp_path / "brief.pdf"),
                     ["Sehr geehrte Damen und Herren,",
                      "anbei erhalten Sie die gewünschten Unterlagen",
                      "und eine Übersicht der offenen Posten."])
    model, session, engine = svc.open_document(pfad)
    svc.analyze(model, session, engine)
    assert model.fields == [], \
        f"Fließtext darf keine Felder werfen: {model.fields}"
