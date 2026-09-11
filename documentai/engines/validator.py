"""Validierungs-Engine: aktiv nach Fehlern suchen, Autokorrektur anbieten."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from ..core.models import DocumentModel, FieldModel, Issue

try:
    import pymupdf
    PYMUPDF_OK = True
except Exception:
    PYMUPDF_OK = False

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
PLZ_RE = re.compile(r"^\d{5}$")
PHONE_RE = re.compile(r"^[0-9+()/\s-]{6,}$")
DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")
NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")

IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{10,30}$")


def iban_checksum_ok(iban: str) -> bool:
    """Prüfsummenprüfung (mod 97) nach ISO 13616."""
    compact = re.sub(r"[\s-]", "", iban or "").upper()
    if not IBAN_RE.match(compact):
        return False
    rearranged = compact[4:] + compact[:4]
    digits = "".join(str(int(c, 36)) for c in rearranged)
    return int(digits) % 97 == 1


def parse_date(value: str):
    """Versucht, ein Datum in bekannten Formaten zu lesen."""
    import datetime
    v = (value or "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.datetime.strptime(v, fmt), fmt
        except ValueError:
            continue
    return None, None


class Validator:
    name = "Validierungs-Engine"
    priority = 100

    @staticmethod
    def is_available() -> bool:
        return True

    # ------------------------------------------------------------------
    def validate(self, model: DocumentModel, session: Any = None) -> list[Issue]:
        issues: list[Issue] = []
        for f in model.fields:
            self._check_field(f, issues)
        self._check_duplicates(model, issues)
        self._check_document(model, issues)
        if session is not None:
            self._check_tables(model, session, issues)
        return issues

    # ------------------------------------------------------------------
    def _check_field(self, f: FieldModel, issues: list[Issue]) -> None:
        value = f.value
        text = "" if value is None else str(value).strip()

        if f.required and (value is None or text == ""):
            issues.append(Issue(
                "fehler", "PFLICHT_FEHLT",
                f'Pflichtfeld "{f.label or f.name}" ist nicht ausgefüllt.',
                field_id=f.id,
                suggestion="Feld befüllen (z. B. über Profildaten)."))
            return
        if not text:
            return

        if f.field_type == "email" or (f.canonical == "email"):
            if not EMAIL_RE.match(text):
                issues.append(Issue(
                    "fehler", "EMAIL_UNGUELTIG",
                    f'Ungültige E-Mail-Adresse in "{f.label or f.name}": '
                    f"{text}", field_id=f.id,
                    suggestion="E-Mail-Adresse korrigieren."))
        elif f.field_type == "plz" or f.canonical == "plz":
            if not PLZ_RE.match(text):
                issues.append(Issue(
                    "fehler", "PLZ_UNGUELTIG",
                    f'Ungültige Postleitzahl in "{f.label or f.name}": '
                    f"{text}", field_id=f.id,
                    suggestion="5-stellige PLZ angeben."))
        elif f.field_type == "iban" or f.canonical == "iban":
            compact = re.sub(r"[\s-]", "", text)
            if not IBAN_RE.match(compact.upper()):
                issues.append(Issue(
                    "fehler", "IBAN_FORMAT",
                    f'IBAN-Format ungültig in "{f.label or f.name}".',
                    field_id=f.id))
            elif not iban_checksum_ok(compact):
                issues.append(Issue(
                    "fehler", "IBAN_PRUEFSUMME",
                    f'IBAN-Prüfsumme falsch in "{f.label or f.name}": {text}',
                    field_id=f.id,
                    suggestion="IBAN auf Tippfehler prüfen."))
            elif compact != text:
                issues.append(Issue(
                    "hinweis", "IBAN_LEERZEICHEN",
                    f'IBAN in "{f.label or f.name}" enthält Leerzeichen.',
                    field_id=f.id, auto_fix="iban_normalisieren"))
        elif f.field_type == "datum" or f.canonical in ("geburtsdatum",
                                                        "datum"):
            dt, fmt = parse_date(text)
            if dt is None:
                issues.append(Issue(
                    "fehler", "DATUM_FORMAT",
                    f'Ungültiges Datumsformat in "{f.label or f.name}": '
                    f"{text} (erwartet TT.MM.JJJJ)", field_id=f.id,
                    suggestion="Format TT.MM.JJJJ verwenden.",
                    auto_fix="datum_normalisieren" if _partial_date(text)
                    else ""))
            else:
                issues.extend(self._date_plausibility(f, dt, text))
                if fmt != "%d.%m.%Y":
                    issues.append(Issue(
                        "hinweis", "DATUM_FORMAT",
                        f'Ungewöhnliches Datumsformat in '
                        f'"{f.label or f.name}": {text} '
                        f"({fmt}) – TT.MM.JJJJ empfohlen.", field_id=f.id,
                        suggestion="Auf TT.MM.JJJJ normalisieren.",
                        auto_fix="datum_normalisieren"))
        elif f.field_type == "telefon":
            if not PHONE_RE.match(text):
                issues.append(Issue(
                    "warnung", "TELEFON_FORMAT",
                    f'Ungewöhnliche Telefonnummer in "{f.label or f.name}": '
                    f"{text}", field_id=f.id))
        elif f.field_type == "zahl":
            if not NUM_RE.match(text.replace("€", "").strip()):
                issues.append(Issue(
                    "fehler", "ZAHL_FORMAT",
                    f'Keine gültige Zahl in "{f.label or f.name}": {text}',
                    field_id=f.id))

        # Textüberlauf abschätzen
        if f.rect and PYMUPDF_OK and f.field_type not in ("checkbox",
                                                          "signatur"):
            try:
                fs = f.font_size or 10.0
                width = pymupdf.get_text_length(text, fontname="helv",
                                                fontsize=fs)
                if width > (f.rect.width - 2) * 1.02:
                    issues.append(Issue(
                        "warnung", "TEXT_ZU_LANG",
                        f'Text überschreitet das erkannte Feld '
                        f'"{f.label or f.name}" '
                        f"({int(width)}pt > {int(f.rect.width)}pt).",
                        field_id=f.id,
                        suggestion="Schrift verkleinern oder Text kürzen.",
                        auto_fix="schrift_verkleinern"))
            except Exception:
                pass
        if f.max_len and len(text) > f.max_len:
            issues.append(Issue(
                "fehler", "TEXT_MAXLEN",
                f'Text in "{f.label or f.name}" länger als '
                f"Maximallänge {f.max_len}.", field_id=f.id))

    @staticmethod
    def _date_plausibility(f: FieldModel, dt, text: str) -> list[Issue]:
        import datetime
        issues: list[Issue] = []
        today = datetime.date.today()
        if f.canonical == "geburtsdatum":
            if dt.year < 1900 or dt.date() > today:
                issues.append(Issue(
                    "fehler", "DATUM_UNPLAUSIBEL",
                    f'Widersprüchliches Geburtsdatum "{text}": liegt in '
                    "der Zukunft oder vor 1900.", field_id=f.id))
        elif dt.date() > today + datetime.timedelta(days=1) and \
                "gültig" not in (f.label or "").lower() and "bis" not in \
                (f.label or "").lower():
            issues.append(Issue(
                "hinweis", "DATUM_ZUKUNFT",
                f'Datum "{text}" in "{f.label or f.name}" liegt in der '
                "Zukunft – bitte prüfen.", field_id=f.id))
        return issues

    # ------------------------------------------------------------------
    @staticmethod
    def _check_duplicates(model: DocumentModel, issues: list[Issue]) -> None:
        by_value: dict[str, list[FieldModel]] = {}
        for f in model.fields:
            if f.value and f.canonical:
                by_value.setdefault(str(f.value).strip().lower(), []).append(f)
        for value, fields in by_value.items():
            canons = {f.canonical for f in fields}
            if len(fields) > 1 and len(canons) > 1 and \
                    canons & {"vorname", "nachname", "strasse", "ort", "plz"}:
                issues.append(Issue(
                    "warnung", "MOEGLICHE_FEHLZUORDNUNG",
                    f'Derselbe Wert "{value[:30]}" in semantisch '
                    "unterschiedlichen Feldern "
                    f"({', '.join(sorted(canons))}) – Zuordnung prüfen.",
                    field_id=fields[0].id,
                    suggestion="Feldzuordnung manuell korrigieren."))

    # ------------------------------------------------------------------
    def _check_document(self, model: DocumentModel, issues: list[Issue]) -> None:
        d = model.diagnosis
        for warn in d.get("warnungen", []):
            issues.append(Issue("warnung", "STRUKTUR", warn))
        for dmg in d.get("beschaedigte_objekte", []):
            issues.append(Issue("warnung", "BESCHAEDIGT",
                                f"Beschädigtes/inkonsistentes Objekt: {dmg}"))
        if model.ocr_used:
            low = [p for p in model.pages if p.low_confidence]
            if low:
                issues.append(Issue(
                    "hinweis", "OCR_KONFIDENZ",
                    f"OCR-Konfidenz niedrig auf {len(low)} Seite(n) "
                    f"(z. B. Seite {low[0].number + 1}) – Ergebnisse prüfen."))
        for p in model.pages:
            if p.needs_ocr and not p.ocr_applied:
                issues.append(Issue(
                    "warnung", "OCR_FEHLT",
                    f"Seite {p.number + 1}: kein Text – OCR erforderlich "
                    "und nicht verfügbar/ausgeführt."))
                break

    # ------------------------------------------------------------------
    @staticmethod
    def _check_tables(model: DocumentModel, session: Any,
                      issues: list[Issue]) -> None:
        """Rechenfehler in Tabellen erkennen (Menge × Preis ≠ Summe)."""
        try:
            from .pdf_mupdf import MuPdfEngine
            tables = MuPdfEngine().find_tables(session)
        except Exception:
            return
        for tab in tables:
            header = [(h or "").lower() for h in tab.header]
            qty_idx = _find(header, ("menge", "anzahl", "qty", "quantity"))
            price_idx = _find(header, ("einzelpreis", "preis", "price", "unit"))
            sum_idx = _find(header, ("gesamt", "summe", "betrag", "total",
                                     "amount"))
            if qty_idx is None or price_idx is None or sum_idx is None:
                continue
            total = Decimal(0)
            for row in tab.rows:
                try:
                    qty = _to_decimal(row[qty_idx])
                    price = _to_decimal(row[price_idx])
                    rowsum = _to_decimal(row[sum_idx])
                except (IndexError, InvalidOperation):
                    continue
                if rowsum is None:
                    continue
                label = " ".join(str(c) for c in row if c).lower()
                if any(k in label for k in ("summe", "gesamt", "total")):
                    if abs(total - rowsum) > Decimal("0.05"):
                        issues.append(Issue(
                            "fehler", "RECHENFEHLER",
                            f"Tabellen-Summe falsch: berechnet "
                            f"{_fmt(total)} ≠ angegeben {_fmt(rowsum)} "
                            f"(Seite {tab.page + 1}).",
                            suggestion="Summe korrigieren."))
                    break
                if qty is not None and price is not None and \
                        abs(qty * price - rowsum) > Decimal("0.05"):
                    issues.append(Issue(
                        "fehler", "RECHENFEHLER",
                        f"Zeilenrechnung falsch (Seite {tab.page + 1}): "
                        f"{qty} × {_fmt(price)} ≠ {_fmt(rowsum)}.",
                        suggestion="Werte prüfen."))
                if qty is not None and price is not None:
                    total += qty * price
                else:
                    total += rowsum

    # ------------------------------------------------------------------
    def autofix(self, issue: Issue, model: DocumentModel) -> bool:
        """Führt eine automatische Korrektur aus (True bei Erfolg)."""
        f = model.field_by_id(issue.field_id)
        if not f or not issue.auto_fix:
            return False
        if issue.auto_fix == "datum_normalisieren" and f.value:
            dt, _ = parse_date(str(f.value))
            if dt:
                f.value = dt.strftime("%d.%m.%Y")
                return True
        if issue.auto_fix == "schrift_verkleinern" and f.rect and PYMUPDF_OK:
            text = str(f.value or "")
            fs = f.font_size or 10.0
            while fs > 4.0 and pymupdf.get_text_length(
                    text, fontname="helv", fontsize=fs) > f.rect.width - 2:
                fs -= 0.5
            if fs != (f.font_size or 10.0):
                f.font_size = fs
                return True
        if issue.auto_fix == "iban_normalisieren" and f.value:
            f.value = re.sub(r"[\s-]", "", str(f.value)).upper()
            return True
        return False


def _partial_date(text: str) -> bool:
    return bool(re.search(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", text or ""))


def _find(header: list[str], keys: tuple) -> Optional[int]:
    for i, h in enumerate(header):
        for k in keys:
            if k in h:
                return i
    return None


def _to_decimal(cell: str) -> Optional[Decimal]:
    if cell is None:
        return None
    cleaned = str(cell).replace("€", "").replace(",", ".").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def _fmt(value: Decimal) -> str:
    return f"{value:.2f}".replace(".", ",")
