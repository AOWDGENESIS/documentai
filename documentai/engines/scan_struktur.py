"""Raster-Strukturerkennung für gescannte Formulare – rein lokal.

Setzt die bewährte Formular-Analyse-Strategie um, die sonst OpenCV-
Morphologie nutzt (Binärisieren, horizontale/vertikale Linien über
long-line-Opening extrahieren, daraus Kästchen/Rahmen ableiten) – hier
completely ohne OpenCV: Pillow-Binarisierung (Otsu) plus C-schnelle
Lauflängen-Analyse der Byte-Zeilen.

Liefert präzise PDF-Punkt-Koordinaten für
- Feldlinien (Unterstriche, Tabellenlinien),
- geschlossene Kästchen (Checkboxen) und Rahmen (Eingabefelder),
- die Tinte-Ausdehnung (Handschrift/Eintrag) innerhalb einer Region –
  die Grundlage, um bei Korrekturen den alten Eintrag pixelgenau zu
  entfernen, ohne die Formularlinie selbst zu beschädigen.
"""
from __future__ import annotations

import io
from dataclasses import dataclass

try:
    from PIL import Image
    PIL_OK = True
except Exception:                       # pragma: no cover - Labor ohne Pillow
    PIL_OK = False


# ------------------------------------------------------------------
# Datenstrukturen (alle Koordinaten in PDF-Punkten, Ursprung oben links)
# ------------------------------------------------------------------
@dataclass
class HLinie:
    x0: float
    y0: float              # obere Kante
    x1: float
    y1: float              # untere Kante (Dicke)

    @property
    def laenge(self) -> float:
        return self.x1 - self.x0

    @property
    def mitte_y(self) -> float:
        return (self.y0 + self.y1) / 2


