"""Semantische Ebene: Labels verstehen, Synonyme (DE/EN), Daten zuordnen.

Regelbasiert (immer verfügbar, keine Cloud) + optional lokale KI
(Ollama / OpenAI-kompatible Server). Grundfunktionen laufen auch
ohne LLM uneingeschränkt.
"""
from __future__ import annotations

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from .. import config
from ..core.models import FieldModel

# --------------------------------------------------------------- Synonyme
CANONICAL_FIELDS: dict[str, dict] = {
    "vorname":        {"syn": ["vorname", "first name", "firstname", "fname",
                               "given name", "name (vorname)", "rufname"],
                       "typ": "text"},
    "nachname":       {"syn": ["nachname", "familienname", "last name",
                               "lastname", "surname", "name (nachname)"],
                       "typ": "text"},
    "name":           {"syn": ["name", "vollständiger name", "full name",
                               "name (komplett)"],
                       "typ": "text"},
    "geburtsdatum":   {"syn": ["geburtsdatum", "geb datum", "geb datum",
                               "geboren am", "geb am", "geb", "date of birth",
                               "dob", "birth date", "birthdate", "geburtstag"],
                       "typ": "datum"},
    "geburtsort":     {"syn": ["geburtsort", "place of birth"], "typ": "text"},
    "strasse":        {"syn": ["strasse", "straße", "str", "wohnstrasse",
                               "wohnsitz strasse", "street", "address line 1",
                               "anschrift strasse"],
                       "typ": "text"},
    "hausnummer":     {"syn": ["hausnummer", "haus nr", "nr", "number",
                               "house number", "street number"],
                       "typ": "text"},
    "adresse":        {"syn": ["adresse", "anschrift", "address",
                               "wohnsitz", "street address"],
                       "typ": "text"},
    "plz":            {"syn": ["plz", "postleitzahl", "zip", "zipcode",
                               "zip code", "postal code", "postcode"],
                       "typ": "plz"},
    "plz_ort":        {"syn": ["plz ort", "postleitzahl ort", "zip city",
                               "plz / ort", "plz/ort"], "typ": "text"},
    "ort":            {"syn": ["ort", "stadt", "city", "town", "wohnort",
                               "place"], "typ": "text"},
    "land":           {"syn": ["land", "staat", "country"], "typ": "text"},
    "telefon":        {"syn": ["telefon", "tel", "telefonnummer", "phone",
                               "phone number", "telephone", "rufnummer"],
                       "typ": "telefon"},
    "mobil":          {"syn": ["mobil", "handy", "mobilfunk",
                               "mobile", "mobile phone"], "typ": "telefon"},
    "email":          {"syn": ["email", "e mail", "e mail adresse",
                               "mail", "mailadresse", "e-mail", "e-mail adresse",
                               "email adresse", "electronic mail"],
                       "typ": "email"},
    "iban":           {"syn": ["iban", "kontonummer iban",
                               "international bank account"], "typ": "iban"},
    "bic":            {"syn": ["bic", "swift", "bank identifier"],
                       "typ": "text"},
    "bank":           {"syn": ["bank", "bankinstitut", "bank name",
                               "kontoführende bank"], "typ": "text"},
    "kundennummer":   {"syn": ["kundennummer", "kunden nr", "kunden-nr",
                               "customer number", "customer id",
                               "kundennummer bitte angeben"], "typ": "zahl"},
    "aktenzeichen":   {"syn": ["aktenzeichen", "az", "file number",
                               "reference number", "ref nr", "referenz"],
                       "typ": "text"},
    "personalnummer": {"syn": ["personalnummer", "personal nr",
                               "personnel number", "mitarbeiternummer"],
                       "typ": "zahl"},
    "steuernummer":   {"syn": ["steuernummer", "steuer id", "steuerident",
                               "tax id", "tax number", "steuer-identnummer"],
                       "typ": "text"},
    "versicherungsnummer": {"syn": ["versicherungsnummer", "vers nr",
                                    "sozialversicherungsnummer", "sv nummer",
                                    "insurance number"], "typ": "text"},
    "personalausweis": {"syn": ["personalausweis", "ausweisnummer",
                                "identity card", "id number", "ausweis nr"],
                        "typ": "text"},
    "datum":          {"syn": ["datum", "date", "datum heute",
                               "tag der antragsstellung"], "typ": "datum"},
    "ort_datum":      {"syn": ["ort datum", "ort und datum", "city date"],
                       "typ": "text"},
    "unterschrift":   {"syn": ["unterschrift", "unterschrift des",
                               "signature", "sign", "signiert von"],
                       "typ": "signatur"},
    "betrag":         {"syn": ["betrag", "eur", "euro", "amount",
                               "gesamtbetrag", "preis"], "typ": "zahl"},
    "firma":          {"syn": ["firma", "unternehmen", "company",
                               "firmenname", "arbeitgeber"], "typ": "text"},
    "beruf":          {"syn": ["beruf", "taetigkeit", "occupation",
                               "profession", "job"], "typ": "text"},
}

