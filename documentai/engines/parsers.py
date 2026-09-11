"""Importeure für DOCX, TXT, RTF, XLSX und Bilddateien.

Nicht vorhandene optionale Bibliotheken führen nicht zum Abbruch:
der Parser meldet sich als nicht verfügbar und die Registry wählt
die nächste Implementierung bzw. meldet das Format klar.
"""
from __future__ import annotations

import os

from ..core import audit
from ..core.errors import DocumentDamagedError
from ..core.models import DocumentModel, PageModel, Rect4, Word


class _BaseParser:
    extensions: tuple[str, ...] = ()

    @staticmethod
    def is_available() -> bool:
        return True

    def parse(self, path: str) -> DocumentModel:
        raise NotImplementedError

    def _base(self, path: str, fmt: str) -> DocumentModel:
        model = DocumentModel(path=path, source_format=fmt)
        audit.log(model, "Dokument geöffnet", fmt)
        return model


class TxtParser(_BaseParser):
    name = "Text-Importer"
    extensions = (".txt", ".md", ".log", ".csv")

    def parse(self, path: str) -> DocumentModel:
        model = self._base(path, "txt")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError as exc:
            raise DocumentDamagedError(str(exc)) from exc
        lines = text.splitlines() or [""]
        page = PageModel(number=0)
        for i, line in enumerate(lines[:5000]):
            page.words.append(Word(text=line, rect=Rect4(0, i * 12,
                                                         min(len(line) * 6, 500),
                                                         12 + i * 12)))
        page.text = text
        model.pages = [page]
        model.diagnosis.update({
            "format": "Text", "seiten": 1, "text_vorhanden": True,
            "bearbeitung_erlaubt": True, "drucken_erlaubt": True,
            "kopieren_erlaubt": True})
        return model


class DocxParser(_BaseParser):
    name = "Word-Importer"
    extensions = (".docx",)

    @staticmethod
    def is_available() -> bool:
        try:
            import docx  # noqa: F401
            return True
        except Exception:
            return False

    def parse(self, path: str) -> DocumentModel:
        try:
            import docx
        except ImportError as exc:
            from ..core.errors import DocumentAIError
            if any(w in str(exc).lower() for w in (
                    "blockiert", "blocked", "steuerungsrichtlinie",
                    "app control")):
                raise DocumentAIError(
                    "Word-Import ist auf diesem PC durch eine Windows-"
                    "Sicherheitsrichtlinie (z. B. Smart App Control) "
                    "blockiert. Freigabe: Einstellungen > Datenschutz "
                    "und Sicherheit > Windows-Sicherheit > App- und "
                    "Browsersteuerung > Smart App Control > „Aus“.")
            raise DocumentAIError(
                f"python-docx nicht verfügbar ({exc})") from exc
        model = self._base(path, "docx")
        try:
            d = docx.Document(path)
        except Exception as exc:
            raise DocumentDamagedError(str(exc)) from exc
        page = PageModel(number=0)
        words: list[Word] = []
        y = 0.0

        def _emit_block(block_items):
            nonlocal y
            for kind, item in block_items:
                if kind == "p":
                    text = item.text
                    if text.strip():
                        words.append(Word(text=text, rect=Rect4(0, y,
                                                                len(text) * 5.5,
                                                                y + 12)))
                        y += 14
                elif kind == "tbl":
                    for row in item.rows:
                        cells = [c.text.strip() for c in row.cells]
                        words.append(Word(text=" | ".join(cells),
                                          rect=Rect4(0, y, 300, y + 12)))
                        y += 14

        def _iter_blocks(parent):
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            for child in parent.element.body.iterchildren():
                if child.tag.endswith("}p"):
                    yield "p", Paragraph(child, parent)
                elif child.tag.endswith("}tbl"):
                    yield "tbl", Table(child, parent)

        _emit_block(list(_iter_blocks(d)))
        page.words = words
        page.text = "\n".join(w.text for w in words)
        model.pages = [page]
        model.diagnosis.update({"format": "DOCX", "seiten": 1,
                                "text_vorhanden": True})
        meta = {}
        for key in ("title", "author", "created", "modified"):
            try:
                value = getattr(d.core_properties, key, None)
                if value:
                    meta[key] = str(value)
            except Exception:
                pass
        model.diagnosis["metadaten"] = meta
        return model


class RtfParser(_BaseParser):
    name = "RTF-Importer"
    extensions = (".rtf",)

    @staticmethod
    def is_available() -> bool:
        try:
            import striprtf  # noqa: F401
            return True
        except Exception:
            return False

    def parse(self, path: str) -> DocumentModel:
        from striprtf.striprtf import rtf_to_text
        model = self._base(path, "rtf")
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                rtf = fh.read()
            text = rtf_to_text(rtf)
        except Exception as exc:
            raise DocumentDamagedError(str(exc)) from exc
        page = PageModel(number=0)
        for i, line in enumerate(text.splitlines()[:3000]):
            page.words.append(Word(text=line,
                                   rect=Rect4(0, i * 12, 300, 12 + i * 12)))
        page.text = text
        model.pages = [page]
        model.diagnosis.update({"format": "RTF", "seiten": 1,
                                "text_vorhanden": True})
        return model


class XlsxParser(_BaseParser):
    name = "Excel-Importer"
    extensions = (".xlsx",)

    @staticmethod
    def is_available() -> bool:
        try:
            import openpyxl  # noqa: F401
            return True
        except Exception:
            return False

    def parse(self, path: str) -> DocumentModel:
        from openpyxl import load_workbook
        model = self._base(path, "xlsx")
        try:
            wb = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            raise DocumentDamagedError(str(exc)) from exc
        pages: list[PageModel] = []
        for pi, ws in enumerate(wb.worksheets):
            page = PageModel(number=pi)
            lines = []
            for row in ws.iter_rows(values_only=True):
                cells = ["" if c is None else str(c) for c in row]
                if any(c.strip() for c in cells):
                    lines.append(" | ".join(cells))
            page.text = "\n".join(lines)
            for i, line in enumerate(lines[:2000]):
                page.words.append(Word(text=line,
                                       rect=Rect4(0, i * 12, 300, 12 + i * 12)))
            pages.append(page)
        wb.close()
        model.pages = pages
        model.diagnosis.update({"format": "XLSX", "seiten": len(pages),
                                "text_vorhanden": True})
        return model


class BilderParser(_BaseParser):
    """Bilddateien: Metadaten + optional OCR (Woerter via OCR-Engine)."""
    name = "Bild-Importer"
    extensions = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff")

    def parse(self, path: str) -> DocumentModel:
        model = self._base(path, "bild")
        try:
            from PIL import Image
            with Image.open(path) as img:
                w, h = img.size
        except Exception as exc:
            raise DocumentDamagedError(str(exc)) from exc
        page = PageModel(number=0, width=w, height=h)
        page.needs_ocr = True
        model.pages = [page]
        model.diagnosis.update({
            "format": "Bild", "seiten": 1, "text_vorhanden": False,
            "bilder": True, "ocr_noetig": True,
            "metadaten": {"groesse": f"{w}x{h}px",
                          "dateigroesse": os.path.getsize(path)}})
        return model
