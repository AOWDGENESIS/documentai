@echo off
rem ============================================================
rem  DocumentAI - Starter (portable, keine Installation)
rem  Startet die grafische Oberflaeche. CLI: DocumentAI.py --cli
rem ============================================================
setlocal
set "DIR=%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python wurde nicht gefunden.
    echo.
    echo Bitte Python 3.9+ von https://www.python.org/downloads/ installieren
    echo ^(Haken bei "Add python.exe to PATH" setzen^) oder die portable
    echo build_portable.bat verwenden, die eine eigenstaendige EXE erzeugt.
    echo.
    pause
    exit /b 1
)

rem Abhaengigkeiten beim ersten Start pruefen (nichts wird automatisch
rem installiert - es wird nur geprueft und ggf. ein Hinweis gegeben):
python -c "import pymupdf" >nul 2>nul || (
    echo [Hinweis] PyMuPDF fehlt. Grundfunktionen laufen mit pypdf-Fallback,
    echo fuer Ansicht ^& OCR bitte ausfuehren:  pip install -r "%DIR%requirements.txt"
    echo.
)

python "%DIR%DocumentAI.py" %*
if errorlevel 1 pause
endlocal