# Kompilierter Typ-Schnelltest (auch fuer Felderkennung genutzt)
# Wortgrenzen/Präfix-Match mit Bedacht (Nutzerfund 10.09.2026: „Bis-
# herige Schule“ wurde per Teilstring „bis“ zum Datum, „Einstieg
# Bushaltestelle“ per „tel“ zum Telefon). Deutsche Komposita wie
# „Telefonnummer“/„Hausnummer“ bleiben über Präfix-Treffer erkannt.
_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("datum",    re.compile(r"(geburts?(datum|tag)|geb\.|datum\b|date\b|"
                            r"seit\b|gültig bis|bis\b)", re.I)),
    ("email",    re.compile(r"(e[- ]?mail|mail\b)", re.I)),
    ("iban",     re.compile(r"\biban\b", re.I)),
    ("plz",      re.compile(r"\b(plz|postleitzahl|zip|postal)\b", re.I)),
    ("telefon",  re.compile(r"(telefon|tel\b|phone|mobil|handy|fax)", re.I)),
    ("zahl",     re.compile(r"(betrag|anzahl|menge|nummer\b|zahl\b|"
                            r"amount|preis|eur\b|nr\.?$)", re.I)),
    ("signatur", re.compile(r"(unterschrift|signature)", re.I)),
]


def normalize(text: str) -> str:
    """Label normalisieren: Umlaute, Kleinschreibung, Zeichensetzung."""
    t = (text or "").strip().lower()
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
                    "á": "a", "à": "a", "é": "e", "è": "e", "í": "i"}
    for k, v in replacements.items():
        t = t.replace(k, v)
    t = re.sub(r"[^\w\s/]", " ", t)       # Doppelpunkte etc. entfernen
    t = re.sub(r"\s+", " ", t).strip()
    return t


def infer_type(label: str, current: str = "text") -> str:
    for typ, pattern in _TYPE_PATTERNS:
        if pattern.search(label or ""):
            return typ
    return current


