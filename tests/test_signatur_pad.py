# -*- coding: utf-8 -*-
"""Unterschriften-Pad: Stift/Maus-Zeichnung, Wiederverwendung, Einfügen."""
import io
import os
import sys
import time

import pymupdf
import pytest

from conftest import app_schliessen

tkinter = pytest.importorskip("tkinter")

HAVE_DISPLAY = (os.environ.get("DISPLAY") or
                sys.platform.startswith("win"))

from documentai.services import unterschriften
from documentai.services.tools import tessdata_verzeichnis

HAT_TESSDATA = bool(tessdata_verzeichnis())


# ======================================================================
# Pad-Logik (ohne echte Maus: Striche direkt füttern)
# ======================================================================
def _app_neu():
    """DocumentAIApp mit Wiederholung (Wine-Tcl-Churn, nur Labor)."""
    import gc
    from documentai.gui.app import DocumentAIApp
    for _ in range(3):
        try:
            return DocumentAIApp()
        except Exception:
            gc.collect()
            time.sleep(0.4)
    return DocumentAIApp()


def _pad(root):
    from documentai.gui.signatur_pad import SignaturPad
    pad = SignaturPad(root)
    pad.update_idletasks()
    return pad


def _tk_root():
    """Tk-Wurzel mit Wiederholung (Wine-Tcl-Churn, nur Labor)."""
    import gc
    for _ in range(3):
        try:
            root = tkinter.Tk()
            root.withdraw()
            return root
        except Exception:
            gc.collect()
            time.sleep(0.4)
    return tkinter.Tk()


def _strich(pad, punkte):
    """Füttert einen Strich wie die Maus/der Stift es täte."""
    import math
    pad._down(type("E", (), {"x": punkte[0][0], "y": punkte[0][1]})())
    t0 = time.time()
    for i, (x, y) in enumerate(punkte[1:]):
        pad._aktuell.append((float(x), float(y),
                             t0 + i * 0.05))
    pad._up(None)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_pad_export_png_mit_transparenz():
    root = _tk_root()
    pad = None
    try:
        pad = _pad(root)
        assert pad.ist_leer()
        assert pad.png_bytes() is None          # leer -> nichts
        _strich(pad, [(60, 120), (120, 60), (200, 130), (300, 70)])
        _strich(pad, [(330, 90), (380, 85)])    # zweiter Strich (Punkt)
        assert not pad.ist_leer()
        png = pad.png_bytes()
        assert png and png[:8] == b"\x89PNG\r\n\x1a\n"
        from PIL import Image
        img = Image.open(io.BytesIO(png))
        assert img.mode == "RGBA"
        alpha = img.getchannel("A")
        assert alpha.getextrema()[1] == 255     # sichtbare Tinte
        assert alpha.getextrema()[0] == 0       # transparenter Hintergrund
        # Tinte ist dunkel (Stift)
        rgb = img.convert("RGB")
        roh = rgb.tobytes()
        dunkel = sum(1 for i in range(0, len(roh), 3)
                     if roh[i] + roh[i + 1] + roh[i + 2] < 240)
        assert dunkel > 30
        # Strich zurück -> immer noch gültiges Bild
        pad.strich_zurueck()
        assert len(pad.streiche) == 1
        pad.alles_loeschen()
        assert pad.ist_leer()
    finally:
        import gc
        if pad is not None:
            try:
                pad.destroy()
            except Exception:
                pass
        pad = None
        gc.collect()                 # StringVar lösen, SOLANGE Tcl lebt
        root.destroy()


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_pad_breite_angepasst_an_geschwindigkeit():
    """Schnell = fein, langsam = kräftig (Stift-Druck-Emulation)."""
    from documentai.gui.signatur_pad import SignaturPad
    schnell = SignaturPad._breite((0, 0, 0.0), (80, 0, 0.05))
    langsam = SignaturPad._breite((0, 0, 0.0), (4, 0, 0.05))
    assert schnell < langsam
    assert 2.2 <= schnell <= 5.6 and 2.2 <= langsam <= 5.6


