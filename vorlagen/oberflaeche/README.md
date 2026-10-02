# PV-Anteil beim Laden – ganz ohne YAML (über Helfer)

> Diese Datei wird erzeugt (`quellen/bauen.py`) aus dem Paket
> [`homeassistant/ev_pv_anteil.yaml`](../homeassistant/ev_pv_anteil.yaml) – bitte nicht von
> Hand ändern.

Ergebnis wie beim Paket: zwei fortlaufende kWh-Zähler

| Sensor | Im EV Tracker |
|--------|---------------|
| `sensor.ev_ladung_pv` | **PV ins Auto geladen (kWh)** |
| `sensor.ev_ladung_netz` | **Netz ins Auto geladen (kWh)** |

Regel „Haus zuerst, das Auto bekommt den Überschuss“: Netz ins Auto = min(Netzbezug,
Wallbox-Leistung), PV ins Auto = Rest. Ein Hausakku, der ins Auto entlädt, zählt als PV.

> **Nur einen Weg nutzen** – Node-RED, HA-Paket, configuration.yaml **oder** diese Helfer.
> Sonst gibt es die Sensoren doppelt (mit `_2` am Ende).

Alles geschieht unter **Einstellungen → Geräte & Dienste → Helfer → Helfer erstellen**.
Die Bezeichnungen der Felder können je nach Home-Assistant-Version leicht abweichen.

## Warum kein Blueprint?

Home Assistant kennt Blueprints für Template-Sensoren, sie lassen sich aber nur per YAML
anlegen (nicht über die Oberfläche), und ein Blueprint erzeugt nur eine Art von Entität.
Die kWh-Zähler (Integral) gehen per Blueprint gar nicht. Die Helfer hier kommen dagegen
ganz ohne YAML aus. Die Automation „Ladung senden“ gibt es als
[Blueprint](../blueprints/README.md).

## Schritt 1–3: drei Template-Sensoren (Leistung in W)

Je Sensor: **Template** → **Template für einen Sensor**. In jeder Vorlage zuerst die
Platzhalter ersetzen:

- `sensor.DEINE_WALLBOX` → Ladeleistung der Wallbox (W oder kW – wird erkannt)
- `sensor.DEIN_NETZ` → Netzleistung am Hausanschluss (W oder kW)

Felder für alle drei: **Maßeinheit** `W`, **Geräteklasse** Leistung, **Zustandsklasse**
Messung. Den **Namen genau so** eintragen – daraus entstehen die Entity-IDs, auf die sich
die nächsten Schritte beziehen.

### 1. Name: `EV Ladeleistung Wallbox` → `sensor.ev_ladeleistung_wallbox`

```jinja
{# ── EINSTELLUNGEN ── unter dieser Leistung gilt die Wallbox als aus #}
{% set standby_w = 50 %}
{% set e = 'sensor.DEINE_WALLBOX' %}
{% set w = states(e) | float(0) * (1000 if state_attr(e, 'unit_of_measurement') == 'kW' else 1) %}
{{ 0 if w < standby_w else w | round(0) }}
```

`standby_w`: unter dieser Leistung gilt die Wallbox als aus.

### 2. Name: `EV Ladeleistung Netz` → `sensor.ev_ladeleistung_netz`

```jinja
{# ── EINSTELLUNGEN ────────────────────────────────────────────────── #}
{# true: positiver Wert = Bezug aus dem Netz, negativ = Einspeisung.     #}
{# false: umgekehrt (z.B. viele SolarEdge-Zähler: positiv = Einspeisung) #}
{% set netz_bezug_positiv = true %}
{# Hausakku-Entladung ins Auto als Netz zählen (Akku lädt auch aus dem Netz)? #}
{# Dann true und sensor.DEIN_AKKU ersetzen (Entladung positiv).          #}
{% set akku_als_netz = false %}
{# ────────────────────────────────────────────────────────────────── #}
{% set e = 'sensor.DEIN_NETZ' %}
{% set netz = states(e) | float(0) * (1000 if state_attr(e, 'unit_of_measurement') == 'kW' else 1) %}
{% set bezug = [netz if netz_bezug_positiv else -netz, 0] | max %}
{% if akku_als_netz %}
  {% set a = 'sensor.DEIN_AKKU' %}
  {% set akku = states(a) | float(0) * (1000 if state_attr(a, 'unit_of_measurement') == 'kW' else 1) %}
  {% set bezug = bezug + [akku, 0] | max %}
{% endif %}
{% set wb = states('sensor.ev_ladeleistung_wallbox') | float(0) %}
{# Netzwert fehlt: vorsichtig alles als Netz zählen #}
{{ ([bezug, wb] | min if states(e) | is_number else wb) | round(0) }}
```

- `netz_bezug_positiv`: `true`, wenn der Netzsensor beim **Bezug positiv** ist (Einspeisung
  negativ). Bei vielen SolarEdge-Zählern ist es umgekehrt – dann `false`. Prüfen: abends
  ohne PV muss der Sensor bei Verbrauch einen **positiven** Wert zeigen, sonst `false`.
- `akku_als_netz`: Hausakku-Entladung ins Auto als Netz zählen (Akku lädt auch aus dem Netz)?
  Dann `true` und `sensor.DEIN_AKKU` ersetzen (Entladung positiv).
- Liefert der Netzsensor gerade keinen Wert, zählt die Ladung vorsichtig **als Netz** – so
  wird nie zu viel PV gebucht.

### 3. Name: `EV Ladeleistung PV` → `sensor.ev_ladeleistung_pv`

```jinja
{% set wb = states('sensor.ev_ladeleistung_wallbox') | float(0) %}
{% set netz = states('sensor.ev_ladeleistung_netz') | float(0) %}
{{ [wb - netz, 0] | max | round(0) }}
```

## Schritt 4–5: zwei Integral-Sensoren (Energie in kWh)

Je Zähler: **Integral-Sensor** (Riemann-Summe).

| Feld | 4. PV | 5. Netz |
|------|-------|---------|
| Name | `EV Ladung PV` | `EV Ladung Netz` |
| Eingangssensor | `sensor.ev_ladeleistung_pv` | `sensor.ev_ladeleistung_netz` |
| Integrationsmethode | Linke Riemann-Summe | Linke Riemann-Summe |
| Präzision | 3 | 3 |
| Metrisches Präfix | k (kilo) | k (kilo) |
| Zeiteinheit | Stunden | Stunden |
| Max. Teilintervall (falls angeboten, ab HA 2024.7) | 1 Minute | 1 Minute |

Die **linke** Riemann-Summe passt zur sprunghaften Ladeleistung (an/aus) und zählt keine
Energie, solange die Leistung 0 ist. Das maximale Teilintervall sorgt dafür, dass auch bei
gleichbleibender Leistung weitergezählt wird.

## Schritt 6: im EV Tracker eintragen

EV Tracker → **Einstellungen → Sensoren**: `sensor.ev_ladung_pv` bei „PV ins Auto geladen
(kWh)“ und `sensor.ev_ladung_netz` bei „Netz ins Auto geladen (kWh)“, speichern. Mit
„Prüfen“ zeigt der EV Tracker die Monatswerte, sobald die Zähler laufen.

Bei einem dynamischen Stromtarif kommt optional der Kostenzähler
[`ev_netzkosten.yaml`](../homeassistant/ev_netzkosten.yaml) dazu – der braucht YAML
(trigger-basierte Sensoren gibt es nicht als Helfer).

## Später ändern

Helfer → Sensor anklicken → Zahnrad → **Template-Optionen**: dort lässt sich die Vorlage
nachträglich anpassen (z. B. `netz_bezug_positiv`).
