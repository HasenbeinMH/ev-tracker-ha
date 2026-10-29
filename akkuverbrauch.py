# -*- coding: utf-8 -*-
"""
Verbrauch aus dem Akkustand: zerlegt den Batterieverlauf (Home Assistant) in
Fahrtabschnitte zwischen zwei Ladungen und rechnet je Abschnitt

    kWh  = (Akku am Start − Akku am Ende) [%] ÷ 100 × Akkukapazitaet
    km   = Kilometerstand am Ende − Kilometerstand am Start
    Verbrauch = kWh ÷ km × 100

Anders als der Verbrauch aus den Ladungen (geladene kWh ÷ km) enthaelt dieser
Wert keine Ladeverluste – er zeigt, was tatsaechlich aus dem Akku kam, inklusive
Standverbrauch (Vorklimatisieren, 12-V-Batterie) zwischen den Fahrten.

Grundlage sind die stuendlichen Langzeitstatistiken von HA; der Akkustand ist
der Stundenmittelwert. Das macht einzelne Abschnitte um etwa ±1 % Akku
(±0,6 kWh) ungenau – bei kurzen Strecken faellt das stark ins Gewicht, daher
zaehlen Abschnitte unter MIN_KM nicht in die Monatswerte.

Als Ladung zaehlt erst ein Anstieg um "Mindestanstieg Ladung" (Einstellungen,
Standard 5 Prozentpunkte) – dieselbe Schwelle wie in der Ladeerkennung.
Kleinere Zwischenladungen trennen den Abschnitt also nicht, gehen dafuer aber
auch nicht in seine kWh ein; der Verbrauch faellt dann etwas zu niedrig aus.
"""
from datetime import datetime, timedelta

import database as db
from i18n import _

# Anstieg, ab dem ein Ladevorgang angenommen wird (Prozentpunkte). Rueckfall,
# wenn in den Einstellungen nichts steht – dort heisst er "lade_min_anstieg"
# und gilt gemeinsam mit der Ladeerkennung (siehe ladeerkennung.MIN_ANSTIEG).
# Kleinere Anstiege sind beim Stundenmittel meist Rauschen und wuerden einen
# Fahrtabschnitt grundlos in lauter Ein-Prozent-Schnipsel zerlegen.
LADE_SCHWELLE = 5.0
# Schwankung des Stundenmittels, die noch keine Richtungsaenderung ist
RAUSCHEN = 0.5
# Abschnitte mit weniger km sind zu ungenau fuer Monatswerte
MIN_KM = 5.0
# Der naechtliche Lauf berechnet diesen Zeitraum neu
TAGE_NACHTLAUF = 45
# Mehr km an einem Tag sind ein Messfehler (Tages-km fuer das Nutzungsprofil)
MAX_TAG_KM = 2000.0


def _stundenwerte(client, entity: str, start: datetime, ende: datetime,
                  felder: tuple) -> list:
    """Stundenwerte aus der HA-Langzeitstatistik als [(zeit 'YYYY-MM-DDTHH:MM', wert), ...].
    `felder` gibt die Reihenfolge an, in der Statistik-Felder genutzt werden."""
    stats = client._get_statistics([entity], start, ende, period="hour")
    werte = []
    for r in stats.get(entity, []):
        for feld in felder:
            wert = r.get(feld)
            if wert is not None:
                werte.append((str(r.get("start", ""))[:16], float(wert)))
                break
    werte.sort(key=lambda x: x[0])
    return werte


