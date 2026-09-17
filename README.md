# ⚡ EV Tracker – Kia EV3

Web-App zur Erfassung und Auswertung der Kosteneinsparungen gegenüber einem Benziner.
Läuft als Docker-Container; Bedienung im Browser.

Installation, Konfiguration und Betrieb: **[webapp/README.md](webapp/README.md)**

## Funktionen

| Seite | Beschreibung |
|-------|-------------|
| 📊 Dashboard | Gesamtübersicht, Kennzahlen, alle Charts |
| 🚗 Fahrten | km erfassen, Benzin-Äquivalent, Verbrauch kWh/100 km |
| 🔌 Laden | Ladevorgänge mit kWh, Preis, Anbieter, AC/DC |
| ⛽ Benzinpreise | Monatsdurchschnitte + Preisverlauf |
| ⚡ Stromtarif | Tarifliste mit Preisverlauf |
| 💶 Steuer & THG | KFZ-Steuer-Ersparnis + THG-Quote-Erträge |
| 📥 HA Import | Nächtlicher Abruf aus Home Assistant, mit Protokoll |
| 🧾 Rechnungen | PDF-Rechnungen einlesen |
| 📄 Berichte | Monatsbericht als PDF, optional per Mail |
| 💾 Backup | Datenbank sichern und zurückspielen |
| ❓ Hilfe | Handbuch, Herleitung jeder Kennzahl, Änderungslog |

## Aufbau

| Ordner / Datei | Inhalt |
|----------------|--------|
| `webapp/` | FastAPI-Anwendung, Templates, statische Dateien, Dockerfile |
| `charts.py` | Chart-Definitionen (Apache ECharts), werden im Browser gezeichnet |
| `berechnung.py` | Alle Kennzahlen und Ersparnis-Berechnungen |
| `database.py` | SQLite-Zugriff und Schema |
| `ha_client.py` | Home Assistant und InfluxDB |
| `berichte.py`, `mailer.py` | Monatsbericht als PDF, Mailversand |
| `pdf_parser.py`, `ladeerkennung.py` | Rechnungs-PDFs, Erkennung von Ladevorgängen |
| `backup_db.py`, `backup.sh` | Sicherung der Datenbank |
| `settings_tool.py` | Einstellungen als JSON exportieren/importieren |
| `testdaten.py`, `testdaten.bat` | Testdaten anlegen |
| `version.py` | Versionsnummer und Änderungslog |

## Daten

Alle Daten liegen in `ev_tracker.db` (SQLite), im Container unter `/data`.

## Benzin-Äquivalent

Berechnung: `km / 100 × 7,0 L × Benzinpreis`
Kia EV3 Referenzverbrauch: **15 kWh/100 km**

## Hinweis zur Desktop-App

Bis Version 1.4 gab es zusätzlich eine Desktop-App (PyQt6, `main.py` und `ui/`).
Sie wurde mit Version 1.5.0 entfernt; die Web-App hat sie vollständig abgelöst.
Der alte Stand liegt weiterhin in der Git-Historie.
