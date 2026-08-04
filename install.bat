@echo off
title EV Tracker - Installation

cd /d "%~dp0"

echo.
echo EV Tracker - Kia EV3
echo Installation der Abhaengigkeiten
echo.

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [FEHLER] Python wurde nicht gefunden!
    echo Bitte Python von https://www.python.org/downloads/ installieren.
    echo WICHTIG: "Add Python to PATH" aktivieren!
    pause
    exit /b 1
)

echo [OK] Python gefunden:
python --version
echo.

echo [1/2] pip aktualisieren...
python -m pip install --upgrade pip
echo.

echo [2/2] Pakete installieren...
python -m pip install -r requirements.txt

IF %ERRORLEVEL% NEQ 0 (
    echo.
    echo [FEHLER] Installation fehlgeschlagen!
    pause
    exit /b 1
)

echo.
echo Pruefe Installation...
python -c "import PyQt6; print('[OK] PyQt6')"
python -c "import plotly; print('[OK] Plotly')"
python -c "import numpy; print('[OK] Numpy')"
python -c "import pdfplumber; print('[OK] pdfplumber')"

echo.
echo Installation erfolgreich! Starte die App mit start.bat
echo.
pause
