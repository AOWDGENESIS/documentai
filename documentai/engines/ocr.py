"""OCR-Engine auf Basis Tesseract (optional, lokal).

Ist Tesseract nicht vorhanden, degradiert die Anwendung sauber:
OCR-Noetig wird erkannt und gemeldet, Kernfunktionen laufen weiter.
Es wird nichts automatisch heruntergeladen oder installiert.
"""
from __future__ import annotations

import io
import os
import subprocess

from ..core.models import Rect4, Word
from ..services.tools import tesseract_binary, tesseract_tessdata

PYTESS_OK = False
try:
    import pytesseract
    from PIL import Image
    PYTESS_OK = True
except Exception:
    PYTESS_OK = False


class TesseractOcrEngine:
    name = "Tesseract-OCR"
    priority = 100

    @staticmethod
    def is_available() -> bool:
        return PYTESS_OK and bool(tesseract_binary())

    def version(self) -> str:
        try:
            out = subprocess.run([tesseract_binary(), "--version"],
                                 capture_output=True, text=True, timeout=10)
            first = (out.stderr or out.stdout).splitlines()
            return first[0] if first else "unbekannt"
        except Exception:
            return "unbekannt"

    def ocr_page(self, png_bytes: bytes,
                 language: str = "deu+eng") -> list[Word]:
        img = Image.open(io.BytesIO(png_bytes))
        if img.mode not in ("L", "RGB"):
            img = img.convert("RGB")
        # Vorverarbeitung (Recherche 10.09.2026, OCR-Best-Practices für
        # Formulare): Graustufen + 2x-Hochskalierung + Auto-Kontrast.
        # Kleine Schrift (Formular-Labels 8–10 pt) wird so deutlich
        # sicherer erkannt; die Koordinaten werden unten über den
        # Skalierungsfaktor zurückgerechnet.
        ocr_faktor = 1.0
        try:
            from PIL import ImageOps
            grau = ImageOps.autocontrast(img.convert("L"))
            if img.size[1] < 2600:            # < ~A5 bei 300 dpi
                ocr_faktor = 2.0
                grau = grau.resize((img.size[0] * 2, img.size[1] * 2),
                                   Image.LANCZOS)
            img = grau
        except Exception:
            ocr_faktor = 1.0
        scale_w, scale_h = img.size
        binary = tesseract_binary()
        # Portable Installation: pytesseract + TESSDATA_PREFIX auf die
        # gefundene Binary lenken (nötig, wenn tesseract nicht im PATH).
        pytesseract.pytesseract.tesseract_cmd = binary
        tessdata = tesseract_tessdata()
        if tessdata:
            os.environ["TESSDATA_PREFIX"] = tessdata
        data = pytesseract.image_to_data(
            img, lang=language,
            output_type=pytesseract.Output.DICT,
            config="--oem 3 --psm 6")
        # Pixeldaten -> PDF-Punkte (Seite wurde mit 200 dpi gerendert,
        # ggf. OCR-interne 2x-Skalierung herausrechnen)
        dpi = 200.0 * ocr_faktor
        pt_w = scale_w / dpi * 72.0
        pt_h = scale_h / dpi * 72.0
        words: list[Word] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data["text"][i] or "").strip()
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1.0
            if not text or conf < 0:
                continue
            x = data["left"][i] / dpi * 72.0
            y = data["top"][i] / dpi * 72.0
            w = data["width"][i] / dpi * 72.0
            h = data["height"][i] / dpi * 72.0
            words.append(Word(text=text, rect=Rect4(x, y, w, h),
                              confidence=conf))
        _ = (pt_w, pt_h)
        return words
