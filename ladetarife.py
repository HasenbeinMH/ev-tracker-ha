# -*- coding: utf-8 -*-
"""
Eigene Ladetarife (Abos wie EnBW S/M/L): Preisverlauf und was ein Tarif wirklich kostet.

Eine Preisaenderung ist ein neuer Eintrag mit neuem gueltig_ab. Ladungen werden
ueber den Anbieternamen und das Datum dem Tarif zugeordnet.

Die Grundgebuehr zaehlt je Monat, anteilig nach den Tagen, an denen der Tarif
galt. Ueber berechnung.ladevorgaenge() fliesst sie als Eintrag ohne kWh in alle
Kosten und die Ersparnis ein.

Ein Tarif mit nur_vergleich ist nicht abgeschlossen (z. B. der Ad-hoc-Preis ohne Abo
oder ein anderes Abo desselben Anbieters): er kostet nichts und belegt keine Preise
vor; rentabilitaet() rechnet die tatsaechlichen Ladungen damit nach.
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


def km_anteil(fahrzeug_id: int, monat: str, km_je: dict | None = None) -> float:
    """Anteil eines Fahrzeugs an den km aller sichtbaren Fahrzeuge im Monat (0…1).
    Ohne km im Monat zu gleichen Teilen. Bei einem Fahrzeug immer 1."""
    ids = db.sichtbare_ids()
    if fahrzeug_id not in ids:
        return 0.0
    if len(ids) == 1:
        return 1.0
    km_je = db.get_fahrten_je_fahrzeug() if km_je is None else km_je
    gesamt = sum(km_je.get(i, {}).get(monat, 0) or 0 for i in ids)
    if gesamt <= 0:
        return 1 / len(ids)
    return (km_je.get(fahrzeug_id, {}).get(monat, 0) or 0) / gesamt


def grundgebuehr_eintraege(tarife: list | None = None) -> list:
    """Die Grundgebuehren als Eintraege mit den Feldern eines Ladevorgangs (0 kWh,
    Markierung "grundgebuehr") – so rechnen alle Auswertungen sie ohne Sonderfall mit.

    Je Fahrzeug: ein Tarif mit Fahrzeug zaehlt nur dort, ein gemeinsamer Tarif (ohne
    Fahrzeug) nach dem km-Anteil des Monats. Bei einem Fahrzeug immer voll."""
    tarife = db.get_ladetarife() if tarife is None else tarife
    fid = db.aktuelles_fahrzeug()
    if fid is not None:
        tarife = [t for t in tarife if not t.get("fahrzeug_id") or t["fahrzeug_id"] == fid]
    km_je = db.get_fahrten_je_fahrzeug() if fid is not None and db.mehrere_fahrzeuge() else {}
    eigene = {(t["anbieter"]) for t in tarife if t.get("fahrzeug_id")}
    eintraege = []
    for (anbieter, monat), g in sorted(grundgebuehren(tarife).items(), key=lambda x: x[1]["datum"]):
        anteil = "" if g["tage"] >= g["monatstage"] else f" (anteilig {g['tage']}/{g['monatstage']} Tage)"
        betrag = g["betrag"]
        if fid is not None and anbieter not in eigene and len(db.sichtbare_ids()) > 1:
            faktor = km_anteil(fid, monat, km_je)
            betrag = round(betrag * faktor, 2)
            anteil += f" · {faktor * 100:.0f} % nach km"
        eintraege.append({
            "id": None, "datum": g["datum"], "menge_kwh": 0.0, "preis_kwh": 0.0,
            "gesamtpreis": betrag, "anbieter": anbieter, "ladeleistung_kw": None,
            "ladetyp": None, "notiz": f"Grundgebühr {g['tarif_name']}".strip() + anteil,
            "blockiergebuehr": None, "grundgebuehr": True})
    return eintraege


def tarif_kosten_monate(tarife: list, ladungen: list, heute: date | None = None) -> list:
    """Je Monat und Anbieter mit Tarif: kWh, Ladekosten, davon Blockiergebuehr,
    Grundgebuehr und effektiver Preis inkl. Grundgebuehr. Neueste Monate zuerst.
    Die Grundgebuehr zaehlt in jedem Monat, in dem der Tarif galt – auch ohne Ladung –,
    anteilig, wenn er nur einen Teil des Monats galt."""
    gebuehren = grundgebuehren(tarife, heute)
    heute = (heute or date.today()).strftime("%Y-%m")
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


def _vergleich_im_monat(liste: list, monat: str):
    """Der Eintrag eines Vergleichstarifs fuer den Monat: der zuletzt begonnene bis
    Monatsende; liegt der Monat vor dem ersten Eintrag, dessen Preis (wer den
    Ad-hoc-Preis heute eintraegt, kann trotzdem die Vormonate vergleichen)."""
    ende = f"{monat}-{calendar.monthrange(int(monat[:4]), int(monat[5:7]))[1]:02d}"
    begonnen = [t for t in liste if t["gueltig_ab"] <= ende]
    return max(begonnen, key=lambda t: t["gueltig_ab"]) if begonnen \
        else min(liste, key=lambda t: t["gueltig_ab"])


def _preis_dc(t) -> float:
    return t["preis_dc"] or t["preis_ac"]


def _ladekosten(t, kwh_ac: float, kwh_dc: float) -> float:
    """Kosten der Energie mit dem Tarif t (ohne Grundgebuehr und Blockiergebuehr)."""
    return (kwh_ac * t["preis_ac"] + kwh_dc * _preis_dc(t)) / 100


def _ist_dc(l) -> bool:
    return (l.get("ladetyp") or "").upper() == "DC"


def break_even(ist, alt, anteil_dc: float = 0.0) -> dict:
    """Ab wie vielen kWh im Monat sind eigenes Abo und Vergleichstarif gleich teuer?
    Grundgebuehr_ist + kWh × Preis_ist = Grundgebuehr_alt + kWh × Preis_alt, die Preise
    gemischt nach dem DC-Anteil. art: "ab" = ab kwh ist das Abo guenstiger,
    "bis" = bis kwh ist das Abo guenstiger, "immer"/"nie" = bei jeder Menge."""
    p_ist = (1 - anteil_dc) * ist["preis_ac"] + anteil_dc * _preis_dc(ist)
    p_alt = (1 - anteil_dc) * alt["preis_ac"] + anteil_dc * _preis_dc(alt)
    g_ist, g_alt = ist["grundgebuehr"] or 0, alt["grundgebuehr"] or 0
    if abs(p_alt - p_ist) < 1e-9:
        return {"art": "immer" if g_ist <= g_alt else "nie", "kwh": None}
    kwh = (g_ist - g_alt) * 100 / (p_alt - p_ist)
    if kwh <= 0:
        # Schnittpunkt bei 0 oder darunter: eine Seite ist bei jeder Menge guenstiger
        return {"art": "immer" if p_ist < p_alt else "nie", "kwh": None}
    return {"art": "ab" if p_ist < p_alt else "bis", "kwh": round(kwh, 1)}


def rentabilitaet(tarife: list, vergleiche: list, ladungen: list,
                  heute: date | None = None) -> list:
    """Je Anbieter mit eigenem Abo und mindestens einem Vergleichstarif desselben
    Anbieters: was dieselben Ladungen mit dem Vergleichstarif gekostet haetten.

    Gleiche kWh (AC/DC getrennt) mit den Preisen des Vergleichstarifs, dazu seine
    Grundgebuehr – in angefangenen Monaten anteilig wie beim eigenen Abo – und die
    tatsaechliche Blockiergebuehr. Neueste Monate zuerst, dazu Summen, Break-even
    und der Verlauf des laufenden Monats fuer das Diagramm."""
    heute = heute or date.today()
    monate_ist = tarif_kosten_monate(tarife, ladungen, heute)
    gebuehren = grundgebuehren(tarife, heute)
    ladungen = [l for l in ladungen if not l.get("grundgebuehr")]
    eigene = {}
    for t in tarife:
        eigene.setdefault(t["anbieter"], []).append(t)
    gruppen = {}
    for t in vergleiche:
        gruppen.setdefault(t["anbieter"], {}).setdefault(t["tarif_name"] or "", []).append(t)

    jetzt = heute.strftime("%Y-%m")
    ergebnis = []
    for anbieter in sorted(set(eigene) & set(gruppen)):
        namen = sorted(gruppen[anbieter])
        zeilen = []
        for z in (z for z in monate_ist if z["anbieter"] == anbieter):
            lade = [l for l in ladungen
                    if l["anbieter"] == anbieter and l["datum"][:7] == z["monat"]]
            kwh_dc = sum(l["menge_kwh"] or 0 for l in lade if _ist_dc(l))
            kwh_ac = z["kwh"] - kwh_dc
            g = gebuehren.get((anbieter, z["monat"]))
            faktor = g["tage"] / g["monatstage"] if g else 1.0
            alt = []
            for name in namen:
                v = _vergleich_im_monat(gruppen[anbieter][name], z["monat"])
                kosten = round(_ladekosten(v, kwh_ac, kwh_dc) + z["blockier"]
                               + (v["grundgebuehr"] or 0) * faktor, 2)
                alt.append({"kosten": kosten, "diff": round(kosten - z["gesamt"], 2)})
            zeilen.append({**z, "kwh_ac": kwh_ac, "kwh_dc": kwh_dc,
                           "gesamt": round(z["gesamt"], 2), "alt": alt})

        # Break-even mit dem aktuellen eigenen Tarif und dem DC-Anteil der letzten 12 Monate
        ist = _tarif_im_monat(eigene[anbieter], jetzt) \
            or max(eigene[anbieter], key=lambda t: t["gueltig_ab"])
        letzte = zeilen[:12]
        kwh_12 = sum(z["kwh"] for z in letzte)
        anteil_dc = sum(z["kwh_dc"] for z in letzte) / kwh_12 if kwh_12 > 0 else 0.0
        vergleich_info = []
        for i, name in enumerate(namen):
            v = _vergleich_im_monat(gruppen[anbieter][name], jetzt)
            vergleich_info.append({
                "name": name, "tarif": v, "break_even": break_even(ist, v, anteil_dc),
                "summe": round(sum(z["alt"][i]["kosten"] for z in zeilen), 2),
                "diff": round(sum(z["alt"][i]["diff"] for z in zeilen), 2)})
        ergebnis.append({
            "anbieter": anbieter, "ist": ist, "monate": zeilen, "vergleiche": vergleich_info,
            "summe_ist": round(sum(z["gesamt"] for z in zeilen), 2),
            "anteil_dc": anteil_dc,
            "kwh_monat": kwh_12 / len(letzte) if letzte else 0.0,
            "kwh_jetzt": next((z["kwh"] for z in zeilen if z["monat"] == jetzt), 0.0),
            "verlauf": monatsverlauf(anbieter, ist, [i["tarif"] for i in vergleich_info],
                                     namen, ladungen, gebuehren, heute),
        })
    return ergebnis


def monatsverlauf(anbieter, ist, vergleiche: list, namen: list, ladungen: list,
                  gebuehren: dict, heute: date) -> dict:
    """Aufsummierte Kosten im laufenden Monat Tag fuer Tag: das eigene Abo startet bei
    seiner Grundgebuehr, jeder Vergleichstarif bei seiner. Die Tage reichen bis zum
    Monatsende, Werte gibt es bis heute (danach None)."""
    monat = heute.strftime("%Y-%m")
    g = gebuehren.get((anbieter, monat))
    faktor = g["tage"] / g["monatstage"] if g else 1.0
    lade = [l for l in ladungen if l["anbieter"] == anbieter and l["datum"][:7] == monat]
    summe_ist = g["betrag"] if g else 0.0
    summe_alt = [(v["grundgebuehr"] or 0) * faktor for v in vergleiche]
    ist_werte, alt_werte = [], [[] for _ in vergleiche]
    for tag in range(1, heute.day + 1):
        for l in (l for l in lade if int(l["datum"][8:10]) == tag):
            kwh = l["menge_kwh"] or 0
            ac, dc = (0, kwh) if _ist_dc(l) else (kwh, 0)
            summe_ist += l["gesamtpreis"] or 0
            for i, v in enumerate(vergleiche):
                summe_alt[i] += _ladekosten(v, ac, dc) + (l.get("blockiergebuehr") or 0)
        ist_werte.append(round(summe_ist, 2))
        for i in range(len(vergleiche)):
            alt_werte[i].append(round(summe_alt[i], 2))
    rest = [None] * (calendar.monthrange(heute.year, heute.month)[1] - heute.day)
    ist_werte += rest
    alt_werte = [w + rest for w in alt_werte]
    return {"monat": monat, "tage": list(range(1, heute.day + 1 + len(rest))), "ist": ist_werte,
            "ist_name": f"{anbieter} {ist['tarif_name'] or ''}".strip(),
            "alt": [{"name": f"{anbieter} {n}".strip(), "werte": w}
                    for n, w in zip(namen, alt_werte)]}


def seite_daten() -> dict:
    alle = db.get_ladetarife(vergleich=None)
    tarife = [t for t in alle if not t.get("nur_vergleich")]
    vergleiche = [t for t in alle if t.get("nur_vergleich")]
    ladungen = db.get_ladevorgaenge(limit=100000)
    return {
        "tarife": verlauf([dict(t) for t in alle]),
        "monate": tarif_kosten_monate(tarife, ladungen),
        "rentabilitaet": rentabilitaet(tarife, vergleiche, ladungen),
        "roh": tarife,
    }
