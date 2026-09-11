# -*- coding: utf-8 -*-
"""Acrobat-Werkzeugkatalog (Screenshots 09.09.2026): Unterstreichen,
Zeichenformen (Linie/Pfeil/Kreis/Rechteck), Füllzeichen (Kreuz/
Häkchen/Punkt/Umrunden/Durchstreichen), Bild, Verknüpfung, Bates-
Nummerierung, Messen, Schwenken – alles lokal, ohne Abo-Elemente."""
import gc
import os
import sys
import time

import pymupdf
import pytest

from conftest import app_schliessen
from documentai import samples
from documentai.engines import annotate

tkinter = pytest.importorskip("tkinter")

HAVE_DISPLAY = (os.environ.get("DISPLAY") or
                sys.platform.startswith("win"))


# ======================================================================
# Backend: Formen, Füllzeichen, Verknüpfung, Bates
# ======================================================================
def test_formen_als_annotationen(svc, tmp_path):
    m, s, e = svc.open_document(samples.make_zeilen_formular_pdf(
        str(tmp_path / "w.pdf")))
    for art in ("linie", "pfeil", "kreis", "rechteck"):
        annotate.form_zeichnen(s, 0, art, (100, 700), (200, 750))
    seite = s.doc[0]          # Proxy am Leben halten (mupdf-GC)
    annots = list(seite.annots())
    assert len(annots) == 4, f"4 Form-Annotationen erwartet: {len(annots)}"
    arten = {a.type[1].lower() for a in annots}
    assert "line" in arten and "circle" in arten and "square" in arten


def test_pfeil_hat_spitze(svc, tmp_path):
    """Der Pfeil braucht eine echte Spitze (line-end ClosedArrow=4)."""
    m, s, e = svc.open_document(samples.make_zeilen_formular_pdf(
        str(tmp_path / "w.pdf")))
    annotate.form_zeichnen(s, 0, "pfeil", (100, 700), (200, 700))
    seite = s.doc[0]          # Proxy am Leben halten (mupdf-GC)
    a = next(iter(seite.annots()))
    assert a.line_ends == (0, 4), a.line_ends


def test_fuell_zeichen_alle_fuenf(svc, tmp_path):
    m, s, e = svc.open_document(samples.make_zeilen_formular_pdf(
        str(tmp_path / "w.pdf")))
    for z in ("haekchen", "kreuz", "punkt", "umranden", "durchstreichen"):
        annotate.fuell_zeichen(s, 0, 120.0, 300.0, z)
    assert len(s.doc[0].get_drawings()) >= 5
    with pytest.raises(Exception):
        annotate.fuell_zeichen(s, 0, 10, 10, "gibtsnicht")


def test_link_wird_gespeichert(svc, tmp_path):
    m, s, e = svc.open_document(samples.make_zeilen_formular_pdf(
        str(tmp_path / "w.pdf")))
    annotate.link_hinzufuegen(s, 0, (50, 50, 200, 70), "example.com")
    ziel = str(tmp_path / "mit_link.pdf")
    s.doc.save(ziel)
    with pymupdf.open(ziel) as d:
        links = d[0].get_links()
    assert len(links) == 1
    assert links[0]["uri"] == "https://example.com"   # Schema ergänzt


def test_bates_nummerierung(svc, tmp_path):
    m, s, e = svc.open_document(samples.make_zeilen_formular_pdf(
        str(tmp_path / "w.pdf")))
    n = annotate.bates_nummerierung(s, praefix="AKTE-", start=7,
                                    suffix="-X")
    assert n == 2
    assert "AKTE-000007-X" in s.doc[0].get_text()
    assert "AKTE-000008-X" in s.doc[1].get_text()


