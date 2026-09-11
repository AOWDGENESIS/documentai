# -*- coding: utf-8 -*-
"""PDF-Werkzeuge, inspiriert von Adobe Acrobat (Reader) DC – vollständig
open-source umgesetzt auf PyMuPDF (AGPL). Ohne Lizenzschlüssel, ohne
Cloud, ohne proprietäre Komponenten.

Bereitgestellt (Acrobat-Name → hier):
  Kommentar-Werkzeuge  → markieren() (Highlight/Durchstreichen/
                         Unterstreichen), haftnotiz(), freihand()
  Schwärzen (Redaktion) → redaktion_markieren() + redaktion_anwenden()
                         entfernt den Inhalt UNTER der Box endgültig
  Seiten verwalten      → seite_loeschen(), seite_extrahieren(),
                          zusammenfuehren()
  PDF schützen          → speichern_verschluesselt() (AES-256)

Alle Funktionen arbeiten auf einer bestehenden PdfSession und verändern
niemals die Originaldatei – gespeichert wird ausschließlich über die
Versions-Pipeline (Neue Version) bzw. in explizite Zieldateien.
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

import pymupdf

from ..core.errors import DocumentAIError

FARBEN = {
    "gelb": (1, 0.95, 0.2),
    "rot": (1, 0.35, 0.35),
    "gruen": (0.45, 0.9, 0.45),
    "blau": (0.45, 0.7, 1),
}


# --------------------------------------------------- Kommentar-Werkzeuge
def markieren(session: Any, page: int, rects: Sequence[Sequence[float]],
              art: str = "highlight", farbe: str = "gelb") -> int:
    """Text hervorheben / durchstreichen / unterstreichen.

    rects: Liste von (x0, y0, x1, y1) in PDF-Punkten.
    Rückgabe: Anzahl erzeugter Annotationen.
    """
    if art not in ("highlight", "strikeout", "underline"):
        raise DocumentAIError(f"Unbekannte Markierungsart: {art!r}")
    doc = session.doc
    if not 0 <= page < doc.page_count:
        raise DocumentAIError(f"Seite {page + 1} existiert nicht.")
    pg = doc[page]
    n = 0
    for (x0, y0, x1, y1) in rects:
        clip = pymupdf.Rect(x0, y0, x1, y1)
        worte = pg.get_text("words", clip=clip)
        if not worte:
            continue                       # kein Text im Bereich
        if art == "highlight":
            quads = [pymupdf.Rect(w[0], w[1], w[2], w[3]) for w in worte]
            annot = pg.add_highlight_annot(quads=quads)
            annot.set_colors(stroke=FARBEN.get(farbe, FARBEN["gelb"]))
            annot.update()
            n += 1
            continue
        # Durchstreichen/Unterstreichen: je Textzeile eine Annotation
        zeilen: dict[float, list[float]] = {}
        for _x0, _y0, _x1, _y1, _txt, *_ in worte:
            zeilen.setdefault(round(_y1, 1), []).extend([_x0, _x1])
        for y, xs in zeilen.items():
            xa, xb = min(xs), max(xs)
            if art == "strikeout":
                pg.add_strikeout_annot(pymupdf.Rect(xa, y - 2, xb, y))
            else:
                pg.add_underline_annot(pymupdf.Rect(xa, y - 2, xb, y))
            n += 1
    return n


def haftnotiz(session: Any, page: int, x: float, y: float,
              text: str) -> None:
    """Haftnotiz (Sticky Note) an Position x/y (PDF-Punkte)."""
    doc = session.doc
    if not 0 <= page < doc.page_count:
        raise DocumentAIError(f"Seite {page + 1} existiert nicht.")
    if not text.strip():
        raise DocumentAIError("Haftnotiz ohne Text macht keinen Sinn.")
    pg = doc[page]
    icon = pg.add_text_annot(pymupdf.Point(x, y), text)
    icon.set_colors(stroke=FARBEN["gelb"])
    icon.update()


def freihand(session: Any, page: int, punkte: Sequence[Sequence[float]],
             farbe: str = "rot") -> None:
    """Freihandzeichnung (Acrobat „Zeichnen“) – Liste von (x, y)-Punkten."""
    doc = session.doc
    if not 0 <= page < doc.page_count:
        raise DocumentAIError(f"Seite {page + 1} existiert nicht.")
    if len(punkte) < 2:
        return                          # einzelner Punkt: keine Linie
    pg = doc[page]
    pg.add_ink_annot([[(px, py) for px, py in punkte]])


# ------------------------------------------------------------ Schwärzen
def redaktion_markieren(session: Any, page: int,
                        rects: Sequence[Sequence[float]],
                        farbe=(0, 0, 0)) -> int:
    """Bereiche zum endgültigen Schwärzen markieren (noch sichtbar rot)."""
    doc = session.doc
    if not 0 <= page < doc.page_count:
        raise DocumentAIError(f"Seite {page + 1} existiert nicht.")
    pg = doc[page]
    n = 0
    for (x0, y0, x1, y1) in rects:
        pg.add_redact_annot(pymupdf.Rect(x0, y0, x1, y1), fill=farbe)
        n += 1
    return n


def redaktion_anwenden(session: Any) -> int:
    session._tables_cache = None
    session._tables_cache_all = None
    """Alle Schwärz-Markierungen anwenden: Inhalt wird ENDGÜLTIG entfernt
    (Text, Vektoren, Bilder im markierten Bereich). Rückgabe: Anzahl
    angewendeter Markierungen (seitenübergreifend)."""
    doc = session.doc
    n = 0
    for pg in doc:
        try:
            marks = list(pg.redact_annotations)
        except Exception:                           # noqa: BLE001
            marks = [a for a in pg.annots()
                     if a.type[1] and a.type[1].lower() == "redact"]
        n += len(marks)
        if marks:
            pg.apply_redactions()
    return n


# ------------------------------------------------------- Seiten-Verwaltung
def seite_loeschen(session: Any, nummern: Iterable[int]) -> int:
    session._tables_cache = None
    session._tables_cache_all = None
    """Seiten (0-basiert) löschen. Rückgabe: Anzahl gelöschter Seiten."""
    doc = session.doc
    loesch = sorted({n for n in nummern if 0 <= n < doc.page_count},
                    reverse=True)
    for n in loesch:
        doc.delete_page(n)
    return len(loesch)


def seite_extrahieren(session: Any, nummer: int, zielpfad: str) -> int:
    """Einzelne Seite als eigene PDF-Datei extrahieren (Original bleibt)."""
    doc = session.doc
    if not 0 <= nummer < doc.page_count:
        raise DocumentAIError(f"Seite {nummer + 1} existiert nicht.")
    with pymupdf.open() as neu:
        neu.insert_pdf(doc, from_page=nummer, to_page=nummer)
        neu.save(zielpfad, garbage=3, deflate=True)
    return 1


def zusammenfuehren(session: Any, pfade: Sequence[str],
                    an_position: int | None = None) -> int:
    """PDF-Dateien ans aktuelle Dokument anhängen (Acrobat „Dateien
    zusammenführen“). Rückgabe: Anzahl anhängender Dateien."""
    doc = session.doc
    session._tables_cache = None
    session._tables_cache_all = None
    n = 0
    for pfad in pfade:
        try:
            quelle = pymupdf.open(pfad)
        except Exception as exc:                    # noqa: BLE001
            raise DocumentAIError(
                f"Datei nicht lesbar: {pfad} ({exc})") from exc
        if quelle.needs_pass:
            raise DocumentAIError(
                f"Datei ist passwortgeschützt und wurde übersprungen: "
                f"{pfad}")
        if an_position is None:
            doc.insert_pdf(quelle)
        else:
            doc.insert_pdf(quelle, start_at=an_position)
        quelle.close()
        n += 1
    return n


# ----------------------------------------------------------- Schutz
def speichern_verschluesselt(session: Any, zielpfad: str,
                             nutzer_passwort: str,
                             erlaubt_drucken: bool = True,
                             erlaubt_kopieren: bool = True) -> dict:
    """Aktuelles Dokument AES-256-verschlüsselt als neue Datei speichern
    (Acrobat „Passwort schützen“ – hier ohne Adobe, nur PyMuPDF)."""
    if len(nutzer_passwort or "") < 4:
        raise DocumentAIError(
            "Passwort zu kurz (mindestens 4 Zeichen).")
    erlaubnis = pymupdf.PDF_PERM_ACCESSIBILITY
    if erlaubt_drucken:
        erlaubnis |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if erlaubt_kopieren:
        erlaubnis |= pymupdf.PDF_PERM_COPY | pymupdf.PDF_PERM_ANNOTATE
    doc = session.doc
    doc.save(zielpfad, encryption=pymupdf.PDF_ENCRYPT_AES_256,
             user_pw=nutzer_passwort, owner_pw=nutzer_passwort,
             permissions=erlaubnis, garbage=3, deflate=True)
    # Verifikation: ohne Passwort gesperrt, mit Passwort lesbar?
    probe = pymupdf.open(zielpfad)
    gesperrt = bool(probe.needs_pass)
    probe.close()
    return {"pfad": zielpfad, "ohne_passwort_gesperrt": gesperrt}


# ═════════════════════════════════════════════════════════════════════
# Acrobat-Pro-Ausbau (Stufe 2+3, 04.09.2026) – alles lokal & offen
# ═════════════════════════════════════════════════════════════════════

STAMPS = {                       # deutsche Anfrage → PDF-Standardstempel
    "geprueft": 0, "vertraulich": 1, "entwurf": 2, "final": 3,
    "freigegeben": 4, "kopie": 5,
}


def _invalidiere_caches(session: Any) -> None:
    """Mutation → Tabellen-Caches der Session verwerfen."""
    for schlüssel in ("_tables_cache", "_tables_cache_all"):
        if hasattr(session, schlüssel):
            setattr(session, schlüssel, None)


def _seite_oder_fehler(doc, page: int):
    if not 0 <= page < doc.page_count:
        raise DocumentAIError(f"Seite {page + 1} existiert nicht.")
    return doc[page]


# ------------------------------------------------ Aktenzeichen & Co.
def wasserzeichen(session: Any, text: str, seiten: list | None = None) -> int:
    """Graues, schräges Wasserzeichen auf alle (oder ausgewählte) Seiten
    (Acrobat „Wasserzeichen“). Gibt Anzahl bearbeiteter Seiten zurück."""
    import pymupdf
    doc = session.doc
    ziel = seiten if seiten is not None else range(doc.page_count)
    grau = 0.80
    n = 0
    for pno in ziel:
        page = _seite_oder_fehler(doc, pno)
        bp = pymupdf.Point(page.rect.width * 0.18, page.rect.height * 0.62)
        mat = pymupdf.Matrix(1, 0, 0, 1, 0, 0)
        mat.prerotate(35)
        page.insert_text(
            bp, text, fontsize=max(18, 56 - 2 * len(text) // 10),
            color=(grau, grau, grau), overlay=True, morph=(bp, mat))
        n += 1
    _invalidiere_caches(session)
    return n


def kopf_fusszeile(session: Any, kopf: str = "", fuss: str = "",
                   seitenzahl: bool = False, bates: str = "") -> int:
    """Kopf-/Fußzeile, Seitenzahlen oder Bates-Nummerierung
    (AKTE-000001 …, Kanzlei-Standard). Zweiter Aufruf ersetzt nichts,
    sondern ergänzt – Bestehendes bleibt sichtbar."""
    doc = session.doc
    n = 0
    for i in range(doc.page_count):
        page = doc[i]
        breite = page.rect.width
        if kopf:
            page.insert_text((breite * 0.08, 28), kopf, fontsize=9,
                             color=(0.25, 0.25, 0.25))
        if bates:
            kzel = f"{bates}-{i + 1:06d}"
            page.insert_text((breite * 0.08, page.rect.height - 16), kzel,
                             fontsize=10, color=(0.2, 0.2, 0.2))
        elif fuss:
            page.insert_text((breite * 0.08, page.rect.height - 16), fuss,
                             fontsize=9, color=(0.25, 0.25, 0.25))
        if seitenzahl:
            page.insert_text((breite / 2 - 10, page.rect.height - 16),
                             f"{i + 1} / {doc.page_count}", fontsize=9,
                             color=(0.25, 0.25, 0.25))
        n += 1
    _invalidiere_caches(session)
    return n


def stempel(session: Any, page: int, rect, art: str = "geprueft") -> None:
    """Standard-Stempel (GEPRÜFT, VERTRAULICH, ENTWURF, FINAL …)."""
    import pymupdf
    art = (art or "").strip().lower()
    ids = [pymupdf.STAMP_Approved, pymupdf.STAMP_Confidential,
           pymupdf.STAMP_Draft, pymupdf.STAMP_Final,
           pymupdf.STAMP_ForPublicRelease, pymupdf.STAMP_NotForPublicRelease]
    nr = STAMPS.get(art, 0)
    p = _seite_oder_fehler(session.doc, page)
    p.add_stamp_annot(pymupdf.Rect(rect), ids[nr])
    _invalidiere_caches(session)


def stempel_text(session: Any, page: int, rect, text: str) -> None:
    """Eigener Text-Stempel (rot umrandet, Acrobat „Dynamic Stempel“-Ersatz)."""
    p = _seite_oder_fehler(session.doc, page)
    p.add_freetext_annot(pymupdf.Rect(rect), text, fontsize=12,
                         fill_color=(1, 1, 1))
    _invalidiere_caches(session)


def text_einfuegen(session: Any, page: int, rect, text: str) -> None:
    """Text an Position/Rahmen einfügen (Acrobat „Text hinzufügen“)."""
    p = _seite_oder_fehler(session.doc, page)
    p.insert_textbox(pymupdf.Rect(rect), text, fontsize=11,
                     color=(0.1, 0.1, 0.1))
    _invalidiere_caches(session)


# ---------------------------------------------------- Seiten organisieren
def seite_verschieben(session: Any, von: int, nach: int) -> None:
    """Seite verschieben: Seite `von` (0-basiert) VOR Position `nach`."""
    import pymupdf
    doc = session.doc
    if not 0 <= von < doc.page_count:
        raise DocumentAIError(f"Quellseite {von + 1} existiert nicht.")
    nach = max(0, min(nach, doc.page_count))
    doc.move_page(von, nach)
    _invalidiere_caches(session)


def seiten_drehen(session: Any, von: int, bis: int, grad: int = 90) -> int:
    """Seitenbereich um 90/180/270 Grad drehen (inklusive). Gibt Anzahl
    gedrehter Seiten zurück."""
    doc = session.doc
    if grad % 90:
        raise DocumentAIError("Nur 90/180/270 Grad erlaubt.")
    n = 0
    for i in range(max(0, von), min(bis + 1, doc.page_count)):
        p = doc[i]
        p.set_rotation((p.rotation + grad) % 360)
        n += 1
    _invalidiere_caches(session)
    return n


def leerseite_einfuegen(session: Any, position: int) -> int:
    """Leere Seite EINFÜGEN VOR `position` (0-basiert)."""
    doc = session.doc
    position = max(0, min(position, doc.page_count))
    doc.insert_page(position)
    _invalidiere_caches(session)
    return position


def seite_einfuegen_aus_pdf(session: Any, quelle: str, position: int,
                            von_seite: int = 0, bis_seite: int | None = None
                            ) -> int:
    """Seiten aus einem ANDEREN PDF EINFÜGEN VOR `position`
    (Acrobat „Datei einfügen“). Gibt Anzahl eingefügter Seiten zurück."""
    import pymupdf
    doc = session.doc
    other = pymupdf.open(quelle)
    try:
        bis = other.page_count - 1 if bis_seite is None else bis_seite
        position = max(0, min(position, doc.page_count))
        doc.insert_pdf(other, from_page=von_seite, to_page=bis,
                       start_at=position)
        n = bis - von_seite + 1
    finally:
        other.close()
    _invalidiere_caches(session)
    return n


def zuschneiden(session: Any, page: int, raender) -> None:
    """Seite zuschneiden: raender = (links, unten, rechts, oben) in pt.
    Schwarzer Rand, Kopfzeile weg … Acrobat „Seite beschneiden“."""
    doc = session.doc
    p = _seite_oder_fehler(doc, page)
    l, u, r, o = raender
    neu = pymupdf.Rect(p.rect.x0 + l, p.rect.y0 + o,
                       p.rect.x1 - r, p.rect.y1 - u)
    if neu.is_empty or neu.width < 30 or neu.height < 30:
        raise DocumentAIError(
            "Zuschnitt zu aggressiv – es bliebe weniger als ein "
            "Briefmarke-Format übrig.")
    p.set_cropbox(neu)
    _invalidiere_caches(session)


def hintergrund(session: Any, farbe=(0.94, 0.96, 1.0), seiten=None) -> int:
    """Hintergrundfarbe HINTER den Inhalt legen (Acrobat „Hintergrund“) –
    z. B. helles Blau für besseres Lesen am Bildschirm."""
    doc = session.doc
    ziel = seiten if seiten is not None else range(doc.page_count)
    n = 0
    for i in ziel:
        p = _seite_oder_fehler(doc, i)
        p.draw_rect(p.rect, color=None, fill=farbe, overlay=False)
        n += 1
    _invalidiere_caches(session)
    return n


# ------------------------------------------------- Suchen & endgültig weg
def suchen_und_schwaerzen(session: Any, begriff: str) -> int:
    """Jedes Vorkommen eines Begriffs AUF ALLEN Seiten endgültig
    entfernen (Text wird wirklich gelöscht, nicht nur verdeckt)."""
    doc = session.doc
    n = 0
    for page in doc:
        treffer = list(page.search_for(begriff))
        for r in treffer:
            page.add_redact_annot(r)
        if treffer:
            page.apply_redactions()
            n += len(treffer)
    _invalidiere_caches(session)
    return n


# ------------------------------------------------------- Optimieren & Co.
def optimieren(session: Any, zielpfad: str) -> dict:
    """PDF neu schreiben mit Kompression (Acrobat „In PDF optimieren,
    verkleinern“). Original bleibt unberührt."""
    import os
    doc = session.doc
    doc.save(zielpfad, garbage=4, deflate=True, clean=True)
    return {"pfad": zielpfad, "bytes": os.path.getsize(zielpfad)}


def formular_abflachen(session: Any, model) -> int:
    """Alle Formularfelder zu festem Inhalt machen (Acrobat „Abflachen“)
    – Werte können danach nicht mehr geändert, aber auch nicht mehr
    versehentlich gelöscht werden."""
    doc = session.doc
    n = 0
    for page in doc:
        widgets = list(page.widgets() or [])
        for w in widgets:
            wert = w.field_value
            if wert not in (None, "", "Off", False):
                if w.field_type_string == "CheckBox":
                    page.insert_textbox(w.rect, "X", fontsize=max(
                        10, w.rect.height * 0.7), color=(0, 0, 0.55))
                else:
                    page.insert_textbox(w.rect, str(wert),
                                        fontsize=11, color=(0, 0, 0.55))
            n += 1
        for w in widgets:
            page.delete_widget(w)
    model.fields = []
    _invalidiere_caches(session)
    return n


# ----------------------------------------------------------- Anhänge
def anhang_einbetten(session: Any, pfad: str, name: str | None = None,
                     beschreibung: str = "") -> None:
    """Datei als PDF-Anhang einbetten (Acrobat „Anlage anfügen“)."""
    import os
    doc = session.doc
    with open(pfad, "rb") as f:              # sauber schließen (0 Warnungen)
        daten = f.read()
    doc.embfile_add(name or os.path.basename(pfad), daten,
                    filename=os.path.basename(pfad),
                    desc=beschreibung or "DocumentAI-Anhang")
    _invalidiere_caches(session)


def anhaenge_lesen(session: Any) -> list[dict]:
    """Eingebettete Anhänge auflisten (Name, Größe, Beschreibung)."""
    doc = session.doc
    out = []
    for name in doc.embfile_names():
        info = doc.embfile_info(name)
        out.append({"name": name, "bytes": info.get("length", 0) or
                    info.get("size", 0), "beschreibung": info.get("desc", "")})
    return out


def anhang_extrahieren(session: Any, name: str, zielpfad: str) -> str:
    """Eingebetteten Anhang als Datei speichern."""
    doc = session.doc
    daten = doc.embfile_get(name)
    with open(zielpfad, "wb") as f:           # sauber schließen (0 Warnungen)
        f.write(daten)
    return zielpfad


# -------------------------------------------------- Bilder ↔ PDF
def bilder_zu_pdf(bilder: list[str], zielpfad: str) -> str:
    """JPEG/PNG-Dateien zu einem PDF zusammenfügen (Acrobat „Aus Datei
    erstellen: Bild“)."""
    import pymupdf
    doc = pymupdf.open()
    for bild in bilder:
        page = doc.new_page()
        page.insert_image(page.rect, filename=bild)
    doc.save(zielpfad)
    doc.close()
    return zielpfad


def bild_einfuegen(session: Any, page: int, rect, bildpfad: str) -> None:
    """Bild (z. B. Unterschrift, Foto) in Rahmen platzieren."""
    p = _seite_oder_fehler(session.doc, page)
    p.insert_image(pymupdf.Rect(rect), filename=bildpfad)
    _invalidiere_caches(session)


def export_als_bilder(session: Any, ordner: str, dpi: int = 150) -> list[str]:
    """Jede Seite als PNG exportieren (Acrobat „Exportieren: Bild“)."""
    import os
    doc = session.doc
    pfade = []
    for i in range(doc.page_count):
        ziel = os.path.join(ordner, f"seite_{i + 1:03d}.png")
        doc[i].get_pixmap(dpi=dpi).save(ziel)
        pfade.append(ziel)
    return pfade


def form_zeichnen(session: Any, page: int, art: str,
                  p0: Sequence[float], p1: Sequence[float],
                  farbe: str = "rot") -> None:
    """Zeichen-Formen (Acrobat „Zeichnen“): Linie, Pfeil, Kreis,
    Rechteck – als echte PDF-Annotationen (lösbar/deletable)."""
    p = _seite_oder_fehler(session.doc, page)
    col = FARBEN.get(farbe, FARBEN["rot"])
    x0, y0 = float(p0[0]), float(p0[1])
    x1, y1 = float(p1[0]), float(p1[1])
    if art == "linie":
        a = p.add_line_annot(pymupdf.Point(x0, y0), pymupdf.Point(x1, y1))
        a.set_colors(stroke=col)
        a.update()
    elif art == "pfeil":
        a = p.add_line_annot(pymupdf.Point(x0, y0), pymupdf.Point(x1, y1))
        a.set_colors(stroke=col)
        a.set_line_ends(0, 4)                # 4 = ClosedArrow (Ende)
        a.update()
    elif art == "kreis":
        r = pymupdf.Rect(min(x0, x1), min(y0, y1),
                         max(x0, x1), max(y0, y1))
        a = p.add_circle_annot(r)
        a.set_colors(stroke=col)
        a.update()
    elif art == "rechteck":
        r = pymupdf.Rect(min(x0, x1), min(y0, y1),
                         max(x0, x1), max(y0, y1))
        a = p.add_rect_annot(r)
        a.set_colors(stroke=col)
        a.update()
    else:
        raise DocumentAIError(f"Unbekannte Zeichenform: {art!r}")
    _invalidiere_caches(session)


def polyform_zeichnen(session: Any, page: int, art: str,
                      punkte: Sequence[Sequence[float]],
                      farbe: str = "rot", text: str = "") -> None:
    """Mehrpunkt-Zeichenformen (Acrobat „Zeichnen“-Palette):
    polygon (geschlossen), polylinie (Verbundene Linien, offen),
    wolke (Kommentarwolke, gezackte Bögen) und legende (Textlegende:
    Zeigerlinie + Textkasten)."""
    p = _seite_oder_fehler(session.doc, page)
    col = FARBEN.get(farbe, FARBEN["rot"])
    pts = [pymupdf.Point(float(x), float(y)) for x, y in punkte]
    if len(pts) < 2:
        raise DocumentAIError("Mehrpunkt-Form braucht mindestens "
                              "2 Punkte.")
    if art == "polygon":
        a = p.add_polygon_annot(pts)
        a.set_colors(stroke=col)
        a.update()
    elif art == "polylinie":
        a = p.add_polyline_annot(pts)
        a.set_colors(stroke=col)
        a.update()
    elif art == "wolke":
        a = p.add_polygon_annot(pts)
        a.set_colors(stroke=col)
        # Wolkenrand: gezackte Bogenkontur statt gerader Kanten
        a.set_border(width=2, clouds=3)
        a.update()
    elif art == "legende":
        if not text:
            raise DocumentAIError("Textlegende braucht einen Text.")
        anker, kasten_ecke = pts[0], pts[-1]
        b = max(120.0, 7.2 * len(text) + 16)     # Kastenbreite
        h = 26.0
        r = pymupdf.Rect(kasten_ecke.x, kasten_ecke.y - h,
                         kasten_ecke.x + b, kasten_ecke.y)
        linie = p.add_line_annot(anker, pymupdf.Point(r.x0, r.y1))
        linie.set_colors(stroke=col)
        linie.update()
        f = p.add_freetext_annot(r, text)
        f.update()
    else:
        raise DocumentAIError(f"Unbekannte Mehrpunkt-Form: {art!r}")
    _invalidiere_caches(session)


def metadaten_lesen(session: Any) -> dict:
    """Dokumenteigenschaften (Acrobat „Datei > Eigenschaften“)."""
    m = dict(session.doc.metadata or {})
    m["seiten"] = session.doc.page_count
    m["verschluesselt"] = bool(session.doc.is_encrypted)
    return m


def metadaten_setzen(session: Any, titel: str | None = None,
                     autor: str | None = None, thema: str | None = None,
                     schlagworte: str | None = None) -> None:
    """Dokumenteigenschaften setzen (Titel, Autor, Thema, Schlagwörter)."""
    alt = dict(session.doc.metadata or {})
    neu = {
        "title": alt.get("title", "") if titel is None else titel,
        "author": alt.get("author", "") if autor is None else autor,
        "subject": alt.get("subject", "") if thema is None else thema,
        "keywords": (alt.get("keywords", "")
                     if schlagworte is None else schlagworte),
    }
    alt.update(neu)
    session.doc.set_metadata(alt)
    _invalidiere_caches(session)


def zertifizierte_kopie(session: Any, zielpfad: str) -> dict:
    """Zertifizierte Kopie (Acrobat: nach dem Signieren schreibgeschützte
    Kopie mit Audit-Spur). Lokal: AES-256-Versiegelung mit zufälligem
    Eigentümer-Geheimnis – lesbar für alle, Ändern für niemanden."""
    import secrets
    info = session.signatur_info() if hasattr(session, "signatur_info") \
        else {}
    geheimnis = secrets.token_urlsafe(24)
    erlaubt = (pymupdf.PDF_PERM_PRINT
               | pymupdf.PDF_PERM_ACCESSIBILITY)
    session.doc.save(zielpfad, encryption=pymupdf.PDF_ENCRYPT_AES_256,
                     owner_pw=geheimnis, user_pw="",
                     permissions=erlaubt, garbage=3, deflate=True)
    return {"pfad": zielpfad, "server_geheimnis_verworfen": True,
            "signiert_vorher": bool(info.get("vorhanden", False)),
            "verfahren": "AES-256, Rechte: nur Lesen/Drucken/Zugriff"}


def fuell_zeichen(session: Any, page: int, x: float, y: float,
                  zeichen: str) -> None:
    """Fill-&-Sign-Ein-Klick-Zeichen (Acrobat „Text eingeben“-Palette):
    Kreuz, Häkchen, Punkt, Umranden, Durchstreichen – als Vektorformen
    (schriften unabhängig, immer darstellbar)."""
    p = _seite_oder_fehler(session.doc, page)
    form = pymupdf.Shape(p)
    rot = FARBEN["rot"]
    if zeichen == "haekchen":
        form.draw_line(pymupdf.Point(x - 4, y + 1), pymupdf.Point(x - 1, y + 4))
        form.draw_line(pymupdf.Point(x - 1, y + 4), pymupdf.Point(x + 5, y - 4))
        form.finish(color=(0.13, 0.55, 0.13), width=1.8)
    elif zeichen == "kreuz":
        form.draw_line(pymupdf.Point(x - 4, y - 4), pymupdf.Point(x + 4, y + 4))
        form.draw_line(pymupdf.Point(x + 4, y - 4), pymupdf.Point(x - 4, y + 4))
        form.finish(color=rot, width=1.8)
    elif zeichen == "punkt":
        form.draw_circle(pymupdf.Point(x, y), 2.5)
        form.finish(color=rot, fill=rot)
    elif zeichen == "umranden":
        form.draw_circle(pymupdf.Point(x, y), 8)
        form.finish(color=FARBEN["blau"], width=1.5)
    elif zeichen == "durchstreichen":
        form.draw_line(pymupdf.Point(x - 8, y), pymupdf.Point(x + 8, y))
        form.finish(color=rot, width=1.5)
    else:
        raise DocumentAIError(f"Unbekanntes Füllzeichen: {zeichen!r}")
    form.commit()
    _invalidiere_caches(session)


def link_hinzufuegen(session: Any, page: int, rect,
                     url: str) -> None:
    """Verknüpfung (Link) auf URL legen (Acrobat „Verknüpfung“)."""
    p = _seite_oder_fehler(session.doc, page)
    if not url.strip():
        raise DocumentAIError("Verknüpfung ohne Ziel macht keinen Sinn.")
    ziel = url.strip()
    if not (ziel.startswith("http://") or ziel.startswith("https://")
            or ziel.startswith("mailto:") or ziel.startswith("file:")):
        ziel = "https://" + ziel
    p.insert_link({"kind": pymupdf.LINK_URI,
                   "from": pymupdf.Rect(rect), "uri": ziel})
    _invalidiere_caches(session)


def bates_nummerierung(session: Any, praefix: str = "",
                       start: int = 1, suffix: str = "",
                       position: str = "unten_rechts") -> int:
    """Bates-Nummerierung: fortlaufende Nummer auf JEDER Seite
    (Acrobat „Bates-Nummerierung“) – lokal, kein Cloud-Dienst."""
    doc = session.doc
    n = 0
    for i in range(doc.page_count):
        p = doc[i]
        nr = f"{praefix}{start + i:06d}{suffix}"
        breite = pymupdf.get_text_length(nr, fontname="hebo", fontsize=9)
        r = p.rect
        if position == "oben_rechts":
            pos = pymupdf.Point(r.width - 40 - breite, 24)
        else:
            pos = pymupdf.Point(r.width - 40 - breite, r.height - 12)
        p.insert_text(pos, nr, fontsize=9, fontname="hebo",
                      color=(0.45, 0.45, 0.45))
        n += 1
    _invalidiere_caches(session)
    return n


def freihand_dick(session: Any, page: int,
                  punkte: Sequence[Sequence[float]], breite: float = 2.2,
                  farbe=(0.85, 0.1, 0.1)) -> None:
    """Deutsche Unterschrift: dicke Freihandlinie (Acrobat „Ausfüllen &
    Signieren“)."""
    import pymupdf
    doc = session.doc
    if len(punkte) < 2:
        return
    pg = _seite_oder_fehler(doc, page)
    form = pymupdf.Shape(pg)
    form.draw_polyline([(px, py) for px, py in punkte])
    form.finish(color=farbe, width=breite, lineCap=1, no_fill=True)
    form.commit()
    _invalidiere_caches(session)


# ------------------------------------------------ Lesezeichen & Kommentare
def lesezeichen_lesen(session: Any) -> list[dict]:
    """PDF-Lesezeichen (Inhaltsverzeichnis) als Liste:
    {ebene, titel, seite} – Seite 0-basiert."""
    doc = session.doc
    return [{"ebene": eb, "titel": ti, "seite": sp - 1}
            for eb, ti, sp in doc.get_toc()]


def lesezeichen_hinzufuegen(session: Any, titel: str, seite: int) -> None:
    """Lesezeichen auf Seite (0-basiert) hinzufügen. Bestehende
    Lesezeichen bleiben erhalten."""
    doc = session.doc
    _seite_oder_fehler(doc, seite)
    toc = doc.get_toc()
    toc.append([1, titel, seite + 1])
    doc.set_toc(toc)
    _invalidiere_caches(session)


def lesezeichen_loeschen(session: Any, index: int) -> None:
    """Lesezeichen (Index in der Leseliste) entfernen."""
    doc = session.doc
    toc = doc.get_toc()
    if not 0 <= index < len(toc):
        raise DocumentAIError("Lesezeichen existiert nicht.")
    del toc[index]
    doc.set_toc(toc)
    _invalidiere_caches(session)


def kommentare_lesen(session: Any) -> list[dict]:
    """Alle Kommentare/Markierungen listen (Acrobat-Kommentarliste):
    {seite, typ, text, rect} – für das Kommentar-Panel."""
    doc = session.doc
    out = []
    for i in range(doc.page_count):
        for a in (doc[i].annots() or []):
            info = a.info
            out.append({"seite": i, "typ": a.type[1], "typ_nr": a.type[0],
                        "text": (info.get("content", "") or ""),
                        "titel": (info.get("title", "") or ""),
                        "rect": tuple(a.rect)})
    return out
