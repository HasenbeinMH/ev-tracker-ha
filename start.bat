@echo off
title EV Tracker - Kia EV3

cd /d "%~dp0"

python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [FEHLER] Python nicht gefunden.
    pause
    exit /b 1
)

python main.py
echo.
echo Fehlercode: %ERRORLEVEL%
pause
