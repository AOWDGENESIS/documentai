"""Zentrale Fehlerklassen von DocumentAI."""
from __future__ import annotations


class DocumentAIError(Exception):
    """Basisfehler mit verstaendlicher, deutscher Beschreibung."""

    def __init__(self, message: str, technical: str = ""):
        super().__init__(message)
        self.message = message
        self.technical = technical or str(message)

    def __str__(self) -> str:  # pragma: no cover
        return self.message


class PasswordRequiredError(DocumentAIError):
    """Dokument ist passwortgeschuetzt; Passwort/Berechtigung fehlt.

    Wichtig: Es wird NIEMALS versucht, den Schutz zu knacken oder zu umgehen.
    """

    def __init__(self, path: str = ""):
        msg = ("Dieses Dokument ist passwortgeschützt. Für die angeforderte "
               "Bearbeitung wird ein Berechtigungsnachweis bzw. das "
               "erforderliche Passwort benötigt.")
        if path:
            msg = f"{msg}\nDatei: {path}"
        super().__init__(msg)


class WrongPasswordError(PasswordRequiredError):
    """Das angegebene Passwort war nicht korrekt."""


class DocumentDamagedError(DocumentAIError):
    """Dokument konnte auch nach Reparaturversuch nicht geoeffnet werden."""

    def __init__(self, detail: str = ""):
        message = "Das Dokument ist beschädigt oder kein unterstütztes Format."
        if detail:
            message = f"{message}\nDetails: {detail}"
        super().__init__(message, technical=detail)


class SignaturePresentError(DocumentAIError):
    """Dokument enthaelt eine digitale Signatur – keine stille Aenderung!."""

    def __init__(self, info: str = ""):
        super().__init__(
            "Dieses Dokument enthält eine digitale Signatur. Eine Änderung kann "
            "die bestehende Signatur ungültig machen. Bitte explizit bestätigen: "
            "[Neue bearbeitete Version erstellen] oder [Abbrechen].",
            technical=info,
        )


class EngineNotAvailableError(DocumentAIError):
    def __init__(self, what: str):
        super().__init__(f"Engine nicht verfügbar: {what}")


class OperationNotAllowedError(DocumentAIError):
    """Sicherheitsrelevantes Verbot (z. B. Original ueberschreiben)."""
