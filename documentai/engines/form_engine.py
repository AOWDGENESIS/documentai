"""Formular-Engine: Daten (nach Benutzerbestätigung) in Felder schreiben."""
from __future__ import annotations

from typing import Any

from ..core import audit
from ..core.models import DocumentModel


class FormEngine:
    name = "Formular-Engine"

    @staticmethod
    def is_available() -> bool:
        return True

    # ------------------------------------------------------------------
    def build_assignments(self, model: DocumentModel, profile: dict,
                          semantic: Any) -> list[dict]:
        """Semantische Zuordnung Profildaten -> Felder (ungeprüft)."""
        return semantic.match_profile(model.fields, profile or {})

    # ------------------------------------------------------------------
    def apply_assignments(self, session: Any, engine: Any,
                          model: DocumentModel,
                          assignments: list[dict]) -> dict:
        """Wendet geprüfte Zuordnungen an. Original bleibt unberührt;
        Änderungen landen in der In-Memory-Sitzung bis zur neuen Version."""
        acro: dict[str, Any] = {}
        overlay: list[dict] = []
        for a in assignments:
            f = model.field_by_id(a["feld_id"])
            if f is None or f.read_only:
                continue
            value = a["wert"]
            if f.source == "acroform":
                acro[f.id] = (True if f.field_type == "checkbox" else value)
            else:
                # Alten Eintrag (Handschrift/Text im Scan oder Fließtext)
                # pixelgenau ersetzen, wenn vorhandener Inhalt erkannt wurde
                ersetze = bool(getattr(f, "tinte_rect", None)) or \
                    bool(f.original_value)
                linie = None
                if getattr(f, "linie_y1", 0.0):
                    linie = (f.linie_y0, f.linie_y1)
                overlay.append({"page": f.page, "rect": f.rect,
                                "value": value, "typ": f.field_type,
                                "font_size": f.font_size,
                                "ersetze": ersetze,
                                "tinte": getattr(f, "tinte_rect", None),
                                "linie": linie})
        result = {"acro": {"ok": [], "fehler": []}, "overlay": 0}
        if acro:
            res = engine.fill_fields(session, acro)
            result["acro"] = res
            for fid in res["ok"]:
                _set_value(model, fid, acro[fid])
                audit.log(model, "Feld geändert",
                          f'"{_label_of(model, fid)}" = '
                          f"{str(acro[fid])[:40]}")
        for ov in overlay:
            engine.queue_overlay(session, ov["page"], ov["rect"], ov["value"],
                                 ov["typ"], ov["font_size"],
                                 ersetze=ov.get("ersetze", False),
                                 tinte=ov.get("tinte"),
                                 linie=ov.get("linie"))
            result["overlay"] += 1
            _set_value(model, _field_id_for_overlay(model, ov), ov["value"])
            audit.log(model, "Feld geändert (Overlay)",
                      f'Seite {ov["page"] + 1}: '
                      f"{str(ov['value'])[:40]}")
        model.edited = True
        audit.log(model, "Zuweisungen angewendet",
                  f"{len(result['acro']['ok'])} AcroForm, "
                  f"{result['overlay']} Overlay")
        return result

    # ------------------------------------------------------------------
    def fill_document(self, session: Any, engine: Any, model: DocumentModel,
                      assignments: list[dict], confirm: bool = True) -> dict:
        """Vollständiger Ablauf inkl. Bestätigungspflicht.

        confirm=True verlangt, dass der Aufrufer die Zuordnungen bereits
        vom Benutzer prüfen ließ (GUI-Dialog / CLI-Rückfrage).
        """
        if confirm and not assignments:
            audit.log(model, "Befüllung abgebrochen", "keine Zuordnungen")
            return {"abgebrochen": True}
        return self.apply_assignments(session, engine, model, assignments)


def _set_value(model: DocumentModel, field_id: str, value: Any) -> None:
    f = model.field_by_id(field_id)
    if f is not None:
        f.value = value


def _label_of(model: DocumentModel, field_id: str) -> str:
    f = model.field_by_id(field_id)
    return (f.label or f.name) if f else field_id


def _field_id_for_overlay(model: DocumentModel, ov: dict) -> str:
    for f in model.fields:
        if f.page == ov["page"] and f.rect == ov["rect"]:
            return f.id
    return ""
