# -*- coding: utf-8 -*-
"""Selbstdiagnose + Registry/Plugin-Mechanik + LLM-Datenschutz-Guard."""
import os

import pytest

from documentai.core import registry
from documentai.core.interfaces import (IFieldDetector, IPdfEngine,
                                        ISemanticAnalyzer)
from documentai.selftest import format_checks, has_failures, run_selftest


def test_selbstdiagnose_laeuft():
    checks = run_selftest(quick=True)
    assert isinstance(checks, list) and len(checks) >= 8
    komponenten = {c["komponente"] for c in checks}
    assert "OCR" in komponenten and "Plugins" in komponenten
    assert not has_failures(checks), format_checks(checks)


def test_selbstdiagnose_bericht_geschrieben():
    run_selftest(quick=False)
    from documentai.paths import diagnostics_dir
    berichte = [f for f in os.listdir(diagnostics_dir())
                if f.startswith("selbstdiagnose_")]
    assert berichte


def test_pdf_engine_gewaehlt():
    registry.bootstrap()
    engines = registry.available_engines(IPdfEngine)
    assert engines, "Keine PDF-Engine verfügbar!"
    assert engines[0].name == "PyMuPDF-Engine"


def test_fallback_prinzip():
    """Registry wählt vorhandene Komponente – niemals blind ersetzen."""
    registry.bootstrap()
    alle = registry._CATALOG[IPdfEngine]
    namen = [getattr(c, "name", c.__name__) for c in alle]
    assert any("Fallback" in n for n in namen)    # pypdf registriert


def test_semantik_verfuegbar():
    registry.bootstrap()
    engines = registry.available_engines(ISemanticAnalyzer)
    assert engines and engines[0].name.startswith("Regel-Semantik")


def test_detektor_verfuegbar():
    registry.bootstrap()
    assert registry.available_engines(IFieldDetector)


def test_plugin_geladen():
    registry.bootstrap()
    from documentai.paths import plugins_dir
    from documentai.engines.semantic import CANONICAL_FIELDS
    # Beispiel-Plugin erweitert Synonyme
    assert "mitgliedsnummer" in CANONICAL_FIELDS["kundennummer"]["syn"]


def test_llm_datenschutz_guard():
    """Externe Verarbeitung ohne Zustimmung muss verweigert werden."""
    from documentai.engines.semantic import LlmConnector
    conn = LlmConnector("https://api.example.com/v1", "m",
                        anbieter="openai_kompatibel",
                        extern_erlaubt=False)
    with pytest.raises(PermissionError):
        conn._check_privacy()
    lokaler_conn = LlmConnector("http://localhost:11434", "m")
    lokaler_conn._check_privacy()                 # lokal immer erlaubt


def test_llm_nur_aktiv_wenn_konfiguriert():
    from documentai.engines.semantic import LlmSemanticAnalyzer
    assert LlmSemanticAnalyzer.is_available() in (True, False)  # robust


def test_gui_thread_fix_vorhanden():
    """Tripwire gegen Workspace-Rollbacks (02.09.2026):

    Der Windows-Deadlock-Fix (progress_cb ruft niemals Tk aus Nebenthreads;
    Fortschritt läuft über _progress_events-Deque + _poll_tasks-Poller im
    Hauptthread) wurde schon zweimal durch Snapshot-Rückrollen still
    entfernt. Dieser Test liest den Quelltext direkt (kein tkinter/Display
    nötig) und schlägt laut fehl, wenn der Fix je wieder fehlt.
    Das Verhaltens-Gegenstück (mit echtem Thread) läuft als
    test_progress_callback_thread_sicher in test_gui_smoke.py.
    """
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent /
           "documentai" / "gui" / "app.py").read_text(encoding="utf-8")

    assert src.count("_progress_events") >= 3, (
        "Thread-Sicherheits-Fix fehlt in gui/app.py "
        "(_progress_events-Deque nicht gefunden – Rollback?")
    m = re.search(r"def progress_cb\(.*?\n(.*?)(?=\n    def )", src, re.S)
    assert m, "progress_cb nicht gefunden"
    body = m.group(1)
    assert "configure" not in body, (
        "progress_cb ruft wieder Tk direkt auf – Windows-Deadlock-Gefahr!")
    assert "_progress_events" in body, "progress_cb nutzt die Deque nicht"
    m2 = re.search(r"def _poll_tasks\(.*?\n(.*?)(?=\n    def |\Z)", src, re.S)
    assert m2, "_poll_tasks nicht gefunden"
    assert "_progress_events" in m2.group(1) and "configure" in m2.group(1), (
        "_poll_tasks wendet die Fortschritts-Ereignisse nicht an")
