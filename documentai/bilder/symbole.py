# -*- coding: utf-8 -*-
"""Werkzeug-Symbole (Nutzerwunsch 10.09.2026: „Symbole passend zum
Objekt"). Alle Symbole werden lokal mit PIL gezeichnet – keine Netz-
Abhängigkeit, keine externen Icon-Dateien, und sie können in jeder
Farbe (helles/dunkles Design) neu erzeugt werden."""
from __future__ import annotations

import threading

try:
    from PIL import Image, ImageDraw
    PIL_OK = True
except Exception:                                  # pragma: no cover
    PIL_OK = False

_LOCK = threading.Lock()
_CACHE: dict[tuple, "Image.Image"] = {}


def _l(d, pts, **kw):
    d.line(pts, **kw)


def _r(d, x0, y0, x1, y1, **kw):
    d.rectangle([x0, y0, x1, y1], **kw)


def _o(d, x0, y0, x1, y1, **kw):
    d.ellipse([x0, y0, x1, y1], **kw)


# ---------------------------------------------------------------------
# Jede Zeichnung arbeitet auf einem 24x24-Raster (Linienbreite 2).
# ---------------------------------------------------------------------
def _cursor(d, c):
    d.polygon([(6, 3), (6, 19), (10, 15), (13, 21), (16, 19), (13, 13),
               (18, 13)], outline=c, width=2)


def _hand(d, c):
    _l(d, [(8, 12), (8, 5), (11, 5), (11, 11)], fill=c, width=2)
    _l(d, [(11, 4), (14, 4), (14, 11)], fill=c, width=2)
    _l(d, [(14, 6), (17, 6), (17, 12)], fill=c, width=2)
    d.arc([4, 11, 13, 20], 90, 210, fill=c, width=2)
    _l(d, [(8, 19), (15, 19)], fill=c, width=2)


def _bbox(d, c):
    for (x, y) in ((4, 4), (15, 4), (4, 15), (15, 15)):
        _r(d, x, y, x + 4, y + 4, outline=c, width=2)
    _l(d, [(8, 5), (15, 5)], fill=c, width=1)
    _l(d, [(5, 8), (5, 15)], fill=c, width=1)
    _l(d, [(8, 18), (15, 18)], fill=c, width=1)
    _l(d, [(18, 8), (18, 15)], fill=c, width=1)


def _textfeld(d, c):
    _r(d, 3, 7, 20, 16, outline=c, width=2)
    _l(d, [(6, 11), (17, 11)], fill=c, width=2)
    d.polygon([(14, 2), (18, 2), (10, 18), (6, 18)], outline=c, width=1)


def _kreuz(d, c):
    _l(d, [(5, 5), (18, 18)], fill=c, width=3)
    _l(d, [(18, 5), (5, 18)], fill=c, width=3)


def _haekchen(d, c):
    _l(d, [(4, 13), (9, 18), (20, 5)], fill=c, width=3)


def _punkt(d, c):
    _o(d, 8, 8, 15, 15, fill=c)


def _umranden(d, c):
    _o(d, 3, 3, 20, 20, outline=c, width=2)


def _durchstreichen(d, c):
    _l(d, [(3, 8), (16, 8), (12, 5)], fill=c, width=2)
    _l(d, [(6, 14), (20, 14), (16, 11)], fill=c, width=2)
    _l(d, [(2, 19), (21, 19)], fill=c, width=3)


def _markieren(d, c):
    d.polygon([(4, 8), (18, 4), (20, 12), (6, 16)], fill=c)
    _l(d, [(4, 20), (20, 20)], fill=c, width=2)


def _unterstreichen(d, c):
    _l(d, [(5, 4), (5, 14)], fill=c, width=2)
    _l(d, [(8, 6), (8, 16)], fill=c, width=2)
    _l(d, [(11, 4), (11, 14)], fill=c, width=2)
    _l(d, [(14, 6), (14, 16)], fill=c, width=2)
    _l(d, [(3, 20), (21, 20)], fill=c, width=3)


def _haftnotiz(d, c):
    _r(d, 4, 3, 19, 17, outline=c, width=2)
    d.polygon([(13, 17), (19, 23), (19, 17)], fill=c)
    _l(d, [(7, 7), (16, 7)], fill=c, width=1)
    _l(d, [(7, 10), (14, 10)], fill=c, width=1)


def _paperclip(d, c):
    _l(d, [(15, 5), (7, 13), (7, 17), (10, 20), (14, 20), (19, 15),
           (19, 10), (16, 7)], fill=c, width=2)
    _l(d, [(12, 9), (6, 15)], fill=c, width=2)


def _feder(d, c):
    d.polygon([(17, 3), (20, 6), (9, 17), (6, 18), (7, 15)],
              outline=c, width=2)
    _l(d, [(4, 20), (10, 14)], fill=c, width=2)
    _l(d, [(13, 7), (16, 10)], fill=c, width=1)


def _linie(d, c):
    _l(d, [(4, 18), (19, 6)], fill=c, width=3)
    _o(d, 2, 16, 6, 20, fill=c)
    _o(d, 17, 4, 21, 8, fill=c)


