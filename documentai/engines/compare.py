"""Dokumentvergleich: Textdiff, Felddiff und visueller Vergleich."""
from __future__ import annotations

import difflib
import os
from typing import Any

from ..core.models import DocumentModel

try:
    from PIL import Image, ImageChops, ImageDraw
    PIL_OK = True
except Exception:
    PIL_OK = False


def compare_models(model_a: DocumentModel, model_b: DocumentModel,
                   session_a: Any = None, session_b: Any = None,
                   engine: Any = None, dpi: int = 100) -> dict:
    """Vergleicht zwei Dokumentversionen miteinander."""
    result: dict = {"text_aenderungen": [], "feld_aenderungen": [],
                    "visuell": {"verfuegbar": False, "bilder": [], "boxen": []},
                    "identisch": True}

    # ---- Textdiff je Seite ------------------------------------------
    pages = min(len(model_a.pages), len(model_b.pages))
    for i in range(pages):
        wa = (model_a.pages[i].text or "").split()
        wb = (model_b.pages[i].text or "").split()
        sm = difflib.SequenceMatcher(a=wa, b=wb, autojunk=False)
        if sm.ratio() == 1.0:
            continue
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                continue
            result["text_aenderungen"].append({
                "seite": i + 1,
                "art": {"replace": "geändert", "delete": "entfernt",
                        "insert": "hinzugefügt"}.get(tag, tag),
                "vorher": " ".join(wa[i1:i2])[:120],
                "nachher": " ".join(wb[j1:j2])[:120],
            })
    if len(model_a.pages) != len(model_b.pages):
        result["text_aenderungen"].append({
            "seite": pages + 1, "art": "seitenzahl",
            "vorher": f"{len(model_a.pages)} Seiten",
            "nachher": f"{len(model_b.pages)} Seiten"})

    # ---- Felddiff ----------------------------------------------------
    # AcroForm-Felder sind maßgeblich: Bei doppeltem Kanoniker
    # (AcroForm-Widget + visuell erkanntes Feld) gewinnt das echte
    # Widget – visuelle Zwillingsfelder verfälschen sonst den Wert.
    def _felder_nach_key(model: DocumentModel) -> dict:
        out: dict = {}
        for f in sorted(model.fields,
                        key=lambda x: (x.source != "acroform")):
            key = f.canonical or f.name
            if key not in out:
                out[key] = f
        return out

    fields_a = _felder_nach_key(model_a)
    fields_b = _felder_nach_key(model_b)
    for key in sorted(set(fields_a) | set(fields_b)):
        fa, fb = fields_a.get(key), fields_b.get(key)
        va = None if fa is None else fa.value
        vb = None if fb is None else fb.value
        if str(va) != str(vb):
            result["feld_aenderungen"].append({
                "feld": key,
                "vorher": "" if va is None else str(va),
                "nachher": "" if vb is None else str(vb),
            })

    # ---- Visueller Vergleich ----------------------------------------
    if PIL_OK and engine is not None and session_a is not None \
            and session_b is not None:
        try:
            result["visuell"] = _visual_diff(model_a, model_b, session_a,
                                             session_b, engine, dpi)
        except Exception:
            pass

    result["identisch"] = (not result["text_aenderungen"]
                           and not result["feld_aenderungen"])
    return result


def _visual_diff(model_a, model_b, session_a, session_b, engine, dpi) -> dict:
    from ..paths import reports_dir
    out = {"verfuegbar": True, "bilder": [], "boxen": []}
    n = min(len(model_a.pages), len(model_b.pages), 50)
    for i in range(n):
        png_a = engine.render_page(session_a, i, dpi=dpi)
        png_b = engine.render_page(session_b, i, dpi=dpi)
        import io
        img_a = Image.open(io.BytesIO(png_a)).convert("RGB")
        img_b = Image.open(io.BytesIO(png_b)).convert("RGB")
        if img_a.size != img_b.size:
            img_b = img_b.resize(img_a.size)
        diff = ImageChops.difference(img_a, img_b).convert("L")
        boxes = _changed_regions(diff, tile=24, threshold=35)
        if not boxes:
            continue
        draw = ImageDraw.Draw(img_b)
        for (x0, y0, x1, y1) in boxes:
            draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=3)
        name = f"vergleich_s{i + 1}_{os.path.splitext(model_a.name)[0]}.png"
        path = os.path.join(reports_dir(), name)
        img_b.save(path)
        out["bilder"].append(path)
        out["boxen"].append({"seite": i + 1, "regionen": len(boxes)})
    return out


def _changed_regions(diff_img, tile: int = 24, threshold: int = 35):
    """Änderungsrechtecke über Kachelvergleich ermitteln."""
    w, h = diff_img.size
    changed: list[tuple[int, int, int, int]] = []
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            box = diff_img.crop((x, y, min(x + tile, w), min(y + tile, h)))
            hist = box.histogram()
            bright = sum(hist[threshold:])          # Pixel über Schwelle
            if bright > max(4, (box.size[0] * box.size[1]) * 0.06):
                changed.append((x, y, min(x + tile, w), min(y + tile, h)))
    if not changed:
        return []
    # Zusammenfassen benachbarter Kacheln
    merged: list[list[int]] = []
    for x0, y0, x1, y1 in changed:
        for m in merged:
            if not (x1 < m[0] - tile or x0 > m[2] + tile or
                    y1 < m[1] - tile or y0 > m[3] + tile):
                m[0], m[1] = min(m[0], x0), min(m[1], y0)
                m[2], m[3] = max(m[2], x1), max(m[3], y1)
                break
        else:
            merged.append([x0, y0, x1, y1])
    # Solange überlappende vereinen
    again = True
    while again:
        again = False
        for i in range(len(merged)):
            for j in range(i + 1, len(merged)):
                a, b = merged[i], merged[j]
                if not (a[2] < b[0] or b[2] < a[0] or
                        a[3] < b[1] or b[3] < a[1]):
                    merged[i] = [min(a[0], b[0]), min(a[1], b[1]),
                                 max(a[2], b[2]), max(a[3], b[3])]
                    merged.pop(j)
                    again = True
                    break
            if again:
                break
    return [tuple(m) for m in merged]


def format_text_diff(result: dict) -> str:
    """Druckbare Gegenüberstellung (ORIGINAL vs. NEUE VERSION)."""
    lines = [f"{'ORIGINAL':<40}NEUE VERSION", "-" * 78]
    for ch in result["text_aenderungen"]:
        if ch["art"] == "geändert":
            lines.append(f"{ch['vorher']:<40}{ch['nachher']}")
            lines.append(f"{'':<40}^ geändert (Seite {ch['seite']})")
        elif ch["art"] == "entfernt":
            lines.append(f"{ch['vorher']:<40}— entfernt (Seite {ch['seite']})")
        elif ch["art"] == "hinzugefügt":
            lines.append(f"{'':<40}{ch['nachher']}  ^ neu "
                         f"(Seite {ch['seite']})")
        else:
            lines.append(f"Seitenzahl: {ch['vorher']} -> {ch['nachher']}")
    for fd in result["feld_aenderungen"]:
        lines.append(f"[Feld] {fd['feld']}: '{fd['vorher']}' -> "
                     f"'{fd['nachher']}'")
    if result["identisch"]:
        lines.append("Keine Unterschiede gefunden.")
    return "\n".join(lines)
