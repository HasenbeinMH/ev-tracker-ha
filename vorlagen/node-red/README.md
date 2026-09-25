# Node-RED-Flow importieren – Schritt für Schritt

Der Flow teilt die Ladeleistung der Wallbox in **PV** und **Netz** auf und legt in
Home Assistant die Zähler `sensor.ev_ladung_pv` und `sensor.ev_ladung_netz` an.
Wie gerechnet wird, steht in der [Übersicht](../README.md).

> **Importiert wird nur eine Datei: [`ev_pv_anteil_flow.json`](ev_pv_anteil_flow.json).**
> Der Ordner `quellen/` enthält den Programmcode der einzelnen Knoten (`.js`) – der
> steckt schon in der JSON-Datei. Fügt man eine `.js`-Datei in Node-RED ein, kommt
> die Meldung *„Unexpected token '/' … is not valid JSON“*.

## 1. Flow-Datei holen

Einer der beiden Wege:

- **Kopieren:** [Rohfassung der Flow-Datei öffnen](https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/vorlagen/node-red/ev_pv_anteil_flow.json),
  alles markieren (Strg+A) und kopieren (Strg+C). Der Text beginnt mit `[` und
  endet mit `]`.
- **Herunterladen:** denselben Link mit Rechtsklick → *Link speichern unter …* als
  `ev_pv_anteil_flow.json` speichern.

## 2. In Node-RED importieren

1. Node-RED öffnen, oben rechts Menü **☰ → Importieren** (oder Strg+I).
2. Den kopierten Text in das Feld einfügen – oder **„Datei für Import auswählen“** und
   die gespeicherte Datei wählen.
3. Unten **„Neuen Flow“** wählen (dann bekommt der Flow einen eigenen Reiter) und
   **Importieren** klicken.

Es entsteht der Reiter **„EV Tracker – PV-Anteil beim Laden“** mit diesen Knoten:

```
alle 10 s → ⚙ Einstellungen → Zustände lesen → sammeln
          → PV / Netz berechnen → Sensoren nach HA schreiben → Antwort
```

## 3. Sensoren eintragen

Doppelklick auf den Knoten **„⚙ Einstellungen – hier Sensoren eintragen“**. Nur der
Block oben zwischen den Doppellinien wird angepasst:

| Feld | Eintragen | Beispiel |
|------|-----------|----------|
| `netz` | Netzleistung (W oder kW) | `"sensor.netz_leistung"` |
| `netz_bezug_positiv` | `true`, wenn der Sensor beim **Bezug** positiv ist; `false`, wenn bei **Einspeisung** (siehe [Vorzeichen](../README.md#vorzeichen-der-netzleistung)) | `true` |
| `wallbox` | Ladeleistung der Wallbox (W oder kW) | `"sensor.wallbox_leistung"` |
| `wallbox_zaehler` | optional, empfohlen: Energiezähler der Wallbox (kWh/Wh), sonst `""` | `"sensor.wallbox_energie"` |
| `akku_als` | Hausakku ins Auto zählt als `"pv"` oder `"netz"` – ohne Akku egal | `"pv"` |
| `ha_url`, `ha_token` | **im Node-RED-Add-on von Home Assistant leer lassen.** Nur bei eigenständigem Node-RED: HA-Adresse und ein [langlebiges Zugriffstoken](https://www.home-assistant.io/docs/authentication/#your-account-profile) | `""` |

Die Entity-IDs findest du in Home Assistant unter *Einstellungen → Geräte & Dienste →
Entitäten*. Anführungszeichen und Kommas am Zeilenende stehen lassen.

Dann **Fertig** und oben rechts **Übernehmen** (Deploy).

## 4. Prüfen

Nach etwa 10 Sekunden steht unter den Knoten ein Status:

| Knoten | Status | Bedeutung |
|--------|--------|-----------|
| ⚙ Einstellungen | 🟢 `liest 4 Sensoren` (mit Wallbox-Zähler 5) | läuft |
| ⚙ Einstellungen | 🔴 `Sensor "netz" eintragen` | Feld noch nicht ausgefüllt |
| ⚙ Einstellungen | 🔴 `Kein Zugang zu HA …` | eigenständiges Node-RED: `ha_url`/`ha_token` fehlen |
| PV / Netz berechnen | 🟢 `PV 5200 W · Netz 5800 W (PV-Anteil 47 %) · 12.40 / 30.15 kWh` | Leistung jetzt, dahinter die Zählerstände PV / Netz |

In Home Assistant erscheinen die Sensoren **EV Ladung PV** und **EV Ladung Netz**.
Diese trägst du im EV Tracker unter *Einstellungen → Sensoren* bei **PV ins Auto** und
**Netz ins Auto** ein.

Stimmt etwas nicht, im Knoten **„Antwort“** die Ausgabe einschalten (Knopf rechts am
Knoten) – die Antworten von Home Assistant stehen dann in der Debug-Seitenleiste.

## Update auf eine neue Version des Flows

Vorher die Einstellungen aus dem Knoten ⚙ kopieren, dann den alten Reiter löschen
(Doppelklick auf den Reiter → *Löschen*), neu importieren und die Einstellungen
wieder einfügen. Die Zählerstände gehen dabei nicht verloren – der Flow übernimmt
beim Start den letzten Stand aus Home Assistant.

## Für Entwickler

`quellen/flow_bauen.py` baut die JSON-Datei aus `quellen/einstellungen.js` und
`quellen/berechnen.js`. Nach einer Änderung an den Quellen:

```
python vorlagen/node-red/quellen/flow_bauen.py
```

`tests/vorlagen_test.py` prüft, dass die JSON-Datei zu den Quellen passt.
