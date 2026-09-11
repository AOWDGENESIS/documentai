"""Hilfsfunktionen: Fehlerberichte, Formatierung, Systeminfo (ohne
personenbezogene Dokumentinhalte!)."""
from __future__ import annotations

import datetime
import os
import platform
import re
import sys
import traceback


def slugify(name: str) -> str:
    keep = [c if (c.isalnum() or c in "-_.") else "_" for c in name or ""]
    return re.sub(r"_+", "_", "".join(keep))[:100] or "unbenannt"


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} PB"


def system_info() -> dict:
    info = {
        "zeitpunkt": datetime.datetime.now().isoformat(timespec="seconds"),
        "plattform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "maschine": platform.machine(),
        "prozessor": platform.processor() or "unbekannt",
        "python": sys.version.split()[0],
        "implementierung": platform.python_implementation(),
        "programmverzeichnis": os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))),
        "cpu_kerne": os.cpu_count(),
    }
    info.update(_memory_info())
    return info


def _memory_info() -> dict:
    try:
        import psutil                       # optional
        vm = psutil.virtual_memory()
        return {"ram_gesamt": human_size(vm.total),
                "ram_verfuegbar": human_size(vm.available)}
    except Exception:
        pass
    if platform.system() == "Windows":      # ohne psutil
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return {"ram_gesamt": human_size(stat.ullTotalPhys),
                    "ram_verfuegbar": human_size(stat.ullAvailPhys)}
        except Exception:
            pass
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        size = os.sysconf("SC_PAGE_SIZE")
        return {"ram_gesamt": human_size(pages * size)}
    except (ValueError, OSError, AttributeError):
        return {}


def write_error_report(exc: BaseException, action: str = "",
                       component: str = "unbekannt") -> str:
    """Erzeugt diagnostics\\ERROR_REPORT.txt (ohne Dokumentinhalte)."""
    from .paths import diagnostics_dir
    path = os.path.join(diagnostics_dir(), "ERROR_REPORT.txt")
    lines = [
        "=" * 62,
        "DocumentAI – FEHLERBERICHT",
        "=" * 62,
        f"Zeitpunkt      : {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"Komponente     : {component}",
        f"Aktion         : {action or '-'}",
        f"Fehler         : {getattr(exc, 'message', str(exc))}",
        f"Techn. Ursache : {type(exc).__name__}",
        "-" * 62,
        "Stack Trace:",
        "".join(traceback.format_exception(type(exc), exc,
                                            exc.__traceback__)),
        "-" * 62,
        "Systeminformationen (ohne Dokumentinhalte):",
    ]
    for key, value in system_info().items():
        lines.append(f"  {key:16}: {value}")
    hint = _possible_solution(exc)
    if hint:
        lines.append("-" * 62)
        lines.append(f"Mögliche Lösung: {hint}")
    lines.append("=" * 62)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
    except OSError:
        pass
    return path


def _possible_solution(exc: BaseException) -> str:
    name = type(exc).__name__
    text = str(exc).lower()
    if name in ("PasswordRequiredError", "WrongPasswordError"):
        return ("Passwort berechtigt angeben – der Schutz wird aus "
                "Sicherheitsgründen niemals umgangen.")
    if "pymupdf" in text or "fitz" in text:
        return "PyMuPDF installieren: pip install pymupdf"
    if "docx" in text:
        return "python-docx installieren: pip install python-docx"
    if "openpyxl" in text:
        return "openpyxl installieren: pip install openpyxl"
    if "tesseract" in text:
        return ("Tesseract OCR installieren und PATH setzen "
                "(https://github.com/UB-Mannheim/tesseract)")
    if name == "PermissionError":
        return "Schreibrechte für das Programmverzeichnis prüfen."
    return ""
