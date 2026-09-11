"""Automatisierte Datenextraktion aus Dokumenten für den Datentresor.

Liest Informationen aus analysierten Dokumenten (Felder, Label-Zeilen,
Freitext) und erzeugt strukturierte Vorschläge (kanonischer Schlüssel,
Wert, Konfidenz, Quelle) – zur Prüfung durch den Benutzer und zur
Übernahme in die verschlüsselte Personen-Datenbank.
"""
from __future__ import annotations

import re
from typing import Any

from ..core.models import DocumentModel
from ..engines.semantic import RuleSemanticAnalyzer, match_canonical

_UNDERSCORE = re.compile(r"^[_.\-]{3,}$")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[ ]?(?:[A-Z0-9]{4}[ ]?){2,7}[A-Z0-9]"
                      r"{1,4}\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+\w")
_PHONE_RE = re.compile(r"\+?\d[\d ()/-]{5,}\d")
_DATE_RE = re.compile(r"\b\d{1,2}\.\d{1,2}\.\d{2,4}\b")
_PLZ_ORT_RE = re.compile(r"\b(\d{5})\s+([A-ZÄÖÜ][\wäöüß-]+)\b")


def extract_structured_data(model: DocumentModel) -> list[dict]:
    """Sammelt alle erkennbaren Personen-/Verwaltungsdaten eines Dokuments.

    Quellen (in dieser Priorität):
    1. Formularfelder mit Wert + Semantik (AcroForm & visuell)
    2. 'Label: Wert'-Zeilen im Text
    3. Muster im Fließtext (E-Mail, IBAN, Telefon, Datum, PLZ+Ort, Name)
    """
    proposals: dict[str, dict] = {}

    def _add(key: str, wert: str, quelle: str, konfidenz: float,
             label: str = ""):
        wert = str(wert).strip().rstrip(",").rstrip(";")
        if not key or not wert or _UNDERSCORE.match(wert):
            return
        alt = proposals.get(key)
        if alt is None or konfidenz > alt["konfidenz"]:
            proposals[key] = {"key": key, "wert": wert,
                              "quelle": quelle,
                              "konfidenz": round(konfidenz, 2),
                              "label": label or key}

    # ---- 1) Formularfelder mit Wert --------------------------------
    for f in model.fields:
        if f.value is None or str(f.value).strip() == "":
            continue
        canon = f.canonical or match_canonical(f.label or f.name)[0]
        if canon and f.field_type not in ("checkbox", "signatur"):
            _add(canon, f.value, "formularfeld", max(0.6, f.confidence),
                 f.label or f.name)

    # ---- 2) Label-Zeilen -------------------------------------------
    for page in model.pages:
        zeilen: dict[tuple[int, int], list] = {}
        for w in page.words:
            zeilen.setdefault((w.block, w.line), []).append(w)
        for _key, woerter in zeilen.items():
            woerter.sort(key=lambda w: w.rect.x)
            for i, w in enumerate(woerter[:-1]):
                if not w.text.endswith(":"):
                    continue
                label = w.text.rstrip(":").strip()
                canon, conf = match_canonical(label)
                if not canon:
                    continue
                rest = [x.text for x in woerter[i + 1:]
                        if not _UNDERSCORE.match(x.text)
                        and x.text not in (":", "|")]
                if rest:
                    _add(canon, " ".join(rest), "label-zeile",
                         min(0.95, conf), label)

    # ---- 3) Fließtext-Muster ----------------------------------------
    volltext = "\n".join(p.text for p in model.pages)
    analyzer = RuleSemanticAnalyzer()
    for zeile in volltext.splitlines():
        if len(zeile) > 120:
            continue
        email = _EMAIL_RE.search(zeile)
        if email:
            _add("email", email.group(0), "text", 0.9)
        iban = _IBAN_RE.search(zeile)
        if iban:
            _add("iban", iban.group(0), "text", 0.9)
        telefon = _PHONE_RE.search(zeile)
        if telefon and sum(c.isdigit() for c in telefon.group(0)) >= 8:
            _add("telefon", telefon.group(0), "text", 0.75)
        plz_ort = _PLZ_ORT_RE.search(zeile)
        if plz_ort:
            _add("plz", plz_ort.group(1), "text", 0.8)
            _add("ort", plz_ort.group(2), "text", 0.8)
    # Freitext-Strukturierung (Namen, Datum, Straße) als ergänzende Quelle
    try:
        freitext = analyzer.parse_freeform_lines(
            [z.strip() for z in volltext.splitlines() if 0 < len(z.strip())
             <= 60])
        for key, wert in freitext.items():
            _add(key, wert, "text", 0.7)
    except Exception:
        pass

    # Aufräumen: Felder mit nutzlosen Werten entfernen
    def _plausibel(key: str, wert: str) -> bool:
        wert = wert.strip()
        if len(wert) < 2 or len(wert) > 60:
            return False
        if key == "plz":
            return bool(re.fullmatch(r"\d{5}", wert))
        if key == "email":
            return "@" in wert and "." in wert
        if key == "geburtsdatum":
            return bool(_DATE_RE.fullmatch(wert) or
                        re.fullmatch(r"\d{4}-\d{2}-\d{2}", wert))
        if key in ("vorname", "nachname"):
            tokens = wert.split()
            return 1 <= len(tokens) <= 3 and all(t.isalpha() for t in tokens)
        if key == "telefon":
            return sum(c.isdigit() for c in wert) >= 6
        return True

    return [p for p in proposals.values() if _plausibel(p["key"], p["wert"])]


def proposals_to_text(proposals: list[dict]) -> str:
    lines = [f"{'Feld':<18}{'Wert':<34}{'Quelle':<14}Konfidenz", "-" * 74]
    for p in sorted(proposals, key=lambda x: x["key"]):
        lines.append(f"{p['key']:<18}{p['wert'][:32]:<34}"
                     f"{p['quelle']:<14}{round(p['konfidenz'] * 100)} %")
    return "\n".join(lines)


def collect_from_document(service: Any, path: str,
                          password: str = "") -> tuple[list[dict], Any, Any]:
    """Öffnet + analysiert ein Dokument und liefert Extraktionsvorschläge."""
    model, session, engine = service.open_document(path, password or None)
    service.analyze(model, session, engine)
    return extract_structured_data(model), model, session
