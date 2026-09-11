# -*- coding: utf-8 -*-
"""„Zuletzt geöffnete Dokumente“ – lokal (Acrobat-Startseite ohne Cloud).

Speichert maximal N Pfade in data/zuletzt.json im Anwendungsordner.
Keine Uploads, keine Kopien der Dokumente – nur die Pfade.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

MAX_EINTRAEGE = 10


def _pfad(db_pfad: str | None = None) -> str:
    if db_pfad:
        return db_pfad
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "zuletzt.json")


def laden(db_pfad: str | None = None) -> list[dict]:
    """Liste [{'pfad': …, 'zeit': …}] – neueste zuerst."""
    p = _pfad(db_pfad)
    try:
        with open(p, encoding="utf-8") as fh:
            eintraege = json.load(fh)
        return [e for e in eintraege
                if isinstance(e, dict) and e.get("pfad")]
    except (OSError, ValueError):
        return []


def merken(pfad: str, db_pfad: str | None = None) -> None:
    """Datei als zuletzt geöffnet vermerken (Duplikate nach vorn)."""
    if not pfad:
        return
    liste = laden(db_pfad)
    liste = [e for e in liste if e.get("pfad") != pfad]
    liste.insert(0, {"pfad": pfad,
                     "zeit": datetime.now().strftime("%Y-%m-%d %H:%M")})
    liste = liste[:MAX_EINTRAEGE]
    p = _pfad(db_pfad)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(liste, fh, ensure_ascii=False, indent=2)


def leeren(db_pfad: str | None = None) -> None:
    """Liste komplett löschen (Datenschutz-Knopf)."""
    p = _pfad(db_pfad)
    try:
        os.remove(p)
    except OSError:
        pass
