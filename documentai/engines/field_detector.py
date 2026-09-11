"""Visuelle Felderkennung: Unterstrichfelder, Kästchen, Linien, Labels.

Erkennt auch ohne echte PDF-Formularfelder Strukturen wie
    Name: ______________________
    Geburtsdatum: ______________
    ☐ Ja   ☐ Nein
und erzeugt daraus strukturierte Feldmodelle mit Position + Konfidenz.
"""
from __future__ import annotations

import re
from typing import Any

from ..core.models import DocumentModel, FieldModel, PageModel, Rect4, Word
from .semantic import infer_type, match_canonical

UNDERSCORE_RE = re.compile(r"^[_.]{3,}$")
CHECKBOX_GLYPHS = {"☐", "□", "◻", "▣", "■", "[ ]", "[]"}
REQUIRED_MARK = re.compile(r"(\*|\(pflicht\)|pflichtfeld)", re.I)
MIN_LINE_LEN = 28.0          # Mindestlänge einer Feldlinie in Punkten
BOX_MIN, BOX_MAX = 6.0, 18.0  # Größenbereich erkannter Checkbox-Kästchen


class VisualFieldDetector:
    name = "Visueller Feld-Detektor"
    priority = 100

    @staticmethod
    def is_available() -> bool:
        return True

    # ------------------------------------------------------------------
    def detect(self, model: DocumentModel, session: Any = None) -> list[FieldModel]:
        fields: list[FieldModel] = []
        occupied = [(f.page, f.rect) for f in model.fields if f.rect]
        for page in model.pages:
            fields.extend(self._detect_page(page, session, occupied))
        return self._dedupe(fields)

    # ------------------------------------------------ Doppelbenennung
    @staticmethod
    def _dedupe(fields: list[FieldModel]) -> list[FieldModel]:
        """Zwei Erkennungsregeln (Unterstriche + Scan-Lücken) können
        dieselbe Zeile JEWEILS melden – „Vorname“ erschien doppelt in
        der Zuordnungsliste (Nutzerfund 04.09.2026). Duplikat, wenn
        gleiche Seite UND (gleiches canonical ODER slug) UND
        (Rect-Überlappung ODER Zeilenmitten < 14 pt). Verschiedene
        Seiten bleiben erlaubt (mehrseitige Formulare!)."""
        out: list[FieldModel] = []
        for f in fields:
            doppelt = False
            for behalten in out:
                if behalten.page != f.page:
                    continue
                slug_a = getattr(behalten, "slug", "") or ""
                slug_b = getattr(f, "slug", "") or ""
                if (behalten.canonical and behalten.canonical == f.canonical
                        ) or (slug_a and slug_a == slug_b):
                    if f.rect and behalten.rect:
                        r1, r2 = behalten.rect, f.rect
                        ueberl = not (r2.x >= r1.x + r1.width
                                      or r2.x + r2.width <= r1.x
                                      or r2.y >= r1.y + r1.height
                                      or r2.y + r2.height <= r1.y)
                        mitte1 = r1.y + r1.height / 2
                        mitte2 = r2.y + r2.height / 2
                        if ueberl or abs(mitte1 - mitte2) < 14:
                            doppelt = True
                            break
                    else:
                        doppelt = True
                        break
            if not doppelt:
                out.append(f)
        return out

    # ------------------------------------------------------------------
    def _detect_page(self, page: PageModel, session: Any,
                     occupied: list) -> list[FieldModel]:
        out: list[FieldModel] = []
        words = sorted(page.words, key=lambda w: (round(w.rect.y, 1),
                                                  w.rect.x))

        # --- 1) Unterstrich-Felder -----------------------------------
        for w in words:
            if UNDERSCORE_RE.match(w.text) and w.rect.width >= 15:
                rect = Rect4(w.rect.x + 1, w.rect.y - 2, w.rect.width,
                             max(w.rect.height, 8))
                label = self._label_left(words, w)
                if not label:
                    label = self._label_above(words, w)
                if not label:
                    # Unterschrifts-/Schreiblinien haben ihre Be-
                    # schriftung oft UNTER der Linie (Nutzerfund
                    # 10.09.2026: „Feld 3“ statt „Unterschrift
                    # Erziehungsberechtigte“)
                    label = self._label_below(words, w)
                if self._overlaps_any(page.number, rect, occupied):
                    continue
                out.append(self._make_field(page.number, rect, label,
                                             "text", len(out)))

        # --- 2) Gezeichnete Feldlinien -------------------------------
        # Acrobat-Prinzip: Der Text gehört AUF die Linie („just above the
        # baseline“). Durchgehende Zeilenlinien (Word-Formulare) werden
        # deshalb an den Labels, die AUF der Linie sitzen, in Abschnitte
        # geteilt – hinter jedem Label genau ein Feld (Nutzerfund
        # 09.09.2026: Riesenfelder über ganze Zeilen = falsch).
        if session is not None:
            try:
                drawings = session.doc.load_page(page.number).get_drawings()
            except Exception:
                drawings = []
            table_bboxes = [t.bbox for t in model_tables(session, page.number)]
            kaestchen_x: list[float] = []
            linien: list[tuple[float, float, float]] = []
            for d in drawings:
                for item in d.get("items", []):
                    op = item[0]
                    if op == "l":                          # Linie
                        p1, p2 = item[1], item[2]
                        if abs(p1.y - p2.y) < 1.5 and \
                                abs(p1.x - p2.x) >= MIN_LINE_LEN:
                            linien.append((min(p1.x, p2.x), max(p1.x, p2.x),
                                           min(p1.y, p2.y)))
                    elif op == "re":                       # Rechteck
                        r = item[1]
                        if BOX_MIN <= r.width <= BOX_MAX and \
                                BOX_MIN <= r.height <= BOX_MAX and \
                                abs(r.width - r.height) <= 3:
                            rect = Rect4(r.x0, r.y0, r.width, r.height)
                            if self._overlaps_any(page.number, rect, occupied):
                                continue
                            label = self._label_right(words, rect,
                                                       stop_px=kaestchen_x)
                            out.append(self._make_field(page.number, rect,
                                                        label or "Option",
                                                        "checkbox", len(out)))
                        elif r.width >= MIN_LINE_LEN and r.height <= 3:
                            linien.append((r.x0, r.x1, r.y0))
                        kaestchen_x.append(r.x0)
            # Tabellen-Zellen ZUERST erkennen (Nutzerfund 10.09.2026,
            # Tiefenprüfung): Raster-Zellen sind die präziseren Felder.
            # Zeilen-Paare dürfen sie nicht überlagern – sonst entstehen
            # Phantom-Felder auf Raster-Trennlinien (Kopfzeile „Mo Di
            # Mi Do“ bekam fälschlich Textfelder).
            out.extend(self._detect_tabellen_zellen(page, words, session,
                                                    occupied, out))
            out.extend(self._linien_paare(page, words, linien,
                                          occupied, out, table_bboxes))
            for (lx0, lx1, ly) in linien:
                out.extend(self._felder_fuer_linie(page, words, lx0, lx1,
                                                   ly, occupied, [],
                                                   out, table_bboxes))

        # --- 3) Checkbox-Zeichen im Text -----------------------------
        for w in words:
            if w.text in CHECKBOX_GLYPHS:
                size = max(w.rect.width, 8)
                rect = Rect4(w.rect.x, w.rect.y, size, size)
                if self._overlaps_any(page.number, rect, occupied):
                    continue
                label = self._label_right(words, rect)
                out.append(self._make_field(page.number, rect,
                                            label or "Option",
                                            "checkbox", len(out)))

        # --- 3b) Scan-Struktur: Feldlinien & Kästchen aus dem Raster --
        # Präzisionspfad für Scans: Otsu-Binarisierung + Lauflängen-
        # Analyse liefert die exakte Geometrie von Feldlinien, Kästchen
        # und Rahmen – unabhängig davon, ob OCR die Unterstriche erkennt
        # oder das Formular bereits handschriftlich ausgefüllt ist.
        if page.ocr_applied or page.needs_ocr:
            out.extend(self._detect_scan_struktur(page, words, session,
                                                  occupied, out))

        # --- 5) Scan-Seiten: Lücke neben Label = Feld -----------------
        # Gescannte Formulare haben keine Vektorlinien, und OCR unterschlägt
        # Unterstrich-Zeichen meist komplett. Was bleibt, ist die Leertaste-
        # Lücke rechts neben einer bekannten Beschriftung – genau dort
        # trägt ein Mensch von Hand ein (Acrobat „Fill & Sign“-Prinzip).
        # Läuft NUR auf OCR-Seiten, damit Digital-PDFs keine Scheinfelder
        # aus Fließtext-Zeilenenden bekommen.
        if page.ocr_applied or page.needs_ocr:
            out.extend(self._detect_scan_gaps(page, words, occupied, out))
        elif words:
            # Digitale PDFs: gleiche Logik mit strengeren Maßen (Fließ-
            # text-Zeilenenden sind kürzer als echte Formular-Lücken)
            out.extend(self._detect_scan_gaps(page, words, occupied, out,
                                              digital=True))
            # Tabellenlayout: Eingabeband unterhalb von Beschriftungen
            out.extend(self._detect_vertikal_baender(page, words,
                                                     occupied, out))

        # --- 4) Bereits ausgefüllte Werte übernehmen -----------------
        for f in out:
            if f.field_type in ("text", "datum", "bereich", "zahl",
                                "email", "telefon", "plz", "iban") and f.rect:
                inside = [w.text for w in words
                          if f.rect.contains(w.rect.x + w.rect.width / 2,
                                             w.rect.y + w.rect.height / 2,
                                             pad=0)
                          and not UNDERSCORE_RE.match(w.text)]
                if inside:
                    f.value = " ".join(inside)
                    f.original_value = f.value
        return out

    # ------------------------------------------------------------------
    def _make_field(self, pno: int, rect: Rect4, label: str, ftype: str,
                    idx: int) -> FieldModel:
        label_clean = (label or "").strip().rstrip(":").strip()
        canon, conf = match_canonical(label_clean)
        if canon:
            from .semantic import CANONICAL_FIELDS
            ftype = CANONICAL_FIELDS[canon]["typ"]
        else:
            ftype = infer_type(label_clean, ftype)
        required = bool(REQUIRED_MARK.search(label or "")) or \
            canon in ("vorname", "nachname", "geburtsdatum")
        slug = re.sub(r"[^a-z0-9]+", "_",
                      (label_clean or f"feld{idx + 1}").lower())[:30]
        confidence = 0.75
        if canon:
            confidence = 0.88
        if label_clean:
            confidence = min(0.95, confidence + 0.05)
        return FieldModel(
            id=f"vis::{pno}::{slug}::{idx}",
            name=slug,
            label=label_clean or f"Feld {idx + 1}",
            field_type=ftype,
            required=required,
            page=pno,
            rect=rect,
            source="visuell",
            confidence=confidence,
            canonical=canon,
        )

    # ------------------------------------------------------------------
    MIN_SCAN_GAP = 60       # pt Leerraum, ab dem eine Lücke ein Feld ist
    MAX_LINE_WORDS = 8      # längere Zeilen gelten als Fließtext
    SCAN_FELDHOEHE = 16.0   # Raum über der Linie für Handschrift (pt)

    # ------------------------------------------------------------------
    def _detect_scan_struktur(self, page: PageModel, words: list[Word],
                              session: Any, occupied: list,
                              existing: list) -> list[FieldModel]:
        """Felder aus der Raster-Geometrie gescannter Seiten: exakte
        Linien-, Kästchen- und Rahmenpositionen samt Tinte-BoundingBox
        (vorhandener Handschrift/Eintrag) für spätere Ersetzungen."""
        out: list[FieldModel] = []
        if session is None:
            return out
        try:
            pdoc = session.doc.load_page(page.number)
            png = pdoc.get_pixmap(dpi=200).tobytes("png")
        except Exception:
            return out
        from .scan_struktur import (KASTEN_MAX_PT, RAHMEN_MIN_BREITE_PT,
                                    RAHMEN_MIN_HOEHE_PT, analysiere)
        struktur = analysiere(png, dpi=200.0)
        if not struktur.linien_h and not struktur.kasten:
            return out
        table_bboxes = [t.bbox for t in model_tables(session, page.number)]
        idx = len(existing)

        def _tinte_rect(x0: float, y0: float, x1: float, y1: float,
                        min_pixel: int = 12,
                        kasten=None) -> "Rect4 | None":
            bbox = struktur.tinte_bbox(x0, y0, x1, y1, min_pixel=min_pixel,
                                       kasten=kasten)
            if bbox is None:
                return None
            return Rect4(bbox[0], bbox[1], bbox[2] - bbox[0],
                         bbox[3] - bbox[1])

        # --- Feldlinien (Unterstriche im Scan) ----------------------
        for l in struktur.linien_h:
            if l.laenge < 40.0:
                continue
            x0 = l.x0 + 1.0
            breite = l.laenge - 2.0
            hoehe = self.SCAN_FELDHOEHE
            for andere in struktur.linien_h:      # oben begrenzen
                if andere is l or andere.mitte_y >= l.mitte_y:
                    continue
                if min(andere.x1, l.x1) - max(andere.x0, l.x0) \
                        < 0.5 * l.laenge:
                    continue
                hoehe = min(hoehe, max(8.0,
                                       l.mitte_y - andere.mitte_y - 2.0))
            oben = max(0.0, l.y0 - hoehe)
            rect = Rect4(x0, oben, breite, l.y0 - oben)
            if self._in_tables(rect, table_bboxes) or \
                    self._overlaps_any(page.number, rect, occupied) or \
                    self._overlaps_existing(rect, out):
                continue
            tinte = _tinte_rect(x0, oben, x0 + breite, l.y0 - 0.8)
            # Unterlängen (g, j, p, q, y, ß): Tinte UNTER der Linie
            # gehört zum selben Eintrag – das Band ist eng (+6,5 pt)
            # und auf die Feldbreite begrenzt, damit die nächste
            # Zeile niemals hineinfällt.
            unten_tinte = struktur.tinte_bbox(
                x0, l.y1 + 0.3, x0 + breite, l.y1 + 6.5, min_pixel=6)
            if unten_tinte is not None and tinte is not None:
                bx0 = min(tinte.x, unten_tinte[0])
                by0 = tinte.y
                bx1 = max(tinte.x + tinte.width, unten_tinte[2])
                by1 = min(unten_tinte[3], l.y1 + 6.5)
                tinte = Rect4(bx0, by0, bx1 - bx0, by1 - by0)
            ziel = Word("", Rect4(x0 - 1, l.y0 - hoehe / 2, 0, hoehe / 2))
            label = self._label_left(words, ziel)
            if not label:
                label = self._label_above(
                    words, Word("", Rect4(x0, oben, 0, 2)))
            if not label and tinte is None:
                continue      # Präzision: Linien ohne Bezug sind keine Felder
            f = self._make_field(page.number, rect, label, "text", idx)
            idx += 1
            f.confidence = min(0.9, 0.72 + (0.08 if label else 0.0)
                               + (0.05 if tinte else 0.0))
            f.tinte_rect = tinte
            f.linie_y0 = l.y0
            f.linie_y1 = l.y1
            out.append(f)

        # --- Kästchen (Checkboxen) und Rahmen (Eingabefelder) --------
        for k in struktur.kasten:
            quer = k.breite / max(0.1, k.hoehe)
            if k.breite <= KASTEN_MAX_PT and k.hoehe <= KASTEN_MAX_PT \
                    and 0.6 <= quer <= 1.6:
                rect = Rect4(k.x0, k.y0, k.breite, k.hoehe)
                if self._overlaps_any(page.number, rect, occupied) or \
                        self._overlaps_existing(rect, out):
                    continue
                tinte = _tinte_rect(k.x0 + 1.2, k.y0 + 1.2,
                                    k.x1 - 1.2, k.y1 - 1.2, min_pixel=6,
                                    kasten=k)
                label = self._label_right(words, rect)
                if not label and tinte is None:
                    continue
                f = self._make_field(page.number, rect, label or "Option",
                                     "checkbox", idx)
                idx += 1
                f.confidence = min(0.88, 0.7 + (0.1 if label else 0.0)
                                   + (0.05 if tinte else 0.0))
                f.tinte_rect = tinte
                if tinte is not None:
                    f.value = True
                    f.original_value = True
                out.append(f)
            elif k.breite >= RAHMEN_MIN_BREITE_PT and \
                    k.hoehe >= RAHMEN_MIN_HOEHE_PT:
                rect = Rect4(k.x0 + 2.0, k.y0 + 2.0,
                             k.breite - 4.0, k.hoehe - 4.0)
                if self._overlaps_any(page.number, rect, occupied) or \
                        self._overlaps_existing(rect, out):
                    continue
                tinte = _tinte_rect(rect.x, rect.y, rect.x + rect.width,
                                    rect.y + rect.height)
                label = self._label_above(
                    words, Word("", Rect4(rect.x, rect.y - 2, 0, 2)))
                if not label:
                    label = self._label_left(
                        words, Word("", Rect4(rect.x - 1, rect.y, 0,
                                              rect.height)))
                if not label and tinte is None:
                    continue
                typ = "bereich" if k.hoehe > 40.0 else "text"
                f = self._make_field(page.number, rect, label, typ, idx)
                idx += 1
                f.confidence = min(0.9, 0.74 + (0.08 if label else 0.0)
                                   + (0.05 if tinte else 0.0))
                f.tinte_rect = tinte
                out.append(f)
        return out

    # ------------------------------------------------------------------
    def _phrase_auf_linie(self, auf: list[Word], bis: int) -> str:
        """Wörter AUF der Linie links vom Abschnitt als Phrase joinen
        (Lücken ≤ 30 pt gehören zusammen: „Telefon / Notfallkontakte:“)."""
        teile = [auf[bis].text.rstrip(":").strip()]
        j = bis
        while j > 0 and auf[j].rect.x - \
                (auf[j - 1].rect.x + auf[j - 1].rect.width) <= 30:
            j -= 1
            teile.insert(0, auf[j].text.rstrip(":").strip())
        return " ".join(t for t in teile if t)

    def _linien_paare(self, page: "PageModel", words: list[Word],
                      linien: list, occupied: list, existing: list,
                      table_bboxes: list) -> list[FieldModel]:
        """Zeilen-Paar-Modell (Nutzerfund 10.09.2026, Bild 2: „hinter
        dem Text eine Linie – der eingegebene Text muss dort auch hin“):
        Die Beschriftung steht oben in der Zelle, die LEERE Linie
        darunter ist die Eingabezeile. Für jedes Linien-Segment ohne
        darauf sitzenden Text wird die nächste Textzeile darüber zur
        Beschriftung – jede Label-Phrase dort bekommt ihr eigenes
        Feld, AUF der Linie (Grundlinie wie handschriftlich).
        Rahmen-/Zierlinien und Überschriften-Boxen bleiben außen vor.
        Läuft bewusst auch in Tabellen-Rastern (besser als Zellen-
        Erkennung, weil Position UND Beschriftung stimmen)."""
        felder: list[FieldModel] = []
        if not linien:
            return felder
        # Segmente je Linie (nur wirklich identische verschmelzen)
        segmente: list[tuple[float, float, float]] = []
        for (x0, x1, y) in sorted(linien, key=lambda l: (l[2], l[0])):
            for i, (sx0, sx1, sy) in enumerate(segmente):
                if abs(sy - y) <= 1.5 and x0 - sx1 <= 0.5:
                    segmente[i] = (sx0, max(sx1, x1), sy)
                    break
            else:
                segmente.append((x0, x1, y))
        for (sx0, sx1, sy) in segmente:
            if sx1 - sx0 < 30:
                continue                      # zu kurz für ein Feld
            # Text, der AUF dieser Linie sitzt (Grundlinie = Linie)?
            # Seitenweit geprüft: Beim klassischen „Label: ____“ steht
            # das Label LINKS neben der Linie (Nutzerfund: das Feld
            # dürfte nicht unter der Überschrift landen).
            auf_linie = [w for w in words
                         if -3.0 <= (w.rect.y + w.rect.height) - sy <= 4.0]
            if auf_linie:
                continue                      # Linie ist beschriftet
            # Label sitzt KNAPP auf der Linie (0–12 pt über der
            # Grundlinie)? Dann ist es der klassische Fall „Label auf
            # der Linie, Feld rechts daneben“ – übernimmt die normale
            # Linien-Erkennung, kein Zeilen-Paar (Raster-Formulare).
            knapp_drauf = [w for w in words
                           if 0.0 <= sy - (w.rect.y + w.rect.height)
                           <= 12.0
                           and w.rect.x < sx1 and
                           w.rect.x + w.rect.width > sx0]
            if knapp_drauf:
                continue
            # Beschriftungs-Band darüber (12–60 pt über der Linie;
            # näher = Zellenrahmen, weiter = anderer Abschnitt).
            # Große Wörter (Überschriften/Titel, > 16 pt hoch) sind
            # KEINE Feld-Beschriftung (Nutzerfund: Seitentitel durfte
            # kein Feld auf der Überschriften-Linie erzeugen).
            band = [w for w in words
                    if 12.0 <= sy - (w.rect.y + w.rect.height) <= 60.0
                    and w.rect.height <= 16.0
                    and w.rect.x < sx1 - 4 and
                    w.rect.x + w.rect.width > sx0 + 4
                    and not UNDERSCORE_RE.match(w.text)]
            if not band:
                continue                      # Rahmen-/Zierlinie
            # Struktur darunter? Eine Eingabelinie steht NIE am Ende
            # eines Datenblocks: Darunter geht das Formular weiter –
            # entweder startet direkt (0–8 pt) die nächste Label-Zeile
            # oder es folgt eine weitere Linie (Raster). Daten-Tabellen
            # enden mit einer Schlusslinie („Summe“) ohne alles.
            text_direkt_darunter = any(
                0.0 <= w.rect.y - sy <= 8.0 for w in words)
            linie_darunter = any(
                abs(ly2 - sy) > 3.0 and sy < ly2 <= sy + 90.0
                and min(ex1, sx1) - max(ex0, sx0) > 20
                for (ex0, ex1, ly2) in segmente)
            if not text_direkt_darunter and not linie_darunter:
                continue
            bez_y = max(w.rect.y + w.rect.height for w in band)
            zeile = sorted([w for w in band
                            if abs((w.rect.y + w.rect.height)
                                   - bez_y) < 4.0],
                           key=lambda w: w.rect.x)
            if not zeile:
                continue
            # Label-Phrasen bilden (Wörter mit kleinem Abstand gehören
            # zusammen: „Name, Vorname der Mutter:“)
            phrasen: list[list[Word]] = [[zeile[0]]]
            for w in zeile[1:]:
                v = phrasen[-1][-1]
                if w.rect.x - (v.rect.x + v.rect.width) <= 14.0:
                    phrasen[-1].append(w)
                else:
                    phrasen.append([w])
            for pi, phrase in enumerate(phrasen):
                px0 = phrase[0].rect.x
                px1 = max(w.rect.x + w.rect.width for w in phrase)
                fx0 = max(sx0 + 1.0, px0 - 2.0)
                if pi + 1 < len(phrasen):
                    fx1 = min(sx1 - 1.0,
                              phrasen[pi + 1][0].rect.x - 6.0)
                else:
                    fx1 = sx1 - 1.0
                if fx1 - fx0 < 24:
                    continue
                label = self._phrase_bereinigen(
                    [w.text for w in phrase])
                if not label or any(c.isdigit() for c in label):
                    continue
                if any(f.page == page.number and f.label == label
                       and f.rect and abs(f.rect.y - (sy - 14.0)) < 40.0
                       for f in existing + felder):
                    continue   # Zwilling direkt daneben (Gap/Band)
                rect = Rect4(fx0, sy - 14.0, fx1 - fx0, 15.5)
                # 4-pt-Puffer NUR gegen bereits existierende Felder
                # (Rasterzellen beginnen 1,7 pt unter der Trennlinie –
                # ohne Puffer überlebten Phantom-Felder auf den
                # Gitterlinien). Gegen Felder aus DEMSELBEN Durchlauf
                # gilt der Puffer NICHT: Nachbar-Felder einer Vier-
                # Label-Zeile grenzen exakt aneinander (Tiefenprüfung
                # 10.09.2026: „Vorname“/„Geburtsdatum“ fielen sonst
                # weg, weil sie das Nachbarfeld berührten).
                pr = Rect4(rect.x - 4.0, rect.y - 4.0,
                           rect.width + 8.0, rect.height + 8.0)
                if self._overlaps_any(page.number, pr, occupied) or \
                        self._overlaps_existing(pr, existing) or \
                        self._overlaps_existing(rect, felder):
                    continue
                felder.append(self._make_field(page.number, rect, label,
                                               "text",
                                               len(existing) + len(felder)))
        return felder

    def _felder_fuer_linie(self, page: "PageModel", words: list[Word],
                           x0: float, x1: float, y: float,
                           occupied: list, existing: list,
                           out: list, table_bboxes: list) -> list:
        """Ein Feld pro FREIEM Linienabschnitt hinter einem Label.

        Wörter, deren Unterkante auf der Linie sitzen, unterteilen die
        Linie; der Abschnitt nach jedem Wort bis zum nächsten Wort
        (bzw. Linienende) wird das Eingabefeld – der Text steht dann
        exakt über der Linie wie handschriftlich (Acrobat-Fill&Sign-
        Auto-Platzierung „just above the baseline“)."""
        felder: list[FieldModel] = []
        h = 12.0
        auf = sorted(
            [w for w in words
             if x0 - 2 <= w.rect.x + w.rect.width * 0.5 <= x1 + 2
             and -4.0 <= (w.rect.y + w.rect.height) - y <= 6.0],
            key=lambda w: w.rect.x)
        segmente: list[tuple[float, float, str]] = []
        if not auf:
            # Freistehende Linie: NUR ein Feld, wenn daneben (links,
            # gleiche Höhe) wirklich eine Beschriftung steht – das ist
            # das klassische „Label neben Linie“-Formular. Seitenrahmen
            # und Zierlinien (Nutzerfund 10.09.2026: Anmeldeformular
            # erzeugte „Feld 10/11“ über die ganze Seitenbreite) haben
            # kein Label in Linienhöhe und werden übersprungen.
            links = self._label_left(
                words, Word("", Rect4(x0, y - 6, 0, 12)))
            if not links:
                return felder
            segmente.append((x0, x1, ""))
        else:
            if auf[0].rect.x - x0 >= 60:     # breite Fläche VOR dem
                segmente.append((x0, auf[0].rect.x - 4, ""))   # 1. Wort
            for i, w in enumerate(auf):
                seg0 = w.rect.x + w.rect.width + 4
                seg1 = (auf[i + 1].rect.x - 4) if i + 1 < len(auf) else x1
                if seg1 - seg0 >= 24:
                    segmente.append((seg0, seg1,
                                     self._phrase_auf_linie(auf, i)))
        for (sx0, sx1, label) in segmente:
            rect = Rect4(sx0, y - h, sx1 - sx0, h)
            if rect.width < 24:
                continue
            if self._in_tables(rect, table_bboxes) or \
                    self._overlaps_any(page.number, rect, occupied) or \
                    self._overlaps_existing(rect, existing) or \
                    self._overlaps_existing(rect, out):
                continue
            if not label:
                label = self._label_left(
                    words, Word("", Rect4(sx0, y - h, 0, h)))
            felder.append(self._make_field(page.number, rect, label,
                                           "text", len(existing) + len(out)))
        return felder

    def _zellen_label_links(self, words: list[Word], z: Rect4) -> str:
        """Beschriftung in der gleichen Zellenzeile links suchen.
        Tabellen-Labelspalten sind oft breiter als das 90-pt-Fenster
        von ``_label_left`` (Nutzerfund 09.09.2026: „Jahrgang erkannt,
        die anderen ignoriert“)."""
        band_oben = z.y - 2
        band_unten = z.y + z.height + 2
        cands = [w for w in words
                 if w.rect.x + w.rect.width <= z.x + 4
                 and band_oben <= (w.rect.y + w.rect.height / 2) <= band_unten
                 and z.x - (w.rect.x + w.rect.width) < 260]
        if not cands:
            return ""
        cands.sort(key=lambda w: w.rect.x, reverse=True)
        parts: list[str] = []
        for i, w in enumerate(cands[:6]):
            parts.append(w.text)
            if i + 1 < len(cands):
                nxt = cands[i + 1]
                if w.rect.x - (nxt.rect.x + nxt.rect.width) > 14:
                    break
        return " ".join(reversed(parts))

    def _detect_tabellen_zellen(self, page: PageModel, words: list[Word],
                                session: Any, occupied: list,
                                existing: list) -> list[FieldModel]:
        """Leere Tabellen-Zellen als Eingabefelder (Acrobat-Auto-Detect
        in Rastern). Beschriftung: Wort links in der Zeile oder Wort
        über der Spalte – ganz ohne Zellen-/Text-Mapping-Zuordnung."""
        out: list[FieldModel] = []
        tabellen = model_tables(session, page.number)
        idx = len(existing)
        for t in tabellen:
            if t.page != page.number or len(t.zellen) < 4:
                continue                       # kein Raster, kein Formular
            # Wortmaterial in der Tabelle? (reine Blind-Raster skippen)
            in_bbox = [w for w in words
                       if t.bbox.x - 2 <= w.rect.x <= t.bbox.x +
                       t.bbox.width and t.bbox.y - 2 <= w.rect.y <=
                       t.bbox.y + t.bbox.height]
            if not in_bbox:
                continue
            # Datentabelle (Kostenübersicht & Co.) ist KEIN Formular:
            # sind > 70 % der Zellen gefüllt, gehört die Tabelle in
            # die Prüfung, nicht in die Eingabemaske.
            def _gefuellt(z: Rect4) -> bool:
                return any(z.contains(w.rect.x + w.rect.width / 2,
                                      w.rect.y + w.rect.height / 2,
                                      pad=1.0) for w in words)
            fuellung = [(_gefuellt(z), z) for z in t.zellen]
            if sum(1 for g, _ in fuellung if g) / len(t.zellen) > 0.7:
                continue
            # Zeilenbänder: nur Bänder mit Wortmaterial ernten – ein
            # leerer Schlussrand (Gitter zieht eine Zeile weiter)
            # bekäme sonst Etiketten von Zeilen darüber.
            band_mit_wort: set[float] = set()
            for band_y in {round(z.y, 1) for _, z in fuellung}:
                band_z = [z for _, z in fuellung
                          if round(z.y, 1) == band_y]
                y_oben = band_z[0].y - 2
                y_unten = band_z[0].y + band_z[0].height + 2
                if any(y_oben <= (w.rect.y + w.rect.height / 2) <= y_unten
                       for w in in_bbox):
                    band_mit_wort.add(band_y)
            for gefuellt, z in fuellung:
                if gefuellt:
                    continue
                if round(z.y, 1) not in band_mit_wort:
                    continue
                if z.width < 24.0 or z.height < 9.0:
                    continue
                if z.width > 420.0 or z.height > 80.0:
                    continue
                # nur LEERE Zellen (kein Wort drin)
                if any(z.contains(w.rect.x + w.rect.width / 2,
                                  w.rect.y + w.rect.height / 2, pad=1.0)
                       for w in words):
                    continue
                rect = Rect4(z.x + 1.5, z.y + 1.5,
                             z.width - 3.0, z.height - 3.0)
                if self._overlaps_any(page.number, rect, occupied) or \
                        self._overlaps_existing(rect, out) or \
                        self._overlaps_existing(rect, existing):
                    continue
                label, wochentag = self._zellen_label_raster(
                    words, t, z, t.zellen)
                if not label:
                    label = self._zellen_label_links(words, z)
                if not label:
                    label = self._label_above(
                        words, Word("", Rect4(z.x, z.y - 1, 0, 2)))
                f = self._make_field(
                    page.number, rect, label,
                    "checkbox" if wochentag else "text", idx)
                idx += 1
                f.confidence = 0.7 if label else 0.6
                out.append(f)
        return out

    def _zellen_label_raster(self, words: list[Word], t,
                             z: Rect4, zellen: list) -> tuple[str, bool]:
        """Saubere Raster-Beschriftung (Nutzerfund 10.09.2026, Tie-
        fenprüfung: Zellen hießen „den Offenen an einer Ganztag:
        Anmeldung“). Label = mehrzeilige Zeilen-Phrase LINKS der Zelle
        + Spalten-Header in Klammern (z. B. „… Ganztag (Mo)“).
        Liefert zusätzlich, ob die Spalte ein WOCHENTAG ist (Ankreuz-
        Raster: „Interessenabfrage Ganztag“ mit Mo/Di/Mi/Do)."""
        # Spalten-Header: die NÄCHSTE Textzeile über der Zelle im
        # x-Bereich der Spalte (Mo/Di/Mi/Do …). Nicht der Spalten-
        # Anfang: Der riesige Zellverband reicht bis zum Briefkopf,
        # dessen Wörter dann als Header durchgingen („… (Entwicklung)“).
        header_kand = [w for w in words
                       if z.x - 2.0 <= w.rect.x + w.rect.width / 2.0
                       <= z.x + z.width + 2.0
                       and 0.0 < z.y - (w.rect.y + w.rect.height) <= 60.0]
        if header_kand:
            bez_bottom = max(w.rect.y + w.rect.height
                             for w in header_kand)
            header = sorted(
                [w for w in header_kand
                 if abs((w.rect.y + w.rect.height) - bez_bottom) < 4.0],
                key=lambda w: w.rect.x)
        else:
            header = []
        header_text = " ".join(w.text.rstrip(":,") for w in header)
        # Zeilen-Phrase: Wörter links der Zelle im Zeilenband
        # (mehrzeilig: „Interesse an einer Anmeldung für den Offenen
        # Ganztag:“ erstreckt sich über zwei Textzeilen)
        band = sorted(
            [w for w in words
             if w.rect.x + w.rect.width <= z.x + 2.0
             and w.rect.x >= t.bbox.x - 2.0
             and w.rect.y < z.y + z.height - 2.0
             and w.rect.y + w.rect.height > z.y + 2.0],
            key=lambda w: (w.rect.y, w.rect.x))
        phrase = self._phrase_bereinigen([w.text for w in band[:12]])
        if not phrase:
            return (header_text, False)
        if header_text:
            return (f"{phrase} ({header_text})",
                    header_text.strip() in
                    ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"))
        return (phrase, False)

    # ------------------------------------------------------------------
    def _detect_scan_gaps(self, page: PageModel, words: list[Word],
                          occupied: list, existing: list,
                          digital: bool = False) -> list[FieldModel]:
        """Felder aus Label-Lücken ableiten. digital=True für PDFs mit
        echter Textebene: strengere Maße, damit Fließtext-Zeilenenden
        niemals als Feld durchgehen."""
        out: list[FieldModel] = []
        if not words:
            return out
        # Nutzerfund 10.09.2026 (Anmeldeformular): vier Label in EINER
        # Zeile (Name/Vorname/Geburtsort/Geburtsdatum) – 90 pt Lücken-
        # minimum und 5 Wörter pro Zeile warfen drei der vier Felder
        # weg. Doppelpunkt/kanonische Labels bleiben Pflicht, Fließtext
        # weiterhin ausgeschlossen.
        min_gap = 45.0 if digital else self.MIN_SCAN_GAP
        max_woerter = 12 if digital else self.MAX_LINE_WORDS
        seiten_breite = page.width or 595
        # Zeilen schlicht über y-Position gruppieren (OCR schwankt)
        zeilen: list[list[Word]] = []
        for w in sorted(words, key=lambda x: (x.rect.y, x.rect.x)):
            platziert = False
            for z in zeilen:
                if abs(z[0].rect.y - w.rect.y) < 6:
                    z.append(w)
                    platziert = True
                    break
            if not platziert:
                zeilen.append([w])
        for zeile in zeilen:
            if len(zeile) > max_woerter:
                continue                       # Fließtext, kein Formular
            zeile.sort(key=lambda x: x.rect.x)
            for i, w in enumerate(zeile):
                # Beschriftung ggf. aus zwei angrenzenden Wörtern bilden
                label_wort = w.text.strip().rstrip(":").strip()
                if not match_canonical(label_wort)[0]:
                    # Phrase nach links erweitern (bis zu 4 Wörter,
                    # Lücke < 20 pt, Wörter NEBENEINANDER – nicht über-
                    # einander gestapelt): „Name, Vorname der Mutter:“
                    # ist EIN Label, aber „Religion:“ unter „Staats-
                    # angehörigkeit:“ bleibt getrennt (Nutzerfund 10.09.)
                    teile = [label_wort]
                    j = i
                    while (j > 0 and len(teile) < 4 and
                           not zeile[j - 1].text.rstrip().endswith(":")
                           and zeile[j - 1].rect.x
                           + zeile[j - 1].rect.width
                           <= zeile[j].rect.x + 2 and
                           zeile[j].rect.x
                           - (zeile[j - 1].rect.x
                              + zeile[j - 1].rect.width) < 20 and
                           abs((zeile[j - 1].rect.y +
                                zeile[j - 1].rect.height / 2)
                               - (zeile[j].rect.y +
                                  zeile[j].rect.height / 2)) < 5):
                        teile.insert(0, zeile[j - 1].text.strip()
                                     .rstrip(":").strip())
                        j -= 1
                    label_wort = " ".join(t for t in teile if t)
                canon, conf = match_canonical(label_wort)
                endet_doppelpunkt = w.text.rstrip().endswith(":")
                # Nur sichere Treffer (exakt/Teilphrase ≥ 0,9) oder
                # Doppelpunkt-Label – Fuzzy-Treffer wie ein Seiten-
                # titel sind KEINE Feld-Beschriftung.
                if (not canon or conf < 0.9) and not endet_doppelpunkt:
                    continue                   # keine bekannte Beschriftung
                # Zeilen-Paar-Modell hat dieses Label schon AUF einer
                # Eingabelinie? Dann kein zweites Feld neben dem Label
                # (Nutzerfund 10.09.2026: Feld saß auf der Beschriftung).
                # Gleiches Label weiter unten/unten ist legitim
                # (Mutter/Vater/Andere mit gleichem Nebenspalten-Label).
                if any(f.page == page.number and f.label == label_wort
                       and f.rect and abs(f.rect.y - w.rect.y) < 40.0
                       for f in existing):
                    continue
                if any(c.isdigit() for c in label_wort) and not canon:
                    continue
                # Rechte Grenze: nächstes Wort oder Blattrand.
                # Ein Wort, das IN einem (AcroForm-)Formfeld steht, ist
                # ein ausgefüllter WERT – es begrenzt die Label-Lücke
                # nicht (Nutzerfund 10.09.2026: gefülltes Formular
                # erzeugte ein Doppel-„Vorname“ beim Vergleich).
                if i + 1 < len(zeile):
                    nxt = zeile[i + 1]
                    nxt_rect = Rect4(nxt.rect.x, nxt.rect.y,
                                     nxt.rect.width, nxt.rect.height)
                    if self._overlaps_any(page.number, nxt_rect, occupied):
                        rand = seiten_breite - 40
                    else:
                        rand = nxt.rect.x - 4
                else:
                    rand = seiten_breite - 40
                luecke = rand - (w.rect.x + w.rect.width)
                if luecke < min_gap:
                    continue
                rect = Rect4(w.rect.x + w.rect.width + 4, w.rect.y - 2,
                             luecke - 8, max(w.rect.height, 10))
                if rect.width < 30:
                    continue
                if self._overlaps_any(page.number, rect, occupied) or \
                        self._overlaps_existing(rect, existing + out):
                    continue
                out.append(self._make_field(page.number, rect, label_wort,
                                            "text", len(existing) + len(out)))
        return out

    def _detect_vertikal_baender(self, page: PageModel,
                                 words: list[Word], occupied: list,
                                 existing: list) -> list[FieldModel]:
        """Eingabeband UNTER einer Beschriftung (Nutzerfund 10.09.2026:
        Anmeldeformular im Tabellenlayout – „Telefon / Notfall-
        kontakte:", „Name, Vorname der Mutter:" … gefolgt von leeren
        Zeilen bis zum nächsten Textblock). Nur wenn rechts vom Label
        kein Feld liegt (das hätte die Lücken-Erkennung schon found)
        und nur auf digitalen Seiten."""
        out: list[FieldModel] = []
        if not words:
            return out
        seiten_breite = page.width or 595
        zeilen: list[list[Word]] = []
        for w in sorted(words, key=lambda x: (x.rect.y, x.rect.x)):
            platziert = False
            for z in zeilen:
                if abs(z[0].rect.y - w.rect.y) < 6:
                    z.append(w)
                    platziert = True
                    break
            if not platziert:
                zeilen.append([w])
        for zeile in zeilen:
            zeile.sort(key=lambda x: x.rect.x)
            for i, w in enumerate(zeile):
                if not w.text.rstrip().endswith(":"):
                    continue
                if any(c.isdigit() for c in w.text):
                    continue
                # Phrase nach links erweitern (bis 4 Wörter, Lücke < 20)
                teile = [w.text.strip().rstrip(":").strip()]
                j, x0 = i, w.rect.x
                while (j > 0 and len(teile) < 4 and
                       not zeile[j - 1].text.rstrip().endswith(":") and
                       zeile[j - 1].rect.x + zeile[j - 1].rect.width
                       > zeile[j].rect.x - 20):
                    teile.insert(0, zeile[j - 1].text.strip()
                                 .rstrip(":").strip())
                    x0 = zeile[j - 1].rect.x
                    j -= 1
                label = " ".join(t for t in teile if t)
                if not label:
                    continue
                w_bottom = w.rect.y + w.rect.height
                label_ende = w.rect.x + w.rect.width
                # rechts vom Label schon ein Feld? -> Lücken-Erkennung
                if any(f.page == page.number and f.rect
                       and abs(f.rect.y - w.rect.y) < 6
                       and f.rect.x + f.rect.width > label_ende
                       and f.rect.x < seiten_breite
                       for f in existing):
                    continue
                # gleiches Label NAHE der Stelle schon erkannt (z. B.
                # Unterstrich-/Lücken-/Zeilen-Feld)? -> kein Duplikat
                if any(f.page == page.number and f.label == label
                       and f.rect and abs(f.rect.y - (w_bottom + 3)) < 40.0
                       for f in existing):
                    continue
                # nächste Textzeile DARUNTER begrenzt das Band
                ny = min((x.rect.y for x in words
                          if x.rect.y > w_bottom + 8), default=None)
                if ny is None:
                    continue
                band_h = ny - 4 - (w_bottom + 3)
                if not 18.0 <= band_h <= 110.0:
                    continue
                rechts = [x for x in zeile if x.rect.x > label_ende + 8]
                x1 = (rechts[0].rect.x - 6) if rechts \
                    else seiten_breite - 40
                if x1 - x0 < 60:
                    continue
                # Ein Eingabeband muss LEER sein: Wörter im Bandbereich
                # zeigen einen beschrifteten Bereich (z. B. Spalten-
                # header „Hinweg Einstieg Bushaltestelle:“) – kein
                # Eingabefeld (Tiefenprüfung 10.09.2026).
                band_top = w_bottom + 3
                if any(x0 + 2 < w2.rect.x + w2.rect.width
                       and w2.rect.x < x1 - 2
                       and band_top + 2 < w2.rect.y + w2.rect.height
                       and w2.rect.y < band_top + band_h - 2
                       for w2 in words):
                    continue
                rect = Rect4(x0, w_bottom + 3, x1 - x0, band_h)
                if self._overlaps_any(page.number, rect, occupied) or \
                        self._overlaps_existing(rect, existing + out):
                    continue
                out.append(self._make_field(page.number, rect, label,
                                            "text",
                                            len(existing) + len(out)))
        return out

    # ------------------------------------------------------------------
    @staticmethod
    def _same_line(w1: Word, w2: Word) -> bool:
        yc1 = w1.rect.y + w1.rect.height / 2
        yc2 = w2.rect.y + w2.rect.height / 2
        return abs(yc1 - yc2) < max(10.0, (w1.rect.height + w2.rect.height) / 2)

    @staticmethod
    def _phrase_bereinigen(texte: list[str]) -> str:
        """Label-Phrase säubern: Nach dem LETZTEN Wort mit Doppelpunkt
        abschneiden („Datum: Georgsmarienhütte“ → „Datum“). Hinter
        einem Doppelpunkt steht vorbedruckter Inhalt, nicht die
        Beschriftung (Nutzerfund 10.09.2026, Tiefenprüfung)."""
        roh = [t for t in texte if t and t.strip()]
        for i in range(len(roh) - 1, -1, -1):
            if roh[i].rstrip().endswith(":"):
                roh = roh[:i + 1]
                break
        return " ".join(t.strip().rstrip(":").strip()
                        for t in roh if t.strip().rstrip(":").strip())

    def _label_left(self, words: list[Word], target: Word) -> str:
        """Wörter links vom Feld als zusammenhängende Phrase sammeln."""
        cands = [w for w in words
                 if w.rect.x + w.rect.width <= target.rect.x + 4
                 and self._same_line(w, target)
                 and target.rect.x - (w.rect.x + w.rect.width) < 120]
        if not cands:
            return ""
        cands.sort(key=lambda w: w.rect.x, reverse=True)
        parts: list[str] = []
        for i, w in enumerate(cands[:6]):
            parts.append(w.text)
            # zusammenhängende Phrase: Lücke zum nächsten Wort klein
            if i + 1 < len(cands):
                nxt = cands[i + 1]
                gap = w.rect.x - (nxt.rect.x + nxt.rect.width)
                if gap > 14:
                    break
        return self._phrase_bereinigen(list(reversed(parts)))

    def _label_above(self, words: list[Word], target: Word) -> str:
        """Beschriftung ÜBER dem Feld als ganze Phrase (Nutzerfund
        10.09.2026: „Hinweg Einstieg Bushaltestelle“ hieß nur
        „Hinweg“). Nimmt die nächste Textzeile über dem Feld, soweit
        sie das Feld x-seitig überlappt."""
        cands = [w for w in words
                 if 0 <= target.rect.y - (w.rect.y + w.rect.height) <= 25
                 and w.rect.x < target.rect.x + target.rect.width + 10
                 and w.rect.x + w.rect.width > target.rect.x - 10]
        if not cands:
            return ""
        bez_y = max(w.rect.y + w.rect.height for w in cands)
        zeile = sorted([w for w in cands
                        if abs((w.rect.y + w.rect.height) - bez_y) < 4.0],
                       key=lambda w: w.rect.x)
        return self._phrase_bereinigen([w.text for w in zeile[:6]])

    def _label_below(self, words: list[Word], target: Word) -> str:
        """Wörter knapp UNTER dem Feld als Beschriftung (Unterschritts-
        linien beschriften von unten)."""
        cands = [w for w in words
                 if w.rect.y > target.rect.y + target.rect.height - 2
                 and w.rect.y - (target.rect.y + target.rect.height) < 16
                 and w.rect.x < target.rect.x + target.rect.width + 10
                 and w.rect.x + w.rect.width > target.rect.x - 10]
        cands.sort(key=lambda w: w.rect.x)
        if not cands:
            return ""
        return self._phrase_bereinigen([w.text for w in cands[:4]])

    def _label_right(self, words: list[Word], rect: Rect4,
                     stop_px: list | None = None) -> str:
        """Beschriftung rechts neben einem Kästchen (z. B. '☐ Ja').

        Stopp am nächsten Checkbox-Glyph (gehört zur nächsten Option)
        und an Schreiblinien (Unterstriche sind keine Beschriftung) –
        Nutzerfund 10.09.2026: „Mutter Vater“/„ES L“ verschmolzen die
        Optionen zweier Kästchen zu einem Label. stop_px: x-Positionen
        weiterer gezeichneter Kästchen (Rechteck-Checkboxen haben kein
        Glyph-Wort im Text)."""
        cands = [w for w in words
                 if w.rect.x >= rect.x + rect.width - 2
                 and w.rect.x - (rect.x + rect.width) < 70
                 and abs((w.rect.y + w.rect.height / 2)
                         - (rect.y + rect.height / 2)) < 12]
        grenze = None
        if stop_px:
            kandidaten = [px for px in stop_px
                          if px > rect.x + rect.width + 2]
            if kandidaten:
                grenze = min(kandidaten)
        if grenze is not None:
            cands = [w for w in cands if w.rect.x < grenze - 2]
        cands.sort(key=lambda w: w.rect.x)
        teile: list[str] = []
        for w in cands[:4]:
            if w.text in CHECKBOX_GLYPHS:
                break                       # nächste Option beginnt
            if UNDERSCORE_RE.match(w.text):
                break                       # Schreiblinie, kein Text
            teile.append(w.text)
        return " ".join(teile)

    @staticmethod
    def _overlaps_any(pno: int, rect: Rect4, occupied: list) -> bool:
        for opno, orect in occupied:
            if opno == pno and orect and rect and \
                    not (rect.x + rect.width < orect.x or
                         orect.x + orect.width < rect.x or
                         rect.y + rect.height < orect.y or
                         orect.y + orect.height < rect.y):
                return True
        return False

    @staticmethod
    def _overlaps_existing(rect: Rect4, existing: list[FieldModel]) -> bool:
        return any(f.rect and not (rect.x + rect.width < f.rect.x or
                                   f.rect.x + f.rect.width < rect.x or
                                   rect.y + rect.height < f.rect.y or
                                   f.rect.y + f.rect.height < rect.y)
                   for f in existing)

    @staticmethod
    def _in_tables(rect: Rect4, table_bboxes: list) -> bool:
        pad = 14                                  # Gitterlinien-Toleranz
        for tb in table_bboxes:
            if tb and rect.x >= tb.x - pad and rect.y >= tb.y - pad and \
                    rect.x + rect.width <= tb.x + tb.width + pad and \
                    rect.y + rect.height <= tb.y + tb.height + pad:
                return True
        return False


def model_tables(session: Any, pno: int) -> list:
    """Tabellen der Seite (damit Linien nicht als Felder fehlgedeutet werden)."""
    cache = getattr(session, "_tables_cache", None)
    if cache is None:
        cache = {}
        session._tables_cache = cache
    if pno not in cache:
        try:
            from .pdf_mupdf import MuPdfEngine
            engine = MuPdfEngine()
            cache[pno] = [t for t in engine.find_tables(session)
                          if t.page == pno]
        except Exception:
            cache[pno] = []
    return cache[pno]
