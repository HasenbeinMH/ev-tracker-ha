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

### Bestehende Desktop-Datenbank übernehmen

Die DB liegt im benannten Volume `ev_tracker_data` unter `/data/ev_tracker.db`.
Vorhandene Desktop-DB in den laufenden Container kopieren:

```bash
docker cp ev_tracker.db ev-tracker:/data/ev_tracker.db
docker restart ev-tracker
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

## Backup der Datenbank nach OneDrive

Das Skript `backup_db.py` (im Hauptordner) sichert beide Datenbanken nach
`D:\OneDrive\EV-Tracker-Backup` und löscht Sicherungen älter als 30 Tage.
Eine tägliche Windows-Aufgabe („EV Tracker DB-Backup", 20:00 Uhr) ruft es auf.

Gesichert werden:
1. die lokale Desktop-DB – immer
2. die Docker-Webapp-DB – sobald zwei Umgebungsvariablen gesetzt sind:

```
EV_TRACKER_WEBAPP_URL   z.B. http://192.168.1.50:8099
EV_TRACKER_BACKUP_TOKEN dasselbe Geheimwort wie im Container
```

Der Container liefert die DB über `GET /api/backup?token=…`. Der Endpunkt ist
deaktiviert, solange `EV_TRACKER_BACKUP_TOKEN` im Container nicht gesetzt ist –
so kann niemand im Netz die Datenbank samt Zugangsdaten herunterladen.

Manuell ausführen: `python backup_db.py` · Protokoll: `backup.log`
