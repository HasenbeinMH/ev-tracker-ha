# -*- coding: utf-8 -*-
"""
Nutzungsprofil, Ladeprofil und Jahresvergleich.

Nutzungsprofil: aus den Tages-km (Tabelle fahrten_tag, gebildet aus dem stuendlichen
Kilometerstand in akkuverbrauch.tages_km) – wie viel an welchem Wochentag gefahren wird,
wie sich die Tage verteilen und wie viel Akku ein typischer Tag braucht.

Ladeprofil: wann geladen wird (Ladungen aus dem Akkustand, akku.ladungen_aus_abschnitten)
und wo (Ladevorgaenge: zuhause PV/Netz oder unterwegs, AC oder DC).

Jahresvergleich: dieselben Monatswerte wie die Statistik (zeitraum.monatswerte), je Jahr
eine Linie ueber Januar bis Dezember, dazu die Kennzahlen je Kalenderjahr.
"""
from datetime import date

import berechnung
import zeitraum
from i18n import N_

WOCHENTAGE = [N_("Mo"), N_("Di"), N_("Mi"), N_("Do"), N_("Fr"), N_("Sa"), N_("So")]
# Tagesstrecken: (Beschriftung, bis ausschliesslich)
KLASSEN = [(N_("kein Fahrtag"), 1), ("1–20 km", 20), ("20–50 km", 50), ("50–100 km", 100),
           ("100–200 km", 200), ("> 200 km", None)]
FAHRTAG_KM = 1.0        # ab so viel km zaehlt ein Tag als Fahrtag
LANGSTRECKE_KM = 200.0
QUANTIL = 95            # "an 95 % der Fahrtage reichen …"


def _quantil(werte: list, p: float) -> float | None:
    """p-Quantil (0–100) mit linearer Interpolation."""
    if not werte:
        return None
    s = sorted(werte)
    pos = (len(s) - 1) * p / 100
    i = int(pos)
    return s[i] if i + 1 >= len(s) else s[i] + (s[i + 1] - s[i]) * (pos - i)


def nutzung(tage: list, reichweite_100: float | None = None) -> dict | None:
    """Nutzungsprofil aus [{datum, km}]. None ohne Tage."""
    if not tage:
        return None
    summe, anzahl, fahrt = [0.0] * 7, [0] * 7, [0] * 7
    klassen = [0] * len(KLASSEN)
    fahrtage, lang_je_jahr = [], {}
    for t in tage:
        wt = date.fromisoformat(t["datum"]).weekday()
        km = t["km"]
        summe[wt] += km
        anzahl[wt] += 1
        if km >= FAHRTAG_KM:
            fahrt[wt] += 1
            fahrtage.append(km)
        for i, (_text, bis) in enumerate(KLASSEN):
            if bis is None or km < bis:
                klassen[i] += 1
                break
        if km > LANGSTRECKE_KM:
            j = t["datum"][:4]
            lang_je_jahr[j] = lang_je_jahr.get(j, 0) + 1
    q = _quantil(fahrtage, QUANTIL)
    laengster = max(tage, key=lambda t: t["km"])
    return {
        "tage": len(tage),
        "von": tage[0]["datum"], "bis": tage[-1]["datum"],
        "fahrtage": len(fahrtage),
        "anteil_fahrtage": len(fahrtage) / len(tage) * 100,
        "km_je_tag": sum(t["km"] for t in tage) / len(tage),
        "km_je_fahrtag": sum(fahrtage) / len(fahrtage) if fahrtage else None,
        "je_wochentag": [round(summe[i] / anzahl[i], 1) if anzahl[i] else None for i in range(7)],
        "fahrtage_wochentag": [round(fahrt[i] / anzahl[i] * 100) if anzahl[i] else None
                               for i in range(7)],
        "klassen": klassen,
        "laengster": laengster if laengster["km"] > 0 else None,
        "langstrecke": dict(sorted(lang_je_jahr.items())),
        "quantil_km": q,
        "quantil_akku": q / reichweite_100 * 100 if q and reichweite_100 else None,
        "median_km": _quantil(fahrtage, 50),
    }


