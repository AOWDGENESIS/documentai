"""Fabrik für Test- und Musterdokumente (PDFs aller Relevanten Arten).

Wird von der automatisierten Testumgebung und von
tools/make_templates.py genutzt.
"""
from __future__ import annotations

import os

try:
    import pymupdf
    OK = True
except Exception:
    OK = False


def _new_doc() -> "pymupdf.Document":
    return pymupdf.open()


def make_normal_pdf(path: str) -> str:
    doc = _new_doc()
    page = doc.new_page()
    page.insert_text((72, 72), "Antrag auf Wohngeld", fontsize=16,
                     fontname="hebo")
    absaetze = [
        "Max Mustermann",
        "Musterstraße 10",
        "49000 Musterstadt",
        "",
        "Sehr geehrte Damen und Herren,",
        "hiermit beantrage ich Wohngeld ab dem 01.10.2026.",
        "Mein Einkommen beträgt 2.450,00 EUR monatlich.",
        "Die Miete beträgt 680,00 EUR.",
        "",
        "Mit freundlichen Grüßen",
    ]
    y = 100
    for text in absaetze:
        page.insert_text((72, y), text, fontsize=11, fontname="helv")
        y += 16
    doc.new_page().insert_text((72, 72), "Anlage: Nachweise",
                               fontsize=12, fontname="hebo")
    doc.new_page().insert_text((72, 72), "Seite 3: Erklaerungen",
                               fontsize=12, fontname="hebo")
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def make_visual_form_pdf(path: str) -> str:
    """Formular OHNE AcroForm-Felder: Unterstriche, Kaestchen, Linien."""
    doc = _new_doc()
    page = doc.new_page()
    page.insert_text((50, 60), "Anmeldeformular Stadt Musterstadt",
                     fontsize=15, fontname="hebo")
    zeilen = [
        ("Vorname:", 100),
        ("Nachname:", 130),
        ("Geburtsdatum:", 160),
        ("Straße:", 190),
        ("PLZ / Ort:", 220),
        ("E-Mail:", 250),
        ("IBAN:", 280),
        ("Telefon:", 310),
    ]
    for label, y in zeilen:
        page.insert_text((50, y), label, fontsize=11, fontname="helv")
        width = 300 if label != "PLZ / Ort:" else 250
        page.draw_line(pymupdf.Point(140, y + 3),
                       pymupdf.Point(140 + width, y + 3),
                       color=(0, 0, 0), width=0.7)
    # Kaestchen mit Beschriftung (Ja/Nein)
    for i, label in enumerate(("Ja", "Nein")):
        x = 50 + i * 90
        page.draw_rect(pymupdf.Rect(x, 340, x + 12, 352), width=0.8)
        page.insert_text((x + 18, 350), label, fontsize=11, fontname="helv")
    page.insert_text((50, 335), "Einwilligung Datenverarbeitung:",
                     fontsize=11, fontname="helv")
    # Unterschriftslinie
    page.insert_text((50, 400), "Ort, Datum, Unterschrift:", fontsize=11,
                     fontname="helv")
    page.draw_line(pymupdf.Point(200, 403), pymupdf.Point(500, 403),
                   color=(0, 0, 0), width=0.7)
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def make_table_pdf(path: str, with_error: bool = True) -> str:
    doc = _new_doc()
    page = doc.new_page()
    page.insert_text((50, 60), "Kostenübersicht", fontsize=14,
                     fontname="hebo")
    header = ("Pos.", "Menge", "Einzelpreis", "Gesamt")
    rows = [("Bürokratie A", "2", "10,00", "20,00"),
            ("Bürokratie B", "3", "5,50", "16,50"),
            ("Bürokratie C", "1", "99,00", "99,00")]
    total = "135,50" if not with_error else "130,00"
    x0, y0 = 50, 80
    colw = (110, 60, 90, 80)
    rowh = 18

    def draw_row(cells, y, bold=False):
        x = x0
        for cell, w in zip(cells, colw):
            page.insert_text((x + 4, y + 12), cell, fontsize=10,
                             fontname="hebo" if bold else "helv")
            x += w

    all_rows = [header] + rows + [("Summe", "", "", total)]
    table_h = rowh * (len(all_rows) + 1)
    table_w = sum(colw)
    # Gitter zeichnen (fuer Tabellenerkennung)
    for i in range(len(all_rows) + 2):
        y = y0 + i * rowh
        page.draw_line(pymupdf.Point(x0, y), pymupdf.Point(x0 + table_w, y))
    x = x0
    for w in colw:
        page.draw_line(pymupdf.Point(x, y0), pymupdf.Point(x, y0 + table_h))
        x += w
    page.draw_line(pymupdf.Point(x0 + table_w, y0),
                   pymupdf.Point(x0 + table_w, y0 + table_h))
    for i, cells in enumerate(all_rows):
        draw_row(cells, y0 + i * rowh, bold=(i == 0 or cells[0] == "Summe"))
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def make_leerfelder_tabelle_pdf(path: str) -> str:
    """Formular-Tabelle: Beschriftungsspalte gefüllt, Wertespalte LEER.

    Mehrere Eingabefelder in einem Raster (Nutzerfund 09.09.2026:
    „in Dokumenten gibt es oft mehr Textfelder“ – Acrobat Auto-Detect
    erkennt alle, nicht nur das eine beste).
    """
    doc = _new_doc()
    page = doc.new_page()
    page.insert_text((50, 55), "Persönliche Angaben", fontsize=14,
                     fontname="hebo")
    zeilen = ["Name", "Vorname", "Geburtsdatum", "Staatsangehörigkeit",
              "Straße und Hausnummer", "PLZ", "Ort", "Telefon"]
    x0, y0 = 50, 80
    colw = (150, 220)
    rowh = 22
    breite = sum(colw)
    hoehe = rowh * len(zeilen)
    for i in range(len(zeilen) + 1):
        y = y0 + i * rowh
        page.draw_line(pymupdf.Point(x0, y), pymupdf.Point(x0 + breite, y))
    x = x0
    for w in colw:
        page.draw_line(pymupdf.Point(x, y0), pymupdf.Point(x, y0 + hoehe))
        x += w
    page.draw_line(pymupdf.Point(x0 + breite, y0),
                   pymupdf.Point(x0 + breite, y0 + hoehe))
    for i, label in enumerate(zeilen):
        y = y0 + i * rowh
        page.insert_text((x0 + 5, y + 15), label, fontsize=10,
                         fontname="helv")
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def make_zeilen_formular_pdf(path: str) -> str:
    """Klassisches Word-Formular: DURCHGEOGENDE Zeilenlinien, Labels
    sitzen AUF der Linie (Nutzerfall 09.09.2026: „bei orange ist hinter
    dem Text eine Linie zu sehen, auf der der Text eingefügt werden
    muss – da war es richtig“). Der freie Linienabschnitt hinter jedem
    Label ist das Eingabefeld."""
    doc = _new_doc()
    seite = doc.new_page()

    def zeile(p, y, labels, x0=50, x1=545):
        p.draw_line(pymupdf.Point(x0, y + 2.5),
                    pymupdf.Point(x1, y + 2.5))
        x = x0
        for text in labels:
            p.insert_text((x, y), text, fontsize=10, fontname="helv")
            x += pymupdf.get_text_length(text, fontname="helv",
                                         fontsize=10) + 130

    seite.insert_text((50, 60), "Anmeldung für das Schuljahr 2026/27",
                      fontsize=14, fontname="hebo")
    zeile(seite, 85, ["für den Jahrgang:"])
    seite.insert_text((50, 120), "Schülerin/Schüler", fontsize=11,
                      fontname="hebo")
    zeile(seite, 145, ["Name:", "Vorname:"])
    zeile(seite, 170, ["Geburtsort:", "Geburtsdatum:"])
    zeile(seite, 195, ["Anschrift:"])
    zeile(seite, 220, ["Staatsangehörigkeit:", "Religion:"])
    zeile(seite, 245, ["Telefon / Notfallkontakte:"])
    zeile(seite, 270, ["E-Mail-Adressen:"])
    zeile(seite, 295, ["Bisherige Schule:"])
    seite.insert_text((50, 330), "Erziehungsberechtigte", fontsize=11,
                      fontname="hebo")
    zeile(seite, 355, ["Name, Vorname:"])
    zeile(seite, 380, ["Anschrift:"])
    zeile(seite, 405, ["Telefon:", "E-Mail:"])
    s2 = doc.new_page()
    s2.insert_text((50, 60), "Schulische Angaben", fontsize=12,
                   fontname="hebo")
    zeile(s2, 90, ["Einschulungsjahr:"])
    zeile(s2, 120, ["Gewünschte Fremdsprache:"])
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def make_acroform_pdf(path: str) -> str:
    doc = _new_doc()
    page = doc.new_page()
    page.insert_text((50, 60), "Personenbogen (AcroForm)", fontsize=15,
                     fontname="hebo")

    def add_text(name: str, label: str, y: int, required=False):
        page.insert_text((50, y + 12), label, fontsize=11, fontname="helv")
        w = pymupdf.Widget()
        w.field_name = name
        w.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
        w.rect = pymupdf.Rect(170, y, 420, y + 20)
        if required:
            w.field_flags = 2                    # Pflichtfeld
        page.add_widget(w)

    add_text("vorname", "Vorname:", 90, required=True)
    add_text("nachname", "Nachname:", 120, required=True)
    add_text("geburtsdatum", "Geburtsdatum:", 150, required=True)
    add_text("strasse", "Straße:", 180)
    add_text("plz", "PLZ:", 210)
    add_text("ort", "Ort:", 240)
    add_text("email", "E-Mail:", 270)

    page.insert_text((50, 312), "Einwilligung:", fontsize=11, fontname="helv")
    cb = pymupdf.Widget()
    cb.field_name = "einwilligung"
    cb.field_type = pymupdf.PDF_WIDGET_TYPE_CHECKBOX
    cb.rect = pymupdf.Rect(150, 300, 164, 314)
    page.add_widget(cb)

    page.insert_text((50, 352), "Anrede:", fontsize=11, fontname="helv")
    combo = pymupdf.Widget()
    combo.field_name = "anrede"
    combo.field_type = pymupdf.PDF_WIDGET_TYPE_COMBOBOX
    combo.rect = pymupdf.Rect(150, 340, 300, 360)
    combo.choice_values = ["Herr", "Frau", "Diverse"]
    page.add_widget(combo)

    page.insert_text((50, 410), "Unterschrift Antragsteller:",
                     fontsize=11, fontname="helv")
    sig = pymupdf.Widget()
    sig.field_name = "unterschrift"
    sig.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE
    sig.rect = pymupdf.Rect(50, 420, 300, 470)
    page.add_widget(sig)

    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def make_scanned_pdf(path: str) -> str:
    """Bild-PDF ohne Textebene (OCR erforderlich)."""
    source = make_visual_form_pdf(path + ".src.pdf")
    try:
        doc = _new_doc()
        src = pymupdf.open(source)
        for pno in range(src.page_count):
            pix = src.load_page(pno).get_pixmap(dpi=150)
            page = doc.new_page(width=pix.width / 150 * 72,
                                height=pix.height / 150 * 72)
            page.insert_image(page.rect, pixmap=pix)
        doc.save(path, deflate=True)
        doc.close()
        src.close()
    finally:
        if os.path.exists(source):
            os.remove(source)
    return path