@dataclass
class VLinie:
    x0: float              # linke Kante (Dicke)
    y0: float
    x1: float              # rechte Kante
    y1: float

    @property
    def laenge(self) -> float:
        return self.y1 - self.y0

    @property
    def mitte_x(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Kasten:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def breite(self) -> float:
        return self.x1 - self.x0

    @property
    def hoehe(self) -> float:
        return self.y1 - self.y0


# ------------------------------------------------------------------
@dataclass
class ScanStruktur:
    """Ergebnis der Raster-Analyse einer Seite."""
    linien_h: list[HLinie]
    linien_v: list[VLinie]
    kasten: list[Kasten]
    breite_pt: float
    hoehe_pt: float
    # interne Pixeldaten für die Tinten-Suche (dunkel = 0)
    _sw: bytes | None = None
    _w: int = 0
    _h: int = 0
    _faktor: float = 1.0     # px -> pt

    # ------------------------------------------------ Tinte in Region
    def tinte_bbox(self, x0: float, y0: float, x1: float, y1: float,
                   min_pixel: int = 12,
                   kasten: "Kasten | None" = None
                   ) -> tuple[float, float, float, float] | None:
        """Dunkle Pixel (Handschrift/Eintrag) in der Region [x0..x1]×
        [y0..y1] (pt). Formularlinien werden ignoriert; ein übergebenes
        Kästchen schützt zusätzlich dessen Ränder. Liefert die
        Tinte-BoundingBox (pt) oder None, wenn nur Rauschen present."""
        if self._sw is None:
            return None
        f = self._faktor
        px_x0 = max(0, int(x0 / f))
        px_x1 = min(self._w, int(round(x1 / f)))
        px_y0 = max(0, int(y0 / f))
        px_y1 = min(self._h, int(round(y1 / f)))
        if px_x1 <= px_x0 or px_y1 <= px_y0:
            return None
        # Zeilen/Formularlinien aussparen (Tinte sitzt ZWISCHEN den Linien)
        linien_zeilen: set[int] = set()
        for l in self.linien_h:
            if l.x1 <= x0 or l.x0 >= x1:
                continue
            for y in range(max(0, int(l.y0 / f) - 2),
                           min(self._h, int(round(l.y1 / f)) + 3)):
                linien_zeilen.add(y)
        linien_spalten: list[tuple[int, int]] = []
        for l in self.linien_v:
            if l.y1 <= y0 or l.y0 >= y1:
                continue
            linien_spalten.append((max(0, int(l.x0 / f) - 1),
                                   int(round(l.x1 / f)) + 2))
        if kasten is not None:
            kband = max(1, int(1.0 / f))
            if not (kasten.x1 <= x0 or kasten.x0 >= x1
                    or kasten.y1 <= y0 or kasten.y0 >= y1):
                for ky in (kasten.y0, kasten.y1):
                    for y in range(max(0, int(ky / f) - kband),
                                   min(self._h,
                                       int(round(ky / f)) + kband + 1)):
                        linien_zeilen.add(y)
                for kx in (kasten.x0, kasten.x1):
                    linien_spalten.append(
                        (max(0, int(kx / f) - kband),
                         int(round(kx / f)) + kband + 1))
        gefunden = 0
        min_x = 1 << 30
        max_x = -1
        min_y = 1 << 30
        max_y = -1
        w = self._w
        sw = self._sw
        for py in range(px_y0, px_y1):
            if py in linien_zeilen:
                continue
            basis = py * w
            zeile = sw[basis + px_x0:basis + px_x1]
            pos = 0
            for teil in zeile.split(b"\xff"):
                n = len(teil)
                if n:
                    ax0 = px_x0 + pos
                    ax1 = px_x0 + pos + n
                    # Spalten strukturierter Linien ausblenden
                    rest = [(ax0, ax1)]
                    for sx0, sx1 in linien_spalten:
                        neu = []
                        for r0, r1 in rest:
                            if r1 <= sx0 or sx1 <= r0:
                                neu.append((r0, r1))
                                continue
                            if r0 < sx0:
                                neu.append((r0, sx0))
                            if r1 > sx1:
                                neu.append((sx1, r1))
                        rest = neu
                    for r0, r1 in rest:
                        if r1 <= r0:
                            continue
                        gefunden += r1 - r0
                        if r0 < min_x:
                            min_x = r0
                        if r1 - 1 > max_x:
                            max_x = r1 - 1
                        if py < min_y:
                            min_y = py
                        if py > max_y:
                            max_y = py
                pos += n + 1
        if gefunden < min_pixel:
            return None
        return (min_x * f, min_y * f, (max_x + 1) * f, (max_y + 1) * f)


# ------------------------------------------------------------------
# Analyse
# ------------------------------------------------------------------
def _otsu(histogramm: list[int]) -> int:
    """Klassischer Otsu-Schwellwert über das 256-Bin-Histogramm."""
    gesamt = sum(histogramm)
    if gesamt == 0:
        return 128
    summe = 0.0
    for i in range(256):
        summe += i * histogramm[i]
    summe_b = 0.0
    w_b = 0
    best = -1.0
    schwelle = 128
    for t in range(256):
        w_b += histogramm[t]
        if w_b == 0:
            continue
        w_v = gesamt - w_b
        if w_v == 0:
            break
        summe_b += t * histogramm[t]
        m_b = summe_b / w_b
        m_v = (summe - summe_b) / w_v
        varianz = w_b * w_v * (m_b - m_v) * (m_b - m_v)
        if varianz > best:
            best = varianz
            schwelle = t
    return schwelle


def _dunkle_runs(zeile: bytes, min_len: int) -> list[tuple[int, int]]:
    """Dunkle Lauflängen (Wert < 255) mit Start/Ende >= min_len."""
    runs: list[tuple[int, int]] = []
    pos = 0
    for teil in zeile.split(b"\xff"):
        n = len(teil)
        if n >= min_len:
            runs.append((pos, pos + n))
        pos += n + 1
    return runs


def _merge_zeilen_segments(segments: list[tuple[int, int, int]],
                           min_deckung: float = 0.55,
                           max_luecke: int = 2) \
        -> list[tuple[int, int, int, int]]:
    """Verschmilzt aufeinanderfolgende Zeilen-Segmente (y, x0, x1) zu
    Linien (y0, y1, x0, x1), sofern sie sich überlagern. Bis zu
    `max_luecke` helle Zwischenzeilen (Anti-Aliasing) werden toleriert."""
    linien: list[tuple[int, int, int, int]] = []
    aktuell: tuple[int, int, int, int] | None = None
    for y, x0, x1 in segments:
        if aktuell is not None and y <= aktuell[1] + 1 + max_luecke:
            ax0, ax1 = aktuell[2], aktuell[3]
            overlap = min(x1, ax1) - max(x0, ax0)
            basis = max(1, min(x1 - x0, ax1 - ax0))
            if overlap / basis >= min_deckung:
                aktuell = (aktuell[0], max(aktuell[1], y),
                           min(ax0, x0), max(ax1, x1))
                continue
        if aktuell is not None:
            linien.append(aktuell)
        aktuell = (y, y, x0, x1)
    if aktuell is not None:
        linien.append(aktuell)
    return linien


MIN_FELDLINIE_PT = 40.0      # kürzeste Linie, die ein Feld andeutet
MAX_DICKE_PT = 4.0           # dickste „Linie“ (dicker = Balken/Fläche)
KASTEN_MIN_PT = 7.5          # Checkbox-Mindestgröße (kleiner = Schrift)
KASTEN_MAX_PT = 22.0         # Checkbox-Maximalgröße
RAHMEN_MIN_BREITE_PT = 30.0  # ab hier gilt ein Kasten als Eingaberahmen
RAHMEN_MIN_HOEHE_PT = 11.0


def analysiere(png_bytes: bytes, dpi: float = 200.0) -> ScanStruktur:
    """Analysiert ein Seiten-Bild (PNG-Bytes) auf Formularstruktur."""
    if not PIL_OK:
        return ScanStruktur([], [], [], 595.0, 842.0)
    img = Image.open(io.BytesIO(png_bytes))
    if img.mode != "L":
        img = img.convert("L")
    otsu = _otsu(img.histogram())
    # Tolerante Schwelle: Anti-Aliasing-Kanten dünner Striche (0,8 pt)
    # liegen GRAU über der Otsu-Schwelle und würden sonst spurlos
    # verschwinden. Sehr helle Flächen (> 220) bleiben weiß.
    schwelle = min(otsu + 60, 220)
    tabelle = [0 if i < schwelle else 255 for i in range(256)]
    sw = img.point(tabelle, "L")
    breite, hoehe = sw.size
    daten = sw.tobytes()
    faktor = 72.0 / dpi
    min_len_px = max(8, int(MIN_FELDLINIE_PT * dpi / 72.0))

    # --- horizontale Feldlinien (lang) -------------------------------
    segments: list[tuple[int, int, int]] = []
    for y in range(hoehe):
        zeile = daten[y * breite:(y + 1) * breite]
        for x0, x1 in _dunkle_runs(zeile, min_len_px):
            segments.append((y, x0, x1))
    linien_h = [
        HLinie(x0 * faktor, y0 * faktor, x1 * faktor, (y1 + 1) * faktor)
        for y0, y1, x0, x1 in _merge_zeilen_segments(segments)
        if (y1 + 1 - y0) * faktor <= MAX_DICKE_PT
    ]

    # --- vertikale Linien (über Hauptdiagonale transponieren) --------
    trans = sw.transpose(Image.TRANSPOSE)
    tdaten = trans.tobytes()
    segments = []
    for x in range(breite):
        spalte = tdaten[x * hoehe:(x + 1) * hoehe]
        for y0, y1 in _dunkle_runs(spalte, min_len_px):
            segments.append((x, y0, y1))
    linien_v = [
        VLinie(x0 * faktor, y0 * faktor, (x1 + 1) * faktor, y1 * faktor)
        for x0, x1, y0, y1 in _merge_zeilen_segments(segments)
        if (x1 + 1 - x0) * faktor <= MAX_DICKE_PT
    ]

    # --- große Rahmen: H-Linienpaare + verbindende V-Linien ---------
    kasten: list[Kasten] = []
    linien_h_sortiert = sorted(linien_h, key=lambda l: (l.mitte_y, l.x0))
    for i, oben in enumerate(linien_h_sortiert):
        for unten in linien_h_sortiert[i + 1:]:
            hoehe_pt = unten.mitte_y - oben.mitte_y
            if hoehe_pt < RAHMEN_MIN_HOEHE_PT:
                continue
            if hoehe_pt > 70.0:
                break
            xl = max(oben.x0, unten.x0)
            xr = min(oben.x1, unten.x1)
            breite_pt = xr - xl
            if breite_pt < RAHMEN_MIN_BREITE_PT:
                continue
            # zusammengehörig? gemeinsame Ausdehnung deutlich
            if breite_pt < 0.6 * max(oben.laenge, unten.laenge):
                continue
            links = _vlinie_an(linien_v, xl, oben.mitte_y, unten.mitte_y)
            rechts = _vlinie_an(linien_v, xr, oben.mitte_y, unten.mitte_y)
            if links and rechts:
                k = Kasten(xl, oben.y0, xr, unten.y1)
                if not any(_kasten_deckung(k, b) > 0.5 for b in kasten):
                    kasten.append(k)

    # --- kleine Kästchen (Checkboxen): Kurz-Kanten-Pass -------------
    # Kästchenränder sind kürzer als Feldlinien; Buchstaben (O, D, 0)
    # erzeugen ähnliche Kantenzüge. Präzision über strenge Geometrie:
    # gerade, durchgehende Kanten + exakt dunkle Ecken (runde Glyphen
    # haben helle Ecken).
    kasten.extend(_kaestchen_aus_kurzkanten(daten, tdaten, breite, hoehe,
                                            dpi, faktor))
    return ScanStruktur(
        linien_h=linien_h, linien_v=linien_v, kasten=kasten,
        breite_pt=breite * faktor, hoehe_pt=hoehe * faktor,
        _sw=daten, _w=breite, _h=hoehe, _faktor=faktor)


def _kaestchen_aus_kurzkanten(daten: bytes, tdaten: bytes, breite: int,
                              hoehe: int, dpi: float, faktor: float
                              ) -> list[Kasten]:
    min_px = max(6, int(4.5 * dpi / 72.0))
    max_px = int(26.0 * dpi / 72.0)
    max_dicke_px = int(3.5 * dpi / 72.0) + 2

    def kanten(buf: bytes, laenge: int, versatz: int):
        segs = []
        for y in range(laenge):
            zeile = buf[y * versatz:(y + 1) * versatz]
            for x0, x1 in _dunkle_runs(zeile, min_px):
                if x1 - x0 <= max_px:
                    segs.append((y, x0, x1))
        roh = [(a, b, c, d) for a, b, c, d in
               _merge_zeilen_segments(segs) if b - a < max_dicke_px]
        # Anti-Aliasing-Splitter zusammenführen (gleiche Lage, nahe Zeile)
        aufgeraeumt: list[tuple[int, int, int, int]] = []
        for a, b, c, d in sorted(roh):
            if aufgeraeumt:
                va, vb, vc, vd = aufgeraeumt[-1]
                if (a - vb) * faktor <= 3.0 and \
                        min(d, vd) - max(c, vc) >= 0.6 * min(d - c, vd - vc):
                    aufgeraeumt[-1] = (va, max(vb, b), min(vc, c),
                                       max(vd, d))
                    continue
            aufgeraeumt.append((a, b, c, d))
        return aufgeraeumt

    kanten_h = kanten(daten, hoehe, breite)
    kanten_v = kanten(tdaten, breite, hoehe)
    hmap = [HLinie(c * faktor, a * faktor, d * faktor, (b + 1) * faktor)
            for a, b, c, d in kanten_h]
    vlist = [VLinie(a * faktor, b * faktor, (a + 1) * faktor, c * faktor)
             for a, b, c, d in kanten_v]
    kasten: list[Kasten] = []
    hmap.sort(key=lambda l: (l.mitte_y, l.x0))
    for i, oben in enumerate(hmap):
        for unten in hmap[i + 1:]:
            h_pt = unten.mitte_y - oben.mitte_y
            if h_pt < KASTEN_MIN_PT:
                continue
            if h_pt > KASTEN_MAX_PT + 2:
                break
            xl = max(oben.x0, unten.x0)
            xr = min(oben.x1, unten.x1)
            b_pt = xr - xl
            if b_pt < KASTEN_MIN_PT or b_pt > KASTEN_MAX_PT + 2:
                continue
            if abs(b_pt - h_pt) > max(3.0, 0.35 * max(b_pt, h_pt)):
                continue                      # Kästchen sind quadratisch
            # Kanten müssen fast die volle Breite/Höhe decken
            if min(oben.laenge, unten.laenge) < 0.85 * b_pt:
                continue
            links = [l for l in vlist
                     if abs(l.mitte_x - xl) <= 2.0
                     and l.laenge >= 0.8 * h_pt]
            rechts = [l for l in vlist
                      if abs(l.mitte_x - xr) <= 2.0
                      and l.laenge >= 0.8 * h_pt]
            if not links or not rechts:
                continue
            k = Kasten(xl, oben.y0, xr, unten.y1)
            if not _ecken_dunkel(daten, breite, hoehe, faktor, k):
                continue
            # Nachbar-Ruhe: Buchstaben-Schlingen (o, e, 0) sitzen IM
            # Text – um ein echtes Kontrollkästchen herum ist es ruhig.
            if not _rand_ruhigh(daten, breite, hoehe, faktor, k):
                continue
            if not any(_kasten_deckung(k, b) > 0.5 for b in kasten):
                kasten.append(k)
    return kasten


def _rand_ruhigh(daten: bytes, breite: int, hoehe: int, faktor: float,
                 k: Kasten, rand_pt: float = 2.5,
                 max_dunkel_anteil: float = 0.45) -> bool:
    """Rundum den Kandidaten muss es überwiegend hell bleiben –
    Schriftzeichen hätten direkte Nachbarn."""
    x0 = int(max(0.0, k.x0 - rand_pt) / faktor)
    x1 = int(min(float(breite) * faktor, k.x1 + rand_pt) / faktor)
    y0 = int(max(0.0, k.y0 - rand_pt) / faktor)
    y1 = int(min(float(hoehe) * faktor, k.y1 + rand_pt) / faktor)
    ix0 = int(k.x0 / faktor)
    ix1 = max(ix0 + 1, int(k.x1 / faktor))
    iy0 = int(k.y0 / faktor)
    iy1 = max(iy0 + 1, int(k.y1 / faktor))
    dunkel = 0
    gesamt = 0
    for y in range(y0, y1):
        for x in range(x0, x1):
            if ix0 <= x < ix1 and iy0 <= y < iy1:
                continue                      # nur der Randring zählt
            gesamt += 1
            if daten[y * breite + x] < 128:
                dunkel += 1
    if gesamt == 0:
        return True
    return dunkel / gesamt <= max_dunkel_anteil


def _ecken_dunkel(daten: bytes, breite: int, hoehe: int, faktor: float,
                  k: Kasten) -> bool:
    """Alle vier Ecken eines echten Rechtecks sind dunkel; runde
    Buchstabenschlingen (O, 0, ö) lassen die exakten Ecken hell."""
    ecke_px = max(2, int(1.1 / faktor))
    punkte = [(k.x0, k.y0), (k.x1 - 1.0 * faktor, k.y0),
              (k.x0, k.y1 - 1.0 * faktor),
              (k.x1 - 1.0 * faktor, k.y1 - 1.0 * faktor)]
    for px, py in punkte:
        x0 = int(px / faktor)
        y0 = int(py / faktor)
        dunkel = 0
        gesamt = 0
        for dy in range(ecke_px):
            for dx in range(ecke_px):
                x = x0 + dx
                y = y0 + dy
                if 0 <= x < breite and 0 <= y < hoehe:
                    gesamt += 1
                    if daten[y * breite + x] < 128:
                        dunkel += 1
        if gesamt == 0 or dunkel / gesamt < 0.55:
            return False
    return True


def _vlinie_an(linien_v: list[VLinie], x: float, y_oben: float,
               y_unten: float) -> bool:
    """Gibt es eine V-Linie an Position x, die den Bereich überdeckt?"""
    toleranz = 2.5
    for l in linien_v:
        if abs(l.mitte_x - x) > toleranz:
            continue
        if l.y0 <= y_oben + toleranz and l.y1 >= y_unten - toleranz:
            return True
        # Teilstrecken (beschädigte Kanten) über mindestens 60 % gelten
        deckend = min(l.y1, y_unten) - max(l.y0, y_oben)
        if deckend >= 0.6 * (y_unten - y_oben):
            return True
    return False


def _kasten_deckung(a: Kasten, b: Kasten) -> float:
    """Überlappungsfläche von a in b (0..1)."""
    ix = min(a.x1, b.x1) - max(a.x0, b.x0)
    iy = min(a.y1, b.y1) - max(a.y0, b.y0)
    if ix <= 0 or iy <= 0:
        return 0.0
    flaeche = ix * iy
    return flaeche / max(1e-6, min((a.x1 - a.x0) * (a.y1 - a.y0),
                                   (b.x1 - b.x0) * (b.y1 - b.y0)))
