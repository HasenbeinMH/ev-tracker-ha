# ⚡ EV Tracker

Web-App zur Erfassung und Auswertung der Kosteneinsparungen eines Elektroautos
gegenüber einem Benziner. Fahrzeugname und -bild sind in den Einstellungen frei wählbar –
nicht auf ein bestimmtes Modell festgelegt. Läuft als Docker-Container oder als
Home-Assistant-Add-on; Bedienung im Browser.

Installation, Konfiguration und Betrieb: **[webapp/README.md](webapp/README.md)**

## Zwei Betriebsarten, eine Codebasis

Dieses Repo unterstützt zwei Deployments **derselben** App. Die eigentliche Anwendung
(`webapp/app.py`, `database.py`, `ha_client.py`, alle Templates usw.) ist bewusst
**gemeinsamer Code** – Änderungen dort wirken sich immer auf beide Betriebsarten aus,
das ist gewollt (gleiche Funktionen, nur anders verpackt). Nur diese Dateien sind
jeweils exklusiv für eine Betriebsart und beeinflussen die andere nicht:

| Datei | Gehört zu |
|-------|-----------|
| `Dockerfile`, `config.yaml`, `repository.yaml`, `icon.png`, `logo.png` | **Home-Assistant-Add-on** |
| `docker-compose.yml`, `webapp/Dockerfile`, `backup.sh`, `backup_db.py` | **Standalone-Docker** (Portainer o.ä.) |

Wo sich das Verhalten der App selbst je nach Betriebsart unterscheidet (Backup-Seite,
Home-Assistant-Verbindung), steht im Code immer die Variable `IST_ADDON`
(`webapp/app.py`) – erkennt automatisch, ob `SUPERVISOR_TOKEN` gesetzt ist. Danach
suchen, wenn unklar ist, wo genau sich beide Wege unterscheiden.

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
Standard-Referenzverbrauch: **15 kWh/100 km** (in den Einstellungen pro Fahrzeug anpassbar)

## Hinweis zur Desktop-App

Bis Version 1.4 gab es zusätzlich eine Desktop-App (PyQt6, `main.py` und `ui/`).
Sie wurde mit Version 1.5.0 entfernt; die Web-App hat sie vollständig abgelöst.
Der alte Stand liegt weiterhin in der Git-Historie.
