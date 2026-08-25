# EV Tracker – Web-Version (Docker)

Browser-Version des EV Trackers. Nutzt dieselben Kern-Module und dasselbe
Datenbankformat wie die Desktop-App – die Desktop-App im Hauptordner bleibt
unverändert nutzbar.

## Deployment über Portainer + GitHub (empfohlen)

1. Projekt liegt in einem (privaten!) GitHub-Repository.
2. In Portainer: **Stacks → Add stack → Repository**
   - Repository URL: `https://github.com/<benutzer>/<repo>`
   - Bei privatem Repo: Authentication aktivieren (GitHub-Benutzer + Personal Access Token)
   - Compose path: `docker-compose.yml`
3. **Deploy the stack** – Portainer klont das Repo und baut das Image selbst.
4. Danach im Browser: `http://<docker-host>:8099`

Updates: neuen Stand nach GitHub pushen, dann in Portainer **Pull and redeploy**.

### Wichtig: HA-Adresse im Container

`homeassistant.local` (mDNS) funktioniert **innerhalb von Containern meist nicht**.
In den Einstellungen der Web-App daher die **IP-Adresse** des HA-Servers eintragen,
z.B. `http://192.168.1.x:8123` (ebenso bei der InfluxDB-URL).

### Datenverzeichnis auf dem Docker-Host

Die Datenbank liegt **nicht** in einem Named Volume, sondern unter
`/home/smarthome/ev-tracker/data/ev_tracker.db` – so kommt das Backup-Skript
direkt heran. Anderer Pfad: Umgebungsvariable `EV_TRACKER_DATA_DIR` setzen.

### Bestehende Desktop-Datenbank übernehmen

Vor dem ersten Start einfach dorthin kopieren (per scp/WinSCP vom Windows-PC):

```bash
mkdir -p /home/smarthome/ev-tracker/data
cp ev_tracker.db /home/smarthome/ev-tracker/data/ev_tracker.db
```

## Start mit Docker lokal

```bash
cd ..
docker compose up -d --build
```

Danach im Browser: **http://localhost:8099**

## Start ohne Docker (lokal testen)

```bash
pip install -r requirements-web.txt
uvicorn webapp.app:app --reload
```

(aus dem **Hauptordner** starten, nicht aus `webapp/`)

## Hinweise

- **Kein Login/HTTPS eingebaut** – nur im eigenen Heimnetz betreiben,
  nicht ins Internet freigeben (sonst Reverse-Proxy mit Auth davorschalten).
- Die Buttons „HA testen" / „InfluxDB testen" prüfen die **gespeicherten**
  Einstellungen – also erst „Alle Einstellungen speichern", dann testen.
- Token-/Passwort-Felder: leer lassen = gespeicherten Wert behalten.

## Einstellungen sichern / laden

Auf der Einstellungsseite gibt es Buttons zum Export/Import aller Parameter,
Sensor-Zuordnungen und Anbieter als JSON-Datei – praktisch, um die Konfiguration
(u.a. den 183 Zeichen langen HA-Token) zwischen Desktop-App und Web-Version zu
uebertragen, ohne sie abzutippen.

- **Exportieren (mit Zugangsdaten)** – enthaelt HA-Token und InfluxDB-Passwort
  im Klartext. Sicher aufbewahren!
- **Ohne Token/Passwort** – zum Weitergeben oder Versionieren.
- **Importieren** – Datei waehlen, bestehende Werte werden ueberschrieben.
  Leere Zugangsdaten in der Datei lassen vorhandene Werte unangetastet.

Dasselbe Format nutzt das CLI-Werkzeug der Desktop-App:

```bash
python settings_tool.py export meine_einstellungen.json
python settings_tool.py import meine_einstellungen.json
```

## Backup nach OneDrive (rclone auf dem Docker-PC)

`backup.sh` laeuft per Cronjob auf dem Docker-PC und laedt einen
SQLite-Hot-Backup-Snapshot per rclone nach OneDrive – unabhaengig davon, ob der
Windows-PC laeuft.

Das Skript steckt im Image – nach jedem Redeploy auf den Host holen:

```bash
docker cp ev-tracker:/app/backup.sh /home/smarthome/ev-tracker/backup.sh && chmod +x /home/smarthome/ev-tracker/backup.sh
```

Cron-Eintraege einmalig anlegen (ohne Editor):

```bash
(crontab -l 2>/dev/null; echo "0 2 * * * /home/smarthome/ev-tracker/backup.sh"; echo "*/5 * * * * [ -f /home/smarthome/ev-tracker/data/.backup_now ] && /home/smarthome/ev-tracker/backup.sh") | crontab -
```

Die erste Zeile sichert taeglich um 02:00 Uhr. Die zweite prueft alle 5 Minuten,
ob in der Weboberflaeche ein Backup angefordert wurde („Backup jetzt anstossen").

- Ziel: `onedrive:EV-Tracker-Backup/data/` (nutzt das vorhandene rclone-Remote `onedrive`)
- Aufbewahrung: 60 Tage, aeltere Snapshots werden automatisch geloescht
- Protokoll und Status landen im Datenordner, damit die Webapp sie anzeigen kann
- Braucht kein `sqlite3` auf dem Host – faellt automatisch auf Python im Container zurueck

### Backup-Seite in der Webapp

Der Reiter **Backup** zeigt Status, Alter der letzten Sicherung, Anzahl der
Sicherungen in OneDrive und das Protokoll. Dort laesst sich auch ein Backup
anstossen und eine Sicherung wieder einspielen: Datei hochladen, zweimal
bestaetigen – die aktuelle Datenbank wird vorher als `vor_restore_….db` im
Datenordner gesichert.

### Zusätzlich: Backup über HTTP

`GET /api/backup?token=…` liefert die Datenbank als Download – praktisch für ein
schnelles Backup aus dem Browser. Der Endpunkt ist deaktiviert, solange
`EV_TRACKER_BACKUP_TOKEN` im Container nicht gesetzt ist.

Auf dem Windows-PC sichert `backup_db.py` (tägliche Aufgabe „EV Tracker DB-Backup")
weiterhin die **Desktop**-Datenbank nach `D:\OneDrive\EV-Tracker-Backup`.
