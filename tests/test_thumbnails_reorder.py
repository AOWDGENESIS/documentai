# -*- coding: utf-8 -*-
"""Miniaturansichten & Seitenanordnung (Acrobat-Seitenleiste):
exakte Rahmen im Seitenverhältnis, Mausrad-Blättern, Drag & Drop."""
import os
import sys
import time

import pytest

from conftest import app_schliessen

tkinter = pytest.importorskip("tkinter")

HAVE_DISPLAY = (os.environ.get("DISPLAY") or
                sys.platform.startswith("win"))


def _app_neu():
    import gc
    from documentai.gui.app import DocumentAIApp
    for _ in range(3):
        try:
            return DocumentAIApp()
        except Exception:
            gc.collect()
            time.sleep(0.4)
    return DocumentAIApp()


def _analyse_fertig(view) -> bool:
    """Analyse REALLY fertig: Audit-Ende UND die Seitenliste ist vom
    _after_analyze-Callback gefüllt worden (nicht nur der Thread fertig)."""
    m = view.model
    return bool(m and m.pages and m.audit
                and m.audit[-1].action == "Analyse abgeschlossen"
                and view.page_list.get(0, "end"))


def _warte_auf(app, bedingung, frist_s=30):
    frist = time.time() + frist_s
    while time.time() < frist:
        app.root.update()
        if bedingung():
            return True
        time.sleep(0.05)
    return False


def _dreiseiten_pdf(pfad):
    """Drei Seiten mit eindeutigem Text A / B / C (Hoch+Querformat)."""
    import pymupdf
    doc = pymupdf.open()
    for text, breite, hoehe in (("Seite Alpha", 595, 842),
                                ("Seite Bravo", 842, 595),
                                ("Seite Charlie", 595, 842)):
        seite = doc.new_page(width=breite, height=hoehe)
        seite.insert_text((50, 60), text, fontsize=18, fontname="hebo")
    doc.save(pfad, garbage=3, deflate=True)
    doc.close()
    return pfad


class _RadEvent:
    """Tk-Mausrad-Ereignis (Windows: delta, Linux: num 4/5)."""
    def __init__(self, delta=0, num=0, x=100, y=100):
        self.delta = delta
        self.num = num
        self.x = x
        self.y = y


# ======================================================================
# Rahmen folgen dem echten Seitenverhältnis
# ======================================================================
@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_thumbnail_rahmen_folgen_seitenverhaeltnis(svc, tmp_path):
    """Hoch- und Querformat bekommen verschiedene Rahmen – kein fester
    90×120-Kasten mehr (Nutzerfund: „nicht sauber an die Seite
    angepasst“)."""
    pfad = _dreiseiten_pdf(str(tmp_path / "drei.pdf"))
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _warte_auf(app, lambda: view.model is not None
                          and len(view.model.pages) == 3
                          and _analyse_fertig(view))
        app.root.update()
        view._panel_zeigen("seiten")
        view._thumbnails_zeichnen()
        app.root.update_idletasks()
        rahmen = []
        for item in view.thumbs.find_all():
            if view.thumbs.type(item) == "rectangle":
                x0, y0, x1, y1 = view.thumbs.coords(item)
                rahmen.append((x1 - x0, y1 - y0))
        assert len(rahmen) >= 3, f"3 Seiten-Rahmen erwartet: {rahmen}"
        hoch = rahmen[0]                       # Seite 1: 595×842
        quer = rahmen[1]                       # Seite 2: 842×595
        assert hoch[1] > hoch[0] * 1.2, "Hochformat-Rahmer muss hoch sein"
        assert quer[0] > quer[1] * 1.2, "Querformat-Rahmen muss breit sein"
        # Rahmen schmiegt sich ±5 px an das gerenderte Bild
        import io
        from PIL import Image
        png = view.engine.render_page(view.session, 0, 22)
        bild = Image.open(io.BytesIO(png)).size
        assert abs(hoch[0] - (bild[0] + 6)) <= 5
        assert abs(hoch[1] - (bild[1] + 6)) <= 5
    finally:
        app_schliessen(app)


