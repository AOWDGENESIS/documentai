# -*- coding: utf-8 -*-
"""Digitale PDF-Signaturen – komplett lokal (keine Cloud, kein Konto).

Acrobat-Äquivalent: „Mit Zertifikat signieren“ / „Signatur prüfen“.
Technik: pyHanko (PAdES-BES). Das Zertifikat wird beim ersten Signieren
SELBST erzeugt (RSA 2048, 5 Jahre gültig) und unter
``config/signatur/{schluessel,zertifikat}.pem`` gespeichert. Die Dateien
gehören dem Nutzer und verlassen den Rechner niemals.

pyHanko-Imports sind bewusst LAZY: Ohne installiertes pyHanko startet
die Anwendung normal – nur das Signieren meldet einen klaren Hinweis.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

from ..core.errors import DocumentAIError

FELDNAME = "DocumentAI-Signatur"
_GUELTIG_JAHRE = 5


# ---------------------------------------------------------------- Zertifikat
def _zertifikat_pfad() -> Path:
    """Ordner für Schlüssel+Zertifikat (relativ zum App-Verzeichnis)."""
    basis = Path(__file__).resolve().parent.parent.parent / "config" / "signatur"
    basis.mkdir(parents=True, exist_ok=True)
    return basis


def sicherstellen(name: str = "Test Nutzer") -> tuple[str, str]:
    """Schlüssel+Zertifikat bereitstellen. Existiert nichts, wird ein
    selbst signiertes Zertifikat (RSA 2048, SHA-256) erzeugt.
    Rückgabe: (schluessel_pfad, zertifikat_pfad)."""
    ordner = _zertifikat_pfad()
    key = ordner / "schluessel.pem"
    cert = ordner / "zertifikat.pem"
    if key.exists() and cert.exists():
        return str(key), str(cert)

    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:                      # pragma: no cover
        raise DocumentAIError(
            "Für digitale Signaturen fehlt die Kryptografie-Bibliothek "
            "(cryptography). Installation: pip install cryptography") from exc

    schluessel = rsa.generate_private_key(public_exponent=65537,
                                          key_size=2048)
    subjekt = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "DE"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME,
                           "DocumentAI (lokal erzeugt)"),
        x509.NameAttribute(NameOID.COMMON_NAME, name),
    ])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    zertifikat = (
        x509.CertificateBuilder()
        .subject_name(subjekt)
        .issuer_name(subjekt)                       # selbst signiert
        .public_key(schluessel.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(jetzt - datetime.timedelta(days=1))
        .not_valid_after(jetzt + datetime.timedelta(days=365 * _GUELTIG_JAHRE))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                       critical=True)
        .add_extension(x509.KeyUsage(
            digital_signature=True, content_commitment=True,
            key_encipherment=False, data_encipherment=False,
            key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=False, decipher_only=False), critical=True)
        .add_extension(x509.ExtendedKeyUsage([
            x509.oid.ExtendedKeyUsageOID.DOCUMENT_SIGNING
            if hasattr(x509.oid.ExtendedKeyUsageOID, "DOCUMENT_SIGNING")
            else x509.oid.ExtendedKeyUsageOID.EMAIL_PROTECTION]),
            critical=False)
        .sign(schluessel, hashes.SHA256())
    )
    key.write_bytes(schluessel.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption()))
    cert.write_bytes(zertifikat.public_bytes(serialization.Encoding.PEM))
    os.chmod(key, 0o600)                            # nur Besitzer darf lesen
    return str(key), str(cert)


# ---------------------------------------------------------------- Signieren
def digital_signieren(session, zielpfad: str, name: str = "Test Nutzer",
                      ort: str = "", grund: str = "") -> str:
    """Geöffnetes Dokument digital signieren (PAdES-BES) und als NEUE
    Datei speichern. Unterschriftsfeld liegt unten rechts auf Seite 1."""
    try:
        from pyhanko.pdf_utils.incremental_writer import \
            IncrementalPdfFileWriter
        from pyhanko.sign import signers
        from pyhanko.sign.fields import SigFieldSpec, append_signature_field
    except ImportError as exc:
        raise DocumentAIError(
            "Für digitale Signaturen fehlt pyHanko. Installation: "
            "pip install pyhanko (der DocumentAI-Installer liefert es "
            "mit).") from exc

    key_pfad, cert_pfad = sicherstellen(name)
    signer = signers.SimpleSigner.load(key_pfad, cert_pfad)   # Schlüssel ZUERST

    quelle = None
    # Stream-geöffnete Dokumente haben keinen Dateinamen (doc.name leer):
    # Die Sitzung weiß, welche Datei sie widerspiegelt (quelle/path).
    for kandidat in (getattr(session, "quelle", None),
                     getattr(session, "path", None),
                     getattr(session.doc, "name", None)):
        if kandidat:
            quelle = kandidat
            break
    quelle = quelle or (session.model.path if hasattr(session, "model")
                        and hasattr(session.model, "path") else None)
    if not quelle:
        raise DocumentAIError("Signieren braucht einen Dateipfad des "
                              "geöffneten Dokuments.")

    with open(quelle, "rb") as inf, open(zielpfad, "wb") as out:
        w = IncrementalPdfFileWriter(inf)
        append_signature_field(
            w, SigFieldSpec(FELDNAME, box=(360, 18, 560, 58)))
        meta = signers.PdfSignatureMetadata(
            field_name=FELDNAME, reason=grund or "Dokument geprüft",
            location=ort or "lokal", name=name)
        signers.sign_pdf(w, meta, signer=signer, output=out)  # Stream!
    return zielpfad


# --------------------------------------------------------------- Prüfen
def signatur_info(pfad: str) -> dict:
    """Signatur(en) eines PDF prüfen. Rückgabe:
    {vorhanden, status, detail} – status: 'intakt_selbst_signiert',
    'geaendert', 'ungueltig', 'unbekannt'."""
    try:
        from pyhanko.pdf_utils.reader import PdfFileReader
        from pyhanko.sign import validation
    except ImportError as exc:
        raise DocumentAIError("Für die Signaturprüfung fehlt pyHanko "
                              "(pip install pyhanko).") from exc

    antwort = {"vorhanden": False, "status": "unbekannt", "detail": ""}

    def _validation_context():
        """Validierung gegen EXPLIZITE Trust-Roots – niemals blind der
        Trust-Liste des Betriebssystems (pyhanko veraltet das, und wir
        wollen ohnehin nur unserem eigenen Zertifikat trauen)."""
        from pyhanko_certvalidator import ValidationContext
        roots = []
        try:
            from pyhanko_certvalidator.asn1.x509 import x509_cert
            _k, cert_pfad = sicherstellen()
            with open(cert_pfad, "rb") as f:
                pem = f.read()
            from cryptography.x509 import load_pem_x509_certificate
            der = load_pem_x509_certificate(pem).public_bytes(
                __import__("cryptography").hazmat.primitives.serialization
                .Encoding.DER)
            roots = [x509_cert.load(der)]     # eigenes Cert = Trusted Root
        except Exception:
            pass                    # fremdes Zertifikat/keins → leere Liste
        return ValidationContext(trust_roots=roots)

    with open(pfad, "rb") as f:
        reader = PdfFileReader(f)
        sig_felder = list(reader.embedded_signatures)
        if not sig_felder:
            antwort["detail"] = "Keine digitale Signatur im Dokument."
            return antwort
        antwort["vorhanden"] = True
        teile = []
        kontext = None
        for fv in sig_felder:
            try:
                if kontext is None:
                    kontext = _validation_context()
                erg = validation.validate_pdf_signature(
                    fv, signer_validation_context=kontext)  # synchron!
            except TypeError:                 # ältere pyhanko-Signatur
                erg = validation.validate_pdf_signature(fv)
            zusammen = erg.summary()          # z. B. INTACT:UNTRUSTED,UNTOUCHED
            try:
                fname = fv.field_name
            except Exception:
                fname = FELDNAME
            teile.append(f"{fname}: {zusammen}")
            if "INTACT" in zusammen and "MODIFIED" not in zusammen:
                antwort["status"] = "intakt_selbst_signiert"
            elif "MODIFIED" in zusammen or "BROKEN" in zusammen:
                antwort["status"] = "geaendert"
        antwort["detail"] = " | ".join(teile)
    return antwort
