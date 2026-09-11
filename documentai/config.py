"""Einstellungen (portable, in config/settings.json)."""
from __future__ import annotations

import json
import os
from typing import Any

from .paths import config_dir

SETTINGS_FILE = os.path.join(config_dir(), "settings.json")

DEFAULTS: dict[str, Any] = {
    "app": {
        "sprache": "de",
        "dpi": 150,
        "backup_original": True,
        "autosave_minutem": 5,
    },
    "ocr": {
        "sprachen": "deu+eng",
        "min_konfidenz": 60.0,
        "automatisch": True,
        "pfad": "",                     # leer = automatisch suchen
    },                                  # (tools/-Ordner, dann PATH)
    "pdfa": {
        "ghostscript": "",              # leer = automatisch suchen
    },
    "ki": {
        "aktiv": False,                 # lokale KI optional, niemals Pflicht
        "anbieter": "ollama",           # ollama | openai_kompatibel
        "basis_url": "http://localhost:11434",
        "modell": "llama3.1",
        "extern_erlaubt": False,        # Cloud/Drittserver standardmaessig gesperrt
        "api_schluessel": "",
    },
    "validierung": {
        "plz_laenge": 5,
        "streng": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings() -> dict:
    """Laedt Einstellungen; legt Default-Datei beim ersten Start an."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as fh:
                return _deep_merge(DEFAULTS, json.load(fh))
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULTS)
    save_settings(DEFAULTS)
    return dict(DEFAULTS)


def save_settings(settings: dict) -> None:
    os.makedirs(config_dir(), exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=2)


def get(path: str, default: Any = None) -> Any:
    """Zugriff per Punkt-Pfad, z. B. get('ki.aktiv')."""
    node: Any = load_settings()
    for part in path.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return default
    return node


def set(path: str, value: Any) -> None:  # noqa: A001
    settings = load_settings()
    node = settings
    parts = path.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value
    save_settings(settings)
