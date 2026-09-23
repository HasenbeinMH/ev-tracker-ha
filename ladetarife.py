# -*- coding: utf-8 -*-
"""
Eigene Ladetarife (Abos wie EnBW S/M/L): Preisverlauf und was ein Tarif wirklich kostet.

Eine Preisaenderung ist ein neuer Eintrag mit neuem gueltig_ab. Ladungen werden
ueber den Anbieternamen und das Datum dem Tarif zugeordnet.

Die Grundgebuehr fliesst nur hier in den effektiven kWh-Preis ein, nicht in die
Ersparnis auf dem Dashboard.
"""
import calendar
from datetime import date

import database as db


def _schluessel(t):
    return (t["anbieter"], t["tarif_name"] or "")


def verlauf(tarife: list) -> list:
    """Eintraege neueste zuerst, je Eintrag mit der Aenderung gegenueber dem
    Vorgaenger desselben Anbieters/Tarifs (ct/kWh AC, None beim ersten)."""
    letzter = {}
    for t in sorted(tarife, key=lambda t: (_schluessel(t), t["gueltig_ab"])):
        vorher = letzter.get(_schluessel(t))
        t["diff_ac"] = None if vorher is None else round(t["preis_ac"] - vorher["preis_ac"], 2)
        letzter[_schluessel(t)] = t
    return sorted(tarife, key=lambda t: (_schluessel(t), t["gueltig_ab"]), reverse=True)


def _monate(von: str, bis: str) -> list:
    """'YYYY-MM' von bis bis einschliesslich."""
    y, m = int(von[:4]), int(von[5:7])
    ende = (int(bis[:4]), int(bis[5:7]))
    liste = []
    while (y, m) <= ende:
        liste.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return liste


def _tarif_im_monat(tarife: list, monat: str):
    """Der zuletzt begonnene Eintrag, der in diesem Monat an mindestens einem Tag galt."""
    start = f"{monat}-01"
    ende = f"{monat}-{calendar.monthrange(int(monat[:4]), int(monat[5:7]))[1]:02d}"
    gueltig = [t for t in tarife
               if t["gueltig_ab"] <= ende and (not t["gueltig_bis"] or t["gueltig_bis"] >= start)]
    return max(gueltig, key=lambda t: t["gueltig_ab"]) if gueltig else None


def tarif_kosten_monate(tarife: list, ladungen: list) -> list:
    """Je Monat und Anbieter mit Tarif: kWh, Ladekosten, davon Blockiergebuehr,
    Grundgebuehr und effektiver Preis inkl. Grundgebuehr. Neueste Monate zuerst.
    Die Grundgebuehr zaehlt in jedem Monat, in dem der Tarif galt – auch ohne Ladung."""
    heute = date.today().strftime("%Y-%m")
    je_anbieter = {}
    for t in tarife:
        je_anbieter.setdefault(t["anbieter"], []).append(t)

    zeilen = []
    for anbieter, liste in je_anbieter.items():
        erster = min(t["gueltig_ab"] for t in liste)[:7]
        if erster > heute:
            continue
        for monat in _monate(erster, heute):
            t = _tarif_im_monat(liste, monat)
            if t is None:
                continue
            lade = [l for l in ladungen
                    if l["anbieter"] == anbieter and l["datum"][:7] == monat]
            kwh = sum(l["menge_kwh"] or 0 for l in lade)
            kosten = sum(l["gesamtpreis"] or 0 for l in lade)
            grund = t["grundgebuehr"] or 0
            zeilen.append({
                "monat": monat,
                "anbieter": anbieter,
                "tarif_name": t["tarif_name"] or "",
                "anzahl": len(lade),
                "kwh": kwh,
                "kosten": kosten,
                "blockier": sum(l.get("blockiergebuehr") or 0 for l in lade),
                "grundgebuehr": grund,
                "gesamt": kosten + grund,
                "effektiv_ct": (kosten + grund) / kwh * 100 if kwh > 0 else None,
                "tarif_ct": t["preis_ac"],
            })
    return sorted(zeilen, key=lambda z: (z["monat"], z["anbieter"]), reverse=True)


def seite_daten() -> dict:
    tarife = db.get_ladetarife()
    ladungen = db.get_ladevorgaenge(limit=100000)
    return {
        "tarife": verlauf([dict(t) for t in tarife]),
        "monate": tarif_kosten_monate(tarife, ladungen),
        "roh": tarife,
    }
