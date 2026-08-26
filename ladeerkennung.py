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


def _client():
    cfg = db.get_ha_settings()
    if not (cfg.get("ha_url") and cfg.get("ha_token")):
        return None, cfg
    from ha_client import HAClient
    return HAClient(cfg["ha_url"], cfg["ha_token"]), cfg


def batterie_verlauf(jahr: int, monat: int) -> list:
    """Stündlicher Verlauf des Batteriestands als [(zeitstempel, prozent), ...].
    Nutzt die Langzeitstatistik, fällt auf die History-API zurück."""
    client, cfg = _client()
    entity = (cfg.get("ha_ev_battery") or "").strip()
    if client is None or not entity:
        return []

    letzter = calendar.monthrange(jahr, monat)[1]
    start = datetime(jahr, monat, 1)
    ende = datetime(jahr, monat, letzter, 23, 59, 59)

    verlauf = []
    try:
        stats = client._get_statistics([entity], start, ende, period="hour")
        for r in stats.get(entity, []):
            wert = r.get("mean")
            if wert is None:
                wert = r.get("state")
            if wert is not None:
                verlauf.append((str(r.get("start", ""))[:16], float(wert)))
    except Exception:
        verlauf = []

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
    Rückgabe: [{"datum", "von_prozent", "bis_prozent", "kwh"}]"""
    if len(verlauf) < 2:
        return []

    ladungen = []
    start_wert = None
    start_zeit = None
    letzter_wert = verlauf[0][1]

    for zeit, wert in verlauf[1:]:
        if wert > letzter_wert + 0.5:          # Anstieg: Ladung läuft
            if start_wert is None:
                start_wert, start_zeit = letzter_wert, zeit
        elif start_wert is not None and wert < letzter_wert - 0.5:
            # Anstieg beendet (Verbrauch beginnt) – Ladung abschließen
            anstieg = letzter_wert - start_wert
            if anstieg >= min_anstieg:
                ladungen.append({
                    "datum": start_zeit[:10],
                    "von_prozent": round(start_wert, 1),
                    "bis_prozent": round(letzter_wert, 1),
                    "kwh": round(anstieg / 100 * kapazitaet_kwh, 1),
                })
            start_wert, start_zeit = None, None
        letzter_wert = wert

    # Noch laufende Ladung am Ende des Zeitraums
    if start_wert is not None:
        anstieg = letzter_wert - start_wert
        if anstieg >= min_anstieg:
            ladungen.append({
                "datum": start_zeit[:10],
                "von_prozent": round(start_wert, 1),
                "bis_prozent": round(letzter_wert, 1),
                "kwh": round(anstieg / 100 * kapazitaet_kwh, 1),
            })
    return ladungen


def _tage_abstand(a: str, b: str) -> int:
    try:
        return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).days)
    except ValueError:
        return 999


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
    offen = list(erfasst)
    fehlend = []
    for ladung in erkannt:
        treffer = next((e for e in offen
                        if _tage_abstand(e["datum"], ladung["datum"]) <= TOLERANZ_TAGE),
                       None)
        if treffer:
            offen.remove(treffer)          # jeden Beleg nur einmal zuordnen
        else:
            fehlend.append(ladung)

    if fehlend:
        summe = sum(f["kwh"] for f in fehlend)
        meldung = (f"{len(fehlend)} Ladevorgang(e) erkannt, aber nicht erfasst "
                   f"(~{summe:.0f} kWh) – vermutlich auswärts geladen.")
        status = "fehlend"
    else:
        meldung = f"Alle {len(erkannt)} erkannten Ladevorgänge sind erfasst."
        status = "ok"

    return {"status": status, "erkannt": erkannt, "fehlend": fehlend,
            "meldung": meldung, "kapazitaet": kapazitaet}
