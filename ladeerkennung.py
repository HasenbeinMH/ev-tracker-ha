# -*- coding: utf-8 -*-
"""
Erkennt Ladevorgänge am Verlauf des Batteriestands (Home Assistant) und
gleicht sie mit den in der Datenbank erfassten Ladevorgängen ab.

Zweck: feststellen, ob auswärts geladen wurde, ohne dass ein Beleg erfasst ist –
denn Ladungen zuhause kommen automatisch aus HA, auswärtige nicht.
"""
import calendar
from datetime import datetime

import database as db

# Ein Anstieg gilt ab dieser Höhe als Ladevorgang (Prozentpunkte)
MIN_ANSTIEG = 5.0
# Toleranz beim Datumsabgleich mit erfassten Ladevorgängen (Tage)
TOLERANZ_TAGE = 1
# Heimladungen: so viel duerfen die erkannten kWh ueber der erfassten Monatssumme liegen.
# Bewusst knapp – die Monatssumme ab Wallbox enthaelt schon die Ladeverluste (~10 %),
# die erkannten kWh aus dem Akkustand nicht. Mehr Spielraum wuerde fehlende Ladungen
# unterwegs verschlucken.
HEIM_TOLERANZ = 0.05


def _client():
    cfg = db.get_ha_settings()
    from ha_client import HAClient, ha_verbindung
    verbindung = ha_verbindung(cfg)
    if verbindung is None:
        return None, cfg
    return HAClient(**verbindung), cfg


def batterie_verlauf(jahr: int, monat: int) -> list:
    """Stündlicher Verlauf des Batteriestands als [(zeitstempel, prozent), ...].
    Nutzt die eingestellte Quelle (InfluxDB oder HA-Langzeitstatistik, siehe
    akkuverbrauch.verlaeufe) und fällt zuletzt auf die History-API zurück."""
    letzter = calendar.monthrange(jahr, monat)[1]
    start = datetime(jahr, monat, 1)
    ende = datetime(jahr, monat, letzter, 23, 59, 59)

    import akkuverbrauch
    try:
        verlauf = akkuverbrauch.verlaeufe(start, ende, mit_km=False)["soc"]
    except Exception:
        verlauf = []
    if verlauf:
        return verlauf

    client, cfg = _client()
    entity = (cfg.get("ha_ev_battery") or "").strip()
    if client is None or not entity:
        return []

    if not verlauf:
        try:
            for eintrag in client.get_history_period(entity, start, ende):
                try:
                    wert = float(eintrag.get("state", ""))
                except (TypeError, ValueError):
                    continue
                zeit = eintrag.get("last_changed") or eintrag.get("last_updated") or ""
                verlauf.append((str(zeit)[:16], wert))
        except Exception:
            return []

    verlauf.sort(key=lambda x: x[0])
    return verlauf


def erkenne_ladungen(verlauf: list, min_anstieg: float = MIN_ANSTIEG,
                     kapazitaet_kwh: float = 58.3) -> list:
    """Findet zusammenhängende Anstiege im Batterieverlauf.
    Rückgabe: [{"datum", "von_prozent", "bis_prozent", "kwh", "leistung_kw"}]

    leistung_kw ist die mittlere Ladeleistung (kWh ÷ Stunden vom letzten Wert vor
    dem Anstieg bis zum Höchststand) – bei Stundenwerten grob, reicht aber, um
    AC zuhause (≤ 11 kW) von einer Schnellladung zu unterscheiden."""
    if len(verlauf) < 2:
        return []

    ladungen = []
    start_wert = start_zeit = vor_zeit = ende_zeit = None
    letzte_zeit, letzter_wert = verlauf[0]

    def abschliessen(bis_wert):
        anstieg = bis_wert - start_wert
        if anstieg < min_anstieg:
            return
        kwh = round(anstieg / 100 * kapazitaet_kwh, 1)
        try:
            stunden = (datetime.fromisoformat(ende_zeit[:16])
                       - datetime.fromisoformat(vor_zeit[:16])).total_seconds() / 3600
        except ValueError:
            stunden = 0
        ladungen.append({
            "datum": start_zeit[:10],
            "von_prozent": round(start_wert, 1),
            "bis_prozent": round(bis_wert, 1),
            "kwh": kwh,
            "leistung_kw": round(kwh / stunden, 1) if stunden > 0 else None,
        })

    for zeit, wert in verlauf[1:]:
        if wert > letzter_wert + 0.5:          # Anstieg: Ladung läuft
            if start_wert is None:
                start_wert, start_zeit, vor_zeit = letzter_wert, zeit, letzte_zeit
            ende_zeit = zeit
        elif start_wert is not None and wert < letzter_wert - 0.5:
            # Anstieg beendet (Verbrauch beginnt) – Ladung abschließen
            abschliessen(letzter_wert)
            start_wert = start_zeit = vor_zeit = ende_zeit = None
        letzte_zeit, letzter_wert = zeit, wert

    # Noch laufende Ladung am Ende des Zeitraums
    if start_wert is not None:
        abschliessen(letzter_wert)
    return ladungen


