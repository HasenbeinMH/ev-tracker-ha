# -*- coding: utf-8 -*-
"""
Verbrauch aus Zaehlerstaenden – auch bei Zaehlern, die zurueckgesetzt werden.

Die App erwartet fuer kWh und Kosten einen Zaehler. Der kann fortlaufend sein
(Wallbox-Gesamtzaehler) oder taeglich/monatlich/jaehrlich auf 0 springen (evcc
"…_monatlich", utility_meter). Bei einem solchen Zaehler ergibt "Stand am Monatsende
minus Stand vor dem Monat" Unsinn (z.B. 50.21 − 32.85 statt 50.21), und auch die
Langzeitstatistik von HA zaehlt den Reset als Abnahme, wenn der Sensor state_class
"total" ohne last_reset hat.

Reset: Abfall auf weniger als 90 % des vorigen Werts (dieselbe Regel wie HA bei
total_increasing). Steht danach direkt wieder etwa der alte Stand (±10 %) da, war es
ein Aussetzer (z.B. kurz 0 nach einem Neustart) und kein Reset.
"""

# Abfall auf weniger als diesen Anteil des vorigen Werts = Reset
RESET_ANTEIL = 0.9


def _schritte(reihe: list):
    """Geht die Reihe [(zeit, wert)] durch und liefert je Wert (zeit, bezug, reset):
    bezug = hoechster Stand seit dem letzten Reset, reset = hier wurde zurueckgesetzt.
    Kleine Ruecksprünge und Aussetzer aendern den Bezug nicht."""
    letzter = None
    for i, (t, v) in enumerate(reihe):
        reset = False
        if letzter is None or v > letzter:
            letzter = v
        elif v < letzter * RESET_ANTEIL:
            # Naechster abweichende Wert – ein Aussetzer kann mehrere Werte lang dauern (0, 0, …)
            j = i + 1
            while j < len(reihe) and reihe[j][1] == v:
                j += 1
            naechster = reihe[j][1] if j < len(reihe) else None
            # Aussetzer: danach direkt wieder etwa der alte Stand (±10 %)
            aussetzer = (naechster is not None
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


def verbrauch(werte: list, vorwert: float | None = None):
    """Verbrauch ueber eine zeitlich sortierte Reihe von Zaehlerstaenden: Summe der
    Zuwaechse, nach einem Reset zaehlt der neue Wert ab 0.

    werte:   [wert, ...] oder [(zeit, wert), ...]
    vorwert: letzter Stand vor dem Zeitraum (None = erster Wert der Reihe ist die Basis)
    Rueckgabe: (verbrauch oder None, zeit bzw. Index des ersten Resets oder None)."""
    reihe = _reihe(werte, vorwert)
    if not reihe or (vorwert is not None and len(reihe) < 2):
        return None, None
    summe, reset_bei, vorher = 0.0, None, None
    for t, bezug, reset in _schritte(reihe):
        if reset:
            summe += bezug
            reset_bei = t if reset_bei is None else reset_bei
        elif vorher is not None:
            summe += bezug - vorher
        vorher = bezug
    return summe, reset_bei


def fortlaufend_machen(werte: list) -> list:
    """[(zeit, stand)] -> [(zeit, fortlaufender Stand)]: Resets werden herausgerechnet,
    damit Differenzen benachbarter Werte nie negativ werden (Stundenverbrauch)."""
    erg, versatz, vorher = [], 0.0, None
    for t, bezug, reset in _schritte(_reihe(werte)):
        if reset:
            versatz += vorher
        erg.append((t, round(versatz + bezug, 6)))
        vorher = bezug
    return erg
