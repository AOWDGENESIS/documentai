"""Primäre PDF-Engine auf Basis PyMuPDF (lokal, keine Cloud).

Falls PyMuPDF nicht vorhanden ist, greift die Registry automatisch auf
die pypdf-Engine zurück (vorhandene Komponente wiederverwenden, nicht
blind ersetzen).
"""
from __future__ import annotations

import os
from typing import Any, Callable, Optional

from ..core import audit
from ..core.errors import (DocumentDamagedError, PasswordRequiredError,
                           WrongPasswordError)
from ..core.models import (FieldModel, PageModel, Rect4, TableData, Word)

try:
    import pymupdf
    PYMUPDF_OK = True
except Exception:                                   # ImportError u. a.
    PYMUPDF_OK = False

_WIDGET_TYPE_MAP: dict[int, str] = {}
if PYMUPDF_OK:
    _W = pymupdf
    _WIDGET_TYPE_MAP = {
        _W.PDF_WIDGET_TYPE_TEXT: "text",
        _W.PDF_WIDGET_TYPE_CHECKBOX: "checkbox",
        _W.PDF_WIDGET_TYPE_RADIOBUTTON: "radio",
        _W.PDF_WIDGET_TYPE_COMBOBOX: "dropdown",
        _W.PDF_WIDGET_TYPE_LISTBOX: "dropdown",
        _W.PDF_WIDGET_TYPE_SIGNATURE: "signatur",
    }

# bit 2 = required, bit 1 = read-only (PDF-Spezifikation AcroForm Field Flags)
_FLAG_READONLY = 1 << 0
_FLAG_REQUIRED = 1 << 1

MAX_SCAN_PAGES = 600          # Diagnose-Deckelung fuer Riesen-Dokumente


class PdfSession:
    """Offene PDF-Sitzung: Original bleibt unveraendert, gearbeitet wird
    auf einer In-Memory-Kopie.

    WICHTIG: Nach erfolgreicher authenticate() darf doc.needs_pass NICHT
    mehr gelesen werden – der Property-Zugriff setzt in PyMuPDF 1.28 den
    Entschlüsselungszustand zurück (Inhalte werden danach leer).
    """

    def __init__(self, path: str, doc: "pymupdf.Document",
                 was_encrypted: bool = False, password: str = "",
                 authenticated: bool = True):
        self.path = path
        self.doc = doc
        self.quelle = path            # Datei, die die Sitzung widerspiegelt
        self.encrypted = was_encrypted or bool(doc.is_encrypted)
        self.password = password
        self.authenticated = authenticated
        self.pending_overlays: list[dict] = []
        self.overlay_applied = False
        self.saved_versions: list[str] = []

    def reload_from(self, path: str) -> None:
        newdoc = MuPdfEngine._open_bytes(path)
        self.doc = newdoc
        self.quelle = path
        self.pending_overlays = []
        self.overlay_applied = False


