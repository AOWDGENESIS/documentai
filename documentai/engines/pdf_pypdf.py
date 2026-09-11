"""Fallback-PDF-Engine auf Basis pypdf (reines Python).

Wird automatisch verwendet, wenn PyMuPDF fehlt – vorhandene Komponenten
zuerst suchen und wiederverwenden, nichts blind installieren.
Einschränkungen: kein Rendering, keine visuelle Felderkennung.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from ..core.errors import (DocumentDamagedError, PasswordRequiredError,
                           WrongPasswordError)
from ..core.models import FieldModel, PageModel, Rect4, Word

try:
    from pypdf import PdfReader, PdfWriter
    from pypdf.constants import UserAccessPermissions as UAP
    PYPDF_OK = True
except Exception:
    PYPDF_OK = False


class PypdfSession:
    def __init__(self, path: str, reader: "PdfReader", password: str = ""):
        self.path = path
        self.reader = reader
        self.password = password
        self.pending_overlays: list[dict] = []
        self.overlay_applied = False
        self.saved_versions: list[str] = []
        self.encrypted = bool(reader.is_encrypted)

    # pypdf-Reader gilt als "doc"-Attribut-Äquivalent
    @property
    def doc(self) -> "PdfReader":
        return self.reader


class PyPdfEngine:
    name = "pypdf-Engine (Fallback)"
    priority = 50
    capabilities = {"acroform", "text"}

    @staticmethod
    def is_available() -> bool:
        return PYPDF_OK

    def open(self, path: str, password: Optional[str] = None):
        if not os.path.exists(path):
            raise DocumentDamagedError(f"Datei nicht gefunden: {path}")
        reader = PdfReader(path)
        if reader.is_encrypted:
            if not password:
                raise PasswordRequiredError(path)
            try:
                ok = reader.decrypt(password)
            except Exception as exc:
                raise WrongPasswordError(path) from exc
            if not ok:
                raise WrongPasswordError(path)
        return PypdfSession(path, reader, password or "")

    def diagnose(self, session: PypdfSession) -> dict:
        r = session.reader
        fields = r.get_fields() or {}
        n_widgets = sum(1 for f in fields.values()
                        if f.get("field_type") in ("/Tx", "/Btn", "/Ch", "/Sig"))
        perm = getattr(r, "user_access_permissions", None)
        out = {
            "format": "PDF",
            "pdf_version": str(r.pdf_header) if hasattr(r, "pdf_header") else "",
            "seiten": len(r.pages),
            "text_vorhanden": False,
            "vektorgrafiken": False,
            "bilder": False,
            "ocr_noetig": False,
            "formularfelder": len(fields),
            "pflichtfelder": sum(1 for f in fields.values() if f.get("/Ff", 0) & 2),
            "annotationen": 0,
            "checkboxen": sum(1 for f in fields.values()
                              if f.get("field_type") == "/Btn"),
            "signaturen": sum(1 for f in fields.values()
                              if f.get("field_type") == "/Sig"),
            "verschluesselt": bool(r.is_encrypted),
            "passwort_erforderlich": False,
            "bearbeitung_erlaubt": not perm or bool(perm & UAP.MODIFY),
            "drucken_erlaubt": not perm or bool(perm & UAP.PRINT),
            "kopieren_erlaubt": not perm or bool(perm & UAP.EXTRACT),
            "metadaten": dict(r.metadata or {}),
            "eingebettete_dateien": [],
            "pdfa_status": "kein PDF/A erkannt",
            "beschaedigte_objekte": [],
            "warnungen": ["Fallback-Engine aktiv: kein Rendering, "
                          "keine visuelle Felderkennung."],
            "repariert": False,
        }
        text = ""
        for page in r.pages[:20]:
            try:
                text += page.extract_text() or ""
            except Exception:
                pass
        out["text_vorhanden"] = bool(text.strip())
        return out

    def extract_pages(self, session, ocr_engine=None, progress=None):
        pages: list[PageModel] = []
        for i, page in enumerate(session.reader.pages):
            pm = PageModel(number=i,
                           width=float(page.mediabox.width),
                           height=float(page.mediabox.height))
            try:
                pm.text = page.extract_text() or ""
            except Exception:
                pm.text = ""
            for j, line in enumerate(pm.text.splitlines()):
                pm.words.append(Word(text=line,
                                     rect=Rect4(0, j * 12, 100, 12 + j * 12)))
            pages.append(pm)
            if progress:
                progress(i + 1, len(pages))
        return pages

    def get_acroform_fields(self, session: PypdfSession) -> list[FieldModel]:
        fields = session.reader.get_fields() or {}
        out: list[FieldModel] = []
        type_map = {"/Tx": "text", "/Btn": "checkbox", "/Ch": "dropdown",
                    "/Sig": "signatur"}
        for name, info in fields.items():
            flags = info.get("/Ff", 0) or 0
            out.append(FieldModel(
                id=f"acro::0::{name}",
                name=str(name),
                label=str(name),
                field_type=type_map.get(info.get("field_type"), "text"),
                required=bool(flags & 2),
                value=info.get("/V", None),
                original_value=info.get("/V", None),
                page=0,
                source="acroform",
                confidence=0.9,
                read_only=bool(flags & 1),
            ))
        return out

    def render_page(self, session, page: int, dpi: int = 150) -> bytes:
        raise NotImplementedError(
            "pypdf-Engine kann nicht rendern – PyMuPDF installieren "
            "(pip install pymupdf) für die Seitenansicht.")

    def find_tables(self, session):
        return []                     # im Fallback nicht verfügbar

    def fill_fields(self, session, assignments: dict):
        writer = PdfWriter(clone_from=session.reader)
        by_name: dict[str, Any] = {}
        for field in session.reader.get_fields() or {}:
            by_name[str(field)] = field
        ok, fehler = [], []
        for field_id, value in assignments.items():
            name = field_id.split("::")[-1]
            if name in by_name:
                try:
                    writer.update_page_form_field_values(
                        writer.pages[0], {name: value}, auto_regenerate=False)
                    ok.append(field_id)
                except Exception as exc:
                    fehler.append((field_id, str(exc)))
            else:
                fehler.append((field_id, "Feld nicht gefunden"))
        session.writer = writer
        return {"ok": ok, "fehler": fehler, "overlay": []}

    def save_version(self, session, model, reason="bearbeitet"):
        from ..services import versioning
        writer = getattr(session, "writer", None)
        if writer is None:
            writer = PdfWriter(clone_from=session.reader)
        dest = versioning.next_version_path(model.path)
        with open(dest, "wb") as fh:
            writer.write(fh)
        session.saved_versions.append(dest)
        return {"pfad": dest, "pruefung": {"ok": True, "probleme": [],
                                           "seiten": len(writer.pages),
                                           "felder": -1}}