def match_canonical(label: str) -> tuple[str, float]:
    """Liefert (kanonischen Schluessel, Konfidenz) fuer eine Beschriftung.

    Mehrstufig: exakte Synonyme schlagen Teil-Treffer, Teil-Treffer
    schlagen Fuzzy-Treffer. Bei Gleichstand gewinnt das laengere
    Synonym ( Spezifitaet).
    """
    norm = normalize(label)
    if not norm:
        return "", 0.0

    def _pass(scorer) -> tuple[str, float]:
        best_canon, best_score, best_len = "", 0.0, 0
        for canon, meta in CANONICAL_FIELDS.items():
            for syn in meta["syn"]:
                syn_n = normalize(syn)
                if not syn_n:
                    continue
                score = scorer(syn_n)
                if score and (score > best_score or
                              (score == best_score and
                               len(syn_n) > best_len)):
                    best_canon, best_score, best_len = canon, score, \
                        len(syn_n)
        return best_canon, best_score

    # Stufe 1: exakte Übereinstimmung
    canon, conf = _pass(lambda s: 0.98 if norm == s else 0.0)
    if canon:
        return canon, conf
    # Stufe 2: Wort-Anfang/Ende ("plz ort" endet mit "ort", beginnt mit "plz")
    canon, conf = _pass(lambda s: 0.90 if (norm.startswith(s + " ") or
                                           norm.endswith(" " + s)) else 0.0)
    if canon:
        return canon, conf
    # Stufe 3: Synonym als eigenes Wort im Label
    tokens = norm.split()
    canon, conf = _pass(lambda s: 0.86 if s in tokens else 0.0)
    if canon:
        return canon, conf
    # Stufe 4: Fuzzy
    import difflib
    best: tuple[str, float] = ("", 0.0)
    for canon_, meta in CANONICAL_FIELDS.items():
        for syn in meta["syn"]:
            ratio = difflib.SequenceMatcher(
                None, norm, normalize(syn)).ratio()
            if ratio > 0.84 and ratio > best[1]:
                best = (canon_, round(ratio * 0.95, 3))
    return best


# ----------------------------------------------------- regelbasierter Analyzer
class RuleSemanticAnalyzer:
    name = "Regel-Semantik (lokal, DE/EN)"
    priority = 100

    @staticmethod
    def is_available() -> bool:
        return True

    def classify(self, fields: list[FieldModel]) -> None:
        for f in fields:
            canon, conf = match_canonical(f.label or f.name)
            if not canon:
                canon, conf = match_canonical(f.name)
            if canon:
                f.canonical = canon
                f.confidence = max(f.confidence, min(0.97, conf))
                meta = CANONICAL_FIELDS[canon]
                if f.field_type == "text":
                    f.field_type = meta["typ"]
            elif f.field_type == "text":
                f.field_type = infer_type(f.label or f.name, f.field_type)

    # ------------------------------------------------------------------
    def match_profile(self, fields: list[FieldModel],
                      profile: dict) -> list[dict]:
        """Profildaten (kanonisch) Feldern zuordnen – mit Konfidenz."""
        assignments: list[dict] = []
        norm_profile = {normalize(k): v for k, v in (profile or {}).items()
                        if str(v).strip() != ""}
        for f in fields:
            canon = f.canonical or match_canonical(f.label or f.name)[0]
            if not canon:
                continue
            value = norm_profile.get(canon)
            reason, conf, review = canon, 0.97, False

            # Spezialfall: kombinierte Felder aus atomaren Daten bauen
            if value is None and canon == "plz_ort":
                plz = norm_profile.get("plz")
                ort = norm_profile.get("ort")
                if plz or ort:
                    value = f"{plz or ''} {ort or ''}".strip()
                    reason = "PLZ + Ort aus Profildaten kombiniert"
                    conf, review = 0.9, True
            elif value is None and canon == "adresse":
                strasse = norm_profile.get("strasse")
                nr = norm_profile.get("hausnummer")
                if strasse:
                    value = f"{strasse} {nr or ''}".strip()
                    reason = "Adresse aus Straße + Hausnummer kombiniert"
                    conf, review = 0.88, True
            elif value is None and canon == "name":
                vn = norm_profile.get("vorname")
                nn = norm_profile.get("nachname")
                if vn and nn:
                    value = f"{vn} {nn}"
                    reason = "Name aus Vor- + Nachname kombiniert"
                    conf, review = 0.88, True
            if value is not None and canon == "plz_ort" and value:
                plz, ort = split_plz_ort(str(value))
                value = f"{plz} {ort}".strip()
            elif canon == "name" and value:
                review = True
                reason = "Vollständiger Name – bitte Zuordnung prüfen"
                conf = 0.8
            if value is None or str(value).strip() == "":
                continue
            assignments.append({
                "feld_id": f.id,
                "feld": f.label or f.name,
                "canonical": canon,
                "wert": str(value),
                "konfidenz": conf,
                "grund": reason,
                "pruefen": review or conf < 0.9,
            })
        return assignments

    # ------------------------------------------------------------------
    def parse_freeform_lines(self, lines: list[str]) -> dict:
        """Freie Datenzeilen verstehen (Beispiel aus der Anforderung)."""
        result: dict[str, str] = {}
        leftovers: list[str] = []
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            email = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", line)
            if email:
                result["email"] = email.group(0)
                continue
            if re.match(r"^[A-Z]{2}\d{2}[ ]?[A-Z0-9]{4,}$",
                        line.replace(" ", ""), re.I):
                result["iban"] = line
                continue
            m = re.match(r"^(\d{1,2}[./]\d{1,2}[./]\d{2,4})$", line)
            if m:
                result["geburtsdatum"] = m.group(1)
                continue
            m = re.match(r"^([\d+()][\d ()/-]{4,})$", line)
            if m and sum(c.isdigit() for c in line) >= 6:
                result.setdefault("telefon", line)
                continue
            m = re.match(r"^(\d{5})\s+(.+)$", line)
            if m:
                result["plz"] = m.group(1)
                result["ort"] = m.group(2)
                continue
            m = re.match(r"^(.*?(?:straße|strasse|str\.|weg|allee|gasse|platz|ring)\.?)\s+(\d+\s*[a-zA-Z]?)$",
                         line, re.I)
            if m:
                result["strasse"] = m.group(1).strip()
                result["hausnummer"] = m.group(2).strip()
                continue
            leftovers.append(line)
        for line in leftovers:
            tokens = line.split()
            # Stoppliste: typische Dokument-Überschriften/-floskeln
            stop = {"antrag", "wohngeld", "kostenübersicht", "anmeldeformular",
                    "personenbogen", "anlage", "nachweise", "erklaerungen",
                    "erklaerung", "seite", "rechnung", "vertrag", "formular",
                    "mitteilung", "bescheid", "zeugnis", "lebenslauf"}
            if tokens and tokens[0].lower().rstrip(",.:") in stop:
                continue
            if len(tokens) == 1 and tokens[0].isalpha():
                if not result.get("vorname"):
                    result["vorname"] = tokens[0].rstrip(",.:")
                elif not result.get("nachname"):
                    result["nachname"] = tokens[0].rstrip(",.:")
            elif len(tokens) == 2 and all(t.isalpha() for t in tokens):
                result.setdefault("vorname", tokens[0].rstrip(",.:"))
                result["nachname"] = tokens[1].rstrip(",.:")
        return result


