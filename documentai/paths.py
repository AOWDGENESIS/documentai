"""Portable Pfadverwaltung.

Alle Laufzeitverzeichnisse liegen relativ zum Programmverzeichnis –
kein Zwang nach C:\\Program Files, keine Registry, laeuft von USB-Stick,
SSD, HDD oder Netzwerkordner.
"""
from __future__ import annotations

import os
import sys

# Bei PyInstaller (frozen) zeigt APP_DIR auf das Verzeichnis der EXE,
# ansonsten auf das Projektverzeichnis (Ordner oberhalb des Packages).
if getattr(sys, "frozen", False):  # portable EXE
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SUBDIRS = [
    "engines",      # Dokumentation/Info ueber eingebundene Engines
    "models",       # optionale lokale Modelle (z. B. Tessdata)
    "plugins",      # erweiterbare Importer/Detektoren
    "templates",    # Vorlagen & Musterdokumente
    "data",         # Profile, Zuordnungen
    "cache",        # Render-Cache, Autosave
    "logs",         # Anwendungslaufbloecke
    "logs/audit",   # Audit-Trail je Dokument
    "backups",      # Sicherungen der Originale
    "config",       # Einstellungen
    "reports",      # Vergleiche, Fehlerberichte, Exporte
    "diagnostics",  # Selbstdiagnose-Berichte
]

_DIR_CACHE: dict[str, str] = {}


def _join(name: str) -> str:
    path = os.path.join(APP_DIR, name)
    _DIR_CACHE[name] = path
    return path


def sub_dir(name: str, create: bool = True) -> str:
    """Liefert ein Laufzeitverzeichnis (und legt es bei Bedarf an)."""
    if name in _DIR_CACHE:
        path = _DIR_CACHE[name]
    else:
        path = _join(name)
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            pass
    return path


def ensure_dirs() -> list[str]:
    """Legt alle Laufzeitverzeichnisse an. Gibt Liste anlegbarer Pfade zurueck."""
    created: list[str] = []
    for name in SUBDIRS:
        sub_dir(name)
        created.append(name)
    return created


def config_dir() -> str:
    return sub_dir("config")


def data_dir() -> str:
    return sub_dir("data")


def cache_dir() -> str:
    return sub_dir("cache")


def logs_dir() -> str:
    return sub_dir("logs")


def audit_dir() -> str:
    return sub_dir("logs/audit")


def backups_dir() -> str:
    return sub_dir("backups")


def reports_dir() -> str:
    return sub_dir("reports")


def diagnostics_dir() -> str:
    return sub_dir("diagnostics")


def plugins_dir() -> str:
    return sub_dir("plugins")


def models_dir() -> str:
    return sub_dir("models")


def templates_dir() -> str:
    return sub_dir("templates")


def is_writable(directory: str) -> bool:
    """Prueft Schreibrechte ohne Dateileichen (Testdatei wird entfernt)."""
    try:
        test = os.path.join(directory, ".write_test")
        with open(test, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(test)
        return True
    except OSError:
        return False
