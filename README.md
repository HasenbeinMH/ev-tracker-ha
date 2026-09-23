# ⚡ EV Tracker

> 🚧 **Noch in aktiver Entwicklung.** Dieses Add-on wird mit Unterstützung von KI (Claude)
> erstellt und getestet. Funktionen, Konfiguration und Datenstruktur können sich noch
> ändern; vor größeren Updates lohnt sich eine Sicherung über Home Assistants eigene
> Backups. Rückmeldungen und Fehlerberichte sind willkommen.

Web-App zur Erfassung und Auswertung der Kosteneinsparungen eines Elektroautos
gegenüber einem Benziner. Fahrzeugname und -bild sind in den Einstellungen frei wählbar –
nicht auf ein bestimmtes Modell festgelegt.

## Installation als Home-Assistant-Add-on

1. **Einstellungen → Add-ons → Add-on-Store** → oben rechts ⋮ → **Repositories**
2. URL einfügen: `https://github.com/HasenbeinMH/ev-tracker-ha`
3. **Hinzufügen**, Store neu laden
4. Unter „EV Tracker Add-ons" erscheint **EV Tracker** → installieren, starten
5. Läuft komplett per Ingress (eigener Menüpunkt in der Seitenleiste) – kein offener Port,
   kein manuelles Access-Token nötig

## Funktionen

| Seite | Beschreibung |
|-------|-------------|
| 📊 Dashboard | Gesamtübersicht, Kennzahlen, alle Charts |
| 🚗 Fahrten | km erfassen, Benzin-Äquivalent, Verbrauch kWh/100 km |
| 🔌 Laden | Ladevorgänge mit kWh, Preis, Anbieter, AC/DC, Blockiergebühr |
| 🔋 Ladetarife | Eigene Lade-Abos mit Preisverlauf |
| ⛽ Benzinpreise | Monatsdurchschnitte + Preisverlauf |
| ⚡ Stromtarif | Tarifliste mit Preisverlauf |
| 💶 Steuer & THG | KFZ-Steuer-Ersparnis + THG-Quote-Erträge |
| 🔧 Instandhaltung | Werkstatt, Reifen, Verschleiß, HU – umgerechnet auf €/100 km |
| 🛡️ Versicherung | Gesellschaft, Deckung, SF-Klassen, Zusatzbausteine |
| 📥 HA Import | Nächtlicher Abruf aus Home Assistant, mit Protokoll |
| 🧾 Rechnungen | PDF-Rechnungen einlesen |
| 📄 Berichte | Monatsbericht als PDF, optional per Mail |
| 💾 Backup | Datenbank sichern und zurückspielen |
| ❓ Hilfe | Handbuch, Herleitung jeder Kennzahl, Änderungslog |

## Daten

Alle Daten liegen in einer eigenen SQLite-Datenbank (`ev_tracker.db`), im Add-on-Betrieb
unter `/data` – wird automatisch von Home Assistants eigenen Sicherungen mit erfasst.

## Benzin-Äquivalent

Berechnung: `km / 100 × 7,0 L × Benzinpreis`
Standard-Referenzverbrauch: **15 kWh/100 km** (in den Einstellungen pro Fahrzeug anpassbar)

---

## Für Entwickler: zwei Betriebsarten, eine Codebasis

Dieses Repo unterstützt zwei Deployments **derselben** App – das Home-Assistant-Add-on
(oben) und einen eigenständigen Docker-Betrieb (Portainer o.ä., siehe
[webapp/README.md](webapp/README.md)). Die eigentliche Anwendung (`webapp/app.py`,
`database.py`, `ha_client.py`, alle Templates usw.) ist bewusst **gemeinsamer Code** –
Änderungen dort wirken sich immer auf beide Betriebsarten aus, das ist gewollt (gleiche
Funktionen, nur anders verpackt). Nur diese Dateien sind jeweils exklusiv für eine
Betriebsart und beeinflussen die andere nicht:

| Datei | Gehört zu |
|-------|-----------|
| `Dockerfile`, `config.yaml`, `repository.yaml`, `icon.png`, `logo.png` | **Home-Assistant-Add-on** |
| `docker-compose.yml`, `webapp/Dockerfile`, `backup.sh`, `backup_db.py` | **Standalone-Docker** (Portainer o.ä.) |

Wo sich das Verhalten der App selbst je nach Betriebsart unterscheidet (Backup-Seite,
Home-Assistant-Verbindung), steht im Code immer die Variable `IST_ADDON`
(`webapp/app.py`) – erkennt automatisch, ob `SUPERVISOR_TOKEN` gesetzt ist. Danach
suchen, wenn unklar ist, wo genau sich beide Wege unterscheiden.

### Aufbau

| Ordner / Datei | Inhalt |
|----------------|--------|
| `webapp/` | FastAPI-Anwendung, Templates, statische Dateien, Dockerfile |
| `charts.py` | Chart-Definitionen (Apache ECharts), werden im Browser gezeichnet |
| `berechnung.py` | Alle Kennzahlen und Ersparnis-Berechnungen |
| `database.py` | SQLite-Zugriff und Schema |
| `ha_client.py` | Home Assistant und InfluxDB |
| `berichte.py`, `mailer.py` | Monatsbericht als PDF, Mailversand |
| `pdf_parser.py`, `ladeerkennung.py` | Rechnungs-PDFs, Erkennung von Ladevorgängen |
| `backup_db.py`, `backup.sh` | Sicherung der Datenbank (nur Standalone-Docker) |
| `settings_tool.py` | Einstellungen als JSON exportieren/importieren |
| `testdaten.py`, `testdaten.bat` | Testdaten anlegen |
| `version.py` | Versionsnummer und Änderungslog |
