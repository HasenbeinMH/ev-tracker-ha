# -*- coding: utf-8 -*-
"""
Unterhaltskosten neben dem Laden: Instandhaltung und KFZ-Versicherung.

Instandhaltung wird auf € pro 100 km umgerechnet – die Kennzahl, mit der E-Autos
gern beworben werden (keine Oelwechsel, kaum Bremsverschleiss dank Rekuperation).
Die km kommen aus den Monatswerten der Seite Fahrten. Stammen dort noch km vom
Vorgaengerfahrzeug, drueckt das den Wert – beim Fahrzeugwechsel die Fahrten ueber
„Messdaten zuruecksetzen“ leeren.

Beides ist ein eigener Wert ohne Benziner-Vergleich – dafuer fehlen realistische
Referenzdaten. Es fliesst deshalb auch nicht in die Ersparnis auf dem Dashboard ein.
"""
from datetime import date

import database as db

KATEGORIEN = ["Inspektion / Wartung", "Reifen", "Bremsen", "Verschleißteile", "Reparatur",
              "HU / AU", "Pflege", "Sonstiges"]

DECKUNGEN = ["Haftpflicht", "Teilkasko", "Vollkasko"]

# Zusatzbausteine der Versicherung: (Spalte, Anzeigename)
ZUSATZ = [("fahrerschutz", "Fahrerschutz"),
          ("werkstattbindung", "Werkstattbindung"),
          ("auslandsschutz", "Auslandsschutz"),
          ("schutzbrief", "Schutzbrief"),
          ("sonstige_zusatz", "Sonstiges")]


def _je_100km(kosten, km):
    return kosten / km * 100 if km and km > 0 else None


# ── Instandhaltung ───────────────────────────────────────────────────────────

def instandhaltung_daten() -> dict:
    eintraege = db.get_instandhaltung()
    km_monat = {f["monat"]: f["km"] or 0 for f in db.get_fahrten_monate()}
    km_gesamt = sum(km_monat.values())
    kosten_gesamt = sum(e["betrag"] for e in eintraege)

    # Je Jahr: alle Jahre mit km oder Kosten
    jahre = sorted({m[:4] for m in km_monat} | {e["datum"][:4] for e in eintraege},
                   reverse=True)
    jahreswerte = []
    for j in jahre:
        kosten = sum(e["betrag"] for e in eintraege if e["datum"][:4] == j)
        km = sum(v for m, v in km_monat.items() if m[:4] == j)
        jahreswerte.append({"jahr": j, "anzahl": sum(1 for e in eintraege if e["datum"][:4] == j),
                            "kosten": kosten, "km": km, "je_100km": _je_100km(kosten, km)})

    kategorien = []
    for k in {e["kategorie"] for e in eintraege}:
        summe = sum(e["betrag"] for e in eintraege if e["kategorie"] == k)
        kategorien.append({"kategorie": k, "kosten": summe,
                           "anteil": summe / kosten_gesamt * 100 if kosten_gesamt else 0,
                           "je_100km": _je_100km(summe, km_gesamt)})
    kategorien.sort(key=lambda k: k["kosten"], reverse=True)

    return {
        "eintraege": eintraege,
        "jahre": jahreswerte,
        "kategorien": kategorien,
        "kosten_gesamt": kosten_gesamt,
        "km_gesamt": km_gesamt,
        "je_100km": _je_100km(kosten_gesamt, km_gesamt),
    }


# ── Versicherung ─────────────────────────────────────────────────────────────

def jahresbeitrag(v: dict) -> float:
    """Grundbeitrag plus alle gebuchten Zusatzbausteine, €/Jahr."""
    return (v["grundbeitrag"] or 0) + sum(v[k] or 0 for k, _ in ZUSATZ)


def _ist_aktiv(v: dict, heute: str) -> bool:
    return v["gueltig_ab"] <= heute and (not v["gueltig_bis"] or v["gueltig_bis"] >= heute)


def km_letzte_12_monate() -> tuple:
    """(km, Anzahl Monate mit Werten) der letzten zwoelf abgeschlossenen Monate –
    zum Abgleich mit der vereinbarten Jahreslaufleistung."""
    heute = date.today()
    j, m = heute.year, heute.month
    monate = []
    for _ in range(12):
        j, m = (j, m - 1) if m > 1 else (j - 1, 12)
        monate.append(f"{j}-{m:02d}")
    km = {f["monat"]: f["km"] or 0 for f in db.get_fahrten_monate()}
    vorhanden = [km[x] for x in monate if x in km]
    return sum(vorhanden), len(vorhanden)


def versicherung_daten() -> dict:
    heute = date.today().strftime("%Y-%m-%d")
    liste = db.get_versicherungen()
    km_12, monate_12 = km_letzte_12_monate()
    # Auf ein Jahr hochgerechnet, falls noch nicht zwoelf Monate erfasst sind
    km_jahr = km_12 / monate_12 * 12 if monate_12 else None

    # Aenderung zum Vorgaenger desselben Fahrzeugs (aelteste zuerst durchlaufen)
    letzter = {}
    for v in sorted(liste, key=lambda v: (v["fahrzeug"], v["gueltig_ab"])):
        v["gesamt"] = jahresbeitrag(v)
        v["zusatz"] = [(name, v[k]) for k, name in ZUSATZ if v[k] is not None]
        vorher = letzter.get(v["fahrzeug"])
        v["diff"] = None if vorher is None else round(v["gesamt"] - vorher["gesamt"], 2)
        v["aktiv"] = _ist_aktiv(v, heute)
        letzter[v["fahrzeug"]] = v

    # Je Fahrzeug der heute gueltige Vertrag (bei Ueberschneidung der juengste)
    aktuell = {}
    for v in liste:
        if v["aktiv"] and (v["fahrzeug"] not in aktuell
                           or v["gueltig_ab"] > aktuell[v["fahrzeug"]]["gueltig_ab"]):
            aktuell[v["fahrzeug"]] = v

    return {
        "eintraege": sorted(liste, key=lambda v: (v["fahrzeug"], v["gueltig_ab"]), reverse=True),
        "aktuell": sorted(aktuell.values(), key=lambda v: v["fahrzeug"]),
        "km_jahr": km_jahr,
        "km_monate": monate_12,
        "fahrzeuge": sorted({v["fahrzeug"] for v in liste}),
        "gesellschaften": sorted({v["gesellschaft"] for v in liste}),
    }
