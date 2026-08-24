# -*- coding: utf-8 -*-
"""
Sichert die EV-Tracker-Datenbanken nach OneDrive.

Quellen:
  1. lokale Desktop-Datenbank (konsistente SQLite-Kopie, auch bei laufender App)
  2. optional die Docker-Webapp über deren /api/backup-Endpunkt

Aufruf:  python backup_db.py
Einrichtung als tägliche Aufgabe: siehe README-Abschnitt "Backup".
"""
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta

# Konsolenausgabe UTF-8-fähig machen (Windows-Aufgabenplanung/Logdatei)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Konfiguration ────────────────────────────────────────────────────────────
ZIEL_ORDNER = r"D:\OneDrive\EV-Tracker-Backup"
LOKALE_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ev_tracker.db")

# Docker-Webapp: leer lassen = überspringen.
# Beispiel: "http://192.168.1.50:8099"
WEBAPP_URL = os.environ.get("EV_TRACKER_WEBAPP_URL", "")
WEBAPP_TOKEN = os.environ.get("EV_TRACKER_BACKUP_TOKEN", "")

BEHALTE_TAGE = 30
# ─────────────────────────────────────────────────────────────────────────────


def log(text):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {text}")


def sichere_lokal(ziel):
    """Konsistente Kopie über die SQLite-Backup-API (kein Datei-Copy)."""
    if not os.path.exists(LOKALE_DB):
        log(f"Lokale DB nicht gefunden: {LOKALE_DB} – übersprungen")
        return False
    quelle = sqlite3.connect(f"file:{LOKALE_DB}?mode=ro", uri=True)
    kopie = sqlite3.connect(ziel)
    try:
        with kopie:
            quelle.backup(kopie)
    finally:
        kopie.close()
        quelle.close()
    log(f"Desktop-DB gesichert: {os.path.basename(ziel)} "
        f"({os.path.getsize(ziel) // 1024} KB)")
    return True


def sichere_webapp(ziel):
    """Holt die Datenbank der Docker-Webapp über /api/backup."""
    if not WEBAPP_URL:
        log("Keine WEBAPP_URL gesetzt – Docker-Backup übersprungen")
        return False
    url = f"{WEBAPP_URL.rstrip('/')}/api/backup?token={WEBAPP_TOKEN}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            daten = resp.read()
    except urllib.error.HTTPError as e:
        log(f"Webapp-Backup fehlgeschlagen: HTTP {e.code} – {e.read()[:120].decode(errors='replace')}")
        return False
    except Exception as e:
        log(f"Webapp-Backup fehlgeschlagen: {e}")
        return False
    with open(ziel, "wb") as f:
        f.write(daten)
    log(f"Webapp-DB gesichert: {os.path.basename(ziel)} ({len(daten) // 1024} KB)")
    return True


def raeume_auf():
    """Löscht Backups, die älter als BEHALTE_TAGE sind."""
    grenze = datetime.now() - timedelta(days=BEHALTE_TAGE)
    geloescht = 0
    for name in os.listdir(ZIEL_ORDNER):
        if not name.endswith(".db"):
            continue
        pfad = os.path.join(ZIEL_ORDNER, name)
        if datetime.fromtimestamp(os.path.getmtime(pfad)) < grenze:
            os.remove(pfad)
            geloescht += 1
    if geloescht:
        log(f"{geloescht} alte Backups (> {BEHALTE_TAGE} Tage) gelöscht")


def main():
    os.makedirs(ZIEL_ORDNER, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")

    erfolge = 0
    if sichere_lokal(os.path.join(ZIEL_ORDNER, f"desktop_{stamp}.db")):
        erfolge += 1
    if sichere_webapp(os.path.join(ZIEL_ORDNER, f"webapp_{stamp}.db")):
        erfolge += 1

    raeume_auf()

    if erfolge == 0:
        log("FEHLER: Keine Datenbank gesichert!")
        return 1
    log(f"Fertig – {erfolge} Datenbank(en) in {ZIEL_ORDNER}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
