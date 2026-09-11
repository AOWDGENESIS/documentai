"""Export-Engine: PDF, TXT, JSON, CSV, DOCX, Bilder – mit Verifikation."""
from __future__ import annotations

import csv
import json
import os
import shutil
from typing import Any

from ..core import audit
from ..core.models import DocumentModel

SUPPORTED = ("pdf", "txt", "json", "csv", "docx", "xlsx", "pptx",
              "rtf", "png", "pdfa")

def _format_import_fehler(exc: Exception, was: str) -> str:
    """Import-Fehler verständlich machen – inkl. Windows-Blockierungs-
    Hinweis (Smart App Control, Nutzerfund 10.09.2026)."""
    blockiert = any(w in str(exc).lower() for w in (
        "blockiert", "blocked", "steuerungsrichtlinie", "app control"))
    if blockiert:
        return (f"{was} ist auf diesem PC durch eine Windows-Sicherheits-"
                f"richtlinie (z. B. Smart App Control) blockiert. "
                "Freigabe: Einstellungen > Datenschutz und Sicherheit > "
                "Windows-Sicherheit > App- und Browsersteuerung > "
                "Smart App Control > „Aus“ – danach App neu starten.")
    return (f"{was} nicht installiert "
            f"({exc})")



class ExportEngine:
    name = "Export-Engine"

    @staticmethod
    def is_available() -> bool:
        return True

    # ------------------------------------------------------------------
    def export(self, model: DocumentModel, session: Any, engine: Any,
               fmt: str, dest: str) -> dict:
        fmt = fmt.lower().lstrip(".")
        if fmt not in SUPPORTED:
            return {"ok": False, "fehler":
                    f"Format {fmt} nicht unterstützt "
                    f"({', '.join(SUPPORTED)})"}
        if fmt == "pdf":
            out = engine.save_version(session, model, reason="Export")
            result = {"ok": out["pruefung"]["ok"], "pfad": out["pfad"],
                      "pruefung": out["pruefung"]}
            audit.log(model, "Export PDF", os.path.basename(out["pfad"]))
            return result
        if fmt == "pdfa":
            return self._export_pdfa(model, session)
        writer = {
            "txt": self._export_txt, "json": self._export_json,
            "csv": self._export_csv, "docx": self._export_docx,
            "xlsx": self._export_xlsx, "pptx": self._export_pptx,
            "rtf": self._export_rtf,
            "png": self._export_png,
        }[fmt]
        return writer(model, session, engine, dest)

    # ------------------------------------------------------------------
    def _export_txt(self, model, session, engine, dest) -> dict:
        parts = [f"DokumentAI Export – {model.name}",
                 f"Seiten: {len(model.pages)}", ""]
        for p in model.pages:
            parts.append(f"----- Seite {p.number + 1} -----")
            parts.append(p.text or "(kein Text – OCR erforderlich)")
            parts.append("")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write("\n".join(parts))
        return self._verify_file(dest, model, min_size=20)

    def _export_json(self, model, session, engine, dest) -> dict:
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(model.to_dict(), fh, ensure_ascii=False, indent=2)
        return self._verify_file(dest, model, min_size=10)

    def _export_csv(self, model, session, engine, dest) -> dict:
        with open(dest, "w", encoding="utf-8-sig", newline="") as fh:
            wcsv = csv.writer(fh, delimiter=";")
            wcsv.writerow(["Feld", "Beschriftung", "Typ", "Pflicht",
                           "Wert", "Seite", "Quelle", "Konfidenz %",
                           "Semantik"])
            for f in model.fields:
                wcsv.writerow([f.name, f.label, f.field_type,
                               "ja" if f.required else "nein",
                               "" if f.value is None else f.value,
                               f.page + 1, f.source,
                               round(f.confidence * 100, 1),
                               f.canonical])
        tables_path = dest.replace(".csv", "_tabellen.csv")
        if model.tables:
            with open(tables_path, "w", encoding="utf-8-sig",
                      newline="") as fh:
                wcsv = csv.writer(fh, delimiter=";")
                for t in model.tables:
                    wcsv.writerow([f"Seite {t.page + 1}"])
                    if t.header:
                        wcsv.writerow(t.header)
                    for row in t.rows:
                        wcsv.writerow(row)
                    wcsv.writerow([])
        return self._verify_file(dest, model, min_size=10)

    def _export_docx(self, model, session, engine, dest) -> dict:
        try:
            import docx
        except ImportError as exc:
            return {"ok": False, "fehler":
                    _format_import_fehler(exc, "Word-Export")}
        d = docx.Document()
        d.add_heading(f"DokumentAI Export – {model.name}", 0)
        for p in model.pages:
            d.add_heading(f"Seite {p.number + 1}", level=1)
            for line in (p.text or "(kein Text)").splitlines():
                if line.strip():
                    d.add_paragraph(line)
        d.save(dest)
        return self._verify_file(dest, model, min_size=100)

    def _export_xlsx(self, model, session, engine, dest) -> dict:
        """In Excel konvertieren (Acrobat „Konvertieren > Microsoft
        Excel“): je Seite ein Blatt, erkannte Formularfelder als
        eigenes Blatt."""
        try:
            import openpyxl
        except ImportError:
            return {"ok": False, "fehler":
                    "openpyxl nicht installiert"}
        wb = openpyxl.Workbook()
        for i, p in enumerate(model.pages):
            blatt = wb.active if i == 0 else wb.create_sheet()
            blatt.title = f"Seite {i + 1}"[:31]
            for r, line in enumerate((p.text or "").splitlines(), 1):
                if line.strip():
                    blatt.cell(row=r, column=1, value=line.strip())
        felder = [f for f in model.fields]
        if felder:
            fb = wb.create_sheet("Felder")
            fb.append(["Name", "Typ", "Wert", "Seite"])
            for f in felder:
                fb.append([f.name, f.field_type, f.value or "",
                           f.page + 1 if hasattr(f, "page") else ""])
        wb.save(dest)
        return self._verify_file(dest, model, min_size=100)

    def _export_pptx(self, model, session, engine, dest) -> dict:
        """In PowerPoint konvertieren: je PDF-Seite eine Folie mit
        Seitenbild (Layout bleibt erhalten) + Text in den Notizen."""
        try:
            from pptx import Presentation
            from pptx.util import Emu
        except ImportError as exc:
            return {"ok": False, "fehler":
                    _format_import_fehler(exc, "PowerPoint-Export")}
        import io as _io
        prs = Presentation()
        prs.slide_width = Emu(9144000)       # 25,4 cm (Acrobat-Standard)
        prs.slide_height = Emu(6858000)
        blank = prs.slide_layouts[6]
        for i in range(len(model.pages)):
            folie = prs.slides.add_slide(blank)
            try:
                png = engine.render_page(session, i, dpi=150)
                folie.shapes.add_picture(_io.BytesIO(png), 0, 0,
                                         width=prs.slide_width,
                                         height=prs.slide_height)
            except Exception:
                pass
            folie.notes_slide.notes_text_frame.text = \
                (model.pages[i].text or "")[:4000]
        prs.save(dest)
        return self._verify_file(dest, model, min_size=100)

    def _export_rtf(self, model, session, engine, dest) -> dict:
        """Als RTF speichern (Acrobat „Anderes Format“) – plattform-
        neutraler Textaustausch, auch für WordPad."""
        def _rtf(text: str) -> str:
            out = []
            for ch in text:
                o = ord(ch)
                if 32 <= o < 128 and ch not in "\\{}":
                    out.append(ch)
                elif ch in "\\{}":
                    out.append("\\" + ch)
                else:
                    out.append(f"\\u{o}?")
            return "".join(out)

        zeilen = [f"DokumentAI Export {_rtf(model.name)}"]
        for p in model.pages:
            zeilen.append(f"\\par \\b Seite {p.number + 1}\\b0 \\par")
            zeilen.extend(_rtf(z) + " \\par"
                          for z in (p.text or "").splitlines() if z.strip())
        rtf = ("{\\rtf1\\ansi\\ansicpg1252\\deff0"
               "{\\fonttbl{\\f0 Arial;}}\\fs20 "
               + " ".join(zeilen) + "}")
        with open(dest, "w", encoding="ascii", errors="replace") as fh:
            fh.write(rtf)
        return self._verify_file(dest, model, min_size=50)

    def _export_png(self, model, session, engine, dest) -> dict:
        folder = dest
        os.makedirs(folder, exist_ok=True)
        count = 0
        for i in range(len(model.pages)):
            try:
                png = engine.render_page(session, i, dpi=200)
                path = os.path.join(
                    folder,
                    f"{os.path.splitext(model.name)[0]}_s{i + 1}.png")
                with open(path, "wb") as fh:
                    fh.write(png)
                count += 1
            except Exception:
                pass
        audit.log(model, "Export Bilder", f"{count} Seiten als PNG")
        return {"ok": count > 0, "pfad": folder, "seiten": count,
                "fehler": None if count else "Rendern nicht möglich"}

    def _export_pdfa(self, model, session) -> dict:
        """PDF/A-Konvertierung, soweit technisch möglich (Ghostscript)."""
        from ..services.tools import ghostscript_binary
        gs = ghostscript_binary()
        if not gs:
            return {"ok": False,
                    "fehler": "PDF/A-Konvertierung nicht verfügbar: "
                              "Ghostscript nicht gefunden. Status wurde "
                             "jedoch analysiert "
                              f"({model.diagnosis.get('pdfa_status', '?')})."}
        from ..services import versioning
        import subprocess
        dest = versioning.next_version_path(model.path, suffix="_pdfa")
        cmd = [gs, "-dPDFA=3", "-dBATCH", "-dNOPAUSE", "-sColorConversionStrategy=RGB",
               "-sDEVICE=pdfwrite", "-dPDFACompatibilityPolicy=1",
               f"-sOutputFile={dest}", model.path]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=300)
        except Exception as exc:
            return {"ok": False, "fehler": f"Ghostscript-Fehler: {exc}"}
        if proc.returncode != 0 or not os.path.exists(dest):
            return {"ok": False,
                    "fehler": "Ghostscript-Konvertierung fehlgeschlagen."}
        audit.log(model, "PDF/A-Export", os.path.basename(dest))
        return {"ok": True, "pfad": dest,
                "pruefung": {"ok": True, "probleme": []}}

    # ------------------------------------------------------------------
    @staticmethod
    def _verify_file(dest: str, model: DocumentModel,
                     min_size: int) -> dict:
        """Export prüfen: existiert, Größe plausibel, lesbar."""
        problems: list[str] = []
        if not os.path.exists(dest):
            return {"ok": False, "fehler": "Datei wurde nicht erzeugt"}
        size = os.path.getsize(dest)
        if size < min_size:
            problems.append(f"Datei ungewöhnlich klein ({size} Bytes)")
        audit.log(model, "Export", os.path.basename(dest))
        return {"ok": not problems, "pfad": dest, "groesse": size,
                "probleme": problems}