def split_street_number(value: str) -> tuple[str, str]:
    m = re.match(r"^(.+?)\s+(\d+\s*[a-zA-Z]?)$", value.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return value.strip(), ""


def split_plz_ort(value: str) -> tuple[str, str]:
    m = re.match(r"^(\d{5})\s+(.+)$", value.strip())
    if m:
        return m.group(1), m.group(2).strip()
    return "", value.strip()


# --------------------------------------------------------------- LLM-Teil
def _is_local_url(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0") or \
        host.endswith(".local")


class LlmConnector:
    """Minimaler Client für Ollama / OpenAI-kompatible lokale Server."""

    def __init__(self, basis_url: str, modell: str,
                 anbieter: str = "ollama", api_schluessel: str = "",
                 extern_erlaubt: bool = False, timeout: int = 90):
        self.basis_url = basis_url.rstrip("/")
        self.modell = modell
        self.anbieter = anbieter
        self.api_schluessel = api_schluessel
        self.extern_erlaubt = extern_erlaubt
        self.timeout = timeout

    def _check_privacy(self) -> None:
        if not _is_local_url(self.basis_url) and not self.extern_erlaubt:
            raise PermissionError(
                "Externe Verarbeitung nicht erlaubt: Der konfigurierte "
                "KI-Server ist nicht lokal. Bitte ausdrücklich zustimmen "
                "(Datenschutz) oder einen lokalen Server verwenden.")

    def chat_json(self, system: str, user: str) -> dict:
        self._check_privacy()
        if self.anbieter == "ollama":
            url = f"{self.basis_url}/api/chat"
            payload = {"model": self.modell, "stream": False,
                       "format": "json",
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}
            headers = {"Content-Type": "application/json"}
        else:                                   # OpenAI-kompatibel (LM Studio …)
            url = f"{self.basis_url}/v1/chat/completions"
            payload = {"model": self.modell, "stream": False,
                       "messages": [{"role": "system", "content": system},
                                    {"role": "user", "content": user}]}
            headers = {"Content-Type": "application/json"}
            if self.api_schluessel:
                headers["Authorization"] = f"Bearer {self.api_schluessel}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if self.anbieter == "ollama":
            content = body.get("message", {}).get("content", "{}")
        else:
            content = body["choices"][0]["message"]["content"]
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start, end = content.find("{"), content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start:end + 1])
            raise

    @staticmethod
    def reachable(basis_url: str, timeout: float = 2.0) -> bool:
        try:
            parsed = urllib.parse.urlparse(basis_url)
            with socket.create_connection((parsed.hostname or "localhost",
                                           parsed.port or (443 if
                                                           parsed.scheme ==
                                                           "https" else 80)),
                                          timeout=timeout):
                return True
        except Exception:
            return False