def _tage_abstand(a: str, b: str) -> int:
    try:
        return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).days)
    except ValueError:
        return 999


def zuordnen(erkannt: list, erfasst: list) -> tuple:
    """Ordnet erkannte Ladungen den erfassten Ladevorgaengen eines Monats zu.

    1. Auswaerts: Belege mit Tagesdatum (alle Anbieter ausser „Privat …“) werden
       ueber das Datum (± TOLERANZ_TAGE) zugeordnet, jeder Beleg nur einmal.
    2. Zuhause: Heimladungen liegen meist nur als Monatssumme (am 1.) vor. Die
       uebrigen erkannten Ladungen werden gegen diese kWh verrechnet – die
       langsamsten zuerst (Wallbox ≤ 11 kW), denn nicht erfasste Ladungen unterwegs
       sind typischerweise Schnellladungen. Die Summe darf um HEIM_TOLERANZ ueberschritten
       werden (Akkukapazitaet und Stundenmittel machen die kWh-Schaetzung ungenau).
       Grenze: Eine fehlende Ladung, die kleiner ist als die Ladeverluste zuhause,
       faellt nicht auf.

    Rueckgabe: (fehlend, anzahl_zuhause).
    """
    import berechnung
    heim_kwh = sum(e["menge_kwh"] or 0 for e in erfasst
                   if berechnung.stromquelle(e["anbieter"]) != berechnung.OEFFENTLICH)
    offen = [e for e in erfasst
             if berechnung.stromquelle(e["anbieter"]) == berechnung.OEFFENTLICH]

    rest = []
    for ladung in erkannt:
        treffer = next((e for e in offen
                        if _tage_abstand(e["datum"], ladung["datum"]) <= TOLERANZ_TAGE),
                       None)
        if treffer:
            offen.remove(treffer)          # jeden Beleg nur einmal zuordnen
        else:
            rest.append(ladung)

    budget = heim_kwh * (1 + HEIM_TOLERANZ)
    fehlend, zuhause = [], 0
    # Ohne bekannte Leistung ans Ende der Reihe (eher unterwegs als zuhause)
    for ladung in sorted(rest, key=lambda l: (l.get("leistung_kw") or 999, l["kwh"])):
        if ladung["kwh"] <= budget:
            budget -= ladung["kwh"]
            zuhause += 1
        else:
            fehlend.append(ladung)
    fehlend.sort(key=lambda l: l["datum"])
    return fehlend, zuhause


def pruefe_monat(jahr: int, monat: int) -> dict:
    """Gleicht erkannte Ladungen mit den erfassten Ladevorgängen ab.

    status:
      "ok"        – alle erkannten Ladungen sind erfasst
      "fehlend"   – es fehlen Ladevorgänge (vermutlich auswärts geladen)
      "unbekannt" – keine Batteriedaten verfügbar, keine Aussage möglich
    """
    cfg_alle = db.get_alle_einstellungen()
    try:
        kapazitaet = float(cfg_alle.get("akku_kapazitaet_kwh") or 58.3)
    except ValueError:
        kapazitaet = 58.3
    try:
        min_anstieg = float(cfg_alle.get("lade_min_anstieg") or MIN_ANSTIEG)
    except ValueError:
        min_anstieg = MIN_ANSTIEG

    verlauf = batterie_verlauf(jahr, monat)
    if not verlauf:
        return {"status": "unbekannt", "erkannt": [], "fehlend": [],
                "meldung": "Keine Batteriedaten aus Home Assistant verfügbar."}

    erkannt = erkenne_ladungen(verlauf, min_anstieg, kapazitaet)

    letzter = calendar.monthrange(jahr, monat)[1]
    erfasst = db.get_ladevorgaenge_zeitraum(f"{jahr}-{monat:02d}-01",
                                            f"{jahr}-{monat:02d}-{letzter:02d}")
    fehlend, zuhause = zuordnen(erkannt, erfasst)

    if fehlend:
        summe = sum(f["kwh"] for f in fehlend)
        meldung = (f"{len(fehlend)} Ladevorgang(e) erkannt, aber nicht erfasst "
                   f"(~{summe:.0f} kWh) – vermutlich auswärts geladen.")
        status = "fehlend"
    else:
        meldung = f"Alle {len(erkannt)} erkannten Ladevorgänge sind erfasst"
        meldung += f" (davon {zuhause} zuhause)." if zuhause else "."
        status = "ok"

    return {"status": status, "erkannt": erkannt, "fehlend": fehlend,
            "meldung": meldung, "kapazitaet": kapazitaet}