# ======================================================================
# GUI: komplette Werkzeug-Journey (echte Klick-Ereignisse)
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
def werk_app(svc, assets, monkeypatch):
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "showerror",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError(f"showerror: {a}")))
    app = _app_neu()
    app.add_document(assets.zeilen)
    view = app._current()
    frist = time.time() + 40
    while time.time() < frist:
        app.root.update()
        if _bereit(view):
            break
        time.sleep(0.05)
    yield app, view
    app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_unterstreichen_werkzeug(werk_app):
    app, view = werk_app
    app._current_unterstreichen()
    app.root.update()
    assert view.mode == "underline"
    scale = (150 * view.zoom) / 72.0
    c = view.canvas
    n0 = len(list(view.session.doc[0].annots()))
    c.event_generate("<Button-1>", x=int(55 * scale), y=int(143 * scale))
    app.root.update()
    c.event_generate("<ButtonRelease-1>", x=int(200 * scale),
                     y=int(150 * scale))
    app.root.update()
    assert len(list(view.session.doc[0].annots())) > n0
    assert view.model.edited


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_formen_und_zeichen(werk_app):
    app, view = werk_app
    scale = (150 * view.zoom) / 72.0
    c = view.canvas

    def zug(x0, y0, x1, y1):
        c.event_generate("<Button-1>", x=int(x0), y=int(y0))
        app.root.update()
        c.event_generate("<B1-Motion>", x=int(x1), y=int(y1))
        app.root.update()
        c.event_generate("<ButtonRelease-1>", x=int(x1), y=int(y1))
        app.root.update()

    n0 = len(list(view.session.doc[0].annots()))
    for art in ("linie", "pfeil", "kreis", "rechteck"):
        view.set_form(art)
        app.root.update()
        assert view.mode == "form"
        zug(100 * scale, 600 * scale, 260 * scale, 640 * scale)
    assert len(list(view.session.doc[0].annots())) == n0 + 4

    d0 = len(view.session.doc[0].get_drawings())
    for z in ("haekchen", "kreuz", "punkt", "umranden", "durchstreichen"):
        view.set_zeichen(z)
        app.root.update()
        c.event_generate("<Button-1>", x=int(300 * scale),
                         y=int(500 * scale))
        app.root.update()
        c.event_generate("<ButtonRelease-1>", x=int(300 * scale),
                         y=int(500 * scale))
        app.root.update()
    assert len(view.session.doc[0].get_drawings()) >= d0 + 5


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_bild_link_messen_schwenken(werk_app, monkeypatch, tmp_path):
    import io
    from PIL import Image
    from documentai.gui import app as appmod
    app, view = werk_app
    scale = (150 * view.zoom) / 72.0
    c = view.canvas

    bild = str(tmp_path / "b.png")
    Image.new("RGB", (40, 30), (200, 30, 30)).save(bild)
    monkeypatch.setattr(appmod.filedialog, "askopenfilename",
                        lambda **k: bild)
    monkeypatch.setattr(appmod.simpledialog, "askstring",
                        lambda t, f, **k: "example.org")

    def zug(x0, y0, x1, y1):
        c.event_generate("<Button-1>", x=int(x0), y=int(y0))
        app.root.update()
        c.event_generate("<B1-Motion>", x=int(x1), y=int(y1))
        app.root.update()
        c.event_generate("<ButtonRelease-1>", x=int(x1), y=int(y1))
        app.root.update()

    # Bild
    app._current_bild()
    zug(400 * scale, 400 * scale, 470 * scale, 440 * scale)
    assert view.model.edited
    # Verknüpfung
    app._current_link()
    zug(50 * scale, 50 * scale, 150 * scale, 62 * scale)
    bio = io.BytesIO()
    view.session.doc.save(bio)
    bio.seek(0)
    with pymupdf.open(stream=bio.read(), filetype="pdf") as d:
        assert len(d[0].get_links()) == 1
    # Messen (Statusmeldung, kein Crash, Messlinie wieder weg)
    app._current_messen()
    zug(100 * scale, 200 * scale, 250 * scale, 200 * scale)
    assert not c.find_withtag("mess_linie")
    # Schwenken
    app._current_schwenken()
    zug(300, 300, 360, 340)
    assert view.mode == "schwenken"
    # Auswählen = zurück zum Normalmodus
    app._current_auswaehlen()
    assert view.mode == "normal"


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_bates_dialog_werkzeug(werk_app, monkeypatch):
    from documentai.gui import app as appmod
    app, view = werk_app
    monkeypatch.setattr(appmod.simpledialog, "askstring",
                        lambda t, f, **k: "AKTE-")
    monkeypatch.setattr(appmod.simpledialog, "askinteger",
                        lambda t, f, **k: 7)
    app._current_bates()
    app.root.update()
    assert "AKTE-000007" in view.session.doc[0].get_text()
    assert "AKTE-000008" in view.session.doc[1].get_text()
    assert view.model.edited


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_werkzeuge_panel_acrobat_katalog(werk_app):
    """Alle Elemente aus den Acrobat-Screenshots sind erreichbar –
    ohne Abo-/Cloud-Knöpfe."""
    app, view = werk_app
    view._panel_zeigen("werkzeuge")
    app.root.update()
    texte = {}
    for k in app.root.winfo_children():
        def sammler(w):
            for kind in w.winfo_children():
                sammler(kind)
            try:
                if w.cget("text"):
                    texte[w.cget("text")] = w
            except Exception:
                pass
        sammler(k)
    for name in ("Auswählen", "Schwenken (Hand)", "Markieren",
                 "Unterstreichen", "Durchstreichen", "Haftnotiz",
                 "Freihand zeichnen", "Linie", "Pfeil", "Kreis",
                 "Rechteck", "Objekte messen", "Kreuz setzen",
                 "Häkchen setzen", "Punkt setzen", "Umrunden",
                 "Text einfügen", "Bild einfügen…",
                 "Verknüpfung hinzufügen…", "Bates-Nummerierung…",
                 "Wasserzeichen…", "Kopf-/Fußzeile…", "Schwärzen",
                 "Geschützt speichern", "Seite löschen", "Zusammenführen…",
                 "Stempel", "Textfeld einfügen",
                 "Felder automatisch erkennen"):
        assert name in texte, f"Werkzeug {name!r} fehlt im Panel"
    # Abo-/Cloud-Elemente bewusst NICHT vorhanden
    for name in ("KI-Assistent", "Kostenlos testen", "Anmelden",
                 "Sparen"):
        assert name not in texte, f"{name!r} soll nicht vorkommen"