class MuPdfEngine:
    name = "PyMuPDF-Engine"
    priority = 100
    capabilities = {"render", "acroform", "overlay", "tabellen", "seiten",
                    "verschluesselung"}

    # ------------------------------------------------- Verfügbarkeit
    @staticmethod
    def is_available() -> bool:
        return PYMUPDF_OK

    # ------------------------------------------------- Öffnen
    @staticmethod
    def _open_bytes(path: str) -> "pymupdf.Document":
        """Öffnet ein PDF aus dem SPEICHER (Stream), nicht als Datei-
        Handle. Grund: Windows sperrt geöffnete Dateien – sonst könnte
        keine andere Anwendung (und nicht „Dokument neu einlesen“)
        die Datei ändern, solange sie in DocumentAI geöffnet ist."""
        with open(path, "rb") as fh:
            daten = fh.read()
        return pymupdf.open(stream=daten, filetype="pdf")

    def open(self, path: str, password: Optional[str] = None) -> PdfSession:
        if not os.path.exists(path):
            raise DocumentDamagedError(f"Datei nicht gefunden: {path}")
        # MuPDF-Fehlermeldungen (z. B. bei verschlüsselten Dateien) stumm
        # schalten – wir melden kontrolliert über die Diagnose
        suppress = getattr(pymupdf, "TOOLS", None)
        old_state = None
        if suppress is not None and hasattr(suppress, "mupdf_display_errors"):
            try:
                old_state = suppress.mupdf_display_errors(False)
            except Exception:
                old_state = None
        try:
            doc = self._open_bytes(path)
        except Exception as exc:
            raise DocumentDamagedError(str(exc)) from exc
        finally:
            if old_state is not None:
                try:
                    suppress.mupdf_display_errors(old_state)
                except Exception:
                    pass
        # WICHTIG (Ursachenanalyse PyMuPDF 1.28.2): authenticate() MUSS vor
        # jedem Zugriff auf needs_pass erfolgen, und nach ERFOLGREICHER
        # authenticate() darf needs_pass NIE mehr gelesen werden – der
        # Zugriff zerstört sonst den Entschlüsselungszustand des Dokuments.
        code = 0
        if password:
            try:
                code = doc.authenticate(password) or 0
            except Exception:
                code = 0
        if code:
            encrypted_flag = True
        elif doc.needs_pass:                 # nur im nicht-authentifizierten
            encrypted_flag = True            # Zustand erlaubt/schadlos
            doc.close()                      # Handle freigeben!
            if password:
                raise WrongPasswordError(path)
            raise PasswordRequiredError(path)
        else:
            encrypted_flag = bool(doc.is_encrypted)
        # Verifikation nach dem Öffnen: bei verschlüsselten Dokumenten
        # defekte Entschlüsselung erkennen und NEU öffnen (Prüfen →
        # reparieren → erneut prüfen, niemals blind aufgeben).
        if encrypted_flag and not self._lesbar_nach_entschluesselung(doc):
            doc.close()
            doc = self._open_bytes(path)
            if password:
                doc.authenticate(password)
            if not self._lesbar_nach_entschluesselung(doc):
                pass        # trotzdem weiterarbeiten, Diagnose meldet Befund
        session = PdfSession(path, doc, encrypted_flag, password or "",
                             authenticated=bool(code) or not encrypted_flag)
        return session

    @staticmethod
    def _lesbar_nach_entschluesselung(doc: "pymupdf.Document") -> bool:
        """True, wenn nach Authentifizierung Inhalte lesbar sind.

        Greift bewusst NICHT auf doc.needs_pass zu (siehe Kommentar oben).
        """
        try:
            if doc.is_encrypted:
                return False
            for i in range(min(doc.page_count, 3)):
                page = doc.load_page(i)
                if page.get_text("text").strip() or page.get_images():
                    return True
            return doc.page_count == 0
        except Exception:
            return False

    # ------------------------------------------------- Diagnose
    def diagnose(self, session: PdfSession) -> dict:
        doc = session.doc
        out: dict[str, Any] = {
            "format": "PDF",
            "pdf_version": (doc.metadata or {}).get("format", ""),
            "seiten": doc.page_count,
            "text_vorhanden": False,
            "vektorgrafiken": False,
            "bilder": False,
            "ocr_noetig": False,
            "formularfelder": 0,
            "pflichtfelder": 0,
            "annotationen": 0,
            "checkboxen": 0,
            "signaturen": 0,
            "verschluesselt": bool(session.encrypted),
            # wir sind authentifiziert, sonst hätte open() bereits
            # PasswordRequiredError geworfen (needs_pass nie nach Auth!)
            "passwort_erforderlich": False,
            "metadaten": {},
            "eingebettete_dateien": [],
            "pdfa_status": "kein PDF/A erkannt",
            "beschaedigte_objekte": [],
            "warnungen": [],
            "repariert": False,
        }
        text_found = False
        images_found = False
        vectors_found = False
        annot_count = 0
        widgets: list[Any] = []
        limit = min(doc.page_count, MAX_SCAN_PAGES)
        for i in range(limit):
            page = doc.load_page(i)
            if not text_found and page.get_text("text").strip():
                text_found = True
            if not images_found and page.get_images(full=True):
                images_found = True
            if not vectors_found:
                try:
                    if page.get_drawings():
                        vectors_found = True
                except Exception:
                    pass
            try:
                annot_count += page.annot_count() or 0
            except Exception:
                pass
            for w in page.widgets():
                widgets.append(w)
        out["text_vorhanden"] = text_found
        out["bilder"] = images_found
        out["vektorgrafiken"] = vectors_found
        out["annotationen"] = annot_count
        out["ocr_noetig"] = (not text_found) and images_found
        out["formularfelder"] = len(widgets)
        out["pflichtfelder"] = sum(
            1 for w in widgets if (w.field_flags or 0) & _FLAG_REQUIRED)
        out["checkboxen"] = sum(
            1 for w in widgets
            if w.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX)
        out["signaturen"] = sum(
            1 for w in widgets
            if w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE)
        out["bearbeitung_erlaubt"] = self._permission(doc, "edit")
        out["drucken_erlaubt"] = self._permission(doc, "print")
        out["kopieren_erlaubt"] = self._permission(doc, "copy")

        meta = dict(doc.metadata or {})
        out["metadaten"] = {k: v for k, v in meta.items()
                            if v and k != "format"}
        try:
            out["eingebettete_dateien"] = list(doc.embfile_names())
        except Exception:
            pass
        try:
            xmp = doc.get_xml_metadata() or ""
            if "pdfaid" in xmp:
                out["pdfa_status"] = "PDF/A (laut XMP-Metadaten)"
        except Exception:
            pass

        # Zweitmeinung pypdf (streng) zur Strukturintegrität
        try:
            from pypdf import PdfReader
            try:
                reader = PdfReader(session.path, strict=True)
                if reader.is_encrypted and session.password:
                    reader.decrypt(session.password)
                _ = len(reader.pages)
            except Exception as exc:                    # struktureller Fehler
                msg = str(exc).splitlines()[0][:200]
                out["beschaedigte_objekte"].append(msg)
                out["warnungen"].append(
                    f"Strukturwarnung (strenge Prüfung): {msg}")
        except ImportError:
            out["warnungen"].append("pypdf nicht verfügbar – "
                                    "Struktur-Zweitprüfung deaktiviert")
        if doc.page_count > MAX_SCAN_PAGES:
            out["warnungen"].append(
                f"Sehr großes Dokument ({doc.page_count} Seiten) – "
                f"Strukturprüfung auf {MAX_SCAN_PAGES} Seiten begrenzt.")
        return out

    @staticmethod
    def _permission(doc: "pymupdf.Document", what: str) -> bool:
        try:
            perm = doc.permissions
            if isinstance(perm, dict):
                return bool(perm.get(what, True))
            value = int(perm)
            bits = {"print": 1 << 2, "edit": 1 << 3,
                    "copy": 1 << 4, "annotate": 1 << 5}
            if value in (-1, 0xFFFFFFFF >> 4):        # alles erlaubt
                pass
            return bool(value & bits.get(what, 0xFFFF))
        except Exception:
            return True                                # Unbekannt => nicht blocken

    # ------------------------------------------------- Seiten extrahieren
    def extract_pages(self, session: PdfSession,
                      ocr_engine: Optional[Any] = None,
                      progress: Optional[Callable] = None) -> list[PageModel]:
        doc = session.doc
        pages: list[PageModel] = []
        for i in range(doc.page_count):
            page = doc.load_page(i)
            pm = PageModel(number=i, width=page.rect.width,
                           height=page.rect.height)
            words = page.get_text("words")            # x0 y0 x1 y1 w b l n
            for x0, y0, x1, y1, wtext, blk, ln, _wn in words:
                pm.words.append(Word(
                    text=wtext,
                    rect=Rect4.from_xy0xy1(x0, y0, x1, y1),
                    block=blk, line=ln, confidence=100.0))
            pm.text = page.get_text("text")
            try:
                pm.image_count = len(page.get_images(full=True))
            except Exception:
                pm.image_count = 0
            try:
                pm.drawing_count = len(page.get_drawings())
            except Exception:
                pm.drawing_count = 0

            if not pm.words and pm.image_count:
                pm.needs_ocr = True
                # Integrierte OCR ZUERST (in PyMuPDF einkompiliert): das
                # ist der Produktionspfad beim Nutzer (kein tesseract.exe
                # nötig – nur den tessdata-Ordner, der der App beiliegt).
                integriert = self._ocr_integriert(page)
                if integriert:
                    pm.words = integriert
                    pm.ocr_applied = True
                    pm.ocr_integriert = True
                    pm.text = " ".join(w.text for w in pm.words)
                elif ocr_engine is not None:
                    # Rückfall: externe Tesseract-Binary, falls die
                    # integrierte Engine nichts liefern konnte.
                    try:
                        png = self.render_page(session, i, dpi=200)
                        ocr_words = ocr_engine.ocr_page(png)
                        if ocr_words:
                            pm.words = ocr_words
                            pm.ocr_applied = True
                            pm.text = " ".join(w.text for w in pm.words)
                            confs = [w.confidence for w in pm.words]
                            pm.low_confidence = (
                                sum(confs) / len(confs) < 60.0)
                    except Exception:
                        pm.words = []
            pages.append(pm)
            if progress:
                progress(i + 1, doc.page_count)
        return pages

    # ------------------------------------------------ Integrierte OCR
    def ocr_seite(self, session: PdfSession, pno: int) -> list[Word]:
        """Integrierte OCR für eine Seite (öffentlich, für die
        Nachanalyse ohne volle Neu-Analyse)."""
        return self._ocr_integriert(session.doc.load_page(pno))

    def _ocr_integriert(self, page: "pymupdf.Page") -> list[Word]:
        """OCR über die in MuPDF einkompilierte Tesseract-Engine.
        Läuft komplett lokal, ohne externe Binary; liefert [] wenn
        kein tessdata-Ordner gefunden wurde."""
        from ..services.tools import tessdata_pfad_fuer_tesseract
        tessdata = tessdata_pfad_fuer_tesseract()
        if not tessdata:
            return []
        try:
            tp = page.get_textpage_ocr(language="deu+eng", dpi=200,
                                       full=True, tessdata=tessdata,
                                       flags=0)
            roh = page.get_text("words", textpage=tp)
            return [Word(text=w[4], rect=Rect4.from_xy0xy1(*w[:4]),
                         confidence=80.0)
                    for w in roh if w[4].strip()]
        except Exception:
            return []

    # ------------------------------------------------- AcroForm-Felder
    def get_acroform_fields(self, session: PdfSession) -> list[FieldModel]:
        fields: list[FieldModel] = []
        for pno in range(session.doc.page_count):
            page = session.doc.load_page(pno)
            for w in page.widgets():
                ftype = _WIDGET_TYPE_MAP.get(w.field_type, "text")
                rect = Rect4.from_xy0xy1(w.rect.x0, w.rect.y0,
                                         w.rect.x1, w.rect.y1)
                label = self._label_near(page, rect)
                value = w.field_value
                if ftype == "checkbox":
                    value = self._checkbox_state(w)
                options: list[str] = []
                try:
                    options = [str(o) for o in (w.choice_values or [])]
                except Exception:
                    options = []
                fields.append(FieldModel(
                    id=f"acro::{pno}::{w.field_name}",
                    name=w.field_name,
                    label=label or w.field_name,
                    field_type=ftype,
                    required=bool((w.field_flags or 0) & _FLAG_REQUIRED),
                    value=value,
                    original_value=value,
                    page=pno,
                    rect=rect,
                    source="acroform",
                    confidence=0.99,
                    options=options,
                    read_only=bool((w.field_flags or 0) & _FLAG_READONLY),
                    max_len=getattr(w, "text_maxlen", None) or None,
                    font_size=float(getattr(w, "text_fontsize", 0) or 0),
                ))
        return fields

    @staticmethod
    def _checkbox_state(w: Any) -> Any:
        try:
            if getattr(w, "on_state", None) and w.field_value:
                on = w.on_state()
                if isinstance(w.field_value, (bool, int)):
                    return bool(w.field_value)
                return str(w.field_value) in (str(on), "Yes", "On", "true")
        except Exception:
            pass
        return w.field_value

    @staticmethod
    def _label_near(page: "pymupdf.Page", rect: Rect4) -> str:
        """Sucht die Beschriftung links neben / ueber einem Feld."""
        try:
            words = page.get_text("words")
        except Exception:
            return ""
        best: tuple[float, str] = (1e9, "")
        for x0, y0, x1, y1, wtext, *_ in words:
            # links daneben, vertikal ueberlappend
            if x1 <= rect.x + 2 and not (y1 < rect.y - 4 or y0 > rect.y + rect.height + 4):
                dist = rect.x - x1
                if 0 <= dist < 120 and dist < best[0]:
                    best = (dist, wtext)
            # direkt darueber
            elif abs(y1 - rect.y) < 6 and abs((x0 + x1) / 2 - (rect.x + rect.width / 2)) < 200:
                dist = 50 + abs(x0 - rect.x) * 0.1
                if dist < best[0]:
                    best = (dist, wtext)
        return best[1]

    # ------------------------------------------------- Rendern
    def render_page(self, session: PdfSession, page: int,
                    dpi: int = 150) -> bytes:
        pix = session.doc.load_page(page).get_pixmap(dpi=dpi)
        return pix.tobytes("png")

    # ------------------------------------------------- Tabellen
    def find_tables(self, session: PdfSession) -> list[TableData]:
        # Cache: Tabellenerkennung ist teuer und wurde zuvor bis zu 3x
        # pro Analyse ausgefuehrt (Detektor, Analyse, Validierung).
        # Geaenderte Dokumente invalidieren den Cache (siehe annotate).
        if getattr(session, "_tables_cache_all", None) is not None:
            return session._tables_cache_all
        tables: list[TableData] = []
        for pno in range(session.doc.page_count):
            page = session.doc.load_page(pno)
            try:
                finder = page.find_tables()
            except Exception:
                continue
            for tab in finder.tables:
                try:
                    rows = tab.extract()
                except Exception:
                    rows = []
                # Zellen säubern: None (leere/verbundene Zellen) → ""
                # – rigoros VOR allen Weiterverwendungen (auch Header-
                # Fallback), sonst crasht z. B. die Validierung mit
                # "'NoneType' object has no attribute 'lower'".
                rows = [[("" if c is None else str(c)) for c in row]
                        for row in rows]
                header: list[str] = []
                try:
                    names = tab.header.get("names")
                    if names:
                        header = [str(n or "") for n in names]
                except Exception:
                    header = list(rows[0]) if rows else []
                tables.append(TableData(
                    page=pno,
                    bbox=Rect4.from_xy0xy1(tab.bbox[0], tab.bbox[1],
                                           tab.bbox[2], tab.bbox[3]),
                    header=header,
                    rows=[[("" if c is None else str(c)) for c in row]
                          for row in rows],
                    zellen=[Rect4.from_xy0xy1(*z) for z in (tab.cells or [])
                            if z and len(z) == 4]))
        session._tables_cache_all = tables
        return tables

    # ------------------------------------------------- Befüllen
    def fill_fields(self, session: PdfSession,
                    assignments: dict[str, Any]) -> dict:
        """assignments: field_id -> Wert. AcroForm direkt, visuell als Overlay."""
        result = {"ok": [], "fehler": [], "overlay": []}
        by_id: dict[str, Any] = {}
        for pno in range(session.doc.page_count):
            page = session.doc.load_page(pno)
            for w in page.widgets():
                by_id[f"acro::{pno}::{w.field_name}"] = (page, w)
        for field_id, value in assignments.items():
            if field_id in by_id:
                page, w = by_id[field_id]
                try:
                    if w.field_type == pymupdf.PDF_WIDGET_TYPE_CHECKBOX:
                        w.field_value = bool(value)
                    else:
                        w.field_value = "" if value is None else str(value)
                    w.update()
                    result["ok"].append(field_id)
                except Exception as exc:
                    result["fehler"].append((field_id, str(exc)))
            else:
                result["overlay"].append(field_id)
        try:
            session.doc.need_appearances(True)      # Viewer sollen Werte zeichnen
        except Exception:
            pass
        return result

    def queue_overlay(self, session: PdfSession, page: int, rect: Rect4,
                      value: Any, field_type: str = "text",
                      font_size: float = 0.0, ersetze: bool = False,
                      tinte: Optional[Rect4] = None,
                      linie: Optional[tuple[float, float]] = None) -> None:
        session.pending_overlays.append({
            "page": page, "rect": rect, "value": value,
            "typ": field_type, "font_size": font_size,
            "ersetze": ersetze, "tinte": tinte, "linie": linie,
        })

    def apply_overlays(self, session: PdfSession) -> dict:
        """Text in erkannte visuelle Felder schreiben (Auto-Schriftpassung).

        Mit ersetze=True wird der ALTE Eintrag (auch Handschrift im Scan)
        vorher per Redaktion pixelgenau entfernt – die Formularlinie
        selbst bleibt erhalten (graphics=LINE_ART_NONE + Tinte-Rechteck
        oberhalb der Linie)."""
        stats = {"angelegt": 0, "verkleinert": 0, "passgenau": 0,
                 "ersetzt": 0, "fehler": []}
        # --- Phase 1: Ersetzungen (Redaktionen) je Seite EINMAL anwenden
        redaktions_seiten: set[int] = set()
        for ov in session.pending_overlays:
            if not ov.get("ersetze"):
                continue
            try:
                page = session.doc.load_page(ov["page"])
                r = ov.get("tinte") or ov["rect"]
                feld = ov["rect"]
                rot_liste: list[pymupdf.Rect] = []
                if ov["typ"] == "checkbox":
                    # strikt innen: der Kastenrand bleibt stehen
                    rahmen = pymupdf.Rect(feld.x + 1.2, feld.y + 1.2,
                                          feld.x + feld.width - 1.2,
                                          feld.y + feld.height - 1.2)
                    rot = pymupdf.Rect(r.x - 1.5, r.y - 1.5,
                                       r.x + r.width + 1.5,
                                       r.y + r.height + 1.5) & rahmen
                    if not rot.is_empty:
                        rot_liste.append(rot)
                else:
                    # Textfeld: die Feldlinie (unter dem Eintrag) bleibt
                    # erhalten. Das geschützte Band folgt der ERKANNTEN
                    # Liniendicke (Render ist breiter als die Vektor-
                    # Geometrie); Ober- und Unterlängen werden getrennt
                    # ober- und unterhalb des Bands entfernt.
                    ly0, ly1 = ov.get("linie") or (0.0, 0.0)
                    if ly1 <= ly0:
                        ly0 = feld.y + feld.height - 0.4
                        ly1 = feld.y + feld.height + 0.4
                    linie_top = min(ly0, feld.y + feld.height) - 0.3
                    linie_bot = max(ly1, feld.y + feld.height + 0.8) + 0.35
                    voll = pymupdf.Rect(r.x - 1.5, r.y - 1.5,
                                        r.x + r.width + 1.5,
                                        r.y + r.height + 1.5)
                    rahmen_oben = pymupdf.Rect(feld.x, feld.y - 1.0,
                                               feld.x + feld.width, linie_top)
                    rahmen_unten = pymupdf.Rect(feld.x, linie_bot,
                                                feld.x + feld.width,
                                                feld.y + feld.height + 6.5)
                    for teil in (
                            pymupdf.Rect(voll.x0, voll.y0, voll.x1,
                                         min(voll.y1, linie_top)) & rahmen_oben,
                            pymupdf.Rect(voll.x0, max(voll.y0, linie_bot),
                                         voll.x1, voll.y1) & rahmen_unten):
                        if not teil.is_empty and teil.width > 0 \
                                and teil.height > 0:
                            rot_liste.append(teil)
                for rot in rot_liste:
                    page.add_redact_annot(rot, fill=(1, 1, 1))
                if rot_liste:
                    redaktions_seiten.add(ov["page"])
                    stats["ersetzt"] += 1
            except Exception as exc:
                stats["fehler"].append((ov.get("rect"), str(exc)))
        for pno in redaktions_seiten:
            try:
                page = session.doc.load_page(pno)
                page.apply_redactions(
                    images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                    graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                    text=pymupdf.PDF_REDACT_TEXT_REMOVE)
            except Exception as exc:
                stats["fehler"].append((f"Seite {pno + 1}", str(exc)))
        # --- Phase 2: neue Werte eintragen ------------------------------
        for ov in session.pending_overlays:
            try:
                page = session.doc.load_page(ov["page"])
                rect = ov["rect"]
                value = ov["value"]
                if value is None:
                    continue
                if ov["typ"] == "checkbox":
                    if value:
                        box = pymupdf.Rect(rect.x, rect.y, rect.x + rect.height,
                                           rect.y + rect.height)
                        page.insert_textbox(box, "X", fontsize=10,
                                            fontname="helv", align=1)
                    stats["angelegt"] += 1
                    continue
                text = str(value).strip()
                if not text:
                    continue
                box = pymupdf.Rect(rect.x, rect.y - 1.5,
                                   rect.x + rect.width + 2,
                                   rect.y + max(rect.height, 3) + 2)
                fs = ov["font_size"] or 10.0
                fitted = False
                while fs >= 5.0:
                    if page.insert_textbox(box, text, fontsize=fs,
                                           fontname="helv",
                                           color=(0, 0, 0.6)) >= 0:
                        fitted = True
                        break
                    fs -= 0.5
                if not fitted:
                    page.insert_textbox(box, text, fontsize=5.0,
                                        fontname="helv", color=(0, 0, 0.6))
                    stats["verkleinert"] += 1
                elif fs < (ov["font_size"] or 10.0):
                    stats["verkleinert"] += 1
                else:
                    stats["passgenau"] += 1
                stats["angelegt"] += 1
            except Exception as exc:
                stats["fehler"].append((ov.get("rect"), str(exc)))
        session.pending_overlays = []
        session.overlay_applied = True
        return stats

    # ------------------------------------------------- Seitenoperationen
    def rotate_page(self, session: PdfSession, page: int, deg: int) -> None:
        session._tables_cache = None
        session._tables_cache_all = None
        session.doc.load_page(page).set_rotation(
            (session.doc.load_page(page).rotation + deg) % 360)

    def delete_page(self, session: PdfSession, page: int) -> None:
        session.doc.delete_page(page)

    def move_page(self, session: PdfSession, frm: int, to: int) -> None:
        session.doc.move_page(frm, to)

    # ------------------------------------------------- Speichern
    def save_version(self, session: PdfSession, model: Any,
                     reason: str = "bearbeitet") -> dict:
        """Erzeugt eine NEUE Version; das Original wird nie ueberschrieben."""
        from ..services import versioning

        if session.pending_overlays:
            stats = self.apply_overlays(session)
            audit.log(model, "Overlay-Änderungen angewendet",
                      f"{stats['angelegt']} Elemente, "
                      f"{stats['verkleinert']} verkleinert")
        dest = versioning.next_version_path(model.path)
        kwargs: dict[str, Any] = {"garbage": 3, "deflate": True}
        if session.doc.is_encrypted:
            kwargs["encryption"] = pymupdf.PDF_ENCRYPT_KEEP
        session.doc.save(dest, **kwargs)
        session.saved_versions.append(dest)
        audit.log(model, "Neue PDF-Version erzeugt",
                  f"{os.path.basename(dest)} ({reason})")
        pruefung = self.verify_saved(dest, model)
        audit.log(model, "PDF-Struktur geprüft",
                  "OK" if pruefung["ok"] else "; ".join(pruefung["probleme"]))
        # Wichtig für Scans: Nach doc.save() würde eine SPÄTERE Redaktion
        # (pixelgenaue Ersetzung) das Seitenbild komplett entfernen –
        # MuPDF-Verhalten nach dem Neuschreiben. Die Sitzung arbeitet
        # daher ab jetzt sicherheitshalber auf der gespeicherten Datei.
        try:
            frisch = self._open_bytes(dest)
            if frisch.needs_pass:
                if not frisch.authenticate(session.password or ""):
                    raise RuntimeError("Passwort nach Neuladen falsch")
            alt = session.doc
            session.doc = frisch
            session.quelle = dest
            session.pending_overlays = []
            session.overlay_applied = False
            alt.close()
        except Exception:
            pass                       # Best Effort: alte Sitzung bleibt
        return {"pfad": dest, "pruefung": pruefung}

    def verify_saved(self, path: str, model: Any) -> dict:
        """Gespeicherte Datei erneut oeffnen und pruefen."""
        result = {"ok": True, "probleme": [], "seiten": 0, "felder": 0}
        try:
            check = self._open_bytes(path)
        except Exception as exc:
            result["ok"] = False
            result["probleme"].append(f"Nicht öffnbar: {exc}")
            return result
        result["seiten"] = check.page_count
        if check.page_count != len(model.pages):
            result["ok"] = False
            result["probleme"].append(
                f"Seitenzahl weicht ab: {check.page_count} != {len(model.pages)}")
        nfields = 0
        try:
            for pno in range(check.page_count):
                nfields += len(list(check.load_page(pno).widgets()))
        except Exception:
            pass
        result["felder"] = nfields
        check.close()
        return result
