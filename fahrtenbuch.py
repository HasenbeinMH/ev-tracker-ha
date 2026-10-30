# -*- coding: utf-8 -*-
"""
Fahrtenbuch: einzelne Fahrten mit Beginn, Ende, Start, Ziel, km und Verbrauch.

Quellen (je Fahrzeug unter Einstellungen → Sensoren):
  - Kilometerstand und Akkustand (wie fuer Akkuverbrauch) aus der HA-Historie (Recorder,
    volle Aufloesung, etwa 10 Tage)
  - optional Motor/Zuendung (binary_sensor) – zeigt, wann das Auto stand
  - Standort: device_tracker des Autos, des Handys oder person.* – das Add-on schreibt ihn
    selbst mit (ort_schleife, jede Minute), weil der Recorder device_tracker oft nicht
    aufnimmt. Liefert der Recorder doch einen Verlauf, wird er mitgenutzt.

Erkennung (fahrten()):
  1. Bewegung: der km-Stand steigt (ein Wert hoeher als der vorige) bzw. der Motor laeuft.
  2. Zwei Bewegungen gehoeren zur selben Fahrt, solange dazwischen kein Stillstand von
     mindestens `pause_min` Minuten belegt ist: Motor aus bzw. Handy/Auto am selben Ort.
     Ohne solche Belege trennt erst eine Luecke von pause_min + TAKT_MIN (ein Abfragetakt
     Spielraum – viele Autos melden nur alle 30 Minuten).
  3. Beginn/Ende: erste/letzte Bewegung, erweitert um "Motor an/aus"; mit Standort
     verfeinert – Abfahrt ist die erste Position, die sich vom Startort entfernt, Ankunft
     die erste, ab der sich nichts mehr bewegt.
  4. Start/Ziel: letzter Ort vor Beginn, erster Ort nach Ende; in einer HA-Zone deren Name.

Die Genauigkeit haengt am Abfragetakt des Autos: Meldet es nur alle 30 Minuten, sind Beginn
und Ende ohne Handy-Standort nur auf etwa eine halbe Stunde genau. Kein Fahrtenbuch fuers
Finanzamt (dafuer muessten Eintraege unveraenderbar sein und Zweck/Geschaeftspartner haben).
"""
import math
import threading
import time
from datetime import datetime, timedelta

import database as db
from i18n import _, N_

PAUSE_STANDARD = 30.0       # Minuten Stillstand, ab denen eine neue Fahrt beginnt
MIN_KM_STANDARD = 0.5
TAKT_MIN = 30.0             # Spielraum, wenn nichts den Stillstand belegt
ORT_RADIUS_M = 200.0        # weiter weg = abgefahren
STILL_RADIUS_M = 150.0      # innerhalb = steht
VERFEINERN_MIN = 40.0       # so weit vor Beginn/Ende wird mit dem Standort verfeinert
NACHT_TAGE = 3              # der naechtliche Lauf rechnet diese Tage neu
MAX_TAGE = 10               # weiter reicht der Recorder meist nicht
ORT_TAKT_S = 60             # Mitschnitt des Standorts
ORT_TAGE = 30               # so lange bleibt der Mitschnitt
KATEGORIEN = {"privat": N_("privat"), "arbeitsweg": N_("Arbeitsweg"),
              "dienstlich": N_("dienstlich")}
_FMT = "%Y-%m-%dT%H:%M"


def _t(text: str) -> datetime:
    return datetime.strptime(text[:16], _FMT)


def _s(t: datetime) -> str:
    return t.strftime(_FMT)


