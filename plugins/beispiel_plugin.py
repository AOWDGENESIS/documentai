# -*- coding: utf-8 -*-
"""Beispiel-Plugin für DocumentAI.

Plugins liegen in plugins\\ und können:
  - zusätzliche Engines registrieren (register)
  - bestehende Synonyme erweitern (SYNONYM_ERWEITERUNGEN)
  - eigene Feld-Detektoren beisteuern

Die Anwendung lädt alle plugins\\*.py beim Start – ein fehlerhaftes
Plugin stürzt die App niemals ab.
"""

# Variante A: kanonische Felder um eigene Synonyme erweitern
SYNONYM_ERWEITERUNGEN = {
    "kundennummer": ["kunden-nr.", "mitgliedsnummer", "membership no"],
    "aktenzeichen": ["vorgangskennzeichen", "zaehlerstand-id"],
}


def bootstrap(registry, interfaces):
    """Variante B: eigene Engine registrieren (hier: Demo-Detektor)."""
    # Beispiel auskommentiert – entkommentieren zum Aktivieren:
    #
    # from documentai.core.models import FieldModel, Rect4
    #
    # class DemoDetektor:
    #     name = "Demo-Detektor (Plugin)"
    #     priority = 10
    #     @staticmethod
    #     def is_available():
    #         return True
    #     def detect(self, model, session=None):
    #         return [FieldModel(id="plugin::demo", name="demo",
    #                             label="Demo-Feld", page=0,
    #                             rect=Rect4(50, 50, 200, 14),
    #                             source="visuell", confidence=0.6)]
    #
    # registry.register(interfaces.IFieldDetector, DemoDetektor, priority=10)
    pass


try:
    from documentai.engines import semantic
    for _canon, _syns in SYNONYM_ERWEITERUNGEN.items():
        if _canon in semantic.CANONICAL_FIELDS:
            semantic.CANONICAL_FIELDS[_canon]["syn"].extend(_syns)
        else:
            semantic.CANONICAL_FIELDS[_canon] = {"syn": _syns,
                                                 "typ": "text"}
except Exception:
    pass
