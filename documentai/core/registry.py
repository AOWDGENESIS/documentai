"""Engine-Registry: Komponenten suchen, pruefen, wiederverwenden –
nie blind ersetzen. Laedt zusaetzlich Plugins aus plugins\\."""
from __future__ import annotations

import importlib.util
import os
import sys
from typing import Optional, Type

from ..paths import plugins_dir
from .interfaces import (IDocumentParser, IFieldDetector, IOcrEngine,
                         IPdfEngine, ISemanticAnalyzer, IValidationEngine)

_CATALOG: dict[type, list[Type]] = {
    IPdfEngine: [],
    IOcrEngine: [],
    IDocumentParser: [],
    IFieldDetector: [],
    ISemanticAnalyzer: [],
    IValidationEngine: [],
}


def register(interface: type, cls: Type, priority: Optional[int] = None) -> None:
    """Registriert eine Engine-Klasse fuer eine Schnittstelle."""
    if priority is not None:
        cls.priority = priority
    if cls not in _CATALOG[interface]:
        _CATALOG[interface].append(cls)


def available_engines(interface: type) -> list[Type]:
    """Alle verfuegbaren Implementierungen, sortiert nach Prioritaet."""
    found = [c for c in _CATALOG[interface] if c.is_available()]
    return sorted(found, key=lambda c: getattr(c, "priority", 0), reverse=True)


def resolve(interface: type):
    """Beste verfuegbare Engine instanziieren; None falls keine."""
    engines = available_engines(interface)
    return engines[0]() if engines else None


def status_report() -> list[dict]:
    """Uebersicht fuer Selbstdiagnose: was ist registriert/verfuegbar?"""
    report = []
    for interface, classes in _CATALOG.items():
        entry = {"schnittstelle": interface.__name__, "implementierungen": []}
        for cls in sorted(classes, key=lambda c: getattr(c, "priority", 0),
                          reverse=True):
            entry["implementierungen"].append({
                "name": getattr(cls, "name", cls.__name__),
                "verfuegbar": bool(cls.is_available()),
            })
        entry["gewaehlt"] = (getattr(available_engines(interface)[0], "name", "")
                             if available_engines(interface) else None)
        report.append(entry)
    return report


def _register_builtin() -> None:
    """Vorhandene Komponenten zuerst suchen und wiederverwenden."""
    try:
        from ..engines.pdf_mupdf import MuPdfEngine
        register(IPdfEngine, MuPdfEngine, priority=100)
    except Exception:            # PyMuPDF fehlt -> Fallback pypdf
        pass
    try:
        from ..engines.pdf_pypdf import PyPdfEngine
        register(IPdfEngine, PyPdfEngine, priority=50)
    except Exception:
        pass
    try:
        from ..engines.ocr import TesseractOcrEngine
        register(IOcrEngine, TesseractOcrEngine, priority=100)
    except Exception:
        pass
    try:
        from ..engines.parsers import (BilderParser, DocxParser, RtfParser,
                                       TxtParser, XlsxParser)
        for parser in (DocxParser, TxtParser, RtfParser, XlsxParser,
                       BilderParser):
            register(IDocumentParser, parser)
    except Exception:
        pass
    try:
        from ..engines.field_detector import VisualFieldDetector
        register(IFieldDetector, VisualFieldDetector, priority=100)
    except Exception:
        pass
    try:
        from ..engines.semantic import RuleSemanticAnalyzer
        register(ISemanticAnalyzer, RuleSemanticAnalyzer, priority=100)
    except Exception:
        pass
    try:
        from ..engines.semantic import LlmSemanticAnalyzer
        register(ISemanticAnalyzer, LlmSemanticAnalyzer, priority=50)
    except Exception:
        pass
    try:
        from ..engines.validator import Validator
        register(IValidationEngine, Validator, priority=100)
    except Exception:
        pass


def load_plugins(verbose: bool = False) -> list[str]:
    """Laedt plugins\\*.py; jedes Plugin kann register(...) aufrufen."""
    loaded: list[str] = []
    pdir = plugins_dir()
    try:
        names = sorted(os.listdir(pdir))
    except OSError:
        names = []
    for fname in names:
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        modname = f"documentai_plugin_{fname[:-3]}"
        try:
            spec = importlib.util.spec_from_file_location(
                modname, os.path.join(pdir, fname))
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[modname] = module
            spec.loader.exec_module(module)
            loaded.append(fname)
        except Exception as exc:                      # Plugin darf App nicht killen
            if verbose:
                print(f"⚠ Plugin {fname} konnte nicht geladen werden: {exc}")
    return loaded


_registered = False


def bootstrap() -> None:
    """Einmalig eingebaute Engines + Plugins registrieren."""
    global _registered
    if _registered:
        return
    _registered = True
    _register_builtin()
    try:
        load_plugins()
    except Exception:
        pass