class LlmSemanticAnalyzer:
    """Optionale lokale KI – nur aktiv, wenn konfiguriert und erreichbar."""
    name = "KI-Semantik (lokal, optional)"
    priority = 50

    def __init__(self):
        self._fallback = RuleSemanticAnalyzer()
        self._connector: Optional[LlmConnector] = None

    @staticmethod
    def is_available() -> bool:
        settings = config.get("ki.aktiv", False)
        if not settings:
            return False
        url = config.get("ki.basis_url", "http://localhost:11434")
        return LlmConnector.reachable(url)

    def _conn(self) -> LlmConnector:
        if self._connector is None:
            self._connector = LlmConnector(
                basis_url=config.get("ki.basis_url",
                                     "http://localhost:11434"),
                modell=config.get("ki.modell", "llama3.1"),
                anbieter=config.get("ki.anbieter", "ollama"),
                api_schluessel=config.get("ki.api_schluessel", ""),
                extern_erlaubt=config.get("ki.extern_erlaubt", False))
        return self._connector

    def classify(self, fields: list[FieldModel]) -> None:
        self._fallback.classify(fields)          # Regelbasis zuerst
        try:
            conn = self._conn()
            labels = {f.id: (f.label or f.name) for f in fields
                      if not f.canonical}
            if not labels:
                return
            mapping = conn.chat_json(
                "Du ordnest Formularbeschriftungen kanonischen Feldern zu. "
                "Antworte nur JSON: {\"<id>\": \"<kanonisch>\"}. Kanonische "
                "Felder: " + ", ".join(sorted(CANONICAL_FIELDS)),
                json.dumps(labels, ensure_ascii=False))
            for f in fields:
                canon = mapping.get(f.id)
                if canon and normalize(canon) in CANONICAL_FIELDS:
                    f.canonical = normalize(canon)
        except Exception:
            pass                                  # lokal weiterarbeiten

    def match_profile(self, fields: list[FieldModel],
                      profile: dict) -> list[dict]:
        base = self._fallback.match_profile(fields, profile)
        if base:
            return base
        try:
            conn = self._conn()
            ask = [{"id": f.id, "beschriftung": f.label or f.name,
                    "kanonisch": f.canonical} for f in fields]
            mapping = conn.chat_json(
                "Ordne Profildaten den Formularfeldern zu. Antworte nur "
                "JSON: {\"<id>\": \"<wert>\"}.",
                json.dumps({"felder": ask, "profil": profile},
                           ensure_ascii=False))
            out = []
            for f in fields:
                if f.id in mapping:
                    out.append({"feld_id": f.id, "feld": f.label or f.name,
                                "canonical": f.canonical,
                                "wert": str(mapping[f.id]),
                                "konfidenz": 0.75,
                                "grund": "KI-Zuordnung (lokal)",
                                "pruefen": True})
            return out
        except Exception:
            return []
