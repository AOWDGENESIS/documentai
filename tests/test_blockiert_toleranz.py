# -*- coding: utf-8 -*-
"""„Das darf nicht passieren“ (Nutzerfund 10.09.2026, Screenshot):
Windows-Anwendungssteuerungsrichtlinie blockierte lxml/etree.pyd –
die Installation brach im Selbsttest komplett ab (Code 1).

Diese Tests sichern:
1. Installer-Selbsttest erkennt Blockierungen und bricht NICHT ab.
2. Die App startet und arbeitet ohne lxml/docx/pptx weiter
   (Degradation mit klarer Meldung statt Absturz)."""
import importlib.util
import os
import sys
import textwrap

import pytest

HIER = os.path.dirname(os.path.abspath(__file__))
INSTALL_TAIL = os.path.join(HIER, "..", "..", "winenv",
                            "installer-src", "install_tail.py")

if not os.path.exists(INSTALL_TAIL):
    it = None
else:
    _spec = importlib.util.spec_from_file_location(
        "install_tail", INSTALL_TAIL)
    it = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(it)

requires_it = pytest.mark.skipif(it is None,
                                 reason="install_tail.py nicht im Container")

# Die EXAKTE Fehlermeldung aus dem Nutzer-Screenshot:
ECHTE_MELDUNG = ("DLL load failed while importing etree: "
                 "Eine Anwendungssteuerungsrichtlinie hat diese Datei "
                 "blockiert.")


@requires_it
def test_blockierung_erkannt():
    assert it.ist_blockiert(ECHTE_MELDUNG)
    assert it.ist_blockiert("... app control policy blocked this file")
    assert not it.ist_blockiert("ModuleNotFoundError: No module named 'x'")
    assert not it.ist_blockiert("")


@requires_it
def test_import_fehler_liefert_meldung():
    ok, meldung = it.import_fehler(sys.executable, "sys")
    assert ok and meldung == ""
    ok, meldung = it.import_fehler(sys.executable, "gibtsnicht123")
    assert not ok and "gibtsnicht123" in meldung


@requires_it
def test_optionale_pruefung_bricht_nie_ab():
    """Auch wenn ALLE optionalen Module fehlen: Funktion liefert eine
    Liste und raised nichts (Kern der Installationstoleranz)."""
    probleme = it.optionale_bibliotheken_pruefen(
        sys.executable, log=lambda *a, **k: None)
    assert isinstance(probleme, list)
    fehlend = [m for m, _b in probleme]
    if fehlend:                       # Host hat evtl. alles installiert
        assert all(m in ("docx", "openpyxl", "striprtf", "pptx")
                   for m in fehlend)


def test_exporter_blockiert_hinweis():
    """Die Export-Fehlermeldung erklärt die Windows-Blockierung."""
    from documentai.engines.exporter import _format_import_fehler
    text = _format_import_fehler(ImportError(ECHTE_MELDUNG),
                                 "Word-Export")
    assert "blockiert" in text
    assert "Smart App Control" in text
    assert "App- und Browsersteuerung" in text
    text2 = _format_import_fehler(
        ImportError("No module named 'docx'"), "Word-Export")
    assert "nicht installiert" in text2
    assert "Smart App Control" not in text2


def _sitecustomize_schreiben(tmp_path):
    """Erzeugt ein Verzeichnis mit sitecustomize.py, das jeden lxml-
    Import mit der ECHTEN Windows-Blockier-Meldung schlagen lässt."""
    sc = tmp_path / "schock"
    sc.mkdir()
    (sc / "sitecustomize.py").write_text(textwrap.dedent('''
        import builtins
        _orig = builtins.__import__
        def _blockiert(name, *a, **k):
            if name.split(".")[0] == "lxml":
                raise ImportError(
                    "DLL load failed while importing etree: "
                    "Eine Anwendungssteuerungsrichtlinie hat diese "
                    "Datei blockiert.")
            return _orig(name, *a, **k)
        builtins.__import__ = _blockiert
    '''), encoding="utf-8")
    return str(sc)


SKRIPT = textwrap.dedent('''
    import sys, time, gc, os
    sys.path.insert(0, os.environ["APP_WURZEL"])
    from tkinter import messagebox
    import documentai.gui.app as appmod
    fehler = {}
    appmod.messagebox.showerror = lambda *a, **k: fehler.update(
        {"titel": a[0] if a else "", "text": a[1] if len(a) > 1 else ""})
    appmod.messagebox.showinfo = lambda *a, **k: fehler.update(
        {"info": a[1] if len(a) > 1 else ""})
    ziel = os.environ["XLSX_ZIEL"]
    appmod.filedialog.asksaveasfilename = lambda **k: ziel
    from documentai import samples
    from documentai.gui.app import DocumentAIApp
    app = None
    for _ in range(3):
        try:
            app = DocumentAIApp(); break
        except Exception:
            gc.collect(); time.sleep(0.4)
    assert app is not None, "App startet nicht ohne lxml!"
    pdf = os.path.join(os.environ["TMP_PDF"])
    app.add_document(samples.make_zeilen_formular_pdf(pdf))
    view = app._current()
    frist = time.time() + 40
    while time.time() < frist:
        app.root.update()
        mm = view.model
        if mm and mm.pages and mm.audit and \\
           mm.audit[-1].action == "Analyse abgeschlossen":
            break
        time.sleep(0.05)
    # 1) XLSX-Export funktioniert OHNE lxml (openpyxl ist pur)
    app._konvertieren("xlsx")
    app.root.update()
    assert os.path.getsize(ziel) > 100, "XLSX-Export ging verloren"
    # 2) DOCX-Export meldet die Blockierung verständlich
    app._konvertieren("docx")
    app.root.update()
    assert "blockiert" in (fehler.get("text") or ""), fehler
    assert "Smart App Control" in (fehler.get("text") or ""), fehler
    # 3) App lebt weiter (kein Crash)
    app.root.update()
    print("DEGRADATION OK")
''')


def test_app_laeuft_weiter_trotz_blockierung(tmp_path):
    """End-to-End: lxml blockiert (echte Windows-Meldung) – App
    startet, XLSX geht, DOCX erklärt die Blockierung."""
    import subprocess
    env = dict(os.environ)
    env["PYTHONPATH"] = _sitecustomize_schreiben(tmp_path)
    env["APP_WURZEL"] = os.path.dirname(HIER)
    env["TMP_PDF"] = str(tmp_path / "w.pdf")
    env["XLSX_ZIEL"] = str(tmp_path / "aus.xlsx")
    env.setdefault("DISPLAY", ":99")
    proc = subprocess.run(
        [sys.executable, "-c", SKRIPT], capture_output=True, text=True,
        env=env, cwd=str(tmp_path), timeout=120)
    assert "DEGRADATION OK" in proc.stdout, (
        proc.stdout[-800:] + proc.stderr[-1200:])