def make_scan_handschrift_pdf(path: str) -> str:
    """Gescanntes, handschriftlich ausgefülltes Formular (nur Bild-Ebene):
    Beschriftungen, Feldlinien, gewellte Handschrift-Kritzel über den
    Linien und ein angehaktes Kontrollkästchen – wie ein echt
    eingescannter, von Hand ausgefüllter Antrag."""
    import random

    rng = random.Random(42)
    src_path = path + ".src.pdf"
    doc = _new_doc()
    page = doc.new_page()
    page.insert_text((50, 60), "Antrag Lernfoerderung (Scan)",
                     fontsize=15, fontname="hebo")
    for label, y in (("Vorname:", 100), ("Nachname:", 132),
                     ("Geburtsdatum:", 164)):
        page.insert_text((50, y), label, fontsize=11, fontname="helv")
        page.draw_line(pymupdf.Point(140, y + 3),
                       pymupdf.Point(440, y + 3), color=(0, 0, 0),
                       width=0.8)
        punkte = [pymupdf.Point(150.0, y - 3.0)]
        px = 150.0
        while px < 265.0:
            px += rng.uniform(6.0, 11.0)
            punkte.append(pymupdf.Point(px, y - 3.0 + rng.uniform(-6.0, 5.0)))
        page.draw_polyline(punkte, color=(0.05, 0.05, 0.45), width=1.4)
    # Unterlängen (wie g, j, p, ß): Schleifen, die ÜBER die Linie
    # hinaus nach unten ragen – nur in der Vorname-Zeile
    page.draw_polyline(
        [pymupdf.Point(196, 95), pymupdf.Point(201, 109),
         pymupdf.Point(206, 94.5)],
        color=(0.05, 0.05, 0.45), width=1.4)
    page.draw_rect(pymupdf.Rect(50, 200, 62, 212), width=0.8)
    page.insert_text((68, 210), "Ja", fontsize=11, fontname="helv")
    page.draw_line(pymupdf.Point(52.5, 206), pymupdf.Point(56, 210.5),
                   color=(0.05, 0.05, 0.45), width=1.4)
    page.draw_line(pymupdf.Point(56, 210.5), pymupdf.Point(61, 202.5),
                   color=(0.05, 0.05, 0.45), width=1.4)
    page.draw_rect(pymupdf.Rect(120, 200, 132, 212), width=0.8)
    page.insert_text((138, 210), "Nein", fontsize=11, fontname="helv")
    doc.save(src_path, garbage=3, deflate=True)
    doc.close()
    try:
        src = pymupdf.open(src_path)
        out = _new_doc()
        pix = src.load_page(0).get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
        npage = out.new_page(width=pix.width / 200 * 72,
                             height=pix.height / 200 * 72)
        npage.insert_image(npage.rect, pixmap=pix)
        out.save(path, deflate=True)
        out.close()
        src.close()
    finally:
        if os.path.exists(src_path):
            os.remove(src_path)
    return path


