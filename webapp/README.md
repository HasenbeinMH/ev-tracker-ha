# EV Tracker – Web-Version (Docker)

Browser-Version des EV Trackers. Nutzt dieselben Kern-Module und dasselbe
Datenbankformat wie die Desktop-App – die Desktop-App im Hauptordner bleibt
unverändert nutzbar.

## Start mit Docker (empfohlen)

```bash
cd webapp
docker compose up -d --build
```

Danach im Browser: **http://localhost:8099** (bzw. die IP des Docker-Hosts).

Die Datenbank liegt im Unterordner `webapp/data/ev_tracker.db` (Docker-Volume).

### Bestehende Desktop-Datenbank übernehmen

Die Datenbank der Desktop-App einfach hineinkopieren (bei gestopptem Container):

```bash
copy ..\ev_tracker.db data\ev_tracker.db
```

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