# ======================================================================
# Mausrad: Windows (<MouseWheel>) und Linux (Button-4/5)
# ======================================================================
@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_rad_blattert_weiter_und_zurueck(svc, tmp_path):
    pfad = _dreiseiten_pdf(str(tmp_path / "drei.pdf"))
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _warte_auf(app, lambda: view.model is not None
                          and len(view.model.pages) == 3
                          and _analyse_fertig(view))
        view._seite_waehlen(0)
        app.root.update()
        # Acrobat-Semantik: passt die Seite nicht ins Fenster, scrollt
        # das Rad INNERHALB der Seite …
        y0, y1 = view.canvas.yview()
        if y1 < 0.999:
            view._on_wheel(_RadEvent(delta=-120))
            assert view.current_page == 0, "erst scrollen, nicht blättern"
            assert view.canvas.yview()[0] > y0
        # … am unteren Ende angekommen, blättert das Rad weiter
        view.canvas.yview_moveto(1.0)
        view._on_wheel(_RadEvent(delta=-120))
        assert view.current_page == 1, "am Ende muss weiterblättern"
        # letzte Seite: am unteren Ende KEIN Rausblättern
        view._seite_waehlen(2)
        view.canvas.yview_moveto(1.0)
        view._on_wheel(_RadEvent(delta=-120))
        assert view.current_page == 2, "am Dokumentende nicht rausblättern"
        # Rad hoch: zurückblättern (oben angekommen)
        view.canvas.yview_moveto(0.0)
        view._on_wheel(_RadEvent(delta=120))
        assert view.current_page == 1, "Rad hoch muss zurückblättern"
        # Linux-Rad: Button-4 = hoch, Button-5 = runter (am Ende)
        view._on_wheel(_RadEvent(num=4))
        assert view.current_page == 0
        view.canvas.yview_moveto(1.0)
        view._on_wheel(_RadEvent(num=5))
        assert view.current_page == 1
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_rad_binding_ist_registriert(svc, tmp_path):
    """Das Canvas muss <MouseWheel> wirklich gebunden haben (Windows
    liefert sonst GAR KEIN Ereignis – Nutzerfund 09.09.2026)."""
    pfad = _dreiseiten_pdf(str(tmp_path / "drei.pdf"))
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _warte_auf(app, lambda: view.model is not None
                          and _analyse_fertig(view))
        app.root.update()
        for binding in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            assert view.canvas.bind(binding), \
                f"Binding {binding} fehlt am Seiten-Canvas"
    finally:
        app_schliessen(app)


# ======================================================================
# Drag & Drop: Seite verschieben hält alles synchron
# ======================================================================
@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_seite_verschieben_haelt_modell_und_dokument_synchron(svc,
                                                               tmp_path):
    pfad = _dreiseiten_pdf(str(tmp_path / "drei.pdf"))
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _warte_auf(app, lambda: view.model is not None
                          and len(view.model.pages) == 3
                          and view.model.audit
                          and view.model.audit[-1].action
                          == "Analyse abgeschlossen")
        # Feld + Schwärzung an Seite 0 (Alpha) heften
        from documentai.core.models import FieldModel, Rect4
        view.model.fields.append(FieldModel(
            id="feld_alpha", name="feld_alpha", label="Alpha-Feld",
            field_type="text", page=0, rect=Rect4(60, 100, 120, 14)))
        view.redact_rects.append((0, (60, 200, 200, 214)))
        view._seite_waehlen(0)
        app.root.update()
        view._seiten_vertauschen(0, 2)        # Alpha an Position 3
        app.root.update()
        # Dokument-Reihenfolge: Bravo, Charlie, Alpha
        text0 = view.session.doc.load_page(0).get_text()
        text2 = view.session.doc.load_page(2).get_text()
        assert "Bravo" in text0, "Seite 1 muss jetzt Bravo sein"
        assert "Alpha" in text2, "Alpha muss an Position 3 liegen"
        # Modell synchron + durchnummeriert
        assert [p.number for p in view.model.pages] == [0, 1, 2]
        # Feld & Schwärzung mitgewandert (0 → 2)
        assert view.model.fields[0].page == 2
        assert view.redact_rects == [(2, (60, 200, 200, 214))]
        # Seitenliste + Audit + Speicherflag
        assert view.page_list.get(0, "end") == \
            ("Seite 1", "Seite 2", "Seite 3")
        assert view.model.audit[-1].action == "Seite neu angeordnet"
        assert view.model.edited is True
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_seite_verschieben_ungueltig_bleibt_harmlos(svc, tmp_path):
    pfad = _dreiseiten_pdf(str(tmp_path / "drei.pdf"))
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _warte_auf(app, lambda: view.model is not None
                          and len(view.model.pages) == 3
                          and _analyse_fertig(view))
        app.root.update()
        view._seiten_vertauschen(0, 0)        # no-op
        view._seiten_vertauschen(-1, 2)       # außerhalb
        view._seiten_vertauschen(0, 99)       # außerhalb
        assert [p.number for p in view.model.pages] == [0, 1, 2]
    finally:
        app_schliessen(app)


