"""Signatur- und Schutzanalyse.

Sicherheitsprinzip: nur analysieren und informieren – niemals
Signaturen manipulieren, Zertifikate fälschen oder Spuren entfernen.
"""
from __future__ import annotations

from typing import Any

from ..core import audit
from ..core.models import DocumentModel


class SignatureAnalyzer:
    name = "Signatur-Analyse"

    @staticmethod
    def is_available() -> bool:
        return True

    # ------------------------------------------------------------------
    def analyze(self, session: Any, model: DocumentModel) -> dict:
        info: dict = {"vorhanden": False, "eintraege": [], "sig_flags": "",
                      "integritaet": "nicht signiert"}
        doc = session.doc
        try:
            flags = doc.xref_get_key(doc.pdf_catalog(), "AcroForm/SigFlags")
            if flags and flags[0] != "null":
                info["sig_flags"] = str(flags[1])
        except Exception:
            pass

        entries: list[dict] = []
        for pno in range(doc.page_count):
            page = doc.load_page(pno)
            for annots_or_widgets in ([], ):
                pass
            widgets = []
            try:
                widgets = list(page.widgets())
            except Exception:
                widgets = []
            for w in widgets:
                if w.field_type == 6:               # PDF_WIDGET_TYPE_SIGNATURE
                    entries.append(self._describe_widget(doc, pno, w))

        info["vorhanden"] = bool(entries)
        info["eintraege"] = entries
        if entries:
            info["integritaet"] = (
                "Signaturwert vorhanden – kryptografische Prüfung wird "
                "nicht durchgeführt; Änderungen können die Signatur "
                "ungültig machen.")
            audit.log(model, "Digitale Signatur erkannt",
                      f"{len(entries)} Signaturfeld(er)")
        return info

    # ------------------------------------------------------------------
    def _describe_widget(self, doc: Any, pno: int, w: Any) -> dict:
        entry: dict = {"seite": pno + 1, "feld": w.field_name,
                       "unterzeichner": None, "zeitpunkt": None,
                       "grund": None, "ort": None,
                       "byte_range": None, "wert_vorhanden": False,
                       "zertifikat": None}
        try:
            for key, target in (("Name", "unterzeichner"), ("M", "zeitpunkt"),
                                ("Reason", "grund"), ("Location", "ort"),
                                ("ByteRange", "byte_range"),
                                ("Contents", "wert_vorhanden"),
                                ("Cert", "zertifikat")):
                try:
                    kind, value = doc.xref_get_key(w.xref, f"V/{key}")
                    if kind in ("string", "text", "array", "dict") and \
                            value not in ("null", "None", ""):
                        entry[target] = str(value)[:120]
                except Exception:
                    continue
        except Exception:
            pass
        if entry["wert_vorhanden"]:
            entry["status"] = "Signaturwert vorhanden"
        else:
            entry["status"] = "Leeres Signaturfeld (noch nicht signiert)"
        return entry

    # ------------------------------------------------------------------
    @staticmethod
    def protection_summary(model: DocumentModel) -> str:
        """Lesbare Zusammenfassung des Schutzstatus."""
        d = model.diagnosis
        sig = model.signature_info or {}
        parts: list[str] = []
        if d.get("verschluesselt"):
            parts.append("verschlüsselt")
        if d.get("passwort_erforderlich"):
            parts.append("Passwort erforderlich")
        if not d.get("bearbeitung_erlaubt", True):
            parts.append("Bearbeitung eingeschränkt")
        if not d.get("drucken_erlaubt", True):
            parts.append("Drucken eingeschränkt")
        if not d.get("kopieren_erlaubt", True):
            parts.append("Kopieren eingeschränkt")
        if sig.get("vorhanden"):
            parts.append("digital signiert")
        return "Normales PDF" if not parts else ", ".join(parts)
