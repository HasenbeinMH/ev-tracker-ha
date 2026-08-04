@echo off
title EV Tracker - Testdaten

cd /d "%~dp0"

echo Lege Testdaten an...
python testdaten.py

echo.
pause
