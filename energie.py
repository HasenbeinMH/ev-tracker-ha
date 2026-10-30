# -*- coding: utf-8 -*-
"""
Energie-Aufteilung: wofuer das Auto die Energie gebraucht hat – Antrieb, Klima,
Bordelektronik, Batteriepflege – und wie viel die Rekuperation zurueckgewonnen hat.

Quelle ist die taegliche Fahrstatistik des Autos in Home Assistant, z. B. bei Kia/Hyundai
(Integration "Kia Uvo / Hyundai Bluelink") der Sensor "Taegliche Fahrstatistik". Seine
Attribute enthalten je Tag (Energie in Wh):

    "2026-10-30": {"distance": 185.8, "total_consumed": 24383,
                   "engine_consumption": 21536, "climate_consumption": 1837,
                   "onboard_electronics_consumption": 1010,
                   "battery_care_consumption": 0, "regenerated_energy": 7849}

Gesamt = Antrieb + Klima + Bordelektronik + Batteriepflege; die Rekuperation steht
daneben. Das Auto haelt nur die letzten Tage vor – der naechtliche Abruf speichert sie
deshalb in der Tabelle energie_tag (der laufende Tag wird bis zum naechsten Abruf
ueberschrieben). Beim Einschalten des Moduls holt nachholen() zusaetzlich die Tage aus
dem Recorder (etwa 10 Tage).

Der Wert "laut Bordcomputer" (Gesamt ÷ km) liegt unter dem Verbrauch laut Auto-Akku: das
Auto zaehlt nur, was waehrend der Fahrten verbraucht wurde, ohne Standverbrauch und Verluste
im Akku. Die Anteile der Verbraucher sind davon unberuehrt.
"""
import re
from datetime import datetime, timedelta

import database as db
from i18n import _, N_

# Attribut der Fahrstatistik -> Spalte in energie_tag
FELDER = {"distance": "km", "total_consumed": "gesamt_wh",
          "engine_consumption": "antrieb_wh", "climate_consumption": "klima_wh",
          "onboard_electronics_consumption": "elektronik_wh",
          "battery_care_consumption": "batterie_wh", "regenerated_energy": "rekuperation_wh"}
KATEGORIEN = [("antrieb_wh", N_("Antrieb")), ("klima_wh", N_("Klima")),
              ("elektronik_wh", N_("Bordelektronik")), ("batterie_wh", N_("Batteriepflege"))]
MAX_KM_TAG = 2000.0
MAX_WH_TAG = 300000.0
STAND_KM = 1.0          # Tage mit weniger km: Standverbrauch (Vorklimatisieren, 12 V …)
NACHHOLEN_TAGE = 11
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def tage_aus_attributen(attr: dict) -> dict:
    """{datum: {km, gesamt_wh, antrieb_wh, …}} aus den Attributen der Fahrstatistik.
    Tage mit fehlenden oder unplausiblen Werten fallen weg."""
    erg = {}
    for datum, werte in (attr or {}).items():
        if not _DATUM.match(str(datum)) or not isinstance(werte, dict):
            continue
        tag = {}
        try:
            for quelle, ziel in FELDER.items():
                v = werte.get(quelle)
                tag[ziel] = float(v) if v not in (None, "") else 0.0
        except (TypeError, ValueError):
            continue
        teile = sum(tag[k] for k, _t in KATEGORIEN)
        if not tag["gesamt_wh"] and teile:
            tag["gesamt_wh"] = teile
        if (not 0 <= tag["km"] <= MAX_KM_TAG or not 0 <= tag["gesamt_wh"] <= MAX_WH_TAG
                or any(tag[k] < 0 for k in tag)):
            continue
        tag["km"] = round(tag["km"], 1)
        erg[datum] = tag
    return erg


def _verbindung():
    import datenquellen
    from ha_client import HAClient, ha_verbindung
    cfg = db.get_ha_settings()
    entity = (datenquellen.namen_liste(cfg.get("ha_ev_tagesstatistik")) or [""])[-1]
    verbindung = ha_verbindung(cfg)
    return (HAClient(**verbindung) if verbindung else None), entity


def aktualisieren(nachholen: bool = False) -> str:
    """Tage aus der Fahrstatistik des aktuellen Fahrzeugs speichern. nachholen=True holt
    zusaetzlich alle Staende aus dem Recorder (aeltere Tage, die das Auto nicht mehr
    vorhaelt). Rueckgabe: Kurzmeldung, leer ohne eingetragenen Sensor."""
    client, entity = _verbindung()
    if not entity:
        return ""
    if client is None:
        return _("Energie: Home Assistant ist nicht konfiguriert")
    tage = {}
    if nachholen:
        jetzt = datetime.now()
        for zustand in client.get_history_full(entity, jetzt - timedelta(days=NACHHOLEN_TAGE), jetzt):
            tage.update(tage_aus_attributen(zustand.get("attributes")))
    zustand = client.get_state_full(entity)
    if zustand is None and not tage:
        return _("Energie: „{0}“ liefert keinen Wert", entity)
    tage.update(tage_aus_attributen((zustand or {}).get("attributes")))
    if not tage:
        return _("Energie: „{0}“ enthält keine Tageswerte", entity)
    db.upsert_energie_tage(tage)
    return _("Energie: {0} Tag(e) aus der Fahrstatistik", len(tage))


