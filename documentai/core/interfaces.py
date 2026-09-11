"""Austauschbare Schnittstellen (Architekturprinzip: keine Monolithen).

Jede wichtige Funktion ist ueber eine Schnittstelle ersetztbar:
IPdfEngine, IOcrEngine, IDocumentParser, IFieldDetector,
ISemanticAnalyzer, IFormEngine, ISignatureAnalyzer,
IValidationEngine, IExportEngine.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from .models import DocumentModel, FieldModel, Issue, PageModel


class IPdfEngine(ABC):
    """PDF oeffnen, rendern, diagnostizieren, acroformfelder, speichern."""

    name = "pdf-basis"
    priority = 0          # hoeher = besser; Registry waehlt Verfuegbaren mit max

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        """Kann diese Engine im aktuellen System laufen?"""

    @abstractmethod
    def open(self, path: str, password: Optional[str] = None) -> Any:
        """Oeffnet eine PDF-Sitzung. Wirft PasswordRequiredError/Damaged."""

    @abstractmethod
    def diagnose(self, session: Any) -> dict:
        """Vollstaendige PDF-Diagnose als dict (siehe models._default_diagnosis)."""

    @abstractmethod
    def extract_pages(self, session: Any, ocr_engine: "Optional[IOcrEngine]" = None,
                      progress=None) -> list[PageModel]:
        """Seiten mit Woertern/Positionen; OCR wenn noetig und verfuegbar."""

    @abstractmethod
    def get_acroform_fields(self, session: Any) -> list[FieldModel]:
        """Echte PDF-Formularfelder inkl. Typ, Pflicht, Optionen."""

    @abstractmethod
    def render_page(self, session: Any, page: int, dpi: int = 150) -> bytes:
        """Seite als PNG-Bytes rendern."""

    @abstractmethod
    def find_tables(self, session: Any) -> list:
        """Tabellenerkennung; liefert TableData-Objekte."""

    @abstractmethod
    def fill_fields(self, session: Any, assignments: dict[str, Any]) -> dict:
        """Werte in Felder schreiben (AcroForm + Overlay). Gibt Ergebnisdict."""

    @abstractmethod
    def save_version(self, session: Any, model: DocumentModel,
                     reason: str = "bearbeitet") -> str:
        """Neue Version erzeugen – Original bleibt unangetastet."""


class IOcrEngine(ABC):
    name = "ocr-basis"
    priority = 0

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        ...

    @abstractmethod
    def ocr_page(self, png_bytes: bytes, language: str = "deu+eng") -> list:
        """Woerter mit Position + Konfidenz aus einem Seitenbild (PNG)."""


class IDocumentParser(ABC):
    """Importeur fuer Nicht-PDF-Formate (DOCX, TXT, RTF, XLSX, Bild...)."""
    name = "parser-basis"
    extensions: tuple[str, ...] = ()

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        ...

    @abstractmethod
    def parse(self, path: str) -> DocumentModel:
        ...


class IFieldDetector(ABC):
    """Visuelle/semantische Felderkennung (Unterstriche, Kaestchen, Linien)."""
    name = "detektor-basis"
    priority = 0

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        ...

    @abstractmethod
    def detect(self, model: DocumentModel, session: Any = None) -> list[FieldModel]:
        ...


class ISemanticAnalyzer(ABC):
    """Semantik: Labels verstehen, Daten zuordnen, Synonyme (DE/EN)."""
    name = "semantik-basis"
    priority = 0

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        ...

    @abstractmethod
    def classify(self, fields: list[FieldModel]) -> None:
        """Setzt field.canonical + Konfidenz inplace."""

    @abstractmethod
    def match_profile(self, fields: list[FieldModel],
                      profile: dict) -> list[dict]:
        """Ordnet Profildaten Feldern zu → Zuordnungen mit Konfidenz."""


class IFormEngine(ABC):
    name = "form-basis"

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        ...

    @abstractmethod
    def fill_document(self, session: Any, model: DocumentModel,
                      assignments: list[dict], confirm: bool = True) -> dict:
        """Felder befuellen mit Benutzerpruefung (confirm-Callback via model)."""


class ISignatureAnalyzer(ABC):
    name = "signatur-basis"

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        ...

    @abstractmethod
    def analyze(self, session: Any, model: DocumentModel) -> dict:
        """Signaturen, Zertifikatinfos, Zeitpunkte, Integritaetsstatus."""


class IValidationEngine(ABC):
    name = "validierung-basis"

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        ...

    @abstractmethod
    def validate(self, model: DocumentModel, session: Any = None) -> list[Issue]:
        ...


class IExportEngine(ABC):
    name = "export-basis"

    @staticmethod
    @abstractmethod
    def is_available() -> bool:
        ...

    @abstractmethod
    def export(self, model: DocumentModel, session: Any, fmt: str,
               dest: str) -> dict:
        """Export + Verifikation des Ergebnisses."""
