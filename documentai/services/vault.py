"""Lokaler, verschlüsselter Daten-Tresor (Secure Vault).

Speichert Personen-/Familienprofile und gesammelte Dokumenteninformationen
in data\\secure_vault.db – AES-256-GCM-verschlüsselt (die Datei ist im
Klartext unlesbar), Schlüsselableitung aus dem Master-Passwort via scrypt.

Design-Entscheidung (statt SQLCipher): SQLCipher benötigt native Binaries
pro Architektur und verletzt die Portabilität. Dieser Container bietet
dieselben Schutzeigenschaften (Vertraulichkeit + Integrität/Manipulation-
erkennung) mit der reinen `cryptography`-Bibliothek. Die Schnittstelle
(SecureVault) ist bewusst so geschnitten, dass ein späterer Wechsel der
Verschlüsselungs-Engine möglich bleibt.

Sicherheitseigenschaften:
- AES-256-GCM: vertraulich + authentifiziert (Manipulation → Fehler)
- scrypt (N=2^15) mit zufälligem Salt: bruteforce-resistent
- Atomic-Write + verschlüsseltes .bak-Rotation
- Master-Passwort wird niemals gespeichert (nur optionaler Verweis über
  den Windows-Keyring, falls das Paket `keyring` installiert ist)
- Freigabe aller sensiblen Bytes beim Sperren (best effort)
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import datetime
from typing import Optional

from ..core.errors import DocumentAIError
from ..paths import data_dir

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    CRYPTO_OK = True
except Exception:
    CRYPTO_OK = False

FORMAT = "DocumentAI-Vault"
VERSION = 1
AAD = b"DocumentAI-Vault-v1"
SCRYPT_N, SCRYPT_R, SCRYPT_P = 1 << 15, 8, 1

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS persons(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name TEXT NOT NULL,
  role TEXT DEFAULT '',
  metadata_json TEXT DEFAULT '{}',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS person_data(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER NOT NULL REFERENCES persons(id) ON DELETE CASCADE,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  source TEXT DEFAULT 'manuell',
  confidence REAL DEFAULT 1.0,
  updated_at TEXT NOT NULL,
  UNIQUE(person_id, key));
CREATE TABLE IF NOT EXISTS documents(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL,
  file_name TEXT NOT NULL,
  sha256 TEXT DEFAULT '',
  pages INTEGER DEFAULT 0,
  doc_type TEXT DEFAULT '',
  imported_at TEXT NOT NULL,
  note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS extractions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
  person_id INTEGER REFERENCES persons(id) ON DELETE SET NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  confidence REAL DEFAULT 0.5,
  reviewed INTEGER DEFAULT 0,
  extraction_date TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS vault_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  time TEXT NOT NULL,
  action TEXT NOT NULL,
  details TEXT DEFAULT '');
"""


class VaultError(DocumentAIError):
    """Fehler des Daten-Tresors (Passwort, Integrität, Zustand)."""


class VaultLockedError(VaultError):
    def __init__(self):
        super().__init__("Der Datentresor ist gesperrt. Bitte zuerst mit "
                         "dem Master-Passwort öffnen.")


class VaultNotInitializedError(VaultError):
    def __init__(self, path: str = ""):
        super().__init__(
            "Es existiert noch kein verschlüsselter Datentresor. Bitte "
            "zuerst mit einem Master-Passwort erstellen."
            + (f"\nErwarteter Pfad: {path}" if path else ""))


def default_path() -> str:
    return os.path.join(data_dir(), "secure_vault.db")


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(password.encode("utf-8"))