# ======================================================================
# Speicher: mehrere Unterschriften, wiederverwenden
# ======================================================================
def test_unterschriften_speicher_mehrfach(tmp_path, monkeypatch):
    monkeypatch.setattr(unterschriften, "config_dir",
                        lambda: str(tmp_path))
    from PIL import Image
    def _png(hoehe):
        img = Image.new("RGBA", (100, hoehe), (0, 0, 0, 0))
        puffer = io.BytesIO()
        img.save(puffer, "PNG")
        return puffer.getvalue()

    a = unterschriften.speichern("Unterschrift", _png(40))
    b = unterschriften.speichern("Unterschrift", _png(50))  # gleicher Name
    c = unterschriften.speichern("Initialen", _png(30))
    assert a != b != c                           # nichts überschrieben
    namen = [e["name"] for e in unterschriften.liste()]
    assert namen == ["Initialen", "Unterschrift", "Unterschrift (2)"]
    # Dateien existieren und sind PNGs
    for e in unterschriften.liste():
        with open(e["pfad"], "rb") as fh:
            assert fh.read(8) == b"\x89PNG\r\n\x1a\n"
    # Löschen: exakt einer weg
    assert unterschriften.loeschen("Unterschrift (2)") is True
    assert [e["name"] for e in unterschriften.liste()] == \
        ["Initialen", "Unterschrift"]
    assert unterschriften.loeschen("Gibtsnicht") is False


# ======================================================================
# Einfügen in das Dokument
# ======================================================================
@pytest.mark.skipif(not HAT_TESSDATA, reason="kein tessdata-Ordner")
def test_gespeicherte_unterschrift_einfuegen(svc, tmp_path, monkeypatch):
    """Nutzerreise: gespeicherte Unterschrift wählen -> Rahmen auf der
    Seite ziehen -> neue Version enthält das Bild."""
    monkeypatch.setattr(unterschriften, "config_dir",
                        lambda: str(tmp_path))
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (200, 80), (0, 0, 0, 0))
    ImageDraw.Draw(img).line([(10, 40), (190, 40)], fill=(13, 27, 62, 255),
                             width=6)
    puffer = io.BytesIO()
    img.save(puffer, "PNG")
    pfad_bild = unterschriften.speichern("Test-Unterschrift",
                                         puffer.getvalue())

    quelle = str(tmp_path / "vertrag.pdf")
    doc = pymupdf.open()
    seite = doc.new_page()
    seite.insert_text((50, 120), "Unterschrift:", fontsize=11)
    doc.save(quelle)
    doc.close()

    model, session, engine = svc.open_document(quelle)
    svc.analyze(model, session, engine)
    # simuliert: Modus sign_img mit vorausgewählter Unterschrift
    from documentai.engines import annotate
    annotate.bild_einfuegen(session, 0,
                            pymupdf.Rect(140, 100, 340, 140), pfad_bild)
    model.edited = True
    ziel = engine.save_version(session, model, "Signiert")["pfad"]
    with pymupdf.open(ziel) as doc:
        bilder = doc.load_page(0).get_images(full=True)
        assert bilder, "Unterschrift-Bild muss im PDF stehen"
        # Bild ist sichtbar: Region unter der Unterschriftenzeile dunkler
        pix = doc.load_page(0).get_pixmap(dpi=150, colorspace=pymupdf.csGRAY,
                                          clip=pymupdf.Rect(150, 105, 330,
                                                            135))
        assert min(pix.samples) < 120


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_signaturdialog_oeffnet_pad_und_uebernimmt(svc, assets, tmp_path,
                                                   monkeypatch):
    """Dialogkette: Signieren -> Pad -> Übernehmen -> Einfügemodus."""
    import shutil
    pfad = str(tmp_path / "formular.pdf")
    shutil.copy(assets.visual, pfad)
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        frist = time.time() + 30
        while time.time() < frist:
            app.root.update()
            if view.model and view.model.pages:
                break
            time.sleep(0.05)
        # Pad öffnen (so wie der Dialog es täte) und Strich füttern
        pad = _pad(app.root)
        _strich(pad, [(40, 100), (120, 60), (240, 110), (400, 70)])
        png = pad.png_bytes()
        assert png
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png",
                                         delete=False) as tmp:
            tmp.write(png)
            voraus = tmp.name
        view._signatur_bild = voraus
        view.set_mode("sign_img")
        assert view.mode == "sign_img"
        # Einfügen über die Release-Logik der Ansicht
        view._start = (10, 10)
        class E:
            pass
        e = E(); e.x = 200; e.y = 80
        view._on_canvas_release(e)
        assert view.model.edited
        assert getattr(view, "_signatur_bild", None) is None  # verbraucht
        pad.destroy()
    finally:
        app_schliessen(app)