# ======================================================================
# Miniatur-Klick vs. Zug
# ======================================================================
@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_thumb_klick_ohne_zug_waehlt_seite(svc, tmp_path):
    pfad = _dreiseiten_pdf(str(tmp_path / "drei.pdf"))
    app = _app_neu()
    try:
        app.add_document(pfad)
        view = app._current()
        assert _warte_auf(app, lambda: view.model is not None
                          and len(view.model.pages) == 3
                          and _analyse_fertig(view))
        view._panel_zeigen("seiten")
        view._thumbnails_zeichnen()
        app.root.update()
        # Press+Release ohne Bewegung = Klick → Seite 2 wählen
        view._thumb_drag_start(_RadEvent(y=200), 1)
        view._thumb_drag_end(_RadEvent(y=205))    # 5 px < 16 px Schwelle
        assert view.current_page == 1
        # echter Zug (> 16 px) auf Slot 0 → Seite verschieben
        view._thumb_drag_start(_RadEvent(y=200), 1)
        slots = view._thumb_slots
        view._thumb_drag_end(_RadEvent(y=slots[0] - 200
                                       if slots else -100))
        app.root.update()
        assert view.model.audit[-1].action == "Seite neu angeordnet"
    finally:
        app_schliessen(app)


# ======================================================================
# Tabs in der Kopfleiste per Drag neu anordnen
# ======================================================================
@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_tab_drag_ordnet_dokumente_neu(svc, assets, tmp_path,
                                       monkeypatch):
    import shutil
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: None)
    pfad_a = str(tmp_path / "a.pdf")
    pfad_b = str(tmp_path / "b.pdf")
    shutil.copy(assets.visual, pfad_a)
    shutil.copy(assets.acro, pfad_b)
    app = _app_neu()
    try:
        app.add_document(pfad_a)
        app.add_document(pfad_b)
        assert _warte_auf(app, lambda: len(app.views) == 2)
        app.root.update()
        erste, zweite = app.views[0], app.views[1]
        class _TabEvent:
            def __init__(self, x_root):
                self.x_root = x_root
        # Kurzer Klick (< 60 px) darf NICHT umordnen
        app._tab_drag = {"view": erste, "x0": 500}
        app._tab_drag_ende(_TabEvent(530), erste)
        assert app.views[0] is erste
        # Zug nach rechts (80 px) tauscht eine Position
        app._tab_drag = {"view": erste, "x0": 500}
        app._tab_drag_ende(_TabEvent(580), erste)
        assert app.views[0] is zweite and app.views[1] is erste
    finally:
        app_schliessen(app)


# ======================================================================
# Feder-Icon: Fenster + Kopfleiste
# ======================================================================
@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_fenster_und_kopfleiste_zeigen_feder(svc):
    from PIL import Image
    app = _app_neu()
    try:
        app.root.update()
        # Fenster-Icon (iconphoto) und Kopfleisten-Logo sind gesetzt
        assert app._icon_bild is not None, "iconphoto braucht ein Bild"
        assert app._logo_bild is not None, "Kopfleisten-Logo: Feder"
        assert app._icon_bild.width() > 0
        assert app._logo_bild.width() > 0
        # Die Bilddateien liegen wirklich im Programm-Verzeichnis
        basis = os.path.join(os.path.dirname(sys.modules[
            "documentai.gui.app"].__file__), "..", "bilder")
        for datei in ("feder_256.png", "feder_64.png", "feder.ico"):
            pfad = os.path.join(basis, datei)
            assert os.path.isfile(pfad), datei
        # Azurblau + transparenter Hintergrund (Nutzerwunsch 09.09.2026)
        img = Image.open(os.path.join(basis, "feder_256.png"))
        assert img.mode == "RGBA"
        ecke = img.getpixel((0, 0))
        assert ecke[3] == 0, f"Ecke muss transparent sein: {ecke}"
        roh = img.tobytes()                 # getdata() ist deprecated
        sichtbar = [roh[i:i + 3] for i in range(0, len(roh), 4)
                    if roh[i + 3] == 255]
        assert sichtbar, "Feder muss sichtbare Pixel haben"
        rgb = sichtbar[len(sichtbar) // 2]
        assert rgb[2] > 200 and rgb[1] < 160 and rgb[0] < 60, \
            f"Feder muss azurblau sein, nicht {rgb}"
    finally:
        app_schliessen(app)
