"""Portable Zusatzwerkzeuge (Tesseract, Ghostscript) auffinden.

Suchreihenfolge (jeweils erste Fundstelle gewinnt):
1. Konfiguration in config/settings.json (ocr.pfad / pdfa.ghostscript)
2. portabler Ordner  <App-Root>/tools/...  (vom Installer automatisch
   befüllt – kein PATH-Eintrag, keine Registry, keine Adminrechte)
3. PATH (klassische Installation auf dem System)

Damit funktioniert OCR/PDF-A sowohl mit Systeminstallationen als auch
komplett portabel vom USB-Stick.
"""
from __future__ import annotations

import os
import shutil


def app_root() -> str:
    """Verzeichnis, das den Ordner `DocumentAI` (und `tools/`) enthält.

    documentai/services/tools.py  ->  drei Ebenen aufwärts = App-Root.
    """
    return os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))


def _search_tree(base: str, names: tuple[str, ...]) -> str:
    """Sucht eine Datei rekursiv – Entpacker legen exes teils in Unterordner."""
    for root, _dirs, files in os.walk(base):
        for n in names:
            if n in files:
                return os.path.join(root, n)
    return ""


def find_tool(config_key: str, portable_dir: str,
              names: tuple[str, ...]) -> str:
    """Liefert den vollständigen Pfad zum Werkzeug oder ''."""
    from .. import config as cfg
    try:
        gepflegt = str(cfg.get(config_key) or "").strip()
    except Exception:
        gepflegt = ""
    if gepflegt and os.path.isfile(gepflegt):
        return gepflegt

    basis = os.path.join(app_root(), "tools", portable_dir)
    eltern = os.path.join(os.path.dirname(app_root()), "tools", portable_dir)
    for wurzel in (basis, eltern):
        if os.path.isdir(wurzel):
            fund = _search_tree(wurzel, names)
            if fund:
                return fund

    for n in names:
        gefunden = shutil.which(n)
        if gefunden:
            return gefunden
    return ""


def tesseract_binary() -> str:
    """Pfad zu tesseract.exe (portabel bevorzugt)."""
    return find_tool("ocr.pfad", "tesseract",
                     ("tesseract.exe", "tesseract"))


def tesseract_tessdata() -> str:
    """Verzeichnis mit traineddata-Dateien (passend zur gefundenen Binary)."""
    binary = tesseract_binary()
    if not binary:
        return ""
    kandidat = os.path.join(os.path.dirname(binary), "tessdata")
    return kandidat if os.path.isdir(kandidat) else ""


def tessdata_verzeichnis() -> str:
    """tessdata-Ordner für die IN PyMuPDF integrierte OCR (kein
    tesseract.exe nötig). Reihenfolge: Konfiguration > mitgelieferter
    App-Ordner > Umgebung (TESSDATA_PREFIX). Liefert '' wenn leer."""
    try:
        from .. import config as cfg
        gepflegt = str(cfg.get("ocr.tessdata") or "").strip()
    except Exception:
        gepflegt = ""
    kandidaten: list[str] = []
    if gepflegt:
        kandidaten.append(gepflegt)
    kandidaten.append(os.path.join(app_root(), "tessdata"))
    kandidaten.append(os.path.join(os.path.dirname(app_root()), "tessdata"))
    umgebung = os.environ.get("TESSDATA_PREFIX", "")
    if umgebung:
        kandidaten.append(umgebung)
    for k in kandidaten:
        try:
            if k and os.path.isdir(k) and any(
                    n.endswith(".traineddata")
                    for n in os.listdir(k) if n[0] != "."):
                return k
        except OSError:
            continue
    return ""


def tessdata_pfad_fuer_tesseract(pfad: str = "") -> str:
    """OCR-tauglicher Pfad zum tessdata-Ordner.

    Die in MuPDF einkompilierte Tesseract-Engine öffnet Dateien über
    die C-Laufzeit und scheitert an Nicht-ASCII-Pfaden (z. B. Benutzer
    „Müller“ oder Ordner „Dokumente ÄÖÜ“). Lösung: 8.3-Kurzpfad über
    die Windows-API; falls nicht verfügbar, ASCII-Kopie ins
    Temp-Verzeichnis. Liefert '' wenn gar kein ASCII-Pfad möglich."""
    pfad = pfad or tessdata_verzeichnis()
    if not pfad:
        return ""
    try:
        if pfad.isascii():
            return pfad
    except AttributeError:                       # sehr alte Pythons
        return pfad
    try:                                         # Windows: Kurzpfad
        import ctypes
        puffer = ctypes.create_unicode_buffer(1024)
        anzahl = ctypes.windll.kernel32.GetShortPathNameW(  # type: ignore[attr-defined]
            pfad, puffer, 1024)
        if anzahl and puffer.value and puffer.value.isascii() \
                and os.path.isdir(puffer.value):
            return puffer.value
    except Exception:
        pass
    try:                                         # Ausweich: Temp-Kopie
        import shutil
        import tempfile
        ziel = os.path.join(tempfile.gettempdir(), "documentai-tessdata")
        if not ziel.isascii():
            return pfad
        os.makedirs(ziel, exist_ok=True)
        for name in os.listdir(pfad):
            if not name.endswith(".traineddata"):
                continue
            her = os.path.join(pfad, name)
            hin = os.path.join(ziel, name)
            if not os.path.isfile(hin) or \
                    os.path.getsize(hin) != os.path.getsize(her):
                shutil.copy2(her, hin)
        return ziel
    except Exception:
        return pfad


def ghostscript_binary() -> str:
    """Pfad zu gswin64c.exe (portabel bevorzugt)."""
    return find_tool("pdfa.ghostscript", "gs",
                     ("gswin64c.exe", "gswin32c.exe", "gs"))
