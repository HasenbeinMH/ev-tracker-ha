# -*- coding: utf-8 -*-
"""
Eigene Ladetarife (Abos wie EnBW S/M/L): Preisverlauf und was ein Tarif wirklich kostet.

Eine Preisaenderung ist ein neuer Eintrag mit neuem gueltig_ab. Ladungen werden
ueber den Anbieternamen und das Datum dem Tarif zugeordnet.

Die Grundgebuehr zaehlt je Monat, anteilig nach den Tagen, an denen der Tarif
galt. Ueber berechnung.ladevorgaenge() fliesst sie als Eintrag ohne kWh in alle
Kosten und die Ersparnis ein.
"""
import calendar
from datetime import date, timedelta

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


def _laufzeiten(tarife: list) -> list:
    """(Tarif, erster Tag, letzter Tag oder None) je Eintrag. Ein neuerer Eintrag
    desselben Anbieters loest den vorigen ab – so wie _tarif_im_monat es sieht."""
    je_anbieter = {}
    for t in tarife:
        je_anbieter.setdefault(t["anbieter"], []).append(t)
    laufzeiten = []
    for liste in je_anbieter.values():
        liste = sorted(liste, key=lambda t: t["gueltig_ab"])
        for i, t in enumerate(liste):
            ab = date.fromisoformat(t["gueltig_ab"][:10])
            bis = date.fromisoformat(t["gueltig_bis"][:10]) if t["gueltig_bis"] else None
            if i + 1 < len(liste):
                abgeloest = date.fromisoformat(liste[i + 1]["gueltig_ab"][:10]) - timedelta(days=1)
                bis = min(bis, abgeloest) if bis else abgeloest
            if bis is None or bis >= ab:
                laufzeiten.append((t, ab, bis))
    return laufzeiten


def grundgebuehren(tarife: list, heute: date | None = None) -> dict:
    """{(anbieter, 'YYYY-MM'): {"betrag", "tage", "monatstage", "datum", "tarif_name"}}.
    Voller Monatsbetrag, wenn der Tarif den ganzen Monat galt, sonst anteilig nach
    Tagen. Gerechnet bis einschliesslich zum laufenden Monat."""
    heute = heute or date.today()
    ende = date(heute.year, heute.month, calendar.monthrange(heute.year, heute.month)[1])
    ergebnis = {}
    for t, ab, bis in _laufzeiten(tarife):
        gebuehr = t["grundgebuehr"] or 0
        if gebuehr <= 0:
            continue
        letzter = min(bis, ende) if bis else ende
        for monat in _monate(ab.isoformat(), letzter.isoformat()) if ab <= letzter else []:
            y, m = int(monat[:4]), int(monat[5:7])
            monatstage = calendar.monthrange(y, m)[1]
            von = max(ab, date(y, m, 1))
            tage = (min(letzter, date(y, m, monatstage)) - von).days + 1
            e = ergebnis.setdefault((t["anbieter"], monat), {
                "betrag": 0.0, "tage": 0, "monatstage": monatstage,
                "datum": von.isoformat(), "tarif_name": t["tarif_name"] or ""})
            e["betrag"] += gebuehr * tage / monatstage
            e["tage"] += tage
            e["datum"] = min(e["datum"], von.isoformat())
            e["tarif_name"] = t["tarif_name"] or e["tarif_name"]
    for e in ergebnis.values():
        e["betrag"] = round(e["betrag"], 2)
    return ergebnis


def grundgebuehr_eintraege(tarife: list | None = None) -> list:
    """Die Grundgebuehren als Eintraege mit den Feldern eines Ladevorgangs (0 kWh,
    Markierung "grundgebuehr") – so rechnen alle Auswertungen sie ohne Sonderfall mit."""
    tarife = db.get_ladetarife() if tarife is None else tarife
    eintraege = []
    for (anbieter, monat), g in sorted(grundgebuehren(tarife).items(), key=lambda x: x[1]["datum"]):
        anteil = "" if g["tage"] >= g["monatstage"] else f" (anteilig {g['tage']}/{g['monatstage']} Tage)"
        eintraege.append({
            "id": None, "datum": g["datum"], "menge_kwh": 0.0, "preis_kwh": 0.0,
            "gesamtpreis": g["betrag"], "anbieter": anbieter, "ladeleistung_kw": None,
            "ladetyp": None, "notiz": f"Grundgebühr {g['tarif_name']}".strip() + anteil,
            "blockiergebuehr": None, "grundgebuehr": True})
    return eintraege


def tarif_kosten_monate(tarife: list, ladungen: list) -> list:
    """Je Monat und Anbieter mit Tarif: kWh, Ladekosten, davon Blockiergebuehr,
    Grundgebuehr und effektiver Preis inkl. Grundgebuehr. Neueste Monate zuerst.
    Die Grundgebuehr zaehlt in jedem Monat, in dem der Tarif galt – auch ohne Ladung –,
    anteilig, wenn er nur einen Teil des Monats galt."""
    heute = date.today().strftime("%Y-%m")
    gebuehren = grundgebuehren(tarife)
    ladungen = [l for l in ladungen if not l.get("grundgebuehr")]
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
            g = gebuehren.get((anbieter, monat))
            grund = g["betrag"] if g else 0.0
            zeilen.append({
                "grund_anteilig": bool(g) and g["tage"] < g["monatstage"],
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
