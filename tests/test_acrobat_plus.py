# -*- coding: utf-8 -*-
"""Acrobat-Ausbau Stufe 2 (04.09.2026): Extras, Inline-Ausfüllen,
Doppelbenennungs-Schutz, Signieren – alles lokal/offen."""
from __future__ import annotations

import os
import sys
from conftest import app_schliessen

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf

from documentai import samples
from documentai.engines import annotate


@pytest.fixture()
def geoeffnet(svc, tmp_path):
    pfad = str(tmp_path / "visuell.pdf")
    samples.make_visual_form_pdf(pfad)
    m, s, e = svc.open_document(pfad)
    svc.analyze(m, s, e)
    yield m, s, e


# ── Doppelbenennung (Nutzerfund) ───────────────────────────────────
def test_keine_doppelten_felder_einer_zeile():
    """Unterstrich-Regel UND Scan-Lücken-Regel dürfen dieselbe Zeile
    nicht doppelt melden („Vorname“ erschien 2× in der Zuordnung)."""
    from documentai.core.models import PageModel, Rect4, Word
    from documentai.engines.field_detector import VisualFieldDetector
    seite = PageModel(number=0, width=595, height=842)
    seite.ocr_applied = True                    # Lücken-Regel aktiv
    seite.words = [
        Word("Vorname", Rect4(50, 100, 60, 12), 0, 0, 95.0),
        Word("______", Rect4(115, 100, 180, 12), 0, 1, 95.0),  # Unterstrich
    ]
    felder = VisualFieldDetector().detect.__self__._detect_page(
        seite, None, [])
    dedupe = VisualFieldDetector._dedupe(felder)
    vornamen = [f for f in dedupe if f.canonical == "vorname"]
    assert len(vornamen) <= 1, f"Doppelbenennung: {vornamen}"


def test_zuordnung_ohne_doppelte_feld_ids(svc, tmp_path):
    """build_assignments darf dieselbe Feld-ID nie doppelt liefern."""
    pfad = str(tmp_path / "doppelt.pdf")
    samples.make_visual_form_pdf(pfad)
    m, s, e = svc.open_document(pfad)
    svc.analyze(m, s, e)
    prof = {"vorname": "Anna", "nachname": "Berg", "plz": "49170",
            "ort": "Hasbergen"}
    asg = svc.prepare_fill(m, prof)
    ids = [a["feld_id"] for a in asg]
    assert len(ids) == len(set(ids)), f"doppelte Feld-IDs: {ids}"


def test_versionierung_niemals_ueberschreiben(tmp_path):
    from documentai.services import versioning
    basis = tmp_path / "doc.pdf"
    d = pymupdf.open(); d.new_page(); d.save(str(basis))
    pfade = []
    for _ in range(3):
        pfad = versioning.next_version_path(str(basis))
        assert pfad not in pfade, "Versionierung liefert Doppelten"
        with open(pfad, "wb") as f:             # sauber schließen!
            f.write(b"%PDF-belegt")             # Name ist jetzt vergeben
        pfade.append(pfad)
    assert versioning.next_version_path(str(basis)) not in pfade


# ── Neue Werkzeuge ─────────────────────────────────────────────────
def test_wasserzeichen(geoeffnet):
    m, s, e = geoeffnet
    n = annotate.wasserzeichen(s, "VERTRAULICH", seiten=[0])
    assert n == 1
    e.save_version(s, m, "wm")
    text = pymupdf.open(s.saved_versions[-1])[0].get_text()
    assert "VERTRAULICH" in text


def test_kopf_fusszeile_und_bates(geoeffnet):
    m, s, e = geoeffnet
    annotate.kopf_fusszeile(s, kopf="Amt Musterstadt",
                            seitenzahl=True)
    annotate.kopf_fusszeile(s, bates="AKTE")     # zweite Runde ersetzt
    e.save_version(s, m, "kf")
    text = pymupdf.open(s.saved_versions[-1])[0].get_text()
    assert "AKTE-000001" in text


def test_stempel_und_text(geoeffnet):
    m, s, e = geoeffnet
    annotate.stempel(s, 0, (100, 100, 240, 140), "geprueft")
    annotate.stempel_text(s, 0, (100, 160, 260, 185), "PRÜFVERMERK")
    annotate.text_einfuegen(s, 0, (100, 200, 300, 220), "Nachtrag")
    e.save_version(s, m, "stempel")
    seite = pymupdf.open(s.saved_versions[-1])[0]
    ann = list(seite.annots() or [])
    assert len(ann) >= 2, f"Stempel-Annots fehlen: {ann}"
    assert "Nachtrag" in seite.get_text()


