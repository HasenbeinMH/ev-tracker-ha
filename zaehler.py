# -*- coding: utf-8 -*-
"""
Verbrauch aus Zaehlerstaenden – auch bei Zaehlern, die zurueckgesetzt werden.

Die App erwartet fuer kWh und Kosten einen Zaehler. Der kann fortlaufend sein
(Wallbox-Gesamtzaehler) oder taeglich/monatlich/jaehrlich auf 0 springen (evcc
"…_monatlich", utility_meter). Bei einem solchen Zaehler ergibt "Stand am Monatsende
minus Stand vor dem Monat" Unsinn (z.B. 50.21 − 32.85 statt 50.21), und auch die
Langzeitstatistik von HA zaehlt den Reset als Abnahme, wenn der Sensor state_class
"total" ohne last_reset hat.

Zaehlerart je Sensor (Einstellung art_<sensor>):
    "auto"         Reset erkennen: Abfall auf weniger als 90 % des vorigen Werts
                   (dieselbe Regel wie HA bei total_increasing). Steht gleich danach
                   wieder etwa der alte Stand (±10 %) da, war es ein Aussetzer
                   (z.B. kurz 0 nach einem Neustart) und kein Reset.
    "fortlaufend"  nie zurueckgesetzt – Ende minus Anfang wie bisher
    "reset"        wird zurueckgesetzt – jeder Abfall ist ein Reset
"""
import re

ARTEN =("auto", "fortlaufend", "reset")
# Abfall auf weniger als diesen Anteil des vorigen Werts = Reset (Zaehlerart "auto")
RESET_ANTEIL = 0.9

# Einstellungsschluessel der Zaehlerart je Sensorfeld
ART_FELD = {"ha_pv_production": "art_pv_production",
            "ha_wallbox_energy": "art_wallbox_energy",
            "ha_wallbox_cost": "art_wallbox_cost"}


_RESET_NAMEN = re.compile(r"(daily|today|heute|t[aä]glich|tages|monthly|monatlich|monats|"
                          r"yearly|j[aä]hrlich|jahres|weekly|w[oö]chentlich)", re.I)


def name_setzt_zurueck(text: str) -> bool:
    """Deutet der Name (Entity-ID/Friendly Name) auf einen Zaehler hin, der zurueckgesetzt
    wird (z.B. "…_monatlich", "energy_today")? Nur ein Hinweis, keine Rechengrundlage."""
    return bool(_RESET_NAMEN.search(text or ""))


def art_aus(cfg: dict, ha_feld: str) -> str:
    """Zaehlerart eines Sensorfelds aus den Einstellungen; unbekannt oder leer = "auto"."""
    art = (cfg.get(ART_FELD.get(ha_feld, "")) or "").strip()
    return art if art in ARTEN else "auto"


def _schritte(reihe: list, art: str):
    """Geht die Reihe [(zeit, wert)] durch und liefert je Wert (zeit, bezug, reset):
    bezug = hoechster Stand seit dem letzten Reset, reset = hier wurde zurueckgesetzt.
    Kleine Ruecksprünge und Aussetzer aendern den Bezug nicht."""
    letzter = None
    for i, (t, v) in enumerate(reihe):
        reset = False
        if letzter is None:
            letzter = v
        elif v > letzter:
            letzter = v
        elif art != "fortlaufend" and v < letzter and (art == "reset" or v < letzter * RESET_ANTEIL):
            naechster = reihe[i + 1][1] if i + 1 < len(reihe) else None
            # Aussetzer: gleich danach wieder etwa der alte Stand (±10 %)
            aussetzer = (art == "auto" and naechster is not None
                         and abs(naechster - letzter) <= letzter * (1 - RESET_ANTEIL))
            if not aussetzer:
                letzter, reset = max(v, 0.0), True
        yield t, letzter, reset


def _reihe(werte: list, vorwert=None) -> list:
    reihe = [(w if isinstance(w, (tuple, list)) else (i, w)) for i, w in enumerate(werte)]
    reihe = [(t, float(v)) for t, v in reihe if v is not None]
    if vorwert is not None:
        reihe.insert(0, (None, float(vorwert)))
    return reihe


def verbrauch(werte: list, vorwert: float | None = None, art: str = "auto"):
    """Verbrauch ueber eine zeitlich sortierte Reihe von Zaehlerstaenden.

    werte:   [wert, ...] oder [(zeit, wert), ...]
    vorwert: letzter Stand vor dem Zeitraum (None = erster Wert der Reihe ist die Basis)
    Rueckgabe: (verbrauch oder None, zeit bzw. Index des ersten Resets oder None).
    "fortlaufend": Ende minus Anfang, negativ = None (wie bisher).
    Sonst: Summe der Zuwaechse; nach einem Reset zaehlt der neue Wert ab 0."""
    reihe = _reihe(werte, vorwert)
    if not reihe or (vorwert is not None and len(reihe) < 2):
        return None, None
    if art == "fortlaufend":
        delta = reihe[-1][1] - reihe[0][1]
        return (delta if delta >= 0 else None), None
    summe, reset_bei, vorher = 0.0, None, None
    for t, bezug, reset in _schritte(reihe, art):
        if reset:
            summe += bezug
            reset_bei = t if reset_bei is None else reset_bei
        elif vorher is not None:
            summe += bezug - vorher
        vorher = bezug
    return summe, reset_bei


def fortlaufend_machen(werte: list, art: str = "auto") -> list:
    """[(zeit, stand)] -> [(zeit, fortlaufender Stand)]: Resets werden herausgerechnet,
    damit Differenzen benachbarter Werte nie negativ werden (Stundenverbrauch)."""
    if art == "fortlaufend" or not werte:
        return list(werte)
    erg, versatz, vorher = [], 0.0, None
    for t, bezug, reset in _schritte(_reihe(werte), art):
        if reset:
            versatz += vorher
        erg.append((t, round(versatz + bezug, 6)))
        vorher = bezug
    return erg
