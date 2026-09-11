<div align="center">

<img src="docs/screenshots/logo.png" width="110" alt="DocumentAI Logo"/>

# DocumentAI

**Local document intelligence – analyse PDFs, detect and fill forms, annotate. Completely offline.**

Languages / Языки / Langues / 语言：
[Deutsch](README.md) | **English** | [Русский](README.ru.md) | [Français](README.fr.md) | [中文](README.zh-CN.md)

![Version](https://img.shields.io/badge/Version-1.9.1-1473e6)
![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078d4)
![Python](https://img.shields.io/badge/Python-3.12-3776ab)
![Offline](https://img.shields.io/badge/100%25-offline-2e7d32)
![License](https://img.shields.io/badge/License-MIT-yellow)

</div>

---

## What is DocumentAI?

DocumentAI is a desktop application for PDF documents: it **analyses**
documents, **detects form fields** automatically, **fills in forms**,
provides **more than 40 tools** for commenting and editing, **compares**
versions, **exports** to Office formats and manages profile data in a
**locally encrypted vault** – all without a cloud, without an account and
without telemetry.

The toolset is modelled on the feature set of **Adobe Acrobat Reader DC
(Professional)** – rebuilt entirely locally and offline, without a
subscription and without a licence key.

## Features

### Form field detection
- **Line-pair model**: caption on top, input line below – the text you
  type lands **exactly on the line**, just like handwriting
- Grids and tables: empty cells become fields; column headers
  (e.g. weekdays) become checkboxes with meaningful captions
- Type detection: date, phone, e-mail, postal code, IBAN, signature,
  number, text
- Checkboxes detected via drawn boxes and glyphs
- Detected fields can be **repositioned with the mouse** if needed

### Tools (45)
Select, pan, insert text field, cross/check/dot, circle, highlight,
underline, strike through, sticky note, attach file, freehand drawing,
line, arrow, circle, rectangle, polygon, connected lines, callout cloud,
text callout, measure objects, insert text, insert image, link,
watermark, header & footer, Bates numbering, background colour, redact,
save protected, sign, certified copy, page management (delete, rotate,
move, merge), convert (Word, Excel, PowerPoint, text, RTF), print, stamp,
field detection, remove field, move field, bounding box – every tool with
**its own icon** and an explanation in the status bar.

### OCR
Scans are read with **Tesseract** (deu+eng). Pre-processing (greyscale,
2× upscaling, auto-contrast) improves the recognition of small captions;
the scan structure analysis finds field lines and boxes even without a
text layer.

### Data & privacy
- **Auto-fill** from profile data (family members) with confidence
  display and validation
- **Data vault**: encrypted locally (AES-256-GCM), master password
  optionally stored in the Windows keyring
- **Versioning**: “Save new version”, undo/redo, version comparison
  (text diff, field diff, visual comparison as image)
- **Export**: Word (.docx), Excel (.xlsx), PowerPoint (.pptx), text, RTF
- **Fully local**: no cloud, no network connection required, no document
  content ever leaves your computer

### Interface
- Acrobat-style layout: tool rail, thumbnails, navigation, properties panel
- **Light and dark theme** (toggle; the choice is remembered)
- Mouse-wheel scrolling, zoom, inline editing (click into the field,
  Esc finishes)

![DocumentAI light](docs/screenshots/app-hell.png)
*Field detection: the entered text sits on the input line.*

![DocumentAI dark](docs/screenshots/app-dunkel.png)
*Dark theme.*

![Tools](docs/screenshots/werkzeuge.png)
*Toolbox with icons.*

## Installation (Windows)

1. Download the archive `DocumentAI-Installer_…_v18_1.9.1.zip` from the
   [releases page](../../releases)
2. Extract it (right-click → “Extract all”)
3. Double-click `DocumentAI-installieren.bat`

That’s all. The installation ships its own Python runtime and all
libraries – **no administrator rights, no internet connection**.
Previous installations and shortcuts are cleaned up automatically
(user data is preserved).

## Installation from source

Requirements: Python 3.10+ (tested: 3.12); Tesseract optional for OCR.

```bash
pip install -r requirements.txt
python DocumentAI.py            # graphical interface
python DocumentAI.py --cli …    # command-line mode
python DocumentAI.py --selbsttest
```

For OCR, additionally install the Tesseract binary (Windows: the
UB-Mannheim build; Debian/Ubuntu: `tesseract-ocr tesseract-ocr-deu`).
Without Tesseract everything else works normally – OCR degrades cleanly
with a clear message.

## Architecture

| Module | Purpose |
|---|---|
| `documentai/engines/field_detector.py` | Visual form field detection (line pairs, grids, bands, gaps, boxes) |
| `documentai/engines/semantic.py` | Type and canonical detection (German compounds) |
| `documentai/engines/ocr.py` | Tesseract integration with pre-processing |
| `documentai/engines/annotate.py` | Annotations (highlight, drawing, stamps, redaction …) |
| `documentai/engines/exporter.py` | Export/import (docx, xlsx, pptx, txt, rtf) |
| `documentai/engines/compare.py` | Text, field and visual comparison |
| `documentai/engines/signatures.py` | Signature analysis, signing (pyhanko) |
| `documentai/services/` | Analysis service, profiles, vault, tool discovery |
| `documentai/gui/` | tkinter interface, themes (light/dark), panels |
| `documentai/bilder/symbole.py` | Locally drawn tool icons |
| `tests/` | 249 tests (field detection, GUI, pipeline, export, vault …) |

## Tests

```bash
python -m pytest tests/ -q
```

- **249 host tests** (unit + GUI under Xvfb)
- **Windows lab**: the complete suite under Wine
- **Fresh-installation verification**: installer → installation →
  smoke test → GUI test, fully automated

## Building the installer yourself

The Windows installer is built on Linux using Wine:

```bash
bash winenv/rebuild-windows-lab.sh   # set up the Wine lab
bash winenv/build-installer-v5.sh    # build the installer ZIP
bash winenv/verify-windows.sh        # verify the installation
```

## Documentation

- [CHANGELOG](CHANGELOG.md) – all versions
- [Test report](docs/TESTBERICHT.md) – complete verification history (German)
- [Installer guide](docs/LIESMICH.txt) – enclosed installation instructions (German)

## Security & privacy

See [SECURITY.md](SECURITY.md). In short: all processing is local; the
data vault is AES-256-GCM encrypted; “Save protected” creates
password-protected PDFs (AES-256); redaction removes content permanently.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

[MIT](LICENSE) – Copyright © 2026 DocumentAI.

---

<div align="center">

**DocumentAI – your documents stay your documents.**

</div>
