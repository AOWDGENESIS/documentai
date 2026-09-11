"""Analyse-Pipeline: Analysieren → Verstehen → Struktur erkennen →
Bearbeitbarkeit feststellen → Felder erkennen → zuordnen → prüfen."""
from __future__ import annotations

import os
from typing import Any, Optional

from .. import config
from ..core import audit, registry
from ..core.errors import DocumentDamagedError
from ..core.interfaces import (IDocumentParser, IFieldDetector,
                               IOcrEngine, IPdfEngine)
from ..core.models import DocumentModel
from ..engines.form_engine import FormEngine
from ..engines.signatures import SignatureAnalyzer
from . import versioning

PDF_EXTS = {".pdf"}


class AnalysisService:
    """Fassade über alle Engines – von der GUI und CLI gemeinsam genutzt."""

    def __init__(self):
        registry.bootstrap()
        self.pdf_engine = registry.resolve(IPdfEngine)
        self.ocr_engine = registry.resolve(IOcrEngine)
        self.detector = registry.resolve(IFieldDetector)
        self.signature_analyzer = SignatureAnalyzer()
        self.form_engine = FormEngine()
        self._semantic = None

    # ------------------------------------------------------------------
    @property
    def semantic(self):
        """Regelbasiert immer; lokale KI, wenn aktiviert UND erreichbar."""
        if self._semantic is None:
            from ..engines.semantic import (LlmSemanticAnalyzer,
                                            RuleSemanticAnalyzer)
            try:
                llm = LlmSemanticAnalyzer()
                if llm.is_available():
                    self._semantic = llm
                else:
                    self._semantic = RuleSemanticAnalyzer()
            except Exception:
                self._semantic = RuleSemanticAnalyzer()
        return self._semantic

    # ------------------------------------------------------------------
    def open_document(self, path: str, password: Optional[str] = None,
                      progress=None):
        """Öffnet ein Dokument (PDF oder anderes Format via Importer).

        Liefert (model, session, engine); session=None bei Nicht-PDF.
        """
        path = str(path)
        ext = os.path.splitext(path)[1].lower()
        if ext in PDF_EXTS:
            if self.pdf_engine is None:
                raise DocumentDamagedError(
                    "Keine PDF-Engine verfügbar (PyMuPDF und pypdf fehlen).")
            session = self.pdf_engine.open(path, password)
            model = DocumentModel(path=path)
            audit.log(model, "Dokument geöffnet",
                      f"PDF, {session.doc.page_count} Seiten")
            return model, session, self.pdf_engine
        # Andere Formate: passenden Importer suchen (vorhandene zuerst)
        for parser in registry.available_engines(IDocumentParser):
            if ext in parser.extensions:
                model = parser().parse(path)
                return model, None, None
        raise DocumentDamagedError(
            f"Kein Importer für Format {ext} vorhanden. "
            "Plugins können zusätzliche Formate registrieren.")

    # ------------------------------------------------------------------
    def analyze(self, model: DocumentModel, session: Any,
                engine: Any, progress=None) -> DocumentModel:
        """Vollständige Analyse + Felderkennung + Semantik + Validierung."""
        if session is not None and engine is not None:
            model.diagnosis.update(engine.diagnose(session))
            use_ocr = config.get("ocr.automatisch", True)
            ocr = self.ocr_engine if use_ocr else None
            model.pages = engine.extract_pages(session, ocr,
                                               progress=progress)
            if any(p.ocr_applied for p in model.pages):
                model.ocr_used = True
                audit.log(model, "OCR durchgeführt",
                          f"{sum(1 for p in model.pages if p.ocr_applied)} "
                          "Seiten")
            model.fields.extend(engine.get_acroform_fields(session))
            audit.log(model, "Felder erkannt",
                      f"{len(model.fields)} Felder "
                      f"({model.diagnosis.get('pflichtfelder', 0)} Pflicht)")
            if self.detector is not None:
                visual = self.detector.detect(model, session)
                before = len(model.fields)
                model.fields.extend(visual)
                if visual:
                    audit.log(model, "Visuelle Felder erkannt",
                              f"{len(model.fields) - before} Elemente")
            try:
                model.tables = engine.find_tables(session)
                if model.tables:
                    audit.log(model, "Tabellen erkannt",
                              str(len(model.tables)))
            except Exception:
                model.tables = []
            model.signature_info = self.signature_analyzer.analyze(session,
                                                                   model)

        self.semantic.classify(model.fields)
        from ..core.interfaces import IValidationEngine
        validator = registry.resolve(IValidationEngine)
        if validator is not None:
            model.issues = validator.validate(model, session)
        counts = model.issue_counts()
        audit.log(model, "Validierung durchgeführt",
                  f"{counts['fehler']} Fehler, {counts['warnung']} "
                  "Warnungen")
        audit.log(model, "Analyse abgeschlossen")
        return model

    # ------------------------------------------------------------------
    def felder_automatisch_erkennen(self, model: DocumentModel, session: Any,
                                    engine: Any) -> int:
        """Setzt Textfelder automatisch (Acrobat „Formularfelder erkennen“):
        holt für Seiten ohne Textebene die integrierte OCR nach und lässt
        den visuellen Detektor laufen (Unterstriche, Scan-Linien, Kästchen,
        Label-Lücken). Vorhandene Felder bleiben, Doppelte werden vermieden.
        Liefert die Zahl der NEU erkannten Felder."""
        if session is None or engine is None or self.detector is None:
            return 0
        # 1) Seiten ohne Worte: integrierte OCR nachholen
        ocr_nachgeholt = False
        for pm in model.pages:
            if not pm.words and pm.image_count:
                try:
                    woerter = engine.ocr_seite(session, pm.number)
                except Exception:
                    woerter = []
                if woerter:
                    pm.words = woerter
                    pm.ocr_applied = True
                    pm.ocr_integriert = True
                    pm.text = " ".join(w.text for w in pm.words)
                    model.ocr_used = True
                    ocr_nachgeholt = True
        # 2) Platzhalter-Felder (ohne Beschriftung, ohne Wert – entstanden
        #    ohne OCR) räumen: sonst blockieren sie die bessere, neu
        #    beschriftete Erkennung. Bei Fehler werden sie zurückgeholt.
        platzhalter: list = []
        if ocr_nachgeholt:
            platzhalter = [
                f for f in model.fields
                if f.source in ("visuell", "ocr") and not f.value
                and (not f.label or f.label.startswith("Feld "))]
            for f in platzhalter:
                model.fields.remove(f)
        # 3) Detektor über das komplette Modell (beachtet vorhandene
        #    Felder als belegt -> keine Überlappungen, keine Duplikate)
        try:
            neu = self.detector.detect(model, session)
        except Exception:
            model.fields.extend(platzhalter)
            return 0
        vorhanden = {f.id for f in model.fields}
        for f in neu:
            if f.id not in vorhanden:
                model.fields.append(f)
                vorhanden.add(f.id)
        gesetzt = sum(1 for f in neu if f.id in vorhanden)
        if platzhalter:
            # Verlorene Platzhalter zurückholen, die nichts Neues ersetzen
            for f in platzhalter:
                if f.id not in vorhanden and not any(
                        x.page == f.page and x.rect and f.rect
                        and not (x.rect.x + x.rect.width < f.rect.x
                                 or f.rect.x + f.rect.width < x.rect.x
                                 or x.rect.y + x.rect.height < f.rect.y
                                 or f.rect.y + f.rect.height < x.rect.y)
                        for x in model.fields):
                    model.fields.append(f)
        if gesetzt:
            audit.log(model, "Textfelder automatisch erkannt",
                      f"{gesetzt} Feld(er) gesetzt")
        return gesetzt

    # ------------------------------------------------------------------
    def prepare_fill(self, model: DocumentModel,
                     profile: dict) -> list[dict]:
        """Daten zuordnen – vor dem Speichern prüft der Benutzer."""
        if not profile:
            return []
        return self.form_engine.build_assignments(model, profile,
                                                  self.semantic)

    def apply_fill(self, model, session, engine,
                   assignments: list[dict]) -> dict:
        if engine is None:
            raise DocumentDamagedError(
                "Befüllung nur für PDF möglich (kein Importer-Format).")
        return self.form_engine.apply_assignments(session, engine, model,
                                                  assignments)

    def save_new_version(self, model, session, engine,
                         reason: str = "bearbeitet") -> dict:
        """Neue Version erzeugen: Backup + Version + Prüfung + Audit."""
        versioning.backup_original(model)
        result = engine.save_version(session, model, reason)
        versioning.guard_original(model.path, result["pfad"])
        model.version += 1
        model.edited = False
        return result

    # ------------------------------------------------------------------
    def compare_paths(self, path_a: str, path_b: str,
                      password_a: str = "", password_b: str = "") -> dict:
        from ..engines.compare import compare_models
        model_a, session_a, engine = self.open_document(
            path_a, password_a or None)
        self.analyze(model_a, session_a, engine)
        model_b, session_b, _ = self.open_document(path_b,
                                                   password_b or None)
        self.analyze(model_b, session_b, engine)
        return compare_models(model_a, model_b, session_a, session_b, engine)