def laden(ladungen: list, ladevorgaenge: list) -> dict:
    """Ladeprofil: Ladungen aus dem Akkustand nach Wochentag und Stunde, Ladevorgaenge nach
    Ort (zuhause/unterwegs) und Art (AC/DC) in kWh."""
    je_wt, je_std = [0] * 7, [0] * 24
    for l in ladungen:
        try:
            t = date.fromisoformat(l["start"][:10])
            std = int(l["start"][11:13])
        except (ValueError, TypeError):
            continue
        je_wt[t.weekday()] += 1
        je_std[std] += 1
    orte = {"PV-Strom": 0.0, "Netzbezug": 0.0, berechnung.OEFFENTLICH: 0.0}
    art = {"AC": 0.0, "DC": 0.0}
    unterwegs = 0
    for l in ladevorgaenge:
        kwh = l.get("menge_kwh") or 0
        if not kwh:
            continue
        quelle = berechnung.stromquelle(l["anbieter"])
        orte[quelle] = orte.get(quelle, 0.0) + kwh
        if quelle == berechnung.OEFFENTLICH:
            unterwegs += 1
            typ = "DC" if (l.get("ladetyp") or "").upper() == "DC" else "AC"
            art[typ] += kwh
    gesamt = sum(orte.values())
    zuhause = orte["PV-Strom"] + orte["Netzbezug"]
    return {
        "ladungen": len(ladungen),
        "je_wochentag": je_wt,
        "je_stunde": je_std,
        "orte": orte,
        "art": art,
        "unterwegs": unterwegs,
        "anteil_zuhause": zuhause / gesamt * 100 if gesamt else None,
        "anteil_dc": art["DC"] / orte[berechnung.OEFFENTLICH] * 100
                     if orte[berechnung.OEFFENTLICH] else None,
    }


# Kennzahlen des Jahresvergleichs: schluessel -> (Beschriftung, Formatierer, Balken?)
JAHR_METRIKEN = {
    "km":             (N_("Kilometer"), "fn:km0", True),
    "verbrauch":      (N_("Verbrauch laut Wallbox/Ladesäule"), "fn:kwh100", False),
    "verbrauch_akku": (N_("Verbrauch laut Auto-Akku"), "fn:kwh100", False),
    "kosten_100km":   (N_("Stromkosten je 100 km"), "fn:euro2", False),
    "ersparnis":      (N_("Kraftstoff-Ersparnis"), "fn:euro2", True),
}


def jahresvergleich(daten: dict) -> dict:
    """{"jahre": [...], "werte": {jahr: {metrik: [12 Werte oder None]}},
        "kennzahlen": {jahr: zeitraum.kennzahlen(...)}} – Jahre aufsteigend."""
    werte = zeitraum.monatswerte(zeitraum.aufloesen(zeitraum.ALLES), daten)
    je_jahr = {}
    for w in werte:
        j, i = w["monat"][:4], int(w["monat"][5:7]) - 1
        reihe = je_jahr.setdefault(j, {k: [None] * 12 for k in JAHR_METRIKEN})
        km = w["km"]
        reihe["km"][i] = km or None
        reihe["verbrauch"][i] = w["verbrauch"]
        reihe["verbrauch_akku"][i] = w["verbrauch_akku"]
        reihe["kosten_100km"][i] = round(w["strom_kosten"] / km * 100, 2) if km and w["strom_kosten"] else None
        reihe["ersparnis"][i] = w["ersparnis"] if km else None
    jahre = sorted(je_jahr)
    kennzahlen = {j: zeitraum.kennzahlen(zeitraum.aufloesen(j), daten) for j in jahre}
    return {"jahre": jahre, "werte": je_jahr, "kennzahlen": kennzahlen}