def verlaeufe(start: datetime, ende: datetime, mit_km: bool = True) -> dict:
    """Stuendlicher Akkustand (und Kilometerstand) aus der eingestellten Datenquelle.

    Ist eine Datenbank gewaehlt (InfluxDB, PostgreSQL, Prometheus – siehe
    datenquellen.py) und sind die Sensoren dort eingetragen, kommt der Verlauf
    von dort; sonst – oder wenn sie nichts liefert – aus der Langzeitstatistik
    der HA-API. Rueckgabe: {"soc", "km", "quelle", "meldung"}.
    """
    import datenquellen
    cfg = db.get_ha_settings()
    hinweise = []

    try:
        dq = datenquellen.aus_einstellungen(cfg)
    except Exception as e:
        dq = None
        hinweise.append(_("{0} nicht nutzbar ({1})", datenquellen.QUELLEN.get(cfg.get('datasource')), e))
    if dq is not None:
        if dq.hat("soc") and (dq.hat("km") or not mit_km):
            try:
                soc = dq.stundenwerte("soc", start, ende, "mean")
                km = dq.stundenwerte("km", start, ende, "last") if mit_km else []
                if soc and (km or not mit_km):
                    return {"soc": soc, "km": km, "quelle": dq.name, "meldung": ""}
                hinweise.append(_("{0} lieferte keine Werte für den Batteriestand", dq.name) if not soc
                                else _("{0} lieferte keine Werte für den Kilometerstand", dq.name))
            except Exception as e:
                hinweise.append(_("{0} nicht erreichbar ({1})", dq.name, e))
        else:
            spalte = "Entity-ID" if dq.nutzt_entity_ids else "Friendly Name"
            hinweise.append(_("{0} für Batteriestand oder Kilometerstand fehlt ({1})", spalte, dq.name))

    from ha_client import HAClient, ha_verbindung
    verbindung = ha_verbindung(cfg)
    if verbindung is None:
        hinweise.append(_("Home Assistant ist nicht konfiguriert"))
        return {"soc": [], "km": [], "quelle": None, "meldung": "; ".join(hinweise)}
    # Bei mehreren Entity-IDs ("alt | neu") gilt fuer HA die aktuelle, also die letzte
    soc_entity = (datenquellen.namen_liste(cfg.get("ha_ev_battery")) or [""])[-1]
    km_entity = (datenquellen.namen_liste(cfg.get("ha_odometer")) or [""])[-1]
    if not soc_entity or (mit_km and not km_entity):
        hinweise.append(_("Entity-ID für Batteriestand oder Kilometerstand fehlt"))
        return {"soc": [], "km": [], "quelle": None, "meldung": "; ".join(hinweise)}

    client = HAClient(**verbindung)
    soc = _stundenwerte(client, soc_entity, start, ende, ("mean", "state"))
    km = _stundenwerte(client, km_entity, start, ende, ("state", "mean")) if mit_km else []
    if not soc:
        hinweise.append(_("keine Statistikdaten für den Batteriestand in HA"))
    elif mit_km and not km:
        hinweise.append(_("keine Statistikdaten für den Kilometerstand in HA"))
    return {"soc": soc, "km": km, "quelle": "Home Assistant",
            "meldung": "; ".join(hinweise)}


def _km_bei(km_verlauf: list, zeit: str):
    """Letzter bekannter Kilometerstand bis einschliesslich `zeit`.
    Das Auto meldet nur, wenn es online ist – Luecken werden so ueberbrueckt."""
    treffer = None
    for t, km in km_verlauf:
        if t > zeit:
            break
        treffer = km
    if treffer is None and km_verlauf:
        # Vor dem ersten Messwert: den ersten nehmen
        treffer = km_verlauf[0][1]
    return treffer


def berechne_abschnitte(soc_verlauf: list, km_verlauf: list, kapazitaet: float,
                        lade_schwelle: float = LADE_SCHWELLE) -> list:
    """Zerlegt den Akkuverlauf in Abschnitte ohne Ladung.

    Ein Abschnitt beginnt am Hoechststand nach einer Ladung und endet am
    Tiefststand vor der naechsten. Der erste Abschnitt ist "angeschnitten",
    wenn der Verlauf mitten in einem Abschnitt beginnt; der letzte ist
    "laufend", wenn danach noch keine Ladung kam.

    `lade_schwelle` ist der Anstieg in Prozentpunkten, ab dem eine Ladung
    angenommen wird – nicht je Stunde, sondern seit dem Tiefststand: eine
    Ladung ueber mehrere Stunden zaehlt so als eine einzige.
    """
    if len(soc_verlauf) < 2 or not km_verlauf:
        return []

    abschnitte = []
    start = soc_verlauf[0]        # Beginn des offenen Abschnitts (Hoechststand)
    tief = soc_verlauf[0]         # tiefster Punkt seither – Kandidat fuers Ende
    gipfel = None                 # hoechster Punkt einer laufenden Ladung
    angeschnitten = True          # vor dem ersten Punkt wissen wir nichts

    def abschliessen(anfang, schluss, laufend):
        km_a = _km_bei(km_verlauf, anfang[0])
        km_e = _km_bei(km_verlauf, schluss[0])
        if km_a is None or km_e is None:
            return
        abschnitte.append({
            "start": anfang[0], "ende": schluss[0],
            "soc_start": round(anfang[1], 1), "soc_ende": round(schluss[1], 1),
            "km_start": round(km_a, 1), "km_ende": round(km_e, 1),
            "kwh": round((anfang[1] - schluss[1]) / 100 * kapazitaet, 2),
            "km": round(km_e - km_a, 1),
            "laufend": 1 if laufend else 0,
            "angeschnitten": angeschnitten,
        })

    for punkt in soc_verlauf[1:]:
        if gipfel is None:
            # Fahrtabschnitt laeuft: Tiefststand mitfuehren und auf eine Ladung warten
            if punkt[1] <= tief[1]:
                tief = punkt
            elif punkt[1] >= tief[1] + lade_schwelle:
                # Gemessen ab dem Tiefststand, nicht von Stunde zu Stunde – eine
                # ueber Nacht schleichende AC-Ladung wird so ebenfalls erkannt.
                if tief[0] > start[0]:
                    abschliessen(start, tief, laufend=False)
                angeschnitten = False
                gipfel = punkt
        else:
            # Ladung laeuft: Hoechststand suchen, dort beginnt der naechste Abschnitt
            if punkt[1] >= gipfel[1]:
                gipfel = punkt
            elif punkt[1] < gipfel[1] - RAUSCHEN:
                start, tief, gipfel = gipfel, punkt, None

    if gipfel is None and tief[0] > start[0]:
        abschliessen(start, tief, laufend=True)
    return abschnitte