# ── Auswertung ───────────────────────────────────────────────────────────────

def summe(tage: list) -> dict:
    """Summen und Kennzahlen ueber Tage [{datum, km, gesamt_wh, …}]."""
    s = {k: sum(t[k] for t in tage) for k in ["km", "gesamt_wh", "rekuperation_wh"]
         + [k for k, _t in KATEGORIEN]}
    gesamt, km = s["gesamt_wh"], s["km"]
    stand = [t for t in tage if t["km"] < STAND_KM and t["gesamt_wh"] > 0]
    return {
        **s,
        "tage": len(tage),
        "anteile": {k: s[k] / gesamt * 100 if gesamt else None for k, _t in KATEGORIEN},
        "je_100km": {k: s[k] / km / 10 if km else None for k, _t in KATEGORIEN},
        "bordcomputer": gesamt / km / 10 if km else None,          # kWh/100 km
        # im Verhaeltnis zum Antrieb – ob das Auto sie dort schon abzieht, ist offen
        "rekuperation_anteil": (s["rekuperation_wh"] / s["antrieb_wh"] * 100
                                if s["antrieb_wh"] else None),
        "stand_tage": len(stand),
        "stand_wh": sum(t["gesamt_wh"] for t in stand),
    }


def je_monat(tage: list) -> list:
    """[{monat, **summe}] aufsteigend."""
    monate = {}
    for t in tage:
        monate.setdefault(t["datum"][:7], []).append(t)
    return [{"monat": m, **summe(liste)} for m, liste in sorted(monate.items())]


def strompreise(monatswerte: list) -> dict:
    """Ø Strompreis je Monat in ct/kWh (an Wallbox/Saeule bezahlt, Ladeverluste darin),
    dazu "_schnitt" ueber alle Monate – aus zeitraum.monatswerte."""
    preise = {w["monat"]: w["strom_kosten"] / w["kwh"] * 100
              for w in monatswerte if w.get("kwh") and w.get("strom_kosten")}
    kwh = sum(w["kwh"] for w in monatswerte if w.get("kwh"))
    kosten = sum(w["strom_kosten"] for w in monatswerte if w.get("kwh"))
    preise["_schnitt"] = kosten / kwh * 100 if kwh else None
    return preise


def kosten(tage: list, preise: dict) -> dict:
    """€ je Verbraucher: kWh des Tages × Ø Strompreis seines Monats (sonst Ø aller Monate)."""
    erg = {k: 0.0 for k, _t in KATEGORIEN}
    for t in tage:
        ct = preise.get(t["datum"][:7]) or preise.get("_schnitt")
        if not ct:
            continue
        for k, _t in KATEGORIEN:
            erg[k] += t[k] / 1000 * ct / 100
    return erg


def saison(monate: list) -> dict:
    """Klima in kWh/100 km im Sommer (Jun–Aug) und Winter (Dez–Feb)."""
    def wert(nummern):
        km = sum(m["km"] for m in monate if int(m["monat"][5:7]) in nummern)
        wh = sum(m["klima_wh"] for m in monate if int(m["monat"][5:7]) in nummern)
        return wh / km / 10 if km else None
    return {"sommer": wert((6, 7, 8)), "winter": wert((12, 1, 2))}


def auswertung(z: dict) -> dict:
    """Alles fuer die Energie-Seite im Zeitraum z (zeitraum.aufloesen) – aktuelles Fahrzeug."""
    import zeitraum
    alle_tage = db.get_energie_tage()
    tage = [t for t in alle_tage if zeitraum.enthaelt(z, t["datum"])]
    daten = zeitraum.laden()
    preise = strompreise(zeitraum.monatswerte(zeitraum.aufloesen(zeitraum.ALLES), daten))
    monate = je_monat(alle_tage)
    return {"summe": summe(tage), "kosten": kosten(tage, preise), "monate": monate,
            "monate_zeitraum": [m for m in monate if zeitraum.enthaelt(z, m["monat"])],
            "saison": saison(monate), "tage": len(alle_tage),
            "von": alle_tage[0]["datum"] if alle_tage else None,
            "bis": alle_tage[-1]["datum"] if alle_tage else None}
