# Vorlagen: PV-Anteil beim Laden

Der EV Tracker braucht für die Ladekosten zuhause zwei fortlaufende kWh-Zähler:
**„PV ins Auto“** und **„Netz ins Auto“**. Viele Wallboxen liefern nur die gesamte
Ladeleistung bzw. -energie – die Aufteilung übernehmen diese Vorlagen. Es gibt zwei
gleichwertige Wege, **nur einen davon** verwenden:

| Weg | Für wen | Datei |
|-----|---------|-------|
| **Node-RED** | wer Node-RED nutzt – nur ein Knoten auszufüllen, Einheiten werden erkannt | [`node-red/ev_pv_anteil_flow.json`](node-red/ev_pv_anteil_flow.json) · [Anleitung](node-red/README.md) |
| **Home Assistant** (ohne Node-RED) | alle anderen – ein Paket mit Template-Sensoren | [`homeassistant/ev_pv_anteil.yaml`](homeassistant/ev_pv_anteil.yaml) bzw. [`…_mit_zaehler.yaml`](homeassistant/ev_pv_anteil_mit_zaehler.yaml) |

Beide legen dieselben Sensoren an:

| Sensor | Inhalt | Im EV Tracker |
|--------|--------|---------------|
| `sensor.ev_ladung_pv` | kWh aus PV (fortlaufend) | **PV ins Auto** |
| `sensor.ev_ladung_netz` | kWh aus dem Netz (fortlaufend) | **Netz ins Auto** |
| `sensor.ev_ladeleistung_pv` | aktuelle Ladeleistung aus PV (W) | – |
| `sensor.ev_ladeleistung_netz` | aktuelle Ladeleistung aus dem Netz (W) | – |

Die kWh-Sensoren eignen sich auch fürs **Energie-Dashboard** von Home Assistant.

## So wird gerechnet

**Haus zuerst, das Auto bekommt den Überschuss** – wie beim Überschussladen:

```
Netz ins Auto = min( Netzbezug , Wallbox-Leistung )
PV ins Auto   = Wallbox-Leistung − Netz ins Auto
```

Beispiel: PV 6 kW, Haus 0,8 kW, Wallbox 11 kW → Netzbezug 5,8 kW → 5,8 kW Netz, 5,2 kW PV.

Dafür reichen **zwei Sensoren**: die Netzleistung und die Ladeleistung der Wallbox.
Das ist dasselbe wie „PV − Hausverbrauch“, aber ohne die Stolperfalle, dass der
Hausverbrauch die Wallbox meist schon enthält.

**Hausakku:** Entlädt der Akku ins Auto, sinkt der Netzbezug – das zählt als PV
(gespeicherter Solarstrom). Lädt dein Akku auch aus dem Netz, kann die Akku-Entladung
stattdessen als Netz gezählt werden (Einstellung `akku_als` bzw. `akku_als_netz`).

**Mit Energiezähler der Wallbox (empfohlen):** Statt die Leistung aufzusummieren, wird
jeder Anstieg des Wallbox-Zählers nach dem PV-Anteil aufgeteilt. PV + Netz ergeben dann
immer genau den Zähler der Wallbox.

## Node-RED

**Ausführliche Anleitung mit allen Feldern und Status-Anzeigen: [node-red/README.md](node-red/README.md).**

Kurzfassung:

1. [Flow-Datei als Rohtext öffnen](https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/vorlagen/node-red/ev_pv_anteil_flow.json),
   alles kopieren – **nur diese JSON-Datei**, nicht die `.js`-Dateien aus `quellen/`.
2. Node-RED → Menü ☰ → **Importieren** → einfügen → **Neuen Flow** → **Importieren**.
3. Knoten **„⚙ Einstellungen – hier Sensoren eintragen“** öffnen, `netz`, `wallbox`
   und optional `wallbox_zaehler` eintragen. Im **Node-RED-Add-on** `ha_url`/`ha_token`
   leer lassen.
4. **Übernehmen** (Deploy). Unter den Knoten erscheint der Status, z.B.
   `PV 5200 W · Netz 5800 W (PV-Anteil 47 %) · 12.40 / 30.15 kWh`.

Es werden nur Standard-Knoten verwendet, keine Zusatzpalette. Die Zählerstände
überstehen Neustarts: nach einem Node-RED-Neustart übernimmt der Flow den letzten
Stand aus Home Assistant. Wer in Node-RED einen Dateispeicher für den Kontext
eingerichtet hat (`contextStorage` mit `file`), nutzt ihn automatisch.

## Home Assistant (ohne Node-RED)

1. Datei nach `/config/packages/ev_pv_anteil.yaml` kopieren – mit Energiezähler der
   Wallbox die Datei `ev_pv_anteil_mit_zaehler.yaml` (ebenfalls unter diesem Namen).
   Falls noch nicht vorhanden, in `configuration.yaml`:
   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```
2. In der Datei **Suchen & Ersetzen**: `sensor.DEIN_NETZ`, `sensor.DEINE_WALLBOX`
   (und ggf. `sensor.DEIN_WALLBOX_ZAEHLER`) durch deine Entity-IDs.
3. Vorzeichen prüfen (`netz_bezug_positiv` im Sensor „EV Ladeleistung Netz“).
4. Home Assistant neu starten.

## Vorzeichen der Netzleistung

Zeigt dein Netz-Sensor **positive Werte beim Bezug** (Strom aus dem Netz), bleibt
`netz_bezug_positiv` auf `true`. Zeigt er **positive Werte bei Einspeisung** (häufig bei
SolarEdge-Zählern), auf `false` stellen. Kurz prüfen: nachts ohne PV muss der Sensor
beim Laden einen großen Wert mit dem Vorzeichen „Bezug“ zeigen. Hast du nur einen
reinen Bezugssensor (immer ≥ 0), passt `true`.

## Prüfen

- Laden bei Sonne ohne Hausverbrauch-Spitzen → `EV Ladeleistung PV` ≈ Wallbox-Leistung.
- Laden nachts → `EV Ladeleistung Netz` ≈ Wallbox-Leistung.
- Mit Zähler: `EV Ladung PV` + `EV Ladung Netz` wächst genauso wie der Wallbox-Zähler.

Die Rechenlogik beider Varianten ist mit simulierten Ladetagen getestet
(`tests/vorlagen_test.py`).
