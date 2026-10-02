# Blueprint: Jede Ladung einzeln an den EV Tracker schicken

Der Blueprint **„EV Tracker – Ladung senden“** macht dasselbe wie die Automation im Paket
[`ev_ladung_senden.yaml`](../homeassistant/ev_ladung_senden.yaml): Er merkt sich beim
Ladebeginn die Zählerstände und schickt am Ladeende kWh aus dem Netz, kWh aus der PV und
optional die Kosten an den EV Tracker. Heimladungen stehen dann einzeln mit Datum statt
nur als Monatssumme im EV Tracker.

Der Unterschied: Sensoren, Adresse und Token wählst du in der Oberfläche aus. Kein
Suchen & Ersetzen, und die Zählerstände liegen in **einem** Text-Helfer statt in vier.

> Nur **einen** Weg nutzen – Paket `ev_ladung_senden.yaml` **oder** Blueprint. Sonst
> kommt jede Ladung doppelt an.

## Voraussetzung

Fortlaufende kWh-Zähler für „Netz ins Auto“ und „PV ins Auto“ – z.B. aus den
[PV-Anteil-Vorlagen](../README.md) (`sensor.ev_ladung_netz`, `sensor.ev_ladung_pv`) – und
ein Sensor mit der Ladeleistung der Wallbox (W oder kW).

## Einrichten

1. **Befehl zum Senden** – einmalig: den Inhalt von [`rest_command.yaml`](rest_command.yaml)
   ans Ende der `configuration.yaml` kopieren (bzw. als Datei nach `/config/packages/`)
   und Home Assistant neu starten. Darin ist nichts zu ersetzen. Steht `rest_command:`
   schon in der Datei, nur den Eintrag `ev_tracker_ladung` darunter anhängen.
2. **Text-Helfer** anlegen: Einstellungen → Geräte & Dienste → Helfer → **Helfer
   erstellen** → **Text**, Name z.B. „EV Tracker Ladung“, **maximale Länge 255**.
3. **Token** holen: EV Tracker → Einstellungen → „Ladungen aus Home Assistant
   empfangen“ → **Token erzeugen**. Dort stehen Adresse und Token.
4. **Blueprint importieren:**

   [![Blueprint importieren](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2FHasenbeinMH%2Fev-tracker-ha%2Fblob%2Fmain%2Fvorlagen%2Fblueprints%2Fev_tracker_ladung_senden.yaml)

   Oder von Hand: Einstellungen → Automationen & Szenen → Blueprints → **Blueprint
   importieren** → diese Adresse einfügen:
   `https://github.com/HasenbeinMH/ev-tracker-ha/blob/main/vorlagen/blueprints/ev_tracker_ladung_senden.yaml`
5. Aus dem Blueprint eine **Automation erstellen** und ausfüllen:

| Feld | Inhalt |
|------|--------|
| Adresse, Token | aus Schritt 3 (Add-on z.B. `http://a0d7b954-ev-tracker:8099/api/ladung`) |
| Ladeleistung der Wallbox | Leistungssensor der Wallbox, z.B. `sensor.ev_ladeleistung_wallbox` |
| kWh aus dem Netz / aus der PV | vorbelegt mit `sensor.ev_ladung_netz` / `sensor.ev_ladung_pv` |
| Kosten Netz ins Auto (optional) | `sensor.ev_ladung_netz_kosten` aus `ev_netzkosten.yaml` |
| Text-Helfer | der Helfer aus Schritt 2 |
| Ladeerkennung (eingeklappt) | ab 50 W, Beginn nach 1 min, Ende nach 15 min ohne Leistung |

## Verhalten

- Eine Ladung beginnt, wenn die Wallbox die Schwelle 1 Minute lang überschreitet, und
  endet nach 15 Minuten darunter – kurze Pausen beim PV-Überschussladen bleiben eine Ladung.
- Am 1. eines Monats um 0 Uhr wird eine laufende Ladung geteilt, damit jeder Teil im
  richtigen Monat zählt.
- Kommt eine Ladung nicht an, erscheint eine Benachrichtigung in Home Assistant. Verloren
  ist sie nicht: der nächtliche Abruf legt den Rest als Monatssumme an.
- Der Text-Helfer zeigt `{}`, wenn keine Ladung offen ist, sonst Beginn und Zählerstände.