def _pfeil(d, c):
    _l(d, [(4, 19), (18, 6)], fill=c, width=3)
    d.polygon([(13, 4), (21, 5), (19, 13)], fill=c)


def _kreis(d, c):
    _o(d, 3, 3, 20, 20, outline=c, width=3)


def _rechteck(d, c):
    _r(d, 3, 5, 20, 18, outline=c, width=3)


def _polygon(d, c):
    d.polygon([(11, 3), (20, 10), (16, 20), (6, 20), (2, 10)],
              outline=c, width=2)


def _polylinien(d, c):
    _l(d, [(3, 18), (9, 8), (14, 14), (20, 4)], fill=c, width=2)
    _o(d, 1, 16, 5, 20, fill=c)
    _o(d, 18, 2, 22, 6, fill=c)


def _wolke(d, c):
    _o(d, 2, 10, 9, 17, outline=c, width=2)
    _o(d, 6, 4, 14, 12, outline=c, width=2)
    _o(d, 12, 9, 20, 17, outline=c, width=2)
    _o(d, 7, 13, 16, 21, outline=c, width=2)


def _legende(d, c):
    _o(d, 3, 16, 7, 20, fill=c)
    _l(d, [(6, 16), (12, 8)], fill=c, width=2)
    _r(d, 11, 2, 21, 9, outline=c, width=2)


def _lineal(d, c):
    _r(d, 2, 9, 21, 15, outline=c, width=2)
    for x in (6, 10, 14, 18):
        _l(d, [(x, 9), (x, 12)], fill=c, width=1)


def _text(d, c):
    _l(d, [(5, 4), (18, 4)], fill=c, width=3)
    _l(d, [(11, 4), (11, 19)], fill=c, width=3)
    _l(d, [(6, 19), (17, 19)], fill=c, width=3)


def _bild(d, c):
    _r(d, 3, 4, 20, 18, outline=c, width=2)
    _o(d, 6, 7, 9, 10, fill=c)
    d.polygon([(10, 18), (14, 12), (18, 18)], fill=c)


def _link(d, c):
    d.arc([2, 8, 11, 17], 90, 270, fill=c, width=2)
    d.arc([12, 8, 21, 17], 270, 90, fill=c, width=2)
    _l(d, [(8, 12), (15, 12)], fill=c, width=2)


def _wasserzeichen(d, c):
    d.polygon([(11, 3), (18, 12), (15, 19), (7, 19), (4, 12)],
              outline=c, width=2)
    _l(d, [(9, 15), (14, 9)], fill=c, width=1)


def _kopffuss(d, c):
    _l(d, [(4, 5), (20, 5)], fill=c, width=3)
    _l(d, [(4, 10), (20, 10)], fill=c, width=1)
    _l(d, [(4, 14), (20, 14)], fill=c, width=1)
    _l(d, [(4, 19), (20, 19)], fill=c, width=3)


def _bates(d, c):
    _r(d, 3, 6, 20, 17, outline=c, width=2)
    d.rectangle([6, 9, 8, 11], fill=c)
    d.rectangle([6, 13, 8, 15], fill=c)
    _l(d, [(11, 10), (18, 10)], fill=c, width=1)
    _l(d, [(11, 14), (16, 14)], fill=c, width=1)


def _hintergrund(d, c):
    _r(d, 4, 4, 19, 19, outline=c, width=2)
    _r(d, 8, 8, 15, 15, fill=c)


def _schwaerzen(d, c):
    _r(d, 3, 4, 20, 9, fill=c)
    _r(d, 3, 13, 20, 18, outline=c, width=2)


def _schloss(d, c):
    _r(d, 5, 10, 18, 20, outline=c, width=2)
    d.arc([8, 3, 15, 11], 180, 360, fill=c, width=2)
    _o(d, 10, 13, 13, 16, fill=c)


def _signatur(d, c):
    _l(d, [(3, 15), (7, 9), (11, 15), (15, 7), (19, 13)],
       fill=c, width=2)
    _l(d, [(4, 19), (20, 19)], fill=c, width=2)


def _schild(d, c):
    d.polygon([(11, 2), (20, 6), (20, 12), (11, 21), (2, 12), (2, 6)],
              outline=c, width=2)
    _l(d, [(7, 11), (10, 14), (16, 8)], fill=c, width=2)


def _seite_loeschen(d, c):
    _r(d, 5, 3, 17, 20, outline=c, width=2)
    _l(d, [(9, 9), (14, 14)], fill=c, width=2)
    _l(d, [(14, 9), (9, 14)], fill=c, width=2)


def _drehen(d, c):
    d.arc([4, 6, 19, 19], 300, 200, fill=c, width=2)
    d.polygon([(3, 6), (10, 4), (8, 11)], fill=c)


def _zusammenfuehren(d, c):
    _r(d, 3, 3, 10, 9, outline=c, width=2)
    _r(d, 13, 3, 20, 9, outline=c, width=2)
    _r(d, 3, 13, 10, 20, outline=c, width=2)
    _r(d, 13, 13, 20, 20, fill=c)