def make_encrypted_pdf(path: str, user_pw: str = "user123",
                       owner_pw: str = "owner123") -> str:
    """Erzeugt eine verschlüsselte PDF – und verifiziert sie sofort
    (selbstheilend: AES-256 als Ausweichvariante)."""
    for verfahren in (pymupdf.PDF_ENCRYPT_AES_128,
                      pymupdf.PDF_ENCRYPT_AES_256):
        doc = _new_doc()
        page = doc.new_page()
        page.insert_text((72, 72), "Vertrauliches Dokument", fontsize=13,
                         fontname="hebo")
        perms = -1 & ~pymupdf.PDF_PERM_MODIFY & ~pymupdf.PDF_PERM_ANNOTATE \
            if hasattr(pymupdf, "PDF_PERM_MODIFY") else -1 ^ 8
        doc.save(path, encryption=verfahren, user_pw=user_pw,
                 owner_pw=owner_pw, permissions=perms)
        doc.close()
        # Verifikation: erneut öffnen, entschlüsseln, Text lesen
        try:
            pruef = pymupdf.open(path)
            if pruef.authenticate(user_pw) and \
                    pruef.load_page(0).get_text().strip():
                pruef.close()
                return path
            pruef.close()
        except Exception:
            continue
    return path                                  # letzte Variante zurückgeben


