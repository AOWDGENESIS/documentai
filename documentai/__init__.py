"""
DocumentAI – Portable Dokumentenintelligenz & PDF-Formularautomatisierung.

Lokale, modulare Anwendung zum Analysieren, Verstehen, Ausfuellen,
Bearbeiten, Validieren und sicheren Versionieren von Dokumenten.
"""


# PyMuPDF druckt sonst einmal pro Prozess einen Empfehlungs-Hinweis
# („Consider using the pymupdf_layout package …“). Offizielle Abschalt-
# API nutzen – Dokumentation von DocumentAI bleibt sauber (0 Warnungen).
try:                                        # pragma: no cover
    import pymupdf as _pymupdf
    _pymupdf.no_recommend_layout()
except Exception:                           # pymupdf nicht installiert
    pass

__app_name__ = "DocumentAI"
__version__ = "1.9.1"

from .paths import APP_DIR, ensure_dirs  # noqa: F401