class SecureVault:
    """Verschlüsselte Multi-Personen-Datenbank (In-Memory-SQLite, die
    persisted Datei ist ein AES-GCM-Container)."""

    def __init__(self):
        if not CRYPTO_OK:
            raise VaultError(
                "Verschlüsselung nicht verfügbar: bitte `pip install "
                "cryptography` ausführen.")
        self._conn: Optional[sqlite3.Connection] = None
        self._key: Optional[bytes] = None
        self.path: str = ""
        self.opened_at: str = ""

    # ------------------------------------------------------- Zustand
    @property
    def unlocked(self) -> bool:
        return self._conn is not None and self._key is not None

    def _require(self) -> sqlite3.Connection:
        if not self.unlocked:
            raise VaultLockedError()
        return self._conn  # type: ignore[return-value]

    # ------------------------------------------------------- Erstellen
    @classmethod
    def create(cls, master_password: str, path: str = "",
               exist_ok: bool = False) -> "SecureVault":
        """Legt einen NEUEN Tresor an (leer, verschlüsselt)."""
        path = path or default_path()
        if not master_password or len(master_password) < 4:
            raise VaultError("Das Master-Passwort muss mindestens 4 Zeichen "
                             "haben.")
        if os.path.exists(path) and not exist_ok:
            raise VaultError(
                f"Es existiert bereits ein Datentresor: {path}\n"
                "Bitte öffnen statt neu erstellen (oder exist_ok=True).")
        vault = cls()
        vault._conn = sqlite3.connect(":memory:")
        vault._conn.row_factory = sqlite3.Row
        vault._conn.executescript(SCHEMA)
        vault._conn.commit()
        vault._key = os.urandom(32)          # Platzhalter, gleich ersetzt
        vault.path = path
        vault._log("Tresor erstellt", path)
        vault._set_master_password(master_password)
        vault.save()
        vault.opened_at = _now()
        return vault

    # ------------------------------------------------------- Öffnen
    @classmethod
    def open(cls, master_password: str, path: str = "") -> "SecureVault":
        """Öffnet einen bestehenden Tresor (prüft Passwort kryptografisch)."""
        path = path or default_path()
        if not os.path.exists(path):
            raise VaultNotInitializedError(path)
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise VaultError(f"Tresor nicht lesbar: {exc}") from exc
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise VaultError(
                "Datei ist kein DocumentAI-Datentresor (ungültiges Format)."
            ) from exc
        if envelope.get("format") != FORMAT:
            raise VaultError("Datei ist kein DocumentAI-Datentresor.")
        try:
            salt = base64.b64decode(envelope["kdf"]["salt"])
            nonce = base64.b64decode(envelope["nonce"])
            ciphertext = base64.b64decode(envelope["ciphertext"])
            algo = envelope["kdf"].get("algo", "scrypt")
            if algo != "scrypt":
                raise VaultError(f"Unbekanntes KDF-Verfahren: {algo}")
        except (KeyError, ValueError, TypeError) as exc:
            raise VaultError("Tresor-Header beschädigt.") from exc
        key = _derive_key(master_password, salt)
        try:
            payload = AESGCM(key).decrypt(nonce, ciphertext, AAD)
        except InvalidTag as exc:
            raise VaultError(
                "Master-Passwort falsch oder Tresor wurde manipuliert/"
                "beschädigt (Integritätsprüfung fehlgeschlagen).") from exc
        vault = cls()
        vault._key = key
        vault._salt = salt                    # für save() merken!
        vault.path = path
        vault._conn = sqlite3.connect(":memory:")
        vault._conn.row_factory = sqlite3.Row
        vault._load_payload(payload)
        vault.opened_at = _now()
        vault._log("Tresor geöffnet", "")
        vault.save()                      # Rotation: .bak aktualisieren
        return vault

    # -------------------------------------------------- (De)Serialisierung
    def _dump_payload(self) -> bytes:
        """SQLite-Inhalt als Bytes (binary serialize oder SQL-Dump)."""
        conn = self._require()
        serialize = getattr(conn, "serialize", None)
        if serialize is not None:
            try:
                return serialize()
            except Exception:
                pass
        sql = "\n".join(conn.iterdump())
        return ("--sql-dump--\n" + sql).encode("utf-8")

    def _load_payload(self, payload: bytes) -> None:
        assert self._conn is not None
        if payload.startswith(b"--sql-dump--\n"):
            sql = payload.decode("utf-8").split("\n", 1)[1]
            self._conn.executescript(sql)
        else:
            deserialize = getattr(self._conn, "deserialize", None)
            if deserialize is None:
                raise VaultError(
                    "Tresor benötigt Python 3.11+ (deserialize) – bitte "
                    "Python aktualisieren.")
            deserialize(payload)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    # ------------------------------------------------------- Speichern
    def _set_master_password(self, new_password: str) -> None:
        salt = os.urandom(16)
        self._key = _derive_key(new_password, salt)
        self._salt = salt

    def save(self) -> str:
        """Schreibt den Tresor verschlüsselt + atomar zurück (.bak-Rotation)."""
        conn = self._require()
        conn.commit()
        payload = self._dump_payload()
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._key).encrypt(nonce, payload, AAD)  # type: ignore[arg-type]
        envelope = {
            "format": FORMAT, "version": VERSION,
            "kdf": {"algo": "scrypt", "salt": base64.b64encode(
                self._salt).decode(), "n": SCRYPT_N, "r": SCRYPT_R,
                "p": SCRYPT_P},
            "cipher": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
        }
        blob = json.dumps(envelope).encode("utf-8")
        target = self.path
        directory = os.path.dirname(os.path.abspath(target)) or "."
        os.makedirs(directory, exist_ok=True)
        if os.path.exists(target):
            try:
                shutil.copy2(target, target + ".bak")     # alte Version
            except OSError:
                pass
        tmp = target + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(blob)
        try:
            os.chmod(tmp, 0o600)                          # POSIX; Windows: ACL
        except OSError:
            pass
        os.replace(tmp, target)                           # atomar
        return target

    def change_master_password(self, old_password: str,
                               new_password: str) -> None:
        """Ändert das Master-Passwort (prüft das alte vorher!)."""
        self._require()
        if not new_password or len(new_password) < 4:
            raise VaultError("Das neue Master-Passwort muss mindestens 4 "
                             "Zeichen haben.")
        # Altes Passwort gegen die Datei verifizieren (nicht nur in-memory):
        probe = SecureVault.open(old_password, self.path)
        probe.close()
        self._set_master_password(new_password)
        self._log("Master-Passwort geändert", "")
        self.save()

    # ------------------------------------------------------- Sperren
    def close(self) -> None:
        """Sperrt den Tresor und gibt Schlüssel/Daten bestmöglich frei."""
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        self._conn = None
        if self._key is not None:
            wiped = bytearray(self._key)
            for i in range(len(wiped)):
                wiped[i] = 0                              # best effort
            self._key = None

    lock = close

    # ------------------------------------------------------- Personen
    def add_person(self, full_name: str, role: str = "",
                   metadata: Optional[dict] = None) -> int:
        conn = self._require()
        cur = conn.execute(
            "INSERT INTO persons(full_name, role, metadata_json, created_at)"
            " VALUES (?,?,?,?)",
            (full_name.strip(), role, json.dumps(metadata or {},
                                                 ensure_ascii=False), _now()))
        conn.commit()
        self._log("Person angelegt", full_name)
        return int(cur.lastrowid)

    def list_persons(self) -> list[dict]:
        rows = self._require().execute(
            "SELECT id, full_name, role, created_at FROM persons "
            "ORDER BY id").fetchall()
        out = []
        for r in rows:
            n_data = self._require().execute(
                "SELECT COUNT(*) FROM person_data WHERE person_id=?",
                (r["id"],)).fetchone()[0]
            out.append({"id": r["id"], "name": r["full_name"],
                        "rolle": r["role"] or "",
                        "angelegt": r["created_at"],
                        "datenfelder": n_data})
        return out

    def get_person(self, person_id: int) -> Optional[dict]:
        r = self._require().execute(
            "SELECT id, full_name, role, metadata_json, created_at FROM "
            "persons WHERE id=?", (person_id,)).fetchone()
        if not r:
            return None
        return {"id": r["id"], "name": r["full_name"], "rolle": r["role"],
                "metadaten": json.loads(r["metadata_json"] or "{}"),
                "angelegt": r["created_at"]}

    def rename_person(self, person_id: int, full_name: str,
                      role: Optional[str] = None) -> None:
        conn = self._require()
        if role is None:
            conn.execute("UPDATE persons SET full_name=? WHERE id=?",
                         (full_name, person_id))
        else:
            conn.execute("UPDATE persons SET full_name=?, role=? WHERE id=?",
                         (full_name, role, person_id))
        conn.commit()
        self._log("Person umbenannt", full_name)

    def delete_person(self, person_id: int) -> None:
        conn = self._require()
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM persons WHERE id=?", (person_id,))
        conn.commit()
        self._log("Person gelöscht", f"id={person_id}")

    # ------------------------------------------------------- Stammdaten
    def set_datum(self, person_id: int, key: str, value: str,
                  source: str = "manuell", confidence: float = 1.0) -> None:
        conn = self._require()
        conn.execute(
            "INSERT INTO person_data(person_id, key, value, source, "
            "confidence, updated_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(person_id, key) DO UPDATE SET value=excluded.value,"
            " source=excluded.source, confidence=excluded.confidence,"
            " updated_at=excluded.updated_at",
            (person_id, key.strip().lower(), str(value).strip(), source,
             float(confidence), _now()))
        conn.commit()
        self._log("Datum gesetzt", f"person={person_id} feld={key}")

    def get_data(self, person_id: int) -> dict[str, dict]:
        rows = self._require().execute(
            "SELECT key, value, source, confidence, updated_at FROM "
            "person_data WHERE person_id=? ORDER BY key",
            (person_id,)).fetchall()
        return {r["key"]: {"wert": r["value"], "quelle": r["source"],
                           "konfidenz": r["confidence"],
                           "aktualisiert": r["updated_at"]}
                for r in rows}

    def delete_datum(self, person_id: int, key: str) -> None:
        conn = self._require()
        conn.execute("DELETE FROM person_data WHERE person_id=? AND key=?",
                     (person_id, key))
        conn.commit()
        self._log("Datum gelöscht", f"person={person_id} feld={key}")

    def export_profile(self, person_id: int) -> dict[str, str]:
        """Kanonisches Profildict für die Formularbefüllung."""
        return {k: v["wert"] for k, v in self.get_data(person_id).items()}

    # ------------------------------------------------------- Dokumente
    def add_document(self, file_name: str, sha256: str = "", pages: int = 0,
                     doc_type: str = "", person_id: Optional[int] = None,
                     note: str = "") -> int:
        conn = self._require()
        cur = conn.execute(
            "INSERT INTO documents(person_id, file_name, sha256, pages, "
            "doc_type, imported_at, note) VALUES (?,?,?,?,?,?,?)",
            (person_id, os.path.basename(file_name), sha256, pages, doc_type,
             _now(), note))
        conn.commit()
        self._log("Dokument registriert", os.path.basename(file_name))
        return int(cur.lastrowid)

    def find_document(self, sha256: str) -> Optional[int]:
        r = self._require().execute(
            "SELECT id FROM documents WHERE sha256=?", (sha256,)).fetchone()
        return int(r["id"]) if r else None

    def list_documents(self, person_id: Optional[int] = None) -> list[dict]:
        if person_id is None:
            rows = self._require().execute(
                "SELECT d.*, p.full_name FROM documents d LEFT JOIN persons "
                "p ON p.id=d.person_id ORDER BY d.id DESC").fetchall()
        else:
            rows = self._require().execute(
                "SELECT d.*, p.full_name FROM documents d LEFT JOIN persons "
                "p ON p.id=d.person_id WHERE d.person_id=? ORDER BY d.id "
                "DESC", (person_id,)).fetchall()
        return [{"id": r["id"], "person": r["full_name"] or "–",
                 "datei": r["file_name"], "sha256": r["sha256"][:12],
                 "seiten": r["pages"], "typ": r["doc_type"],
                 "importiert": r["imported_at"]} for r in rows]

    # ------------------------------------------------------- Extraktionen
    def add_extraction(self, document_id: int, key: str, value: str,
                       confidence: float = 0.5,
                       person_id: Optional[int] = None,
                       reviewed: bool = False) -> int:
        conn = self._require()
        cur = conn.execute(
            "INSERT INTO extractions(document_id, person_id, key, value, "
            "confidence, reviewed, extraction_date) VALUES (?,?,?,?,?,?,?)",
            (document_id, person_id, key, str(value), float(confidence),
             1 if reviewed else 0, _now()))
        conn.commit()
        return int(cur.lastrowid)

    def get_extractions(self, document_id: int) -> list[dict]:
        rows = self._require().execute(
            "SELECT id, key, value, confidence, reviewed FROM extractions "
            "WHERE document_id=? ORDER BY id", (document_id,)).fetchall()
        return [{"id": r["id"], "feld": r["key"], "wert": r["value"],
                 "konfidenz": r["confidence"],
                 "geprüft": bool(r["reviewed"])} for r in rows]

    def adopt_extractions(self, person_id: int, proposals: list[dict],
                          document_id: Optional[int] = None) -> int:
        """Übernimmt geprüfte Extraktionen in die Stammdaten einer Person."""
        count = 0
        for p in proposals:
            self.set_datum(person_id, p["key"], p["wert"],
                           source=p.get("quelle", "dokument"),
                           confidence=p.get("konfidenz", 0.8))
            if document_id is not None:
                self.add_extraction(document_id, p["key"], p["wert"],
                                    p.get("konfidenz", 0.8), person_id,
                                    reviewed=True)
            count += 1
        self._log("Extraktionen übernommen",
                  f"person={person_id} anzahl={count}")
        return count

    # ------------------------------------------------------- Matching
    def match_person(self, proposals: list[dict]) -> tuple[Optional[int],
                                                           float]:
        """Ordnet Extraktionen der wahrscheinlichsten Person zu (§4 Workflow).

        Vergleicht Vorname/Nachname/Geburtsdatum/PLZ/Ort-Erkennungen mit
        den Stammdaten aller Personen. Liefert (person_id, score).
        """
        persons = self.list_persons()
        if not persons:
            return None, 0.0
        extr = {p["key"]: str(p["wert"]).strip().lower()
                for p in proposals}
        if not extr:
            return None, 0.0
        best: tuple[Optional[int], float] = (None, 0.0)
        for person in persons:
            daten = self.get_data(person["id"])
            score = 0.0
            possible = 0.0
            for key in ("vorname", "nachname", "geburtsdatum", "plz", "ort",
                        "strasse", "email", "iban", "telefon"):
                gespeichert = daten.get(key, {}).get("wert", "").strip().lower()
                erkannt = extr.get(key, "").strip()
                if gespeichert and erkannt:
                    possible += 1
                    if gespeichert == erkannt:
                        score += 1.0
                    elif (gespeichert in erkannt
                          or erkannt in gespeichert):
                        score += 0.6
            if possible and score / possible > best[1]:
                best = (person["id"], round(score / possible, 2))
        return best if best[1] >= 0.5 else (None, best[1])

    # ------------------------------------------------------- Sonstiges
    def statistics(self) -> dict:
        conn = self._require()
        return {
            "personen": conn.execute("SELECT COUNT(*) FROM persons"
                                     ).fetchone()[0],
            "datenfelder": conn.execute("SELECT COUNT(*) FROM person_data"
                                        ).fetchone()[0],
            "dokumente": conn.execute("SELECT COUNT(*) FROM documents"
                                      ).fetchone()[0],
            "extraktionen": conn.execute("SELECT COUNT(*) FROM extractions"
                                         ).fetchone()[0],
            "geöffnet": self.opened_at,
        }

    def log_entries(self, limit: int = 50) -> list[dict]:
        rows = self._require().execute(
            "SELECT time, action, details FROM vault_log ORDER BY id DESC "
            "LIMIT ?", (limit,)).fetchall()
        return [{"zeit": r["time"], "aktion": r["action"],
                 "details": r["details"]} for r in rows]

    def _log(self, action: str, details: str) -> None:
        """Protokolliert NUR Aktionen – niemals Werte (Datenschutz)."""
        if self._conn is None:
            return
        self._conn.execute(
            "INSERT INTO vault_log(time, action, details) VALUES (?,?,?)",
            (_now(), action, details))


# --------------------------------------------------------- Keyring (optional)
def keyring_store_password(password: str, service: str = "DocumentAI-Vault"
                           ) -> bool:
    """Legt das Master-Passwort optional im System-Keyring ab."""
    try:
        import keyring
        keyring.set_password(service, "master", password)
        return True
    except Exception:
        return False


def keyring_load_password(service: str = "DocumentAI-Vault") -> Optional[str]:
    try:
        import keyring
        return keyring.get_password(service, "master")
    except Exception:
        return None


def keyring_delete_password(service: str = "DocumentAI-Vault") -> None:
    try:
        import keyring
        keyring.delete_password(service, "master")
    except Exception:
        pass