def abstand_m(a, b) -> float:
    """Entfernung zweier (lat, lon) in Metern (Haversine)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(h))


def einstellungen() -> dict:
    pause = db.get_einstellung("fahrt_pause_min")
    min_km = db.get_einstellung("fahrt_min_km")
    return {"pause_min": pause if pause and pause > 0 else PAUSE_STANDARD,
            "min_km": min_km if min_km is not None and min_km >= 0 else MIN_KM_STANDARD,
            "adressen": db.get_einstellung_str("fahrt_adressen") == "1"}


# ── Erkennung ────────────────────────────────────────────────────────────────

def ort_takt(orte: list) -> float:
    """Wie oft der Standort waehrend der Fahrt meldet (Minuten): Median der Abstaende
    zwischen Positionen, die auseinanderliegen – Handy oft 1–5, Auto oft 30. Ohne solche
    Paare TAKT_MIN."""
    abstaende = sorted((_t(b["zeit"]) - _t(a["zeit"])).total_seconds() / 60
                       for a, b in zip(orte, orte[1:])
                       if abstand_m((a["lat"], a["lon"]), (b["lat"], b["lon"])) > STILL_RADIUS_M)
    abstaende = [x for x in abstaende if 0 < x <= 60]
    if not abstaende:
        return TAKT_MIN
    return min(TAKT_MIN, max(1.0, abstaende[len(abstaende) // 2]))


def _stillstand(orte: list, motor: list, bewegt: list = ()) -> list:
    """Belegte Stillstaende [(von, bis)], bis=None = offen bis zur naechsten Bewegung.

    Motor: jede Phase "aus". Standort: gespeichert wird nur eine Aenderung – eine Position
    gilt also bis zur naechsten. Liegt die naechste am selben Ort, stand das Auto die ganze
    Zeit; liegt sie woanders, fuhr es irgendwann dazwischen los – dann zaehlt die Zeit bis
    einen Meldetakt des Standorts (ort_takt) vor der naechsten Position. Hat das Auto in dieser Zeit
    km gemeldet (`bewegt`: Zeiten der Bewegungen), stand es nicht – der Abschnitt faellt weg."""
    erg = []
    for (t, an), nxt in zip(motor, motor[1:] + [None]):
        if not an:
            erg.append((t, nxt[0] if nxt else None))
    takt = ort_takt(orte)
    for o, nxt in zip(orte, orte[1:] + [None]):
        if nxt is None:
            erg.append((o["zeit"], None))
        elif abstand_m((o["lat"], o["lon"]), (nxt["lat"], nxt["lon"])) <= STILL_RADIUS_M:
            erg.append((o["zeit"], nxt["zeit"]))
        else:
            bis = _s(_t(nxt["zeit"]) - timedelta(minutes=takt))
            # eine km-Meldung bei t heisst: bewegt irgendwann in [t − Takt, t]
            frei_ab = _s(_t(o["zeit"]) + timedelta(minutes=TAKT_MIN))
            if bis > o["zeit"] and not any(frei_ab < t < bis for t in bewegt):
                erg.append((o["zeit"], bis))
    return erg


def _getrennt(a: str, b: str, still: list, pause_min: float, belegt: bool) -> bool:
    """Liegt zwischen zwei Bewegungen (Zeiten a < b) ein Stillstand >= pause_min?"""
    for von, bis in still:
        # offen: bis zur naechsten Bewegung, abzueglich eines Abfragetakts (die erste
        # km-Aenderung meldet das Auto erst nach der Abfahrt)
        bis = bis or _s(_t(b) - timedelta(minutes=TAKT_MIN))
        von_c, bis_c = max(von, a), min(bis, b)
        if bis_c > von_c and (_t(bis_c) - _t(von_c)).total_seconds() / 60 >= pause_min:
            return True
    if belegt:
        return False
    return (_t(b) - _t(a)).total_seconds() / 60 > pause_min + TAKT_MIN


def _ort_vor(orte: list, zeit: str):
    vorher = [o for o in orte if o["zeit"] <= zeit]
    return vorher[-1] if vorher else None


def _ort_nach(orte: list, zeit: str, minuten: float = 60):
    grenze = _s(_t(zeit) + timedelta(minutes=minuten))
    nachher = [o for o in orte if zeit <= o["zeit"] <= grenze]
    return nachher[0] if nachher else _ort_vor(orte, zeit)


def _wert_bei(verlauf: list, zeit: str, nach: bool = False):
    """Letzter Wert bis `zeit` (nach=True: erster Wert ab `zeit`, sonst letzter davor)."""
    if nach:
        for t, v in verlauf:
            if t >= zeit:
                return v
    vorher = [v for t, v in verlauf if t <= zeit]
    return vorher[-1] if vorher else None


def _verfeinern(start: str, ende: str, orte: list) -> tuple:
    """Beginn und Ende mit den Positionen innerhalb von VERFEINERN_MIN verfeinern."""
    if not orte:
        return start, ende
    # Abfahrt: erste Position, die sich vom Ort zu Beginn des Fensters entfernt hat
    fenster = _s(_t(start) - timedelta(minutes=VERFEINERN_MIN))
    ab = _ort_vor(orte, fenster)
    if ab:
        weg = next((o for o in orte if fenster <= o["zeit"] <= start
                    and abstand_m((ab["lat"], ab["lon"]), (o["lat"], o["lon"])) > ORT_RADIUS_M), None)
        if weg:
            start = weg["zeit"]
    # Ankunft: erste Position, ab der sich bis kurz nach dem Ende nichts mehr bewegt
    von = max(start, _s(_t(ende) - timedelta(minutes=VERFEINERN_MIN)))
    rest = [o for o in orte if von <= o["zeit"] <= _s(_t(ende) + timedelta(minutes=5))]
    for i, o in enumerate(rest):
        if all(abstand_m((o["lat"], o["lon"]), (p["lat"], p["lon"])) <= STILL_RADIUS_M
               for p in rest[i:]):
            if o["zeit"] < ende:
                ende = o["zeit"]
            break
    return start, max(ende, start)


def fahrten(km: list, soc: list = (), orte: list = (), motor: list = (),
            pause_min: float = PAUSE_STANDARD, min_km: float = MIN_KM_STANDARD,
            kapazitaet: float | None = None) -> list:
    """Erkennt Fahrten. km/soc: [(zeit 'YYYY-MM-DDTHH:MM', wert)], motor: [(zeit, an?)],
    orte: [{zeit, lat, lon, zone}] – alles aufsteigend. Rueckgabe: [{start, ende, km_start,
    km_ende, km, soc_start, soc_ende, kwh, start_lat, …, ziel_ort}]."""
    km, soc, orte, motor = list(km), list(soc), list(orte), list(motor)
    # Bewegungen: (zeit, km davor, km danach)
    bew = []
    for (t0, k0), (t1, k1) in zip(km, km[1:]):
        if k1 > k0 + 0.05:
            bew.append((t1, k0, k1))
    for (t, an), nxt in zip(motor, motor[1:] + [None]):
        if an:
            k = _wert_bei(km, t)
            bew.append((t, k, k))
            if nxt:
                k2 = _wert_bei(km, nxt[0])
                bew.append((nxt[0], k2, k2))
    if not bew:
        return []
    bew.sort()
    still = _stillstand(orte, motor, [b[0] for b in bew if b[2] != b[1]])
    belegt = bool(motor) or bool(orte)

    gruppen, aktuell = [], [bew[0]]
    for b in bew[1:]:
        if _getrennt(aktuell[-1][0], b[0], still, pause_min, belegt):
            gruppen.append(aktuell)
            aktuell = [b]
        else:
            aktuell.append(b)
    gruppen.append(aktuell)

    erg = []
    for g in gruppen:
        kms = [x for x in g if x[1] is not None]
        if not kms:
            continue
        k_start = min(x[1] for x in kms)
        k_ende = max(x[2] for x in kms)
        if k_ende - k_start < min_km:
            continue
        start, ende = g[0][0], g[-1][0]
        # Ohne eigenen Beleg: die erste km-Aenderung kommt erst NACH der Abfahrt
        start, ende = _verfeinern(start, ende, orte)
        s_a, s_e = _wert_bei(soc, start), _wert_bei(soc, ende, nach=True)
        kwh = ((s_a - s_e) / 100 * kapazitaet
               if kapazitaet and s_a is not None and s_e is not None and s_a > s_e else None)
        # Startort: letzte Position vor der Abfahrt (die bei `start` ist schon unterwegs)
        o_a = _ort_vor([o for o in orte if o["zeit"] < start], start) or _ort_vor(orte, start)
        o_z = _ort_nach(orte, ende)
        erg.append({
            "start": start, "ende": ende,
            "km_start": round(k_start, 1), "km_ende": round(k_ende, 1),
            "km": round(k_ende - k_start, 1),
            "soc_start": s_a, "soc_ende": s_e, "kwh": round(kwh, 2) if kwh else None,
            "start_lat": o_a["lat"] if o_a else None, "start_lon": o_a["lon"] if o_a else None,
            "start_ort": o_a.get("zone") if o_a else None,
            "ziel_lat": o_z["lat"] if o_z else None, "ziel_lon": o_z["lon"] if o_z else None,
            "ziel_ort": o_z.get("zone") if o_z else None,
        })
    return erg


# ── Daten aus Home Assistant ─────────────────────────────────────────────────

def _zeit_lokal(text: str) -> str:
    t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    return _s(t.astimezone().replace(tzinfo=None) if t.tzinfo else t)


def _zahl_verlauf(zustaende: list) -> list:
    erg = []
    for z in zustaende:
        try:
            erg.append((_zeit_lokal(z.get("last_changed") or z.get("last_updated")),
                        float(z.get("state"))))
        except (TypeError, ValueError):
            continue
    return erg


def _an_verlauf(zustaende: list) -> list:
    erg = []
    for z in zustaende:
        st = str(z.get("state", "")).lower()
        if st in ("on", "off", "true", "false"):
            try:
                erg.append((_zeit_lokal(z.get("last_changed") or z.get("last_updated")),
                            st in ("on", "true")))
            except ValueError:
                continue
    return erg


ZONE_LEER = {"not_home", "unknown", "unavailable", ""}


def ort_aus_zustand(z: dict) -> dict | None:
    """{lat, lon, zone} aus einem device_tracker/person-Zustand – None ohne Koordinaten."""
    a = (z or {}).get("attributes") or {}
    try:
        lat, lon = float(a["latitude"]), float(a["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    zone = str(z.get("state") or "")
    zone = None if zone.lower() in ZONE_LEER else zone      # "home" erst in ort_text uebersetzt
    return {"lat": lat, "lon": lon, "zone": zone}


def _client():
    from ha_client import HAClient, ha_verbindung
    verbindung = ha_verbindung(db.get_ha_settings())
    return HAClient(**verbindung) if verbindung else None


def _entity(key: str, alle: bool = False):
    import datenquellen
    namen = datenquellen.namen_liste(db.get_ha_settings().get(key))
    return namen if alle else (namen[-1] if namen else "")


def aktualisieren(tage: int = NACHT_TAGE) -> str:
    """Fahrten der letzten `tage` Tage des aktuellen Fahrzeugs neu erkennen und speichern."""
    client = _client()
    km_entity = _entity("ha_odometer")
    if client is None or not km_entity:
        return _("Fahrtenbuch: Home Assistant oder Kilometerstand fehlt")
    jetzt = datetime.now()
    ab = (jetzt - timedelta(days=min(tage, MAX_TAGE))).replace(hour=3, minute=0, second=0,
                                                                microsecond=0)
    km = _zahl_verlauf(client.get_history_full(km_entity, ab, jetzt, attribute=False))
    soc_entity = _entity("ha_ev_battery")
    soc = _zahl_verlauf(client.get_history_full(soc_entity, ab, jetzt, attribute=False)) if soc_entity else []
    motor_entity = _entity("ha_ev_fahrt")
    motor = _an_verlauf(client.get_history_full(motor_entity, ab, jetzt, attribute=False)) if motor_entity else []
    # Standort: eigener Mitschnitt, ergaenzt um den Recorder (falls er ihn aufnimmt)
    orte = {o["zeit"]: o for o in db.get_orte(_s(ab))}
    for entity in _entity("ha_ev_ort", alle=True):
        for z in client.get_history_full(entity, ab, jetzt):
            o = ort_aus_zustand(z)
            if o:
                try:
                    orte.setdefault(_zeit_lokal(z.get("last_updated") or z.get("last_changed")),
                                    o | {"zeit": _zeit_lokal(z.get("last_updated") or z.get("last_changed"))})
                except ValueError:
                    continue
    e = einstellungen()
    import akku
    erkannt = fahrten(km, soc, sorted(orte.values(), key=lambda o: o["zeit"]), motor,
                      e["pause_min"], e["min_km"], akku.kapazitaet())
    # Die erste Bewegung im Fenster kann zu einer Fahrt von davor gehoeren – erst ab
    # einer Stunde nach Fensterbeginn ersetzen
    grenze = _s(ab + timedelta(hours=1))
    erkannt = [f for f in erkannt if f["start"] >= grenze]
    if e["adressen"]:
        adressen_ergaenzen(erkannt)
    db.ersetze_fahrten(grenze, erkannt)
    return _("Fahrtenbuch: {0} Fahrt(en) seit {1}", len(erkannt), ab.strftime("%d.%m."))


# ── Adressen (optional, OpenStreetMap/Nominatim) ─────────────────────────────

_letzte_anfrage = [0.0]


def adresse(lat: float, lon: float) -> str | None:
    """Adresse zu einer Position ueber Nominatim – hoechstens 1 Anfrage je Sekunde,
    Ergebnisse je auf ~10 m gerundeter Position zwischengespeichert."""
    import json
    import urllib.parse
    import urllib.request
    schluessel = f"adresse:{lat:.4f},{lon:.4f}"
    gemerkt = db.get_einstellung_str(schluessel)
    if gemerkt is not None:
        return gemerkt or None
    warten = 1.1 - (time.time() - _letzte_anfrage[0])
    if warten > 0:
        time.sleep(warten)
    _letzte_anfrage[0] = time.time()
    url = ("https://nominatim.openstreetmap.org/reverse?format=jsonv2&zoom=17&"
           + urllib.parse.urlencode({"lat": f"{lat:.5f}", "lon": f"{lon:.5f}"}))
    req = urllib.request.Request(url, headers={"User-Agent": "EV-Tracker (Home Assistant add-on)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            daten = json.loads(r.read().decode())
    except Exception:
        return None
    a = daten.get("address") or {}
    strasse = " ".join(x for x in (a.get("road"), a.get("house_number")) if x)
    ort = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or ""
    text = ", ".join(x for x in (strasse, ort) if x) or daten.get("display_name", "")[:80]
    db.set_einstellung(schluessel, text)
    return text or None


def adressen_ergaenzen(liste: list):
    for f in liste:
        for p in ("start", "ziel"):
            if not f.get(f"{p}_ort") and f.get(f"{p}_lat") is not None:
                f[f"{p}_ort"] = adresse(f[f"{p}_lat"], f[f"{p}_lon"])


# ── Standort mitschreiben ────────────────────────────────────────────────────

def ort_merken(fahrzeug_id: int, client) -> bool:
    """Liest den Standort eines Fahrzeugs und speichert ihn, wenn er sich geaendert hat.
    Bei mehreren Entities (mit "|") gilt die erste mit Koordinaten."""
    with db.fahrzeug_kontext(fahrzeug_id):
        for entity in _entity("ha_ev_ort", alle=True):
            o = ort_aus_zustand(client.get_state_full(entity))
            if not o:
                continue
            letzter = db.letzter_ort()
            if (letzter and letzter.get("zone") == o["zone"]
                    and abstand_m((letzter["lat"], letzter["lon"]), (o["lat"], o["lon"])) < 25):
                return False
            db.add_ort(_s(datetime.now()), o["lat"], o["lon"], o["zone"])
            return True
    return False


def ort_schleife():
    """Hintergrund-Thread: Standort jede Minute mitschreiben, solange das Modul an ist."""
    import module
    aufgeraeumt = 0.0
    while True:
        time.sleep(ORT_TAKT_S)
        try:
            if db.SCHEMA_ZU_NEU or not module.an("fahrtenbuch"):
                continue
            client = _client()
            if client is None:
                continue
            for fz in db.fahrzeuge(alle=True):
                ort_merken(fz["id"], client)
            if time.time() - aufgeraeumt > 3600:
                db.orte_aufraeumen(_s(datetime.now() - timedelta(days=ORT_TAGE)))
                aufgeraeumt = time.time()
        except Exception as e:
            print(f"[Fahrtenbuch] Standort: {e}", flush=True)


def starten():
    threading.Thread(target=ort_schleife, daemon=True).start()


# ── Auswertung ───────────────────────────────────────────────────────────────

def ort_text(f: dict, p: str) -> str:
    """Ort fuer die Anzeige: Zone/Adresse, sonst Koordinaten."""
    if f.get(f"{p}_ort"):
        return _("Zuhause") if f[f"{p}_ort"] == "home" else f[f"{p}_ort"]
    if f.get(f"{p}_lat") is not None:
        return f"{f[f'{p}_lat']:.4f}, {f[f'{p}_lon']:.4f}"
    return "–"


def profil(liste: list) -> dict | None:
    """Fahrprofil aus Fahrten: je Tag, Laengen, Abfahrtszeiten, haeufigste Ziele."""
    if not liste:
        return None
    klassen = [(N_("unter 5 km"), 5), ("5–20 km", 20), ("20–50 km", 50), ("50–100 km", 100),
               (N_("über 100 km"), None)]
    zaehler = [0] * len(klassen)
    for f in liste:
        for i, (_text, bis) in enumerate(klassen):
            if bis is None or f["km"] < bis:
                zaehler[i] += 1
                break
    stunden = [0] * 24
    for f in liste:
        stunden[int(f["start"][11:13])] += 1
    ziele = {}
    for f in liste:
        name = ort_text(f, "ziel")
        if name != "–":
            ziele[name] = ziele.get(name, 0) + 1
    tage = len({f["start"][:10] for f in liste})
    km = [f["km"] for f in liste]
    return {"fahrten": len(liste), "tage": tage, "je_tag": len(liste) / tage if tage else None,
            "km_schnitt": sum(km) / len(km), "kurz_anteil": zaehler[0] / len(liste) * 100,
            "klassen": [(t, n) for (t, _b), n in zip(klassen, zaehler)], "stunden": stunden,
            "ziele": sorted(ziele.items(), key=lambda x: -x[1])[:8]}


def csv_text(liste: list) -> str:
    """Fahrten als CSV (Semikolon, deutsche Zahlen) fuer Tabellenkalkulationen."""
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow([_("Beginn"), _("Ende"), _("Start"), _("Ziel"), _("km"), _("km-Stand Beginn"),
                _("km-Stand Ende"), _("Akku Beginn %"), _("Akku Ende %"), _("kWh"),
                _("Kategorie"), _("Notiz")])
    zahl = lambda v, n=1: "" if v is None else f"{v:.{n}f}".replace(".", ",")
    for f in liste:
        w.writerow([f["start"].replace("T", " "), f["ende"].replace("T", " "),
                    ort_text(f, "start"), ort_text(f, "ziel"), zahl(f["km"]),
                    zahl(f["km_start"]), zahl(f["km_ende"]), zahl(f["soc_start"], 0),
                    zahl(f["soc_ende"], 0), zahl(f["kwh"], 2),
                    _(KATEGORIEN.get(f.get("kategorie") or "", "")) if f.get("kategorie") else "",
                    f.get("notiz") or ""])
    return out.getvalue()