def test_seite_verschieben_und_zuschneiden(geoeffnet, tmp_path):
    m, s, e = geoeffnet
    d3 = tmp_path / "drei.pdf"
    doc = pymupdf.open()
    for marke in ("SeiteA", "SeiteB", "SeiteC"):
        pg = doc.new_page()
        pg.insert_text((50, 60), marke, fontsize=14)
    doc.save(str(d3)); doc.close()
    from documentai.services.analysis import AnalysisService
    m2, s2, e2 = AnalysisService().open_document(str(d3))
    annotate.seite_verschieben(s2, 2, 0)         # letzte ganz nach vorn
    assert "SeiteC" in s2.doc[0].get_text()
    assert "SeiteA" in s2.doc[1].get_text()
    annotate.zuschneiden(s2, 0, (5, 5, 5, 5))
    assert s2.doc[0].cropbox.width < 595
    from documentai.core.errors import DocumentAIError
    with pytest.raises(DocumentAIError):
        annotate.zuschneiden(s2, 0, (300, 300, 300, 300))


def test_suchen_und_schwaerzen(geoeffnet):
    m, s, e = geoeffnet
    n = annotate.suchen_und_schwaerzen(s, "Vorname")
    assert n >= 1
    e.save_version(s, m, "sw")
    text = pymupdf.open(s.saved_versions[-1])[0].get_text()
    assert "Vorname" not in text


def test_optimieren_und_abflachen(tmp_path):
    samples.make_acroform_pdf(str(tmp_path / "af.pdf"))
    from documentai.services.analysis import AnalysisService
    svc = AnalysisService()
    m, s, e = svc.open_document(str(tmp_path / "af.pdf"))
    svc.analyze(m, s, e)
    svc.apply_fill(m, s, e, svc.prepare_fill(
        m, {"vorname": "Anna", "nachname": "Berg"}))
    n = annotate.formular_abflachen(s, m)
    assert n >= 1
    widgets = sum(1 for p in s.doc for _ in (p.widgets() or []))
    assert widgets == 0
    erg = annotate.optimieren(s, str(tmp_path / "opt.pdf"))
    assert os.path.getsize(erg["pfad"]) > 100


def test_anhang_und_bilder(tmp_path):
    from documentai.services.analysis import AnalysisService
    basis = tmp_path / "anhang_basis.pdf"
    d = pymupdf.open(); d.new_page(); d.save(str(basis)); d.close()
    svc = AnalysisService()
    m, s, e = svc.open_document(str(basis))
    annotate.anhang_einbetten(s, str(basis), "Beilage")
    assert len(s.doc.embfile_names()) == 1
    png = str(tmp_path / "bild.png")
    pymupdf.open(str(basis))[0].get_pixmap(dpi=100).save(png)
    ziel = annotate.bilder_zu_pdf([png], str(tmp_path / "aus_bildern.pdf"))
    assert pymupdf.open(ziel).page_count == 1


def test_signieren_digital(tmp_path):
    pytest.importorskip("pyhanko")
    from documentai.services.analysis import AnalysisService
    from documentai.services import signing
    samples.make_normal_pdf(str(tmp_path / "sig.pdf"))
    svc = AnalysisService()
    m, s, e = svc.open_document(str(tmp_path / "sig.pdf"))
    ziel = signing.digital_signieren(s, str(tmp_path / "sig_out.pdf"),
                                     name="Testperson")
    info = signing.signatur_info(ziel)
    assert info["vorhanden"]
    assert info["status"] in ("intakt_selbst_signiert", "gueltig")
    chk = pymupdf.open(ziel)                     # PDF bleibt lesbar
    assert chk.page_count >= 1


# ── GUI: Inline-Ausfüllen + Extras überleben Klicks ───────────────
HAVE_DISPLAY = (os.environ.get("DISPLAY") or sys.platform.startswith("win"))
GUI = pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display")


def _pump(app, bedingung, sekunden=20):
    import time
    frist = time.time() + sekunden
    while time.time() < frist:
        app.root.update()
        if bedingung():
            return True
        time.sleep(0.05)
    return False


