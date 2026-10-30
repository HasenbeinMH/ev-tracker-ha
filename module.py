# -*- coding: utf-8 -*-
"""
Module: Zusatzauswertungen, die jeder fuer sich ein- und ausschaltet (Einstellungen →
Module). Gilt fuer die ganze App, nicht je Fahrzeug; Sensoren und Daten bleiben je Fahrzeug.

Ein ausgeschaltetes Modul verschwindet aus Menue, Dashboard (Kacheln, Bereiche, Diagramme),
Einstellungen, Bericht und naechtlichem Abruf; seine Seiten leiten auf die Einstellungen
um. Gespeicherte Daten bleiben erhalten – nach dem Einschalten ist alles wieder da.

Gespeichert als JSON in der Einstellung "module" ({id: true/false}). Ohne Eintrag gilt der
Standard: Akku und Profil an (seit 3.8.0 da), Leasing an, wenn ein Vertrag eingetragen ist,
Energie an, wenn eine Tagesstatistik eingetragen ist, Fahrtenbuch aus.
"""
import json

import database as db
from i18n import N_

SCHLUESSEL = "module"

# id -> Beschriftung, Beschreibung und was zum Modul gehoert: Seiten (Menue-Schluessel bzw.
# Routen), Dashboard-Elemente und Sensorzeilen in den Einstellungen
MODULE = {
    "akku": {
        "name": N_("Akku"),
        "beschreibung": N_("Akku-Gesundheit (SoH), Ladezyklen, Ladefenster und Reichweite."),
        "seiten": ["akku"], "kacheln": ["soh", "reichweite", "zyklen"],
        "bereiche": [], "diagramme": [], "sensoren": ["ha_ev_range", "ha_ev_soh"],
    },
    "profil": {
        "name": N_("Profil"),
        "beschreibung": N_("Wie du fährst und lädst: km je Wochentag, Tage nach Strecke, Ladezeiten, Entwicklung über die Jahre."),
        "seiten": ["profil"], "kacheln": [], "bereiche": [], "diagramme": [], "sensoren": [],
    },
    "leasing": {
        "name": N_("Leasing"),
        "beschreibung": N_("Leasing-Kilometer: Soll gegen gefahren, Prognose bis Vertragsende, Mehr- oder Minder-km."),
        "seiten": [], "kacheln": [], "bereiche": ["leasing"], "diagramme": [], "sensoren": [],
    },
    "energie": {
        "name": N_("Energie"),
        "beschreibung": N_("Wofür die Energie gebraucht wird: Antrieb, Klima, Bordelektronik, Rekuperation – aus der täglichen Fahrstatistik des Autos (z. B. Kia/Hyundai)."),
        "seiten": ["energie"], "kacheln": ["klima_anteil", "bordcomputer"],
        "bereiche": [], "diagramme": ["energieaufteilung"], "sensoren": ["ha_ev_tagesstatistik"],
    },
    "fahrtenbuch": {
        "name": N_("Fahrtenbuch"),
        "beschreibung": N_("Einzelne Fahrten mit Start, Ziel, km und Verbrauch; das Profil wertet sie mit aus."),
        "seiten": ["fahrtenbuch"], "kacheln": [], "bereiche": [], "diagramme": [],
        "sensoren": ["ha_ev_ort", "ha_ev_fahrt"],
    },
}


def _gesetzt(alle: dict, key: str, wert=None) -> bool:
    """Ist die Fahrzeug-Einstellung `key` bei irgendeinem Fahrzeug gesetzt (bzw. = wert)?"""
    for k, v in alle.items():
        if k == key or k.startswith(key + "@"):
            if (v == wert) if wert is not None else bool((v or "").strip()):
                return True
    return False


def standard(mid: str, alle: dict | None = None) -> bool:
    """Standard eines Moduls ohne gespeicherte Wahl."""
    if mid in ("akku", "profil"):
        return True
    alle = db.get_alle_einstellungen() if alle is None else alle
    if mid == "leasing":
        return _gesetzt(alle, "leasing_aktiv", "1")
    if mid == "energie":
        return _gesetzt(alle, "ha_ev_tagesstatistik")
    return False


def alle() -> dict:
    """{id: an?} aller Module."""
    einst = db.get_alle_einstellungen()
    try:
        gespeichert = json.loads(einst.get(SCHLUESSEL) or "{}")
    except ValueError:
        gespeichert = {}
    if not isinstance(gespeichert, dict):
        gespeichert = {}
    return {mid: bool(gespeichert[mid]) if mid in gespeichert else standard(mid, einst)
            for mid in MODULE}


def an(mid: str) -> bool:
    return alle().get(mid, False)


def speichern(wahl: dict):
    """Speichert die Wahl aller Module (unbekannte Schluessel fallen weg)."""
    db.set_einstellung(SCHLUESSEL, json.dumps({mid: bool(wahl.get(mid)) for mid in MODULE},
                                              sort_keys=True))


def seite_sichtbar(seite: str, zustand: dict | None = None) -> bool:
    """Gehoert die Seite (Menue-Schluessel) zu einem ausgeschalteten Modul?"""
    zustand = alle() if zustand is None else zustand
    return all(zustand[mid] for mid, m in MODULE.items() if seite in m["seiten"])


def menue(eintraege: list) -> list:
    """Menue-Eintraege (schluessel, url, text) ohne die Seiten ausgeschalteter Module."""
    zustand = alle()
    return [e for e in eintraege if seite_sichtbar(e[0], zustand)]


def ausgeblendet() -> set:
    """Dashboard-Elemente ausgeschalteter Module als {(gruppe, id)} – die Gruppe gehoert
    dazu, weil Kacheln und Diagramme gleiche ids haben koennen."""
    zustand = alle()
    return {(g, i) for mid, m in MODULE.items() if not zustand[mid]
            for g in ("kacheln", "bereiche", "diagramme") for i in m[g]}


def sensoren_aus() -> set:
    """Sensorzeilen der Einstellungen, die zu ausgeschalteten Modulen gehoeren."""
    zustand = alle()
    return {s for mid, m in MODULE.items() if not zustand[mid] for s in m["sensoren"]}


def sensor_modul(ha_key: str) -> str | None:
    """Zu welchem Modul eine Sensorzeile gehoert (None = Grundausstattung)."""
    return next((mid for mid, m in MODULE.items() if ha_key in m["sensoren"]), None)
