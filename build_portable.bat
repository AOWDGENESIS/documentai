@echo off
rem ============================================================
rem  DocumentAI - Portable Windows-EXE bauen (PyInstaller)
rem  Erzeugt:  dist\DocumentAI\DocumentAI.exe  (laeuft ohne Installation,
rem  direkt von USB-Stick / Netzwerkordner; "_internal" = Runtime)
rem ============================================================
setlocal
set "DIR=%~dp0"

echo [1/5] Pruefe Python ...
where python >nul 2>nul || (echo Python nicht gefunden - bitte python.org-Installer nutzen. & exit /b 1)
python --version

echo [2/5] Erstelle virtuelle Umgebung .build-venv ...
python -m venv "%DIR%.build-venv" || exit /b 1
call "%DIR%.build-venv\Scripts\activate.bat"

echo [3/5] Installiere Abhaengigkeiten ...
python -m pip install --upgrade pip >nul
pip install pymupdf pypdf pillow cryptography python-docx openpyxl striprtf pytesseract pyinstaller || exit /b 1

echo [4/5] Baue portable Anwendung ...
pyinstaller --noconfirm --clean --onedir --windowed ^
  --name DocumentAI ^
  --add-data "%DIR%plugins;plugins" ^
  --add-data "%DIR%templates;templates" ^
  "%DIR%DocumentAI.py" || exit /b 1

echo [5/5] Struktur vervollstaendigen ...
for %%D in (engines models data cache logs logs\audit backups config reports diagnostics) do (
    if not exist "dist\DocumentAI\%%D" mkdir "dist\DocumentAI\%%D"
)
copy /y "%DIR%README.md" "dist\DocumentAI\" >nul
copy /y "%DIR%requirements.txt" "dist\DocumentAI\" >nul

echo.
echo FERTIG: dist\DocumentAI\DocumentAI.exe
echo Hinweis: Fuer OCR Tesseract (UB-Mannheim-Build) installieren und
echo           in config\settings.json nichts weiter anpassen - es wird
echo           automatisch erkannt. Ohne Tesseract laeuft alles sonstige
echo           vollstaendig, gescannte Seiten werden als OCR-noetig markiert.
endlocal
