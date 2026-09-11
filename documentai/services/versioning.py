"""Versionierung & Backups: Originale werden niemals überschrieben."""
from __future__ import annotations

import glob
import json
import os
import re
import shutil
from typing import Optional

from .. import config
from ..paths import backups_dir
from ..core.errors import OperationNotAllowedError

_NAME_RE = re.compile(r"_v(\d+)_bearbeitet$")


def next_version_path(orig_path: str, suffix: str = "_bearbeitet") -> str:
    """Dokument.pdf -> Dokument_v2_bearbeitet.pdf -> Dokument_v3_..."""
    directory = os.path.dirname(os.path.abspath(orig_path))
    stem, ext = os.path.splitext(os.path.basename(orig_path))
    highest = 1
    pattern = os.path.join(directory, f"{glob.escape(stem)}_v*{suffix}{ext}")
    for path in glob.glob(pattern):
        m = _NAME_RE.search(os.path.basename(path))
        if m:
            highest = max(highest, int(m.group(1)))
    candidate = os.path.join(directory,
                             f"{stem}_v{highest + 1}{suffix}{ext}")
    while os.path.exists(candidate):            # absolut sicher
        highest += 1
        candidate = os.path.join(directory,
                                 f"{stem}_v{highest + 1}{suffix}{ext}")
    return candidate


def guard_original(path: str, new_path: str) -> None:
    """Verhindert jedes versehentliche Überschreiben des Originals."""
    if os.path.abspath(path) == os.path.abspath(new_path):
        raise OperationNotAllowedError(
            "Das Originaldokument darf niemals automatisch überschrieben "
            "werden. Bitte eine neue Version (z. B. *_v2_bearbeitet.pdf) "
            "erzeugen.")


def backup_original(model) -> Optional[str]:
    """Sichert das Original einmalig nach backups\\ (hash-basiert)."""
    if not config.get("app.backup_original", True):
        return None
    if not model.path or not os.path.exists(model.path):
        return None
    sha8 = (model.sha256 or "x")[:8]
    stem, ext = os.path.splitext(os.path.basename(model.path))
    dest = os.path.join(backups_dir(), f"{stem}_{sha8}{ext}")
    if not os.path.exists(dest):
        try:
            shutil.copy2(model.path, dest)
        except OSError:
            return None
        _manifest_append(dest, model)
    return dest


def _manifest_append(backup_path: str, model) -> None:
    manifest = os.path.join(backups_dir(), "manifest.json")
    data: dict = {}
    if os.path.exists(manifest):
        try:
            with open(manifest, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            data = {}
    eintraege = data.setdefault("sicherungen", [])
    eintraege.append({
        "original": str(model.path),
        "sicherung": str(backup_path),
        "sha256": model.sha256,
        "zeitpunkt": _now_iso(),
    })
    try:
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


def _now_iso() -> str:
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")
