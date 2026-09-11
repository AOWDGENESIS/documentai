# -*- coding: utf-8 -*-
"""Hell-/Dunkel-Design (Nutzerwunsch 10.09.2026). Alle Farben an
einer Stelle – die Anwendung setzt sie zentral über anwenden()."""
from __future__ import annotations

THEMES = {
    "hell": {
        "kopf": "#26282e",              # dunkle Kopfzeile (Acrobat-Look)
        "kopf_knopf": "#3a3d44",
        "kopf_aktiv": "#4a4e57",
        "schine": "#26282e",             # linke Werkzeug-Schiene
        "schine_text": "#c9cdd4",
        "schine_kurz": "#8b909a",
        "seite": "#f5f5f7",              # Arbeitsflächen
        "mitte": "#eceef2",
        "panel": "#ffffff",              # Werkzeug-Panel
        "panel_rand": "#d9dce1",
        "kasten": "#ffffff",
        "text": "#1f2430",
        "grau": "#5a6472",
        "akzent": "#1473e6",
        "akzent_aktiv": "#0f5fc9",
        "akzent_druck": "#0b4a9e",
        "knopf_aktiv": "#e8f1fd",
        "knopf_druck": "#d3e3fc",
        "canvas": "#e9ebef",
        "navbar": "#ffffff",
        "banner_bg": "#fff8e1",
        "banner_fg": "#7a5c00",
        "banner_rand": "#f0d060",
        "banner_aktiv": "#ffe082",
        "symbol": "#1f6feb",
        "trenner": "#d9dce1",
    },
    "dunkel": {
        "kopf": "#1b1d22",
        "kopf_knopf": "#2c2f36",
        "kopf_aktiv": "#3a3e47",
        "schine": "#1b1d22",
        "schine_text": "#c9cdd4",
        "schine_kurz": "#8b909a",
        "seite": "#23262c",
        "mitte": "#1a1c21",
        "panel": "#26292f",
        "panel_rand": "#3a3e46",
        "kasten": "#26292f",
        "text": "#e8eaee",
        "grau": "#9aa1ac",
        "akzent": "#3b8bff",
        "akzent_aktiv": "#2f79e0",
        "akzent_druck": "#2660b4",
        "knopf_aktiv": "#31404f",
        "knopf_druck": "#3a4c5e",
        "canvas": "#14161a",
        "navbar": "#26292f",
        "banner_bg": "#3a341c",
        "banner_fg": "#ffd98a",
        "banner_rand": "#8a7430",
        "banner_aktiv": "#4a4124",
        "symbol": "#7db4ff",
        "trenner": "#3a3e46",
    },
}


def norm(modus: str) -> str:
    return "dunkel" if str(modus).lower().startswith("d") else "hell"


def farben(modus: str) -> dict:
    return THEMES[norm(modus)]
