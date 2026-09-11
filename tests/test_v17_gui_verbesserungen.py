# -*- coding: utf-8 -*-
"""v17 (Nutzerfund 10.09.2026, „rot ist schlecht, gelb wäre richtig“):
Zeilen-Paar-Felderkennung (Eingabetext AUF der Linie), Felder ver-
schieben, Werkzeug-Symbole, Hell-/Dunkel-Design, OCR-Vorverarbeitung."""
import gc
import os
import sys
import time

import pytest

from conftest import app_schliessen
from documentai import samples
from documentai.bilder import symbole

tkinter = pytest.importorskip("tkinter")
HAVE_DISPLAY = (os.environ.get("DISPLAY") or
                sys.platform.startswith("win"))


# ======================================================================
# Symbole
# ======================================================================
def test_alle_werkzeug_symbole_zeichnbar():
    for name in symbole.verfuegbare_symbole():
        bild = symbole.symbol_bild(name, "#3b7dd8", 18)
        assert bild is not None and bild.size == (18, 18)
        # Alpha-Kanal muss irgendwo sichtbar sein (getbbox = None
        # wäre ein komplett leeres Symbol)
        assert bild.getchannel("A").getbbox() is not None, \
            f"Symbol {name!r} ist leer"


def test_symbole_werden_gecacht():
    a = symbole.symbol_bild("pfeil", "#123456", 20)
    b = symbole.symbol_bild("pfeil", "#123456", 20)
    assert a is b


# ======================================================================
# Zeilen-Paar-Erkennung: Eingabetext AUF der Linie
# ======================================================================
def test_felder_stehen_auf_der_eingabelinie(svc, tmp_path):
    """Bild-2-Beweis: „hinter dem Text eine Linie – der eingegebene
    Text muss dort auch hin“. Die vier Schüler-Felder müssen mit der
    Grundlinie AUF der leeren Linie (300 pt) sitzen, nicht auf der
    Beschriftung."""
    pdf = samples.make_anmelde_formular_pdf(str(tmp_path / "a.pdf"))
    m, s, e = svc.open_document(pdf)
    svc.analyze(m, s, e)
    nach_label = {f.label: f for f in m.fields}
    for name in ("Name", "Vorname", "Geburtsort", "Geburtsdatum"):
        f = nach_label.get(name)
        assert f is not None, name
        grundlinie = f.rect.y + f.rect.height - 1.5
        assert abs(grundlinie - 300.0) < 1.0, \
            f"{name}: Grundlinie {grundlinie:.1f} statt 300 (Linie)"
    # Felder untereinander bündig (gleiche Zeile)
    ys = {round(nach_label[n].rect.y, 1)
          for n in ("Name", "Vorname", "Geburtsort", "Geburtsdatum")}
    assert len(ys) == 1


def test_keine_felder_mehr_auf_der_beschriftung(svc, tmp_path):
    pdf = samples.make_anmelde_formular_pdf(str(tmp_path / "a.pdf"))
    m, s, e = svc.open_document(pdf)
    svc.analyze(m, s, e)
    for f in m.fields:
        if f.label in ("Name", "Vorname", "Geburtsort", "Geburtsdatum"):
            assert f.rect.y > 280, \
                f"{f.label} sitzt wieder auf der Beschriftung"


# ======================================================================
# GUI: Theme + Feld verschieben
# ======================================================================
def _app_neu():
    from documentai.gui.app import DocumentAIApp
    for _ in range(3):
        try:
            return DocumentAIApp()
        except Exception:
            gc.collect()
            time.sleep(0.4)
    return DocumentAIApp()


def _bereit(view):
    m = view.model
    return bool(m and m.pages and m.audit
                and m.audit[-1].action == "Analyse abgeschlossen"
                and view.page_list.get(0, "end"))


@pytest.fixture()
def gui_app(svc, tmp_path, monkeypatch):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "showerror",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError(f"showerror: {a}")))
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    pdf = samples.make_anmelde_formular_pdf(str(tmp_path / "z.pdf"))
    app = _app_neu()
    app.add_document(pdf)
    view = app._current()
    frist = time.time() + 40
    while time.time() < frist:
        app.root.update()
        if _bereit(view):
            break
        time.sleep(0.05)
    yield app, view
    app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display")
def test_hell_dunkel_umschaltung(gui_app):
    app, view = gui_app
    app.thema_modus = "hell"
    app._thema_anwenden("dunkel")
    app.root.update()
    assert app.thema_modus == "dunkel"
    assert str(view.canvas.cget("background")) == "#14161a"
    app._thema_anwenden("hell")
    app.root.update()
    assert app.thema_modus == "hell"
    assert str(view.canvas.cget("background")) != "#14161a"


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display")
def test_feld_verschieben(gui_app):
    app, view = gui_app
    scale = (150 * view.zoom) / 72.0
    c = view.canvas
    name_f = next(f for f in view.model.fields if f.label == "Name")
    alt_x, alt_y = name_f.rect.x, name_f.rect.y
    app._current_feld_verschieben()
    app.root.update()
    assert view.mode == "feld_bewegen"
    cx = (name_f.rect.x + 20) * scale
    cy = (name_f.rect.y + 8) * scale
    c.event_generate("<Button-1>", x=int(cx), y=int(cy))
    app.root.update()
    c.event_generate("<B1-Motion>", x=int(cx + 80), y=int(cy + 40))
    app.root.update()
    c.event_generate("<ButtonRelease-1>", x=int(cx + 80), y=int(cy + 40))
    app.root.update()
    assert name_f.rect.x > alt_x + 30
    assert name_f.rect.y > alt_y + 15
    assert view.model.edited
    assert any("verschoben" in (a.action or "")
               for a in view.model.audit)
    assert view.mode == "feld_bewegen"      # Modus bleibt aktiv
    view.set_mode("normal")
    assert view.mode == "normal"


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display")
def test_panel_knoepfe_mit_symbolen(gui_app):
    app, view = gui_app
    view._panel_zeigen("werkzeuge")
    app.root.update()
    # Mindestens 30 Werkzeug-Knöpfe tragen ein Symbol-Bild
    assert len(app._thema_bilder) >= 30
    from documentai.gui.app import DocumentView
    for text, symbol in DocumentView._SYMBOL_MAP.items():
        assert symbol in symbole.verfuegbare_symbole(), \
            f"Symbol {symbol!r} für {text!r} fehlt"


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display")
def test_theme_überlebt_neue_view(gui_app, tmp_path):
    app, view = gui_app
    app._thema_anwenden("dunkel")
    app.root.update()
    pdf2 = samples.make_zeilen_formular_pdf(str(tmp_path / "z2.pdf"))
    app.add_document(pdf2)
    view2 = app._current()
    frist = time.time() + 30
    while time.time() < frist:
        app.root.update()
        if _bereit(view2):
            break
        time.sleep(0.05)
    assert str(view2.canvas.cget("background")) == "#14161a"
