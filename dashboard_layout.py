# -*- coding: utf-8 -*-
"""
Anordnung des Dashboards: welche Abschnitte, Kacheln und Diagramme in welcher
Reihenfolge sichtbar sind und welche Diagramme die volle Breite nutzen.

Gespeichert als JSON in der Einstellung "dashboard_layout" – eine Anordnung fuer die
ganze App (nicht je Fahrzeug). Ohne Eintrag gilt der Standard: genau das Dashboard
wie vor 3.4. Neue Elemente einer spaeteren Version werden hinten angehaengt, die
zusaetzlichen sind anfangs ausgeblendet.
"""
import json

import database as db

SCHLUESSEL = "dashboard_layout"

# (id, im Standard sichtbar) in Standard-Reihenfolge
BEREICHE = [("kacheln", True), ("amortisation", True), ("je_fahrzeug", True),
            ("abo", False), ("diagramme", True)]
KACHELN = [("strecke", True), ("energie", True), ("ersparnis_kraft", True),
           ("steuer", True), ("thg", True), ("co2", True),
           ("ersparnis_gesamt", False), ("ladevorgaenge", False), ("stromkosten", False),
           ("verbrenner_kosten", False), ("verbrauch", False), ("strompreis", False),
           ("kosten_100km", False), ("ersparnis_100km", False), ("pv_anteil", False)]
DIAGRAMME = [("monatlich", True), ("kosten", True), ("co2", True), ("verbrauch", True),
             ("benzin", True), ("strom", True), ("anbieter", True), ("strommix", True),
             ("thg", True)]
GRUPPEN = {"bereiche": BEREICHE, "kacheln": KACHELN, "diagramme": DIAGRAMME}


def standard() -> dict:
    return {g: [{"id": i, "an": an, "breit": False} for i, an in liste]
            for g, liste in GRUPPEN.items()}


def bereinigen(roh) -> dict:
    """Gespeicherte oder gesendete Anordnung -> gueltige Anordnung: unbekannte und
    doppelte Eintraege fallen weg, fehlende kommen mit ihrem Standard hinten dazu."""
    roh = roh if isinstance(roh, dict) else {}
    ergebnis = {}
    for gruppe, liste in GRUPPEN.items():
        bekannt = dict(liste)
        eintraege, gesehen = [], set()
        for e in roh.get(gruppe) or []:
            if not isinstance(e, dict) or e.get("id") not in bekannt or e["id"] in gesehen:
                continue
            gesehen.add(e["id"])
            eintraege.append({"id": e["id"], "an": bool(e.get("an", True)),
                              "breit": bool(e.get("breit", False))})
        eintraege += [{"id": i, "an": an, "breit": False}
                      for i, an in liste if i not in gesehen]
        ergebnis[gruppe] = eintraege
    return ergebnis


def laden() -> dict:
    roh = db.get_einstellung_str(SCHLUESSEL)
    if not roh:
        return standard()
    try:
        return bereinigen(json.loads(roh))
    except ValueError:
        return standard()


def speichern(roh) -> dict:
    layout = bereinigen(roh)
    db.set_einstellung(SCHLUESSEL, json.dumps(layout, separators=(",", ":")))
    return layout


def zuruecksetzen():
    db.set_einstellung(SCHLUESSEL, "")
