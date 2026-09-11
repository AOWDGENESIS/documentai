# -*- coding: utf-8 -*-
"""Gemeinsame Testfixtures: erzeugt alle Testdokumente on the fly."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from documentai import samples                      # noqa: E402
from documentai.services.analysis import AnalysisService  # noqa: E402


@pytest.fixture(scope="session")
def svc() -> AnalysisService:
    return AnalysisService()


@pytest.fixture(scope="session")
def assets(tmp_path_factory):
    """Alle Test-PDFs einmalig erzeugen."""
    base = tmp_path_factory.mktemp("assets")

    class Assets:
        acro = samples.make_acroform_pdf(str(base / "acro.pdf"))
        visual = samples.make_visual_form_pdf(str(base / "visuell.pdf"))
        table_ok = samples.make_table_pdf(str(base / "tabelle_ok.pdf"),
                                          with_error=False)
        table_err = samples.make_table_pdf(str(base / "tabelle_err.pdf"),
                                           with_error=True)
        scanned = samples.make_scanned_pdf(str(base / "gescannt.pdf"))
        encrypted = samples.make_encrypted_pdf(str(base / "verschluesselt.pdf"))
        empty = samples.make_empty_pdf(str(base / "leer.pdf"))
        corrupted = samples.make_corrupted_pdf(str(base / "beschaedigt.pdf"))
        many = samples.make_many_pages_pdf(str(base / "viele_seiten.pdf"),
                                           pages=120)
        images = samples.make_images_pdf(str(base / "bilder.pdf"))
        normal = samples.make_normal_pdf(str(base / "normal.pdf"))
        zeilen = samples.make_zeilen_formular_pdf(str(base / "zeilen.pdf"))

    return Assets()


PROFIL = {
    "vorname": "Max", "nachname": "Mustermann",
    "geburtsdatum": "01.01.1980", "strasse": "Musterstraße",
    "hausnummer": "10", "plz": "49000", "ort": "Musterstadt",
    "email": "max@example.de", "telefon": "+49 541 123456",
    "iban": "DE89370400440532013000",
}


# ---------------------------------------------------- Tk sauber schließen
def app_schliessen(app) -> None:
    """Tk-Anwendung warnungsfrei beenden (Best Practice).

    Tk-Variablen (StringVar & Co.) werfen in ``__del__`` eine
    „invalid command name“-Ausnahme, wenn sie ERST NACH
    ``root.destroy()`` vom Garbage Collector geholt werden – der
    Tcl-Interpreter ist dann schon weg (PytestUnraisableException-
    Warning). Wurzel-Lösung statt Filter: Referenzen lösen und
    ``gc.collect()`` SOLANGE der Interpreter lebt, dann erst
    ``destroy()``.
    """
    import gc
    try:
        app.views.clear()
        app.view_aktiv = None
        app.search_var = None
        gc.collect()                      # __del__ mit lebendem Tcl
        app.root.destroy()
        gc.collect()
    except Exception:
        pass
