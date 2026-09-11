"""Audit-Trail: jede Aenderung nachvollziehbar protokollieren."""
from __future__ import annotations

import datetime
import os
import threading

from ..paths import audit_dir, logs_dir

_lock = threading.Lock()


def _now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _slug(name: str) -> str:
    keep = [c if (c.isalnum() or c in "-_.") else "_" for c in name]
    return "".join(keep)[:120] or "dokument"


def log(model, action: str, details: str = "") -> None:
    """Haengt einen Audit-Eintrag an Modell + Datei (logs\\audit\\*.log)."""
    from .models import AuditEntry

    entry = AuditEntry(timestamp=_now(), action=action, details=details)
    model.audit.append(entry)
    try:
        with _lock:
            path = os.path.join(audit_dir(), _slug(model.name) + ".log")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"[{_stamp()}] {action}"
                         + (f" – {details}" if details else "") + "\n")
    except OSError:
        pass


def global_log(message: str) -> None:
    """Anwendungsweites Protokoll (ohne Dokumentinhalte)."""
    try:
        with _lock:
            path = os.path.join(logs_dir(), "documentai.log")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(f"[{_stamp()}] {message}\n")
    except OSError:
        pass


def audit_path_for(name: str) -> str:
    return os.path.join(audit_dir(), _slug(name) + ".log")