def aktualisieren(tage: int | None = TAGE_NACHTLAUF) -> str:
    """Holt Akku- und Kilometerverlauf und speichert die Abschnitte.

    tage=None rechnet die gesamte Historie neu (ab dem ersten erfassten
    Fahrtenmonat), sonst nur die letzten `tage` Tage. Rueckgabe: Kurzmeldung.
    """
    # Werte des aktuellen Fahrzeugs (bei mehreren Fahrzeugen je Auto eigene)
    cfg_alle = db.get_mail_settings()
    try:
        kapazitaet = float(cfg_alle.get("akku_kapazitaet_kwh") or 58.3)
    except ValueError:
        kapazitaet = 58.3
    try:
        lade_schwelle = float(cfg_alle.get("lade_min_anstieg") or LADE_SCHWELLE)
    except ValueError:
        lade_schwelle = LADE_SCHWELLE

    ende = datetime.now()
    if tage is None:
        monate = [f["monat"] for f in db.get_fahrten_monate()]
        erster = min(monate) if monate else f"{ende.year - 1}-{ende.month:02d}"
        start = datetime.strptime(erster + "-01", "%Y-%m-%d")
    else:
        start = ende - timedelta(days=tage)

    v = verlaeufe(start, ende)
    # Beginnt der Verlauf erst deutlich nach dem Fensterbeginn, gab es vorher keine
    # Werte (Auto neu in HA) – dann ist der erste Wert wirklich der Anfang
    von_anfang = tage is None or (
        bool(v["soc"]) and v["soc"][0][0] > (start + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"))
    if v["soc"]:
        _staende_speichern(monatsstaende(v["soc"], von_anfang))
    tage_km = tages_km(v["km"])
    if tage_km:
        db.ersetze_fahrten_tag(None if tage is None else min(tage_km), tage_km)
    if not v["soc"] or not v["km"]:
        return _("Keine Daten: {0}", v["meldung"] or _("Batterie- oder Kilometerverlauf leer"))

    abschnitte = berechne_abschnitte(v["soc"], v["km"], kapazitaet, lade_schwelle)
    if not von_anfang:
        # Der angeschnittene erste Abschnitt steht vollstaendig schon in der DB
        abschnitte = [a for a in abschnitte if not a["angeschnitten"]]
    if not abschnitte:
        return _("Keine abgeschlossenen Fahrtabschnitte im Zeitraum (Quelle: {0})", v['quelle'])

    ab = None if tage is None else abschnitte[0]["start"]
    db.ersetze_akku_abschnitte(ab, abschnitte)
    gesamt_km = sum(a["km"] for a in abschnitte)
    return _("{0} Fahrtabschnitt(e) aus dem Akkustand berechnet ({1} km, Quelle: {2})",
             len(abschnitte), f"{gesamt_km:.0f}", v['quelle'])


def tages_km(km_verlauf: list) -> dict:
    """Gefahrene km je Tag aus dem stuendlichen Kilometerstand: {'YYYY-MM-DD': km}.

    km eines Tages = letzter Stand des Tages − letzter Stand davor. Der erste Tag fehlt
    (kein Stand davor), Tage ohne Werte zaehlen 0 km – meldet das Auto erst spaeter
    wieder, landen die km am Tag des naechsten Werts. Ein Ruecksprung des Zaehlers oder
    mehr als MAX_TAG_KM gelten als Messfehler (0 km)."""
    letzte = {}
    for t, km in sorted(km_verlauf):
        letzte[t[:10]] = km
    if len(letzte) < 2:
        return {}
    tage = sorted(letzte)
    tag, ende = datetime.strptime(tage[0], "%Y-%m-%d"), datetime.strptime(tage[-1], "%Y-%m-%d")
    vorher = letzte[tage[0]]
    erg = {}
    while tag < ende:
        tag += timedelta(days=1)
        k = tag.strftime("%Y-%m-%d")
        if k not in letzte:
            erg[k] = 0.0
            continue
        diff = letzte[k] - vorher
        erg[k] = round(diff, 1) if 0 <= diff <= MAX_TAG_KM else 0.0
        vorher = letzte[k]
    return erg


def monatsstaende(soc_verlauf: list, von_anfang: bool) -> dict:
    """Akkustand am Anfang und Ende jedes Monats im Verlauf: {monat: [anfang, ende]}.

    Anfang ist der letzte Wert vor dem Monat; gibt es keinen, der erste im Monat –
    aber nur, wenn der Verlauf `von_anfang` vollstaendig ist (sonst None: der Stand
    zu Monatsbeginn liegt vor dem abgerufenen Fenster)."""
    staende = {}
    vorher = None
    for t, wert in soc_verlauf:
        m = t[:7]
        if m not in staende:
            staende[m] = [vorher if vorher is not None else (wert if von_anfang else None), wert]
        staende[m][1] = wert
        vorher = wert
    return staende


def _staende_speichern(neu: dict):
    """Mit den gespeicherten Monatsstaenden zusammenfuehren; ein unbekannter Anfang
    ueberschreibt keinen bekannten."""
    import json
    try:
        alt = json.loads(db.get_einstellung_str("akkustand_monate") or "{}")
    except ValueError:
        alt = {}
    for m, (anfang, ende) in neu.items():
        anfang = anfang if anfang is not None else (alt.get(m) or [None])[0]
        alt[m] = [None if anfang is None else round(anfang, 1), round(ende, 1)]
    db.set_einstellung("akkustand_monate", json.dumps(alt, sort_keys=True))


def entnahme_je_monat() -> dict:
    """kWh, die je Monat mehr aus dem Akku kamen als hineingeladen wurden:
    (Akkustand Anfang − Ende) ÷ 100 × Kapazitaet. Negativ, wenn der Akku am
    Monatsende voller ist. Damit wird "Verbrauch laut Wallbox/Ladesaeule" korrigiert – sonst
    zaehlt z. B. ein voll uebernommenes Auto, das erst spaeter geladen wird, zu wenig.
    In der Gesamtsicht mehrerer Fahrzeuge die Summe aller."""
    import json
    if db.aktuelles_fahrzeug() is None:
        summe = {}
        for fz in db.fahrzeuge():
            with db.fahrzeug_kontext(fz["id"]):
                for m, kwh in entnahme_je_monat().items():
                    summe[m] = summe.get(m, 0.0) + kwh
        return summe
    try:
        staende = json.loads(db.get_einstellung_str("akkustand_monate") or "{}")
        kapazitaet = float(db.get_einstellung("akku_kapazitaet_kwh") or 58.3)
    except ValueError:
        return {}
    return {m: (a - e) / 100 * kapazitaet for m, (a, e) in staende.items()
            if a is not None and e is not None}


def pro_monat() -> list:
    """Monatswerte aus den Abschnitten: [{monat, km, kwh, verbrauch}], aufsteigend.
    Zugeordnet nach dem Ende des Abschnitts; gewichtet ueber Σ kWh ÷ Σ km."""
    summen = {}
    for a in db.get_akku_abschnitte():
        if a["km"] < MIN_KM or a["kwh"] <= 0:
            continue
        m = summen.setdefault(a["ende"][:7], {"km": 0.0, "kwh": 0.0})
        m["km"] += a["km"]
        m["kwh"] += a["kwh"]
    return [{"monat": monat, "km": round(s["km"], 1), "kwh": round(s["kwh"], 2),
             "verbrauch": round(s["kwh"] / s["km"] * 100, 2)}
            for monat, s in sorted(summen.items()) if s["km"] > 0]
