# -*- coding: utf-8 -*-
"""
Baut die Anleitung "PV-Anteil ohne YAML" (../README.md) aus dem Home-Assistant-Paket
vorlagen/homeassistant/ev_pv_anteil.yaml. Das Paket bleibt die einzige Quelle – nach
jeder Aenderung dort dieses Skript laufen lassen:

    python vorlagen/oberflaeche/quellen/bauen.py

Unterschied zum Paket: Der Template-Helfer in der Oberflaeche hat kein Feld fuer
"availability". Damit ein fehlender Netzwert nicht als PV gezaehlt wird, steht die
Rueckfallregel im Zustand selbst: Netzsensor ohne Zahl -> alles als Netz (vorsichtig),
Wallbox ohne Zahl -> 0 W (das tut das Paket-Template mit float(0) schon).
"""
import os

import yaml

HIER = os.path.dirname(os.path.abspath(__file__))
ZIEL = os.path.join(os.path.dirname(HIER), "README.md")
PAKET = os.path.join(os.path.dirname(os.path.dirname(HIER)), "homeassistant", "ev_pv_anteil.yaml")

# Name im Helfer = Name im Paket -> gleiche Entity-ID (sensor.ev_ladeleistung_…)
SENSOREN = ("ev_tracker_ladeleistung_wallbox", "ev_tracker_ladeleistung_netz", "ev_tracker_ladeleistung_pv")
# Aenderungen gegenueber dem Paket: (unique_id, alt, neu) – jede muss genau einmal passen
ANPASSUNGEN = [
    ("ev_tracker_ladeleistung_netz",
     "{{ [bezug, wb] | min | round(0) }}",
     "{# Netzwert fehlt: vorsichtig alles als Netz zählen #}\n"
     "{{ ([bezug, wb] | min if states(e) | is_number else wb) | round(0) }}"),
]


def _state_block(zeilen: list, uid: str) -> str:
    """Den "state: >"-Block nach "unique_id: <uid>" zeilengetreu (mit Kommentaren) lesen."""
    i = next(n for n, z in enumerate(zeilen) if z.strip() == f"unique_id: {uid}")
    i = next(n for n in range(i, len(zeilen)) if zeilen[n].strip() == "state: >")
    tiefe = len(zeilen[i]) - len(zeilen[i].lstrip())
    block = []
    for z in zeilen[i + 1:]:
        if z.strip() and len(z) - len(z.lstrip()) <= tiefe:
            break
        block.append(z)
    while block and not block[-1].strip():
        block.pop()
    rand = min(len(z) - len(z.lstrip()) for z in block if z.strip())
    return "\n".join(z[rand:] for z in block)


def helfer_templates() -> dict:
    """{unique_id: {"name", "state"}} – Zustandsvorlagen fuer den Template-Helfer."""
    text = open(PAKET, encoding="utf-8").read()
    d = yaml.safe_load(text)
    alle = {s["unique_id"]: s for block in d["template"] for s in block["sensor"]}
    zeilen = text.splitlines()
    erg = {uid: {"name": alle[uid]["name"], "state": _state_block(zeilen, uid)} for uid in SENSOREN}
    # Zeilengetreu gelesen = derselbe Inhalt wie im Paket (YAML faltet nur Zeilenumbrueche)
    for uid in SENSOREN:
        assert " ".join(erg[uid]["state"].split()) == " ".join(alle[uid]["state"].split()), uid
    for uid, alt, neu in ANPASSUNGEN:
        assert erg[uid]["state"].count(alt) == 1, f"{uid}: '{alt}' nicht genau einmal im Paket"
        erg[uid]["state"] = erg[uid]["state"].replace(alt, neu)
    return erg


def integral() -> dict:
    """{name: quelle} der Integral-Sensoren aus dem Paket."""
    d = yaml.safe_load(open(PAKET, encoding="utf-8"))
    return {s["name"]: s["source"] for s in d["sensor"] if s["platform"] == "integration"}


def readme() -> str:
    t = helfer_templates()
    w, n, p = (t[u] for u in SENSOREN)
    integ = integral()

    def block(x):
        return "```jinja\n" + x["state"] + "\n```"

    return f"""# PV-Anteil beim Laden – ganz ohne YAML (über Helfer)

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

### 1. Name: `{w["name"]}` → `sensor.ev_ladeleistung_wallbox`

{block(w)}

`standby_w`: unter dieser Leistung gilt die Wallbox als aus.

### 2. Name: `{n["name"]}` → `sensor.ev_ladeleistung_netz`

{block(n)}

- `netz_bezug_positiv`: `true`, wenn der Netzsensor beim **Bezug positiv** ist (Einspeisung
  negativ). Bei vielen SolarEdge-Zählern ist es umgekehrt – dann `false`. Prüfen: abends
  ohne PV muss der Sensor bei Verbrauch einen **positiven** Wert zeigen, sonst `false`.
- `akku_als_netz`: Hausakku-Entladung ins Auto als Netz zählen (Akku lädt auch aus dem Netz)?
  Dann `true` und `sensor.DEIN_AKKU` ersetzen (Entladung positiv).
- Liefert der Netzsensor gerade keinen Wert, zählt die Ladung vorsichtig **als Netz** – so
  wird nie zu viel PV gebucht.

### 3. Name: `{p["name"]}` → `sensor.ev_ladeleistung_pv`

{block(p)}

## Schritt 4–5: zwei Integral-Sensoren (Energie in kWh)

Je Zähler: **Integral-Sensor** (Riemann-Summe).

| Feld | 4. PV | 5. Netz |
|------|-------|---------|
| Name | `EV Ladung PV` | `EV Ladung Netz` |
| Eingangssensor | `{integ["EV Ladung PV"]}` | `{integ["EV Ladung Netz"]}` |
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
"""


if __name__ == "__main__":
    os.makedirs(os.path.dirname(ZIEL), exist_ok=True)
    neu = readme()
    alt = open(ZIEL, encoding="utf-8").read() if os.path.exists(ZIEL) else ""
    if neu != alt:
        open(ZIEL, "w", encoding="utf-8").write(neu)
        print("geschrieben:", os.path.relpath(ZIEL))
    else:
        print("unveraendert:", os.path.relpath(ZIEL))
