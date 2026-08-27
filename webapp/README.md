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

## Naechtlicher Datenabruf

Jede Nacht um 0:00 Uhr holt die App selbsttaetig die aktuellen Werte aus Home
Assistant bzw. InfluxDB – fuer den **laufenden Monat und den Vormonat**:

- gefahrene Kilometer und Benzinpreis (werden fortgeschrieben)
- ins Auto geladene kWh aus PV und Netz (als Ladevorgang je Monat)

Wiederholte Laeufe legen keine Duplikate an: Ein automatisch erzeugter
Ladevorgang wird erkannt (Notiz „Auto-Import HA") und aktualisiert, sobald sich
der Wert aendert. **Manuell erfasste Ladevorgaenge bleiben unberuehrt** – das
gilt besonders fuer auswaerts geladene Rechnungen, die du selbst eintraegst.

Der Abruf laesst sich im Reiter Berichte abschalten und im Reiter HA Import
jederzeit von Hand ausloesen („Jetzt ausfuehren"). Dort steht auch, wann er
zuletzt lief und was er geschrieben hat.

Direkt im Anschluss prueft die App, ob ein Bericht faellig ist – so sind die
Daten beim Berichtsversand auf dem aktuellen Stand.

## Daten nachtraeglich korrigieren

Ladevorgaenge lassen sich im Reiter **Laden** direkt in der Tabelle bearbeiten
(Stift-Symbol): Datum, kWh, Preis, Anbieter, Leistung, Typ und Notiz. Das ist
vor allem fuer automatisch importierte Werte nuetzlich, wenn ein Sensor etwas
anderes gezaehlt hat als gedacht.

Kilometer und Benzinpreise werden korrigiert, indem derselbe Monat oben im
Formular erneut gespeichert wird – der alte Wert wird dabei ueberschrieben.

## Verbrauchsauswertung

Der Reiter **Fahrten** zeigt den Verbrauch in kWh/100 km:

- niedrigster und hoechster Monatsverbrauch (mit Monatsangabe)
- Durchschnitt nach Kilometern gewichtet (Gesamt-kWh / Gesamt-km)
- einfaches Mittel ueber alle Monate
- Monatstabelle mit Balken zum Vergleich

## Berichte per E-Mail

Der Reiter **Berichte** erstellt Monats- und Jahresberichte mit Kennzahlen,
Vergleich zur Vorperiode, Aufstellung nach Ladeanbieter und (im Jahresbericht)
Monatsverlauf.

- **Vorschau** – Bericht im Browser ansehen, bevor er verschickt wird
- **Jetzt senden** – Einzelversand an einen beliebigen Empfaenger
- **Automatischer Versand** – Monatsbericht ab dem 1. des Folgemonats,
  Jahresbericht ab dem 1. Januar

Der Zeitplan laeuft als Hintergrund-Thread und prueft **einmal taeglich** zum
eingestellten Zeitpunkt (Standard 00:00), ob ein Bericht faellig und der Zeitraum
vollstaendig ist. Ein Merker in der Datenbank verhindert Doppelversand; schlaegt
der Versand fehl (z.B. Mailserver nicht erreichbar), wird es beim naechsten
naechtlichen Lauf erneut versucht.

### Monatsabschluss: warten, bis die Daten vollstaendig sind

Am 1. des Folgemonats sind die Daten meist noch nicht gepflegt. Deshalb prueft
die App vor dem Versand, ob der Monat abschlussreif ist:

- Sind gefahrene Kilometer und Benzinpreis erfasst?
- Gibt es Ladevorgaenge?
- **Wurde auswaerts geladen, ohne dass ein Beleg erfasst ist?**

Der letzte Punkt kommt aus dem Batterieverlauf in Home Assistant: Steigt der
Ladestand des Autos (Sensor „EV Batterie"), war das ein Ladevorgang. Jede
erkannte Ladung wird mit den erfassten Ladevorgaengen abgeglichen (Datum +/- 1 Tag).
Bleibt eine uebrig, wurde vermutlich auswaerts geladen und die Rechnung fehlt noch –
der Bericht wartet dann.

Sobald die Daten nachgetragen sind, geht der Bericht beim naechsten naechtlichen
Lauf automatisch raus. Als Notbremse wird spaetestens am eingestellten Tag
(Standard: 10.) trotzdem versendet, dann mit einem Hinweis auf die fehlenden Daten.

Auf der Berichte-Seite zeigt **„Monat pruefen"** den Status jederzeit an,
inklusive Liste der erkannten, aber nicht erfassten Ladungen mit geschaetzter kWh-Menge.

Einstellbar: Akkukapazitaet (fuer die kWh-Schaetzung), ab wieviel Prozentpunkten
Anstieg eine Ladung gilt (Standard 5), und die Wartefrist. Ohne Batteriesensor
oder ohne HA-Verbindung meldet die Pruefung „unbekannt" und blockiert nicht.

### SMTP einrichten

Zugangsdaten stehen unter **Berichte → Postausgang**:

| Feld | Beispiel web.de |
|---|---|
| Server | `smtp.web.de` |
| Port | `587` (STARTTLS) oder `465` (SSL) |
| Benutzer / Absender | die eigene Mailadresse |

Bei web.de und GMX muss der **SMTP-Zugang im Postfach freigeschaltet** sein
(Einstellungen → POP3/IMAP). Das Passwortfeld leer lassen behaelt das
gespeicherte Passwort.

**Hinweis zur Datenlage:** Kilometer und Benzinpreise werden nur monatsweise
erfasst – deshalb gibt es Monats- und Jahresberichte, aber keinen Wochenbericht.

## Backup nach OneDrive (rclone auf dem Docker-PC)

`backup.sh` laeuft per Cronjob auf dem Docker-PC und laedt einen
SQLite-Hot-Backup-Snapshot per rclone nach OneDrive – unabhaengig davon, ob der
Windows-PC laeuft.

**Einmalig nach dem ersten Deploy:** Docker legt den Datenordner als `root` an –
dem Cronjob fehlen dann die Schreibrechte fuer Protokoll und Statusdatei:

```bash
sudo chown -R $USER: /home/smarthome/ev-tracker/data
```

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
