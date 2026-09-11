"""Personendaten-Profil: einmal erfassen, viele Dokumente befüllen."""
from __future__ import annotations

import csv
import json
import os
from typing import Optional

from ..paths import data_dir

PROFILE_PATH = os.path.join(data_dir(), "profil.json")

PROFILE_TEMPLATE: dict[str, str] = {
    "vorname": "",
    "nachname": "",
    "geburtsdatum": "",
    "strasse": "",
    "hausnummer": "",
    "plz": "",
    "ort": "",
    "telefon": "",
    "email": "",
    "iban": "",
    "kundennummer": "",
}


def load() -> dict:
    if os.path.exists(PROFILE_PATH):
        try:
            with open(PROFILE_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return {k: v for k, v in data.items()
                        if str(v).strip() != ""}
        except (OSError, json.JSONDecodeError):
            pass
    return dict(PROFILE_TEMPLATE)


def save(profile: dict) -> None:
    merged = dict(PROFILE_TEMPLATE)
    merged.update({k: v for k, v in (profile or {}).items()
                   if str(v).strip() != ""})
    with open(PROFILE_PATH, "w", encoding="utf-8") as fh:
        json.dump(merged, fh, ensure_ascii=False, indent=2)


def import_file(path: str) -> dict:
    """Import aus JSON oder CSV (Spalten: schlüssel;wert bzw. key,value)."""
    ext = os.path.splitext(path)[1].lower()
    profile: dict = {}
    if ext == ".json":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("JSON-Profil muss ein Objekt sein.")
        profile = {str(k): v for k, v in data.items()}
    elif ext == ".csv":
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.reader(fh, delimiter=";"):
                if len(row) >= 2 and row[0].strip():
                    profile[row[0].strip()] = row[1].strip()
    else:
        raise ValueError("Nur JSON oder CSV als Profilimport möglich.")
    return profile


def is_filled(profile: Optional[dict]) -> bool:
    return bool(profile) and any(str(v).strip()
                                 for v in (profile or {}).values())


def describe(canonical: str) -> str:
    """Anzeigename für einen kanonischen Schlüssel."""
    return {"vorname": "Vorname", "nachname": "Nachname",
            "geburtsdatum": "Geburtsdatum", "strasse": "Straße",
            "hausnummer": "Hausnummer", "plz": "PLZ", "ort": "Ort",
            "telefon": "Telefon", "email": "E-Mail", "iban": "IBAN",
            "bic": "BIC", "kundennummer": "Kundennummer",
            "aktenzeichen": "Aktenzeichen"}.get(
                canonical, canonical.replace("_", " ").capitalize())
