"""Gespeicherte Unterschriften – lokal, mehrfach, wiederverwendbar.

Die Unterschrifts-Bilder (PNG, transparenter Hintergrund) liegen im
Konfigurationsverzeichnis der App (unterschriften/). Keine Cloud, kein
Konto: die Bilder verlassen den Rechner nie. Mehrere Unterschriften
(z. B. „Unterschrift“, „Initialen“, „Sammelunterschrift“) sind möglich;
doppelte Namen bekommen einen Suffix (2), (3), … – nichts wird je
 kommentarlos überschrieben.
"""
from __future__ import annotations

import os
import re
import time

from ..paths import config_dir

_TYP = ".png"


def verzeichnis() -> str:
    """Ordner mit den gespeicherten Unterschriften (wird angelegt)."""
    basis = os.path.join(config_dir(), "unterschriften")
    os.makedirs(basis, exist_ok=True)
    return basis


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9äöüÄÖÜß]+", "_", (name or "").strip())
    slug = slug.strip("_")[:40]
    return slug or "unterschrift"


def speichern(name: str, png_bytes: bytes) -> str:
    """Speichert eine Unterschrift unter dem Namen. Existiert der Name
    schon, wird ein Suffix angehängt (nichts wird überschrieben).
    Liefert den Dateipfad zurück."""
    basis = _slug(name)
    ziel = os.path.join(verzeichnis(), basis + _TYP)
    nr = 2
    while os.path.exists(ziel):
        ziel = os.path.join(verzeichnis(), f"{basis} ({nr})" + _TYP)
        nr += 1
    with open(ziel, "wb") as fh:
        fh.write(png_bytes or b"")
    return ziel


def liste() -> list[dict]:
    """Alle gespeicherten Unterschriften (Name, Pfad, Datum) – neueste
    zuerst."""
    eintraege: list[dict] = []
    try:
        namen = sorted(os.listdir(verzeichnis()))
    except OSError:
        return []
    for n in namen:
        if not n.endswith(_TYP) or n.startswith("."):
            continue
        pfad = os.path.join(verzeichnis(), n)
        try:
            stamp = os.path.getmtime(pfad)
        except OSError:
            stamp = 0.0
        eintraege.append({
            "name": n[:-len(_TYP)],
            "pfad": pfad,
            "datum": time.strftime("%d.%m.%Y %H:%M", time.localtime(stamp))
            if stamp else "–",
        })
    eintraege.sort(key=lambda e: e["name"].lower())
    return eintraege


def loeschen(name: str) -> bool:
    """Entfernt eine gespeicherte Unterschrift (Datei)."""
    pfad = os.path.join(verzeichnis(), _slug(name) + _TYP)
    if os.path.exists(pfad):
        try:
            os.remove(pfad)
            return True
        except OSError:
            return False
    # exakte Datei (mit Suffix) versuchen
    for e in liste():
        if e["name"] == name:
            try:
                os.remove(e["pfad"])
                return True
            except OSError:
                return False
    return False