def make_signed_field_pdf(path: str) -> str:
    """PDF mit (leerem) Signaturfeld – Signaturerkennung testen."""
    path = make_acroform_pdf(path)
    return path                                    # enthält Sig-Feld


def make_empty_pdf(path: str) -> str:
    doc = _new_doc()
    doc.new_page()                                 # leere Seite
    doc.save(path)
    doc.close()
    return path


def make_corrupted_pdf(path: str) -> str:
    with open(path, "wb") as fh:
        fh.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        fh.write(os.urandom(700))                  # Müll, kein Trailer
    return path


def make_many_pages_pdf(path: str, pages: int = 120) -> str:
    doc = _new_doc()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"Seite {i + 1} von {pages}",
                         fontsize=12, fontname="helv")
        if i % 10 == 0:
            page.insert_text((72, 100), f"Abschnitt {i // 10 + 1}",
                             fontsize=10, fontname="helv")
    doc.save(path, garbage=3, deflate=True)
    doc.close()
    return path


def make_images_pdf(path: str, pages: int = 3) -> str:
    doc = _new_doc()
    for i in range(pages):
        page = doc.new_page()
        pix = pymupdf.Pixmap(pymupdf.csRGB,
                             pymupdf.IRect(0, 0, 512, 512))
        pix.clear_with(90 + i * 40)              # Grauwert füllen
        page.insert_image(page.rect, pixmap=pix)
    doc.save(path, deflate=True)
    doc.close()
    return path


