# -*- coding: utf-8 -*-
"""
Verbrauch aus dem Akkustand: zerlegt den Batterieverlauf (Home Assistant) in
Fahrtabschnitte zwischen zwei Ladungen und rechnet je Abschnitt

    kWh  = (Akku am Start − Akku am Ende) [%] ÷ 100 × Akkukapazitaet
    km   = Kilometerstand am Ende − Kilometerstand am Start
    Verbrauch = kWh ÷ km × 100

Anders als der Verbrauch aus den Ladungen (geladene kWh ÷ km) enthaelt dieser
Wert keine Ladeverluste – er zeigt, was tatsaechlich aus dem Akku kam, inklusive
Standverbrauch (Vorklimatisieren, 12-V-Batterie) zwischen den Fahrten.

Grundlage sind die stuendlichen Langzeitstatistiken von HA; der Akkustand ist
der Stundenmittelwert. Das macht einzelne Abschnitte um etwa ±1 % Akku
(±0,6 kWh) ungenau – bei kurzen Strecken faellt das stark ins Gewicht, daher
zaehlen Abschnitte unter MIN_KM nicht in die Monatswerte.
"""
from datetime import datetime, timedelta

import database as db

# Anstieg je Stunde, ab dem ein Ladevorgang angenommen wird (Prozentpunkte).
# Kleinere Schwankungen des Stundenmittels sind Rauschen.
LADE_SCHWELLE = 0.5
# Abschnitte mit weniger km sind zu ungenau fuer Monatswerte
MIN_KM = 5.0
# Der naechtliche Lauf berechnet diesen Zeitraum neu
TAGE_NACHTLAUF = 45


def _client():
    cfg = db.get_ha_settings()
    if not (cfg.get("ha_url") and cfg.get("ha_token")):
        return None, cfg
    from ha_client import HAClient
    return HAClient(cfg["ha_url"], cfg["ha_token"]), cfg


def _stundenwerte(client, entity: str, start: datetime, ende: datetime,
                  felder: tuple) -> list:
    """Stundenwerte als [(zeit 'YYYY-MM-DDTHH:MM', wert), ...], aufsteigend.
    `felder` gibt die Reihenfolge an, in der Statistik-Felder genutzt werden."""
    stats = client._get_statistics([entity], start, ende, period="hour")
    werte = []
    for r in stats.get(entity, []):
        for feld in felder:
            wert = r.get(feld)
            if wert is not None:
                werte.append((str(r.get("start", ""))[:16], float(wert)))
                break
    werte.sort(key=lambda x: x[0])
    return werte


def _km_bei(km_verlauf: list, zeit: str):
    """Letzter bekannter Kilometerstand bis einschliesslich `zeit`.
    Das Auto meldet nur, wenn es online ist – Luecken werden so ueberbrueckt."""
    treffer = None
    for t, km in km_verlauf:
        if t > zeit:
            break
        treffer = km
    if treffer is None and km_verlauf:
        # Vor dem ersten Messwert: den ersten nehmen
        treffer = km_verlauf[0][1]
    return treffer


def berechne_abschnitte(soc_verlauf: list, km_verlauf: list, kapazitaet: float) -> list:
    """Zerlegt den Akkuverlauf in Abschnitte ohne Ladung.

    Ein Abschnitt beginnt am Hoechststand nach einer Ladung und endet am
    Tiefststand vor der naechsten. Der erste Abschnitt ist "angeschnitten",
    wenn der Verlauf mitten in einem Abschnitt beginnt; der letzte ist
    "laufend", wenn danach noch keine Ladung kam.
    """
    if len(soc_verlauf) < 2 or not km_verlauf:
        return []

    abschnitte = []
    start = soc_verlauf[0]
    angeschnitten = True          # vor dem ersten Punkt wissen wir nichts
    vorher = soc_verlauf[0]

    def abschliessen(anfang, schluss, laufend):
        km_a = _km_bei(km_verlauf, anfang[0])
        km_e = _km_bei(km_verlauf, schluss[0])
        if km_a is None or km_e is None:
            return
        abschnitte.append({
            "start": anfang[0], "ende": schluss[0],
            "soc_start": round(anfang[1], 1), "soc_ende": round(schluss[1], 1),
            "km_start": round(km_a, 1), "km_ende": round(km_e, 1),
            "kwh": round((anfang[1] - schluss[1]) / 100 * kapazitaet, 2),
            "km": round(km_e - km_a, 1),
            "laufend": 1 if laufend else 0,
            "angeschnitten": angeschnitten,
        })

    for punkt in soc_verlauf[1:]:
        if punkt[1] > vorher[1] + LADE_SCHWELLE:
            # Ladung laeuft: offenen Abschnitt am Tiefststand davor abschliessen
            if start is not None:
                if vorher[0] > start[0]:
                    abschliessen(start, vorher, laufend=False)
                start = None
                angeschnitten = False
        elif start is None:
            # Erster Punkt ohne Anstieg nach einer Ladung: Hoechststand war davor
            start = vorher
        vorher = punkt

    if start is not None and vorher[0] > start[0]:
        abschliessen(start, vorher, laufend=True)
    return abschnitte


