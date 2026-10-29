# -*- coding: utf-8 -*-
"""
Leasing-Kilometer: gefahrene km gegen die im Vertrag vereinbarten.

Einstellungen je Fahrzeug: leasing_aktiv, leasing_start / leasing_ende ('YYYY-MM-DD'),
leasing_km_jahr (vereinbarte km je Jahr), leasing_km_start (km-Stand bei Uebernahme),
leasing_toleranz_km (Freigrenze, in der weder Mehr- noch Minder-km abgerechnet werden),
leasing_mehr_ct / leasing_minder_ct (Satz je km).

    Soll heute   = km je Jahr × Tage seit Vertragsbeginn ÷ 365,25
    Ist          = km-Stand − km-Stand bei Uebernahme
    Prognose     = Ist + km bis Vertragsende, je Monat wie im selben Monat des Vorjahres
                   (sonst Ø km je Tag der letzten 12 Monate)
    Mehr-km      = Prognose − Vertrags-km − Freigrenze  (× Satz = Euro)
"""
import calendar
from datetime import date, timedelta

import akku
import database as db

TAGE_JAHR = 365.25


def _datum(key: str) -> date | None:
    try:
        return date.fromisoformat((db.get_einstellung_str(key) or "").strip())
    except ValueError:
        return None


def vertrag() -> dict | None:
    """Vertragsdaten des aktuellen Fahrzeugs – None, wenn Leasing aus oder unvollstaendig."""
    if db.get_einstellung_str("leasing_aktiv") != "1":
        return None
    start, ende = _datum("leasing_start"), _datum("leasing_ende")
    km_jahr = db.get_einstellung("leasing_km_jahr") or 0.0
    if not start or not ende or ende <= start or km_jahr <= 0:
        return None
    return {"start": start, "ende": ende, "km_jahr": km_jahr,
            # leer: km-Stand bei Kauf (Neuwagen 0)
            "km_start": (db.get_einstellung("leasing_km_start")
                         or db.get_einstellung("km_bei_kauf") or 0.0),
            "toleranz": db.get_einstellung("leasing_toleranz_km") or 0.0,
            "mehr_ct": db.get_einstellung("leasing_mehr_ct") or 0.0,
            "minder_ct": db.get_einstellung("leasing_minder_ct") or 0.0}


def _tage_im_monat(monat: str) -> int:
    return calendar.monthrange(int(monat[:4]), int(monat[5:7]))[1]


def _vorjahr(monat: str) -> str:
    return f"{int(monat[:4]) - 1}{monat[4:]}"


def rest_km(heute: date, ende: date, km_monat: dict, je_tag: float | None) -> float:
    """Erwartete km von morgen bis Vertragsende: je Monat die km/Tag des gleichen Monats
    im Vorjahr, sonst `je_tag`."""
    summe, tag = 0.0, heute + timedelta(days=1)
    while tag <= ende:
        monat = tag.strftime("%Y-%m")
        letzter = date(tag.year, tag.month, _tage_im_monat(monat))
        bis = min(letzter, ende)
        tage = (bis - tag).days + 1
        vj = km_monat.get(_vorjahr(monat))
        rate = vj / _tage_im_monat(monat) if vj else je_tag
        summe += (rate or 0.0) * tage
        tag = bis + timedelta(days=1)
    return summe


def auswertung(heute: date | None = None, v: dict | None = None,
               fahrten: list | None = None, stand: float | None = None) -> dict | None:
    """Stand des Leasingvertrags des aktuellen Fahrzeugs. None ohne aktiven Vertrag.
    v, fahrten und stand sind fuer Tests; sonst kommen sie aus der Datenbank."""
    heute = heute or date.today()
    v = v or vertrag()
    if not v:
        return None
    fahrten = db.get_fahrten_alle_als_liste() if fahrten is None else fahrten
    km_monat = {f["datum"][:7]: f["km"] for f in fahrten}
    start, ende = v["start"], v["ende"]
    gesamt_tage = (ende - start).days
    vertrag_km = v["km_jahr"] * gesamt_tage / TAGE_JAHR
    stichtag = min(max(heute, start), ende)
    vergangen = (stichtag - start).days
    soll = v["km_jahr"] * vergangen / TAGE_JAHR

    # Ist aus dem km-Stand; ohne ihn aus den Monats-km (Startmonat anteilig)
    if stand is None:
        stand = akku.km_stand()
    kum, summe = [], 0.0
    for monat in sorted(km_monat):
        if monat < start.strftime("%Y-%m") or monat > stichtag.strftime("%Y-%m"):
            continue
        km = km_monat[monat]
        if monat == start.strftime("%Y-%m"):
            km *= (_tage_im_monat(monat) - start.day + 1) / _tage_im_monat(monat)
        summe += km
        kum.append({"monat": monat, "km": round(summe)})
    ist = stand - v["km_start"] if stand is not None else summe
    ist = max(0.0, ist)
    if kum:
        kum[-1]["km"] = round(ist)

    rest = rest_km(stichtag, ende, km_monat, akku.km_pro_tag(fahrten)) if heute < ende else 0.0
    prognose = ist + rest
    ueber = prognose - vertrag_km
    mehr = max(0.0, ueber - v["toleranz"])
    minder = max(0.0, -ueber - v["toleranz"])
    rest_monate = max(0.0, (ende - stichtag).days / (TAGE_JAHR / 12))
    return {
        **v,
        "start": start.isoformat(), "ende": ende.isoformat(),
        "vertrag_km": vertrag_km,
        "soll": soll,
        "ist": ist,
        "differenz": ist - soll,
        "prognose": prognose,
        "ueber": ueber,
        "mehr_km": mehr, "mehr_eur": mehr * v["mehr_ct"] / 100,
        "minder_km": minder, "minder_eur": minder * v["minder_ct"] / 100,
        "anteil_km": ist / vertrag_km * 100 if vertrag_km else None,
        "anteil_zeit": vergangen / gesamt_tage * 100 if gesamt_tage else None,
        "noch_je_monat": (max(0.0, vertrag_km + v["toleranz"] - ist) / rest_monate
                          if rest_monate >= 1 else None),
        "rest_monate": rest_monate,
        "beendet": heute >= ende,
        "verlauf": kum,
    }
