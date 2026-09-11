# -*- coding: utf-8 -*-
"""Zeilen-Formulare (Word-Stil: durchgehende Linien, Labels darauf):
Acrobat-Semantik – ein Feld pro FREIEM Linienabschnitt hinter dem
Label, Text sitzt exakt auf der Linie („just above the baseline“).
Nutzerfund 09.09.2026: Riesenfelder über ganze Zeilen = falsch."""
from documentai import samples


# Linienhöhen im Sample: Zeilen-y + 2.5 (draw_line bei y+2.5)
_ZEILEN_S0 = [87.5, 147.5, 172.5, 197.5, 222.5, 247.5, 272.5, 297.5,
              322.5, 357.5, 382.5, 407.5]


def test_zeilen_formular_alle_felder(svc, assets):
    model, session, engine = svc.open_document(assets.zeilen)
    svc.analyze(model, session, engine)
    felder = sorted(model.fields, key=lambda f: (f.page, f.rect.y,
                                                 f.rect.x))
    # 15 Felder Seite 1 + 2 Felder Seite 2
    assert len(felder) == 17, \
        f"17 Felder erwartet (15+2), gefunden: {len(felder)}"
    by_label = {f.label: f for f in felder}
    for label in ("Name", "Vorname", "Geburtsort", "Geburtsdatum",
                  "Anschrift", "Staatsangehörigkeit", "Religion",
                  "Telefon / Notfallkontakte", "E-Mail-Adressen",
                  "Bisherige Schule", "Name, Vorname", "Telefon",
                  "E-Mail", "für den Jahrgang", "Einschulungsjahr",
                  "Gewünschte Fremdsprache"):
        assert label in by_label, f"Label {label!r} fehlt: {sorted(by_label)}"
    assert by_label["Geburtsdatum"].field_type == "datum"


def test_felder_sitzen_exakt_auf_der_linie(svc, assets):
    """Unterkante jedes Feldes = Linienhöhe (Acrobat: Text auf der
    Linie, nicht darüber schwebend und nicht darunter)."""
    model, session, engine = svc.open_document(assets.zeilen)
    svc.analyze(model, session, engine)
    for f in model.fields:
        basis = f.rect.y + f.rect.height
        assert basis in _ZEILEN_S0 or basis in (92.5, 122.5), \
            f"Feld {f.label!r} endet bei {basis} – keine Formular-Linie"


def test_feld_nur_auf_freiem_abschnitt_hinter_label(svc, assets):
    """Kein Feld überdeckt ein Label-Wort, keins ragt über die
    Zeilenlinie hinaus, und die Name-Zeile hat GENAU zwei Felder."""
    model, session, engine = svc.open_document(assets.zeilen)
    svc.analyze(model, session, engine)
    seite0 = model.pages[0]
    for f in model.fields:
        if f.page != 0:
            continue
        for w in seite0.words:
            mx = w.rect.x + w.rect.width / 2
            my = w.rect.y + w.rect.height / 2
            drin = (f.rect.x - 1 <= mx <= f.rect.x + f.rect.width + 1
                    and f.rect.y - 1 <= my <= f.rect.y + f.rect.height + 1)
            assert not drin, \
                f"Feld {f.label!r} überdeckt Label-Wort {w.text!r}"
    name_zeile = [f for f in model.fields if f.page == 0
                  and abs(f.rect.y - 135.5) < 1]
    assert len(name_zeile) == 2, \
        f"Name-Zeile braucht 2 Felder (Name, Vorname): {len(name_zeile)}"
    name_zeile.sort(key=lambda f: f.rect.x)
    assert 80 < name_zeile[0].rect.x < 90          # hinter „Name:“
    assert name_zeile[0].rect.x + name_zeile[0].rect.width < 260
    assert name_zeile[1].rect.x > 250              # hinter „Vorname:“


def test_keine_riesenfelder_ueber_ganze_zeile(svc, assets):
    """Vorher stand hier das eigentliche Fehlverhalten: EIN Feld über
    die GANZE Zeile (x=50, Breite 495) ohne Label."""
    model, session, engine = svc.open_document(assets.zeilen)
    svc.analyze(model, session, engine)
    for f in model.fields:
        assert f.label, f"Feld ohne Label: {f}"
        assert f.rect.x > 60, \
            f"Feld {f.label!r} beginnt am Zeilenrand (Riesenfeld)"


def test_manuelles_werkzeug_setzt_tuple_rect(svc, assets):
    """Regression des GUI-Bugs: textfeld_einfuegen muss TUPLE
    verarbeiten (vorher: „'tuple' object has no attribute 'x'“ –
    das Werkzeug crashete bei jedem echten Mausklick)."""
    import pymupdf
    from conftest import app_schliessen
    import os
    import sys
    import pytest
    tkinter = pytest.importorskip("tkinter")
    if not (os.environ.get("DISPLAY")
            or sys.platform.startswith("win")):
        pytest.skip("kein Display vorhanden")
    from documentai.gui.app import DocumentAIApp
    app = None
    import gc
    import time
    for _ in range(3):
        try:
            app = DocumentAIApp()
            break
        except Exception:
            gc.collect()
            time.sleep(0.4)
    try:
        app.add_document(assets.zeilen)
        view = app._current()
        frist = time.time() + 40
        while time.time() < frist:
            app.root.update()
            if view.model and view.page_list.get(0, "end") \
                    and view.model.audit and view.model.audit[-1].action \
                    == "Analyse abgeschlossen":
                break
            time.sleep(0.05)
        # Tuple (der GUI-Weg!)
        f = view.textfeld_einfuegen((100.0, 430.0, 100.0, 430.0))
        assert f is not None and f.source == "manuell"
        assert f.rect.width == 180 and f.rect.height == 16
        # pymupdf.Rect (der alte Test-Weg) geht weiterhin
        f2 = view.textfeld_einfuegen(pymupdf.Rect(100, 500, 300, 516))
        assert f2 is not None and f2.rect.width == 200
    finally:
        app_schliessen(app)
