"""Datenmodelle der Dokumentenintelligenz-Schicht."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------- Rechteck
@dataclass
class Rect4:
    """Position in PDF-Punkten (Ursprung oben links, y nach unten)."""
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    def to_list(self) -> list[float]:
        return [round(self.x, 2), round(self.y, 2),
                round(self.width, 2), round(self.height, 2)]

    def contains(self, px: float, py: float, pad: float = 3.0) -> bool:
        return (self.x - pad <= px <= self.x + self.width + pad
                and self.y - pad <= py <= self.y + self.height + pad)

    @classmethod
    def from_xy0xy1(cls, x0: float, y0: float, x1: float, y1: float) -> "Rect4":
        return cls(x=x0, y=y0, width=max(0.0, x1 - x0), height=max(0.0, y1 - y0))


# ---------------------------------------------------------------- Woerter
@dataclass
class Word:
    text: str
    rect: Rect4
    block: int = 0
    line: int = 0
    confidence: float = 100.0   # 100 = Originaltext (kein OCR)

    def to_dict(self) -> dict:
        return {"text": self.text, "rect": self.rect.to_list(),
                "konfidenz": round(self.confidence, 1)}


# ---------------------------------------------------------------- Felder
FIELD_TYPES = {"text", "datum", "zahl", "email", "telefon", "plz", "iban",
               "checkbox", "radio", "dropdown", "signatur", "bereich"}


@dataclass
class FieldModel:
    """Ein erkanntes Feld – egal ob AcroForm, visuell erkannt oder OCR."""
    id: str
    name: str                       # technischer Name (AcroForm) oder generiert
    label: str = ""                 # sichtbare Beschriftung im Dokument
    field_type: str = "text"
    required: bool = False
    value: Any = None
    original_value: Any = None
    page: int = 0                   # 0-basiert
    rect: Optional[Rect4] = None
    source: str = "acroform"        # acroform | visuell | ocr
    confidence: float = 0.9
    canonical: str = ""             # semantischer Schluessel, z. B. 'geburtsdatum'
    options: list[str] = field(default_factory=list)   # dropdown/radio
    read_only: bool = False
    max_len: Optional[int] = None
    font_size: float = 0.0          # 0 = automatisch
    notes: str = ""
    # Tinte-BoundingBox (Handschrift/Eintrag im Scan) innerhalb des
    # Feldrechtecks – Grundlage der pixelgenauen Ersetzung bei Korrektur
    tinte_rect: Optional[Rect4] = None
    # Geometrie der Feldlinie (Scan): y0=Oberkante, y1=Unterkante.
    # 0 = keine Linie (Kasten/AcroForm). Schützt bei der Ersetzung.
    linie_y0: float = 0.0
    linie_y1: float = 0.0

    def to_dict(self) -> dict:
        return {
            "feld": self.name,
            "beschriftung": self.label,
            "typ": self.field_type,
            "pflicht": self.required,
            "wert": self.value,
            "seite": self.page + 1,
            "position": self.rect.to_list() if self.rect else None,
            "quelle": self.source,
            "konfidenz_prozent": round(self.confidence * 100, 1),
            "semantik": self.canonical or None,
            "optionen": self.options or None,
            "schreibgeschuetzt": self.read_only or None,
        }


# ---------------------------------------------------------------- Seiten
@dataclass
class PageModel:
    number: int                     # 0-basiert
    width: float = 595.0
    height: float = 842.0
    words: list[Word] = field(default_factory=list)
    text: str = ""
    image_count: int = 0
    drawing_count: int = 0
    needs_ocr: bool = False
    ocr_applied: bool = False
    ocr_integriert: bool = False    # OCR lief über MuPDFs Tesseract-Engine
    low_confidence: bool = False    # OCR-Konfidenz unter Schwelle

    def to_dict(self) -> dict:
        return {"seite": self.number + 1, "breite": round(self.width, 1),
                "hoehe": round(self.height, 1),
                "woerter": len(self.words), "bilder": self.image_count,
                "grafiken": self.drawing_count,
                "ocr_noetig": self.needs_ocr, "ocr_angewandt": self.ocr_applied}


# ---------------------------------------------------------------- Tabellen
@dataclass
class TableData:
    page: int
    bbox: Rect4
    header: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    # Zell-Rechtecke (PDF-Punkte) – Grundlage für Felder in Tabellen
    zellen: list[Rect4] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"seite": self.page + 1, "position": self.bbox.to_list(),
                "kopfzeile": self.header, "zeilen": self.rows}


# ---------------------------------------------------------------- Probleme
@dataclass
class Issue:
    severity: str                   # fehler | warnung | hinweis
    code: str
    message: str
    field_id: str = ""
    suggestion: str = ""
    auto_fix: str = ""              # Kennung einer moeglichen Autokorrektur

    def to_dict(self) -> dict:
        return {"schwere": self.severity, "code": self.code,
                "meldung": self.message, "feld": self.field_id or None,
                "vorschlag": self.suggestion or None,
                "autokorrektur": self.auto_fix or None}


# ---------------------------------------------------------------- Audit
@dataclass
class AuditEntry:
    timestamp: str
    action: str
    details: str = ""

    def to_dict(self) -> dict:
        return {"zeit": self.timestamp, "aktion": self.action,
                "details": self.details}


# ---------------------------------------------------------------- Diagnose
def _default_diagnosis() -> dict:
    return {
        "format": "unbekannt",
        "pdf_version": "",
        "seiten": 0,
        "text_vorhanden": False,
        "vektorgrafiken": False,
        "bilder": False,
        "ocr_noetig": False,
        "formularfelder": 0,
        "pflichtfelder": 0,
        "annotationen": 0,
        "checkboxen": 0,
        "signaturen": 0,
        "verschluesselt": False,
        "passwort_erforderlich": False,
        "bearbeitung_erlaubt": True,
        "drucken_erlaubt": True,
        "kopieren_erlaubt": True,
        "metadaten": {},
        "eingebettete_dateien": [],
        "pdfa_status": "nicht erkannt",
        "beschaedigte_objekte": [],
        "warnungen": [],
        "repariert": False,
    }


# ---------------------------------------------------------------- Dokument
@dataclass
class DocumentModel:
    path: str
    name: str = ""
    sha256: str = ""
    source_format: str = "pdf"      # pdf | docx | txt | rtf | xlsx | bild
    pages: list[PageModel] = field(default_factory=list)
    fields: list[FieldModel] = field(default_factory=list)
    tables: list[TableData] = field(default_factory=list)
    diagnosis: dict = field(default_factory=_default_diagnosis)
    issues: list[Issue] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)
    ocr_used: bool = False
    signature_info: dict = field(default_factory=dict)
    version: int = 1                # Versionszaehler der Arbeitskopie
    edited: bool = False

    def __post_init__(self) -> None:
        if not self.name:
            self.name = os.path.basename(self.path)
        if self.path and os.path.exists(self.path):
            try:
                self.sha256 = file_sha256(self.path)
            except OSError:
                self.sha256 = ""

    # -- Komfort -----------------------------------------------
    def field_by_id(self, field_id: str) -> Optional[FieldModel]:
        for f in self.fields:
            if f.id == field_id:
                return f
        return None

    def summary_lines(self) -> list[str]:
        """Kurzfassung fuer Statusleiste/Konsole."""
        d = self.diagnosis
        lines = []
        icon = "✓" if True else "✓"
        lines.append(f"{icon} Analyse: {d.get('format', '?')}, "
                     f"{d.get('seiten', 0)} Seiten")
        lines.append("✓ Text erkannt" if d.get("text_vorhanden")
                     else "⚠ Kein Text – OCR erforderlich")
        if d.get("formularfelder"):
            lines.append(f"✓ {d['formularfelder']} Formularfelder, "
                         f"davon {d.get('pflichtfelder', 0)} Pflichtfelder")
        if d.get("checkboxen"):
            lines.append(f"✓ {d['checkboxen']} Checkboxen")
        if d.get("signaturen"):
            lines.append(f"⚠ {d['signaturen']} Signatur(en) erkannt – "
                         "Änderungen können die Signatur ungültig machen")
        if d.get("verschluesselt"):
            lines.append("⚠ Dokument ist verschlüsselt")
        return lines

    def issue_counts(self) -> dict:
        out = {"fehler": 0, "warnung": 0, "hinweis": 0}
        for issue in self.issues:
            out[issue.severity] = out.get(issue.severity, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "datei": self.name,
            "pfad": self.path,
            "sha256": self.sha256,
            "format": self.source_format,
            "version": self.version,
            "diagnose": self.diagnosis,
            "seiten": [p.to_dict() for p in self.pages],
            "felder": [f.to_dict() for f in self.fields],
            "tabellen": [t.to_dict() for t in self.tables],
            "probleme": [i.to_dict() for i in self.issues],
            "audit": [a.to_dict() for a in self.audit],
            "ocr_verwendet": self.ocr_used,
            "signaturen": self.signature_info or None,
        }


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()
