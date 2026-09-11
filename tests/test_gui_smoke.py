# -*- coding: utf-8 -*-
"""GUI-Rauchtest (nur mit Display; auf Windows lauffähig)."""
import os
import sys
from conftest import app_schliessen

import pytest

tkinter = pytest.importorskip("tkinter")

HAVE_DISPLAY = (os.environ.get("DISPLAY") or
                sys.platform.startswith("win"))


def _app_neu():
    """DocumentAIApp mit Wiederholung (Wine-Tcl-Churn, nur Labor)."""
    import gc
    import time as _t
    from documentai.gui.app import DocumentAIApp
    for _ in range(3):
        try:
            return DocumentAIApp()
        except Exception:
            gc.collect()
            _t.sleep(0.4)
    return DocumentAIApp()


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_gui_importierbar_und_fenster():
    app = _app_neu()
    app.root.update_idletasks()
    # Werkzeugleiste & Status vorhanden?
    kinder = [w for w in app.root.winfo_children()]
    assert kinder
    app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_gui_dokument_oeffnen(svc, assets, tmp_path):
    import shutil
    app = _app_neu()
    try:
        app.add_document(assets.visual)
        app.root.update()
        view = app._current()
        assert view is not None
        # Analyse läuft im Thread – warten (auch unter Test-Last)
        import time
        frist = time.time() + 30
        while time.time() < frist:
            app.root.update()
            if view.model and view.model.pages and view.model.fields:
                break
            time.sleep(0.1)
        assert view.model.fields, "Felder sollten erkannt sein"
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_progress_callback_thread_sicher():
    """Regressionsschutz (Windows-Deadlock, 02.09.2026):

    progress_cb() wird aus Analyse-Nebenthreads gerufen und darf selbst
    KEINE Tk-Aufrufe machen – Windows-Tcl deadlocked sonst zuverlässig,
    sobald der Hauptthread gleichzeitig in update() wartet. Fix:
    progress_cb legt nur Daten in einer Deque ab; _poll_tasks wendet sie
    im Hauptthread an. Dieser Test schlägt fehl, wenn der Fix entfernt
    wird (z. B. durch einen Workspace-Rollback).
    """
    import threading
    import time

    app = _app_neu()
    try:
        verstoesse: list = []
        haupt_aufrufe: list = []
        orig = app.progress.configure

        def wachter(*a, **k):
            if threading.current_thread() is not threading.main_thread():
                verstoesse.append(a)
                raise RuntimeError("Tk-Aufruf aus Nebenthread "
                                   "(Windows-Deadlock-Gefahr)")
            haupt_aufrufe.append((a, k))
            return orig(*a, **k)

        app.progress.configure = wachter

        t = threading.Thread(target=lambda: app.progress_cb(3, 10))
        t.start()
        t.join(timeout=2)

        # Poller (120 ms) muss das Ereignis im Hauptthread anwenden
        for _ in range(40):
            app.root.update()
            time.sleep(0.05)
            if haupt_aufrufe:
                break

        assert not verstoesse, (
            "progress_cb hat Tk aus einem Nebenthread aufgerufen – "
            "Thread-Sicherheits-Fix fehlt!")
        assert haupt_aufrufe, ("Fortschritt wurde im Hauptthread nicht "
                               "angewendet (Poller/Deque defekt?)")
    finally:
        app_schliessen(app)
