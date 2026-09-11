# -*- coding: utf-8 -*-
"""Versions-Sichtbarkeit: Der Nutzerfund 09.09.2026 (Screenshot mit
dem v8-Fehler 'tuple' object has no attribute 'x') zeigte einen Test
gegen die ALTE Version – die App selbst machte Installations-Stände
ununterscheidbar. Version gehört in Titelleiste, Taskleiste und
Über-Dialog."""
import gc
import os
import sys
import time

import pytest

from conftest import app_schliessen

tkinter = pytest.importorskip("tkinter")

HAVE_DISPLAY = (os.environ.get("DISPLAY") or
                sys.platform.startswith("win"))


def _app_neu():
    from documentai.gui.app import DocumentAIApp
    for _ in range(3):
        try:
            return DocumentAIApp()
        except Exception:
            gc.collect()
            time.sleep(0.4)
    return DocumentAIApp()


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_version_steht_in_der_titelleiste():
    from documentai import __version__
    app = _app_neu()
    try:
        app.root.update()
        titel = app.root.title()
        assert __version__ in titel, \
            f"Version {__version} fehlt im Titel: {titel!r}"
        assert "DocumentAI" in titel
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_titel_zeigt_dokumentname_und_version(svc, assets):
    from documentai import __version__
    app = _app_neu()
    try:
        app.add_document(assets.visual)
        frist = time.time() + 40
        while time.time() < frist:
            app.root.update()
            if app._current() and app._current().model \
                    and app._current().model.pages:
                break
            time.sleep(0.05)
        titel = app.root.title()
        assert "visuell.pdf" in titel, titel
        assert __version__ in titel, titel
        # nach dem Schließen: Basistitel mit Version
        app._ansicht_schliessen(app._current())
        app.root.update()
        titel2 = app.root.title()
        assert __version__ in titel2 and "visuell" not in titel2, titel2
    finally:
        app_schliessen(app)


@pytest.mark.skipif(not HAVE_DISPLAY, reason="kein Display vorhanden")
def test_ueber_dialog_zeigt_version(monkeypatch):
    from documentai import __version__
    from tkinter import messagebox
    texte = []
    monkeypatch.setattr(messagebox, "showinfo",
                        lambda titel, text, **k: texte.append((titel, text))
                        or "ok")
    app = _app_neu()
    try:
        app._ueber_dialog()
        assert texte, "Über-Dialog muss sich öffnen"
        titel, text = texte[0]
        assert __version__ in titel and __version__ in text
    finally:
        app_schliessen(app)