def _word(d, c):
    _r(d, 3, 4, 20, 19, outline=c, width=2)
    _text(d, c)


def _excel(d, c):
    _r(d, 3, 4, 20, 19, outline=c, width=2)
    _l(d, [(3, 11), (20, 11)], fill=c, width=1)
    _l(d, [(11, 4), (11, 19)], fill=c, width=1)
    _l(d, [(6, 7), (9, 16)], fill=c, width=2)


def _powerpoint(d, c):
    _r(d, 3, 4, 20, 19, outline=c, width=2)
    _o(d, 9, 8, 14, 13, fill=c)
    _l(d, [(12, 13), (12, 17)], fill=c, width=2)


def _textdatei(d, c):
    d.polygon([(6, 2), (17, 2), (20, 6), (20, 21), (6, 21)],
              outline=c, width=2)
    _l(d, [(9, 8), (17, 8)], fill=c, width=1)
    _l(d, [(9, 12), (17, 12)], fill=c, width=1)
    _l(d, [(9, 16), (14, 16)], fill=c, width=1)


def _drucker(d, c):
    _r(d, 6, 3, 17, 8, outline=c, width=2)
    _r(d, 3, 8, 20, 16, outline=c, width=2)
    _r(d, 7, 14, 16, 20, outline=c, width=2)


def _stempel(d, c):
    _l(d, [(4, 8), (18, 8)], fill=c, width=2)
    _r(d, 6, 8, 16, 15, outline=c, width=2)
    _l(d, [(3, 19), (20, 19)], fill=c, width=3)


def _verschieben(d, c):
    for (x0, y0, x1, y1) in ((9, 2, 14, 7), (9, 17, 14, 22),
                             (2, 9, 7, 14), (17, 9, 22, 14)):
        _l(d, [(x0 + 2, y0), (x0 + 2, y1)], fill=c, width=1)
        d.polygon([(x0 + 2, y0), (x1, (y0 + y1) // 2), (x0 + 2, y1)],
                  fill=c)
    _r(d, 9, 9, 14, 14, outline=c, width=2)


def _sonne(d, c):
    _o(d, 8, 8, 15, 15, fill=c)
    for (x0, y0, x1, y1) in ((11, 1, 12, 4), (11, 19, 12, 22),
                             (1, 11, 4, 12), (19, 11, 22, 12),
                             (4, 4, 6, 6), (17, 17, 19, 19),
                             (17, 4, 19, 6), (4, 17, 6, 19)):
        _l(d, [(x0, y0), (x1, y1)], fill=c, width=2)


def _mond(d, c):
    d.arc([4, 3, 18, 19], 300, 120, fill=c, width=2)
    d.arc([8, 5, 20, 19], 90, 260, fill=c, width=2)


_ZEICHNUNGEN = {
    "auswaehlen": _cursor, "schwenken": _hand, "bbox": _bbox,
    "textfeld": _textfeld, "kreuz": _kreuz, "haekchen": _haekchen,
    "punkt": _punkt, "umranden": _umranden, "durchstreichen": _durchstreichen,
    "markieren": _markieren, "unterstreichen": _unterstreichen,
    "haftnotiz": _haftnotiz, "anhang": _paperclip, "feder": _feder,
    "linie": _linie, "pfeil": _pfeil, "kreis": _kreis,
    "rechteck": _rechteck, "polygon": _polygon,
    "polylinien": _polylinien, "wolke": _wolke, "legende": _legende,
    "messen": _lineal, "text": _text, "bild": _bild, "link": _link,
    "wasserzeichen": _wasserzeichen, "kopffuss": _kopffuss,
    "bates": _bates, "hintergrund": _hintergrund,
    "schwaerzen": _schwaerzen, "schloss": _schloss,
    "signatur": _signatur, "schild": _schild,
    "seite_loeschen": _seite_loeschen, "drehen": _drehen,
    "zusammenfuehren": _zusammenfuehren, "word": _word,
    "excel": _excel, "powerpoint": _powerpoint,
    "textdatei": _textdatei, "drucker": _drucker, "stempel": _stempel,
    "verschieben": _verschieben, "sonne": _sonne, "mond": _mond,
}


def symbol_bild(name: str, farbe: str = "#1f6feb",
                groesse: int = 20):
    """Liefert ein PIL-Bild für ein Werkzeug-Symbol (gecached)."""
    if not PIL_OK:
        return None
    schluessel = (name, farbe, groesse)
    with _LOCK:
        if schluessel in _CACHE:
            return _CACHE[schluessel]
    fn = _ZEICHNUNGEN.get(name)
    if fn is None:
        fn = _text
    img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fn(d, farbe)
    if groesse != 24:
        img = img.resize((groesse, groesse), Image.LANCZOS)
    with _LOCK:
        _CACHE[schluessel] = img
    return img


def verfuegbare_symbole() -> list[str]:
    return sorted(_ZEICHNUNGEN)
