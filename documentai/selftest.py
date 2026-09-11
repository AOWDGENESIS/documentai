"""Selbstdiagnose beim Start.

Prinzip: Problem erkannt → Ursache analysieren → Lösung bestimmen →
Reparatur (z. B. Verzeichnisse anlegen, Fallback-Engine wählen) →
Test erneut → Erfolg bestätigen. Kein blindes BLOCKED.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil

from . import __version__, config
from .core import registry
from .core.interfaces import IOcrEngine
from .paths import (APP_DIR, diagnostics_dir, is_writable, plugins_dir,
                    sub_dir, SUBDIRS)
from .util import human_size, system_info


def run_selftest(quick: bool = False) -> list[dict]:
    checks: list[dict] = []

    def add(komponente, ok, detail, hinweis=""):
        checks.append({"komponente": komponente,
                       "status": "ok" if ok is True else
                                 ("warnung" if ok == "warnung" else "fehler"),
                       "detail": detail, "hinweis": hinweis})

    info = system_info()
    ok_win = info["system"] in ("Windows", "Linux", "Darwin")
    add("Betriebssystem", True if ok_win else "warnung",
        f"{info['plattform']} ({info['maschine']})",
        "" if ok_win else "Nicht getestetes System – Funktionen können "
                          "eingeschränkt sein.")

    add("Python", True if tuple(map(int, info["python"].split(".")[:2]))
        >= (3, 9) else "warnung",
        f"{info['implementierung']} {info['python']}",
        "Python 3.9+ empfohlen." if info["python"][:3] < "3.9" else "")

    # Verzeichnisse anlegen (Reparatur) und erneut prüfen
    for name in SUBDIRS:
        path = sub_dir(name)                      # Reparatur: anlegen
        add(f"Verzeichnis {name}\\", True if is_writable(path) else "fehler",
            path if is_writable(path) else "keine Schreibrechte",
            "Schreibrechte prüfen oder Programmordner wechseln."
            if not is_writable(path) else "")

    try:
        usage = shutil.disk_usage(APP_DIR)
        free = usage.free
        add("Speicherplatz", True if free > 100 * 1024 * 1024 else "warnung",
            f"{human_size(free)} frei",
            "Wenig Speicherplatz – Backups/Exporte könnten scheitern."
            if free <= 100 * 1024 * 1024 else "")
    except OSError:
        add("Speicherplatz", "warnung", "nicht ermittelbar")

    add("Arbeitsspeicher", True,
        f"{info.get('ram_gesamt', '?')} "
        f"(frei: {info.get('ram_verfuegbar', '?')})")
    add("CPU", True, f"{info.get('cpu_kerne', '?')} Kerne, "
        f"{info.get('prozessor', '?')[:60]}")

    # Engines über Registry (wählt automatisch verfügbare/fallback)
    try:
        registry.bootstrap()
        for entry in registry.status_report():
            gewaehlt = entry.get("gewaehlt")
            if gewaehlt:
                add(f"Engine {entry['schnittstelle']}", True,
                    f"gewählt: {gewaehlt}")
            else:
                impls = ", ".join(
                    f"{i['name']} ({'verfügbar' if i['verfuegbar'] else 'fehlt'})"
                    for i in entry["implementierungen"]) or "keine"
                add(f"Engine {entry['schnittstelle']}", "warnung",
                    f"keine verfügbare Implementierung: {impls}")
    except Exception as exc:
        add("Engine-Registry", "fehler", str(exc))

    # OCR-Verfügbarkeit
    ocr = registry.resolve(IOcrEngine)
    if ocr is not None:
        version = getattr(ocr, "version", lambda: "?")()
        add("OCR", True, f"{ocr.name} – {version}")
    else:
        add("OCR", "warnung",
            "Tesseract nicht verfügbar – gescannte Seiten werden erkannt, "
            "aber nicht gelesen",
            "Tesseract installieren (Windows: UB-Mannheim-Build), "
            "danach neu starten.")

    # Lokale KI (optional, niemals Pflicht)
    if config.get("ki.aktiv", False):
        try:
            from .engines.semantic import LlmConnector
            url = config.get("ki.basis_url", "http://localhost:11434")
            add("Lokale KI", True if LlmConnector.reachable(url)
                else "warnung",
                f"{config.get('ki.anbieter')} @ {url} "
                f"(Modell {config.get('ki.modell')})",
                "" if LlmConnector.reachable(url)
                else "Server nicht erreichbar – Regel-Semantik übernimmt.")
        except Exception as exc:
            add("Lokale KI", "warnung", str(exc))
    else:
        add("Lokale KI", "warnung",
            "deaktiviert – Grundfunktionen laufen vollständig ohne KI",
            "Optional in config/settings.json aktivieren (ki.aktiv=true).")

    # Ghostscript für PDF/A (portabel in tools/ oder im PATH)
    try:
        from .services.tools import ghostscript_binary
        gs = ghostscript_binary()
    except Exception:
        gs = shutil.which("gs") or shutil.which("gswin64c")
    add("PDF/A-Konvertierung", True if gs else "warnung",
        "Ghostscript verfügbar" if gs else
        "Ghostscript nicht gefunden – PDF/A-Status wird nur angezeigt",
        "Ghostscript installieren, um PDF/A-Export zu ermöglichen."
        if not gs else "")

    # Plugins
    try:
        plugins = [f for f in os.listdir(plugins_dir())
                   if f.endswith(".py") and not f.startswith("_")]
        add("Plugins", True,
            f"{len(plugins)} geladen: {', '.join(plugins)}"
            if plugins else "keine (Ordner plugins\\ ist leer)")
    except OSError:
        add("Plugins", "warnung", "plugins\\ nicht lesbar")

    # PDF-Schnelltest: Engine kann Mini-PDF öffnen?
    try:
        import pymupdf
        doc = pymupdf.open()
        doc.new_page()
        data = doc.tobytes()
        check = pymupdf.open(stream=data, filetype="pdf")
        add("PDF-Engine Funktionstest", True if check.page_count == 1
            else "fehler",
            "Mini-PDF erzeugt, gespeichert, erneut geöffnet: OK")
        check.close()
    except ImportError:
        add("PDF-Engine Funktionstest", "warnung",
            "PyMuPDF fehlt – pypdf-Fallback übernimmt Text/Formulare",
            "pip install pymupdf (empfohlen für Ansicht & OCR)")
    except Exception as exc:
        add("PDF-Engine Funktionstest", "fehler", str(exc))

    if not quick:
        _write_report(checks, info)
    return checks


def _write_report(checks: list[dict], info: dict) -> str:
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(diagnostics_dir(), f"selbstdiagnose_{stamp}.json")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"version": __version__, "system": info,
                       "pruefungen": checks}, fh, ensure_ascii=False,
                      indent=2)
    except OSError:
        pass
    return path


def format_checks(checks: list[dict]) -> str:
    icons = {"ok": "✓", "warnung": "⚠", "fehler": "✗"}
    lines = []
    for c in checks:
        line = f"{icons[c['status']]} {c['komponente']}: {c['detail']}"
        if c["status"] != "ok" and c.get("hinweis"):
            line += f"\n    → {c['hinweis']}"
        lines.append(line)
    return "\n".join(lines)


def has_failures(checks: list[dict]) -> bool:
    return any(c["status"] == "fehler" for c in checks)