@GUI
def test_inline_direkt_ins_feld_schreiben(svc, assets, monkeypatch):
    """Nutzerwunsch: selbst in die Felder schreiben – Klick ins Feld
    öffnet EINGABEFELD direkt im PDF, Tippen + Enter übernimmt."""
    from documentai.gui.app import DocumentAIApp
    app = DocumentAIApp()
    try:
        app.add_document(assets.visual)
        # WICHTIG: auf das ENDE der Analyse warten (Audit-Ende + Felder
        # stehen erst im _after_analyze-Callback bereit) – nur auf
        # ``pages`` zu warten ist ein Race (Feldliste noch leer).
        def _fertig():
            v = app._current()
            m = v.model if v else None
            return bool(m and m.pages and m.audit
                        and m.audit[-1].action == "Analyse abgeschlossen"
                        and v.page_list.get(0, "end"))
        assert _pump(app, _fertig)
        view = app._current()
        feld = next(f for f in view.model.fields
                    if f.field_type not in ("checkbox",) and f.rect)
        scale = (150 * view.zoom) / 72.0
        cx = (feld.rect.x + feld.rect.width / 2) * scale
        cy = (feld.rect.y + feld.rect.height / 2) * scale
        class E:  # simulierter Mausklick aufs Feld
            x, y = cx, cy
        view._on_canvas_click(E())
        app.root.update()
        eintrag = getattr(view, "_inline_entry", None)
        assert eintrag, "Inline-Eingabefeld wurde nicht geöffnet"
        entry, f2, var = eintrag
        assert f2.id == feld.id
        var.set("Erika Mustermann")
        view._inline_commit()
        app.root.update()
        assert feld.value == "Erika Mustermann"
        assert view.undo_stack[-1]["neu"] == "Erika Mustermann"
    finally:
        app_schliessen(app)


@GUI
def test_extras_knoepfe_klickbar_ohne_dokument(monkeypatch):
    from tkinter import messagebox, simpledialog
    from tkinter import filedialog
    from documentai.gui.app import DocumentAIApp
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: "ok")
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: False)
    monkeypatch.setattr(simpledialog, "askstring", lambda *a, **k: None)
    monkeypatch.setattr(simpledialog, "askinteger", lambda *a, **k: None)
    monkeypatch.setattr(simpledialog, "askfloat", lambda *a, **k: None)
    monkeypatch.setattr(filedialog, "askopenfilenames", lambda **k: ())
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **k: "")
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **k: "")
    monkeypatch.setattr(filedialog, "askdirectory", lambda **k: "")
    import tkinter
    monkeypatch.setattr(tkinter.Misc, "wait_window", lambda s, w=None: None)
    monkeypatch.setattr(tkinter.Misc, "grab_set", lambda s: None)
    from documentai import samples as _samples
    import time as _time
    app = DocumentAIApp()
    try:
        _samples.make_visual_form_pdf("/tmp/x_extras_panel.pdf")
        app.add_document("/tmp/x_extras_panel.pdf")
        frist = _time.time() + 25
        while _time.time() < frist:
            app.root.update()
            v = app._current()
            if v and v.model and v.model.pages and v.model.fields:
                break
            _time.sleep(0.1)
        v = app._current()
        v._panel_zeigen("werkzeuge")
        app.root.update()
        def knoepfe(w):
            out = {}
            for c in w.winfo_children():
                if c.winfo_class() == "TButton":
                    out[str(c.cget("text"))] = c
                out.update(knoepfe(c))
            return out
        k = knoepfe(app.root)
        k.update(knoepfe(v))
        extras = ["Text einfügen", "Stempel", "Wasserzeichen…",
                  "Kopf-/Fußzeile…", "Suchen & schwärzen…", "Signieren…",
                  "Seite verschieben…", "Zuschneiden…", "Optimieren (komprimieren)",
                  "Formular abflachen", "Datei anhängen…", "Drucken",
                  "Aus Bildern… (PDF erstellen)", "Seiten drehen…", "Leerseite einfügen",
                  "Aus PDF einfügen…", "Als Bilder exportieren…",
                  "Hintergrundfarbe…", "Lesezeichen hinzufügen"]
        for name in extras:
            assert name in k, f"Knopf fehlt: {name}"
            if k[name].winfo_exists():
                k[name].invoke()
                app.root.update()
        for tl in list(app.root.winfo_children()):
            if isinstance(tl, __import__("tkinter").Toplevel):
                tl.destroy()
    finally:
        app_schliessen(app)