def aktualisieren(tage: int | None = TAGE_NACHTLAUF) -> str:
    """Holt Akku- und Kilometerverlauf und speichert die Abschnitte.

    tage=None rechnet die gesamte Historie neu (ab dem ersten erfassten
    Fahrtenmonat), sonst nur die letzten `tage` Tage. Rueckgabe: Kurzmeldung.
    """
    client, cfg = _client()
    if client is None:
        return "Home Assistant ist nicht konfiguriert"
    soc_entity = (cfg.get("ha_ev_battery") or "").strip()
    km_entity = (cfg.get("ha_odometer") or "").strip()
    if not soc_entity or not km_entity:
        return "Sensoren für Batteriestand oder Kilometerstand fehlen in den Einstellungen"

    try:
        kapazitaet = float(db.get_alle_einstellungen().get("akku_kapazitaet_kwh") or 58.3)
    except ValueError:
        kapazitaet = 58.3

    ende = datetime.now()
    if tage is None:
        monate = [f["monat"] for f in db.get_fahrten_monate()]
        erster = min(monate) if monate else f"{ende.year - 1}-{ende.month:02d}"
        start = datetime.strptime(erster + "-01", "%Y-%m-%d")
    else:
        start = ende - timedelta(days=tage)

    soc = _stundenwerte(client, soc_entity, start, ende, ("mean", "state"))
    km = _stundenwerte(client, km_entity, start, ende, ("state", "mean"))
    if not soc:
        return "Keine Statistikdaten für den Batteriestand gefunden"
    if not km:
        return "Keine Statistikdaten für den Kilometerstand gefunden"

    abschnitte = berechne_abschnitte(soc, km, kapazitaet)
    if tage is not None:
        # Der angeschnittene erste Abschnitt steht vollstaendig schon in der DB
        abschnitte = [a for a in abschnitte if not a["angeschnitten"]]
    if not abschnitte:
        return "Keine abgeschlossenen Fahrtabschnitte im Zeitraum"

    ab = None if tage is None else abschnitte[0]["start"]
    db.ersetze_akku_abschnitte(ab, abschnitte)
    gesamt_km = sum(a["km"] for a in abschnitte)
    return (f"{len(abschnitte)} Fahrtabschnitt(e) aus dem Akkustand berechnet "
            f"({gesamt_km:.0f} km)")


def pro_monat() -> list:
    """Monatswerte aus den Abschnitten: [{monat, km, kwh, verbrauch}], aufsteigend.
    Zugeordnet nach dem Ende des Abschnitts; gewichtet ueber Σ kWh ÷ Σ km."""
    summen = {}
    for a in db.get_akku_abschnitte():
        if a["km"] < MIN_KM or a["kwh"] <= 0:
            continue
        m = summen.setdefault(a["ende"][:7], {"km": 0.0, "kwh": 0.0})
        m["km"] += a["km"]
        m["kwh"] += a["kwh"]
    return [{"monat": monat, "km": round(s["km"], 1), "kwh": round(s["kwh"], 2),
             "verbrauch": round(s["kwh"] / s["km"] * 100, 2)}
            for monat, s in sorted(summen.items()) if s["km"] > 0]