def make_musterformular(path: str) -> str:
    """Vorlage für Endanwender: AcroForm + Tabelle + visuelle Elemente."""
    path = make_acroform_pdf(path)
    doc = pymupdf.open(path)
    page2 = doc.new_page()
    page2.insert_text((50, 60), "Anlage: Einkommensnachweis (bitte ausfüllen)",
                      fontsize=12, fontname="hebo")
    for label, y in (("Arbeitgeber:", 100), ("Monatliches Netto:", 130),
                     ("Beschäftigt seit:", 160)):
        page2.insert_text((50, y), label, fontsize=11, fontname="helv")
        page2.draw_line(pymupdf.Point(170, y + 3), pymupdf.Point(470, y + 3))
    doc.saveIncr()
    doc.close()
    return path

def make_anmelde_formular_pdf(pfad: str) -> str:
    """Nachbau eines echten Schul-Anmeldeformulars (Nutzerfund
    10.09.2026, Struktur ohne personenbezogene Daten): Gittertabelle
    mit Label-Zeilen und leeren Eingabebändern, Vier-Label-Zeile,
    Doppel-Doppelpunkt-Zeile, Rechteck-Checkboxen, Seitenrahmen und
    Unterschriftslinie mit Label DARUNTER – die Fallen für die
    Felderkennung."""
    import pymupdf

    d = pymupdf.open()
    p = d.new_page()                      # 595 x 842

    def linie(x0, y, x1):
        p.draw_rect(pymupdf.Rect(x0, y, x1, y + 0.5), width=0,
                    color=(0, 0, 0), fill=(0, 0, 0))

    def kasten(x, y):
        p.draw_rect(pymupdf.Rect(x, y, x + 10, y + 10), width=0.8)

    # Seitenrahmen (drei Striche übereinander wie im Original)
    for dy in (0, 0.5, 1.0):
        p.draw_rect(pymupdf.Rect(25 + dy, 24, 570 - dy, 24.5), width=0)
        p.draw_rect(pymupdf.Rect(25 + dy, 816.5 - dy, 570 - dy, 817 - dy),
                    width=0)
    # Zierlinie unter der Überschrift (kein Label in Linienhöhe)
    linie(71, 156, 536)

    p.insert_text((76, 175), "Anmeldung für das Schuljahr 2026/27",
                  fontsize=11)
    p.insert_text((76, 196), "für den Jahrgang: ")
    p.insert_text((190, 196), "____________", fontsize=11)

    # Vier-Label-Zeile mit Gitter (Name/Vorname/Geburtsort/Geburtsdatum)
    p.insert_text((76, 260), "Name:", fontsize=10)
    p.insert_text((208, 260), "Vorname:", fontsize=10)
    p.insert_text((334, 260), "Geburtsort:", fontsize=10)
    p.insert_text((451, 260), "Geburtsdatum:", fontsize=10)
    for x0, x1 in ((71, 202), (202, 328), (328, 445), (445, 535)):
        linie(x0, 300, x1)

    # Zeile 2: Labels UNTER der Eingabelinie 300 (wie im echten
    # Formular: Label-Zeile, darunter die nächste Eingabelinie 351)
    p.insert_text((76, 314), "Anschrift:", fontsize=10)
    p.insert_text((334, 314), "Staatsangehörigkeit:", fontsize=10)
    p.insert_text((451, 312), "Religion:", fontsize=10)
    for x0, x1 in ((71, 262), (328, 445), (445, 535)):
        linie(x0, 351, x1)

    # Band-Label: Telefon links, E-Mail rechts (Falle: Bushaltestelle)
    p.insert_text((76, 366), "Telefon / Notfallkontakte:", fontsize=10)
    p.insert_text((268, 366), "E-Mail-Adressen:", fontsize=10)
    p.insert_text((76, 445), "Bisherige Schule:", fontsize=10)
    p.insert_text((270, 445), "Einstieg Bushaltestelle:", fontsize=10)

    # Sorgerecht mit Rechteck-Checkboxen (Optionen dürfen nicht
    # verschmelzen)
    p.insert_text((76, 672), "Sorgerecht:", fontsize=10)
    for i, text in enumerate(("gemeinsam", "Mutter", "Vater")):
        x = 143 + i * 70
        kasten(x, 669)
        p.insert_text((x + 13, 678), text, fontsize=10)

    # Unterschriftslinie mit Label DARUNTER
    p.insert_text((76, 705), "Hiermit melden wir unser Kind an.", fontsize=10)
    linie(72, 740, 396)
    p.insert_text((177, 755), "Unterschrift Erziehungsberechtigte",
                  fontsize=10)
    d.save(pfad)
    d.close()
    return pfad

