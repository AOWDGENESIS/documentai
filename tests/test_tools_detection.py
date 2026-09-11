"""Portable Tool-Erkennung (Tesseract/Ghostscript) – Nutzerfund 03.09.2026.

Der Installer kann Komponenten automatisch nach <App-Root>/tools/ laden;
die App muss sie OHNE PATH-Anpassung finden (portable, USB-Stick-tauglich).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from documentai.services import tools


def _fake_root(tmp_path, struktur: dict[str, str]) -> str:
    for rel, inhalt in struktur.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(inhalt)
    return str(tmp_path)


def test_portable_tesseract_wird_vorgezogen(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, {
        "tools/tesseract/bin/tesseract.exe": "fake",
        "tools/tesseract/bin/tessdata/deu.traineddata": "fake",
    })
    monkeypatch.setattr(tools, "app_root", lambda: root)
    monkeypatch.setattr("documentai.config.get", lambda k, d=None: "")
    monkeypatch.setattr("shutil.which", lambda n: "/usr/bin/tesseract")
    fund = tools.tesseract_binary()
    assert fund.endswith("tesseract.exe") and "tools" in fund
    assert not fund.startswith("/usr/bin")


def test_config_eintrag_hat_vorrang(tmp_path, monkeypatch):
    eigene = tmp_path / "eigene/tesseract.exe"
    eigene.parent.mkdir(parents=True, exist_ok=True)
    eigene.write_text("x")
    root = _fake_root(tmp_path / "app", {})
    monkeypatch.setattr(tools, "app_root", lambda: root)
    monkeypatch.setattr("documentai.config.get",
                        lambda k, d=None: str(eigene) if k == "ocr.pfad" else "")
    assert tools.tesseract_binary() == str(eigene)


def test_path_fallback_ohne_portable(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "app_root", lambda: str(tmp_path))
    monkeypatch.setattr("documentai.config.get", lambda k, d=None: "")
    monkeypatch.setattr("shutil.which",
                        lambda n: r"C:\gs\gswin64c.exe" if n == "gswin64c.exe" else None)
    assert tools.ghostscript_binary() == r"C:\gs\gswin64c.exe"


def test_nichts_gefunden_liefert_leer(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "app_root", lambda: str(tmp_path))
    monkeypatch.setattr("documentai.config.get", lambda k, d=None: "")
    monkeypatch.setattr("shutil.which", lambda n: None)
    assert tools.tesseract_binary() == ""
    assert tools.ghostscript_binary() == ""


def test_tessdata_neben_binary(tmp_path, monkeypatch):
    root = _fake_root(tmp_path, {
        "tools/tesseract/tesseract.exe": "fake",
        "tools/tesseract/tessdata/deu.traineddata": "fake",
    })
    monkeypatch.setattr(tools, "app_root", lambda: root)
    monkeypatch.setattr("documentai.config.get", lambda k, d=None: "")
    monkeypatch.setattr("shutil.which", lambda n: None)
    td = tools.tesseract_tessdata()
    assert td.endswith("tessdata") and os.path.isdir(td)


def test_config_defaults_enthalten_neue_schluessel():
    from documentai import config as cfg
    s = cfg.load_settings()
    assert "pfad" in s["ocr"]
    assert "pdfa" in s and "ghostscript" in s["pdfa"]
