# -*- coding: utf-8 -*-
"""
Akku-Gesundheit, Ladezyklen und Reichweite eines Fahrzeugs.

Grundlage sind die Fahrtabschnitte aus dem Akkustand (akkuverbrauch.py) – zwischen
zwei Abschnitten liegt eine Ladung von "Akku am Ende" bis "Akku am Start des naechsten".
So ergeben sich Ladezyklen und Ladefenster ohne weitere Daten.

SoH (State of Health, nutzbare Kapazitaet im Verhaeltnis zum Neuzustand), drei Quellen –
gemessene Werte gehen immer vor:
  1. von Hand eingetragen (Werkstatt, OBD-App, Akku-Zertifikat; Tabelle soh_messung)
  2. Sensor aus Home Assistant (optional, Monatsmittel in der Einstellung soh_monate)
  3. geschaetzt aus Wallbox-kWh und Akkustand:

        Verlust_gemessen = 1 − Verbrauch laut Auto-Akku ÷ Verbrauch laut Wallbox/Saeule
        SoH = (1 − Verlust_Annahme) ÷ (1 − Verlust_gemessen)

     Der Verbrauch laut Auto-Akku rechnet mit der eingestellten (neuen) Kapazitaet. Hat der
     Akku weniger, ueberschaetzt er die kWh, und die gemessenen Ladeverluste fallen zu
     niedrig aus. Gealterter Akku und Ladeverluste lassen sich aus diesen Daten aber nicht
     trennen – die Schaetzung haengt an der Annahme fuer die Ladeverluste (Standard 10 %).
     Ein von Hand eingetragener Wert eicht die Annahme (kalibrieren()).

Die eingestellte Kapazitaet bleibt die Grundlage fuer Verbrauch und Ladeverluste – der
SoH ist nur Anzeige, damit sich nichts im Kreis rechnet.

Reichweite: Akku-Kapazitaet ÷ Verbrauch laut Auto-Akku × 100 ist dasselbe wie km je
Prozent Akku × 100 – die Kapazitaet kuerzt sich heraus. Der Akkustand des Autos bezieht
sich schon auf die heute nutzbare Kapazitaet, ein Abschlag fuer den SoH waere doppelt.
"""
import calendar
import json
from datetime import date, datetime, timedelta

import database as db
from i18n import _, N_

KAPAZITAET_STANDARD = 58.3
VERLUST_STANDARD = 10.0         # angenommene Ladeverluste in %, Einstellung akku_verlust_annahme
BAND = 5.0                      # Unsicherheit der Annahme (± Prozentpunkte)
BAND_KALIBRIERT = 2.0           # … nach einem von Hand eingetragenen Wert
FENSTER = 6                     # Monate je Schaetzwert (gleitend)
MIN_MONATE = 3                  # so viele Monate mit beiden Verbrauchswerten braucht ein Schaetzwert
SOH_MIN, SOH_MAX = 60.0, 110.0  # ausserhalb: Messfehler, kein Akku
VERLUST_MAX = 35.0              # wie zeitraum.LADEVERLUST_MAX
# Vergleichswert fuer die Alterung: Ø etwa 1,8 % je Jahr (Auswertung von rund 10.000
# E-Autos durch Geotab, 2024). Nur zur Einordnung, kein Mass fuer ein bestimmtes Auto.
REFERENZ_PRO_JAHR = 1.8
GARANTIE_STANDARD = {"jahre": 8.0, "km": 160000.0, "soh": 70.0}
VOLL = 95.0                     # "bis voll geladen"
TIEF = (20.0, 10.0)             # Ladung begann unter diesem Akkustand
KLASSEN = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 101)]
SOH_SENSOR_TAGE = 45            # der naechtliche Lauf holt den SoH-Sensor fuer diesen Zeitraum

QUELLEN = {"hand": N_("von Hand"), "sensor": N_("Sensor"), "geschaetzt": N_("geschätzt")}


def _zahl(key: str, standard: float) -> float:
    wert = db.get_einstellung(key)
    return standard if wert is None or wert <= 0 else wert


def kapazitaet() -> float:
    return _zahl("akku_kapazitaet_kwh", KAPAZITAET_STANDARD)


def verlust_annahme() -> float:
    wert = db.get_einstellung("akku_verlust_annahme")
    return VERLUST_STANDARD if wert is None or not 0 <= wert <= VERLUST_MAX else wert


def garantie() -> dict:
    return {k: _zahl(f"akku_garantie_{k}", v) for k, v in GARANTIE_STANDARD.items()}


def _monat_datum(monat: str) -> date:
    return date(int(monat[:4]), int(monat[5:7]), 15)


def _jahre(a: date, b: date) -> float:
    return (b - a).days / 365.25


# ── Ladungen und Zyklen ──────────────────────────────────────────────────────

def ladungen_aus_abschnitten(abschnitte: list) -> list:
    """Ladungen zwischen zwei aufeinanderfolgenden Fahrtabschnitten, aelteste zuerst:
    [{start, ende, von, bis, anstieg}]. start ist das Ende des Abschnitts davor (Tiefststand,
    stuendlich) – ungefaehr der Ladebeginn. Ladungen unter der Mindestschwelle der
    Abschnitte trennen keinen Abschnitt und fehlen deshalb hier."""
    liste = sorted(abschnitte, key=lambda a: a["start"])
    erg = []
    for a, b in zip(liste, liste[1:]):
        anstieg = b["soc_start"] - a["soc_ende"]
        if anstieg <= 0 or b["start"] < a["ende"]:
            continue
        erg.append({"start": a["ende"], "ende": b["start"], "von": a["soc_ende"],
                    "bis": b["soc_start"], "anstieg": round(anstieg, 1)})
    return erg


def _klasse(wert: float) -> int:
    for i, (u, o) in enumerate(KLASSEN):
        if u <= wert < o:
            return i
    return len(KLASSEN) - 1 if wert >= KLASSEN[-1][0] else 0


def zyklen(ladungen: list, lade_kwh_monat: dict | None = None, kap: float | None = None,
           verlust: float | None = None) -> dict:
    """Vollzyklen = Σ Akku-Anstiege ÷ 100. Monate vor der ersten Ladung aus dem Akkustand
    werden aus den geladenen kWh geschaetzt: kWh × (1 − Ladeverluste) ÷ Kapazitaet.

    lade_kwh_monat: {monat: kWh an Wallbox/Saeule}. Rueckgabe mit je_monat, je_jahr,
    Ladefenster (Ø von/bis, Anteile, Klassen) und der Herkunft."""
    kap = kap or kapazitaet()
    verlust = VERLUST_STANDARD if verlust is None else verlust
    je_monat = {}
    for l in ladungen:
        m = l["ende"][:7]
        je_monat[m] = je_monat.get(m, 0.0) + l["anstieg"] / 100
    erster = min(je_monat) if je_monat else None
    geschaetzt = 0
    for m, kwh in (lade_kwh_monat or {}).items():
        if kwh > 0 and (erster is None or m < erster):
            je_monat[m] = je_monat.get(m, 0.0) + kwh * (1 - verlust / 100) / kap
            geschaetzt += 1
    je_jahr = {}
    for m, z in je_monat.items():
        je_jahr[m[:4]] = je_jahr.get(m[:4], 0.0) + z

    anzahl = len(ladungen)
    von_klassen, bis_klassen = [0] * len(KLASSEN), [0] * len(KLASSEN)
    for l in ladungen:
        von_klassen[_klasse(l["von"])] += 1
        bis_klassen[_klasse(l["bis"])] += 1
    return {
        "vollzyklen": round(sum(je_monat.values()), 1),
        "je_monat": {m: round(z, 2) for m, z in sorted(je_monat.items())},
        "je_jahr": {j: round(z, 1) for j, z in sorted(je_jahr.items())},
        "ladungen": anzahl,
        "geschaetzte_monate": geschaetzt,
        "von_schnitt": sum(l["von"] for l in ladungen) / anzahl if anzahl else None,
        "bis_schnitt": sum(l["bis"] for l in ladungen) / anzahl if anzahl else None,
        "hub_schnitt": sum(l["anstieg"] for l in ladungen) / anzahl if anzahl else None,
        "anteil_voll": (sum(1 for l in ladungen if l["bis"] >= VOLL) / anzahl * 100
                        if anzahl else None),
        "anteil_tief": {g: sum(1 for l in ladungen if l["von"] < g) / anzahl * 100
                        for g in TIEF} if anzahl else {},
        "von_klassen": von_klassen,
        "bis_klassen": bis_klassen,
    }


# ── SoH ──────────────────────────────────────────────────────────────────────

def paare(monatswerte: list) -> list:
    """Monate mit beiden Verbrauchswerten (zeitraum.monatswerte): [{monat, km, kwh, akm, akwh}]."""
    return [{"monat": w["monat"], "km": w["km"], "kwh": w["_kwh_v"],
             "akm": w["km_akku"], "akwh": w["kwh_akku"]}
            for w in monatswerte
            if w["km"] and w.get("_kwh_v", 0) > 0 and w.get("km_akku") and w.get("kwh_akku")]


def _verlust(teil: list) -> float | None:
    """Gemessene Ladeverluste (0–1) ueber mehrere Monate, gewichtet ueber die Summen."""
    km, kwh = sum(p["km"] for p in teil), sum(p["kwh"] for p in teil)
    akm, akwh = sum(p["akm"] for p in teil), sum(p["akwh"] for p in teil)
    if not (km and kwh > 0 and akm and akwh > 0):
        return None
    return 1 - (akwh / akm) / (kwh / km)


def soh_aus_verlust(verlust: float, annahme: float) -> float:
    """SoH in % aus gemessenen Ladeverlusten (0–1) und der Annahme (in %)."""
    return (1 - annahme / 100) / (1 - verlust) * 100


def schaetzung(liste: list, annahme: float, band: float = BAND) -> list:
    """Geschaetzter SoH je Monat, gleitend ueber bis zu FENSTER Monate mit beiden Werten:
    [{monat, soh, unten, oben, monate}]. Werte ausserhalb SOH_MIN–SOH_MAX fallen weg."""
    erg = []
    for i in range(MIN_MONATE - 1, len(liste)):
        teil = liste[max(0, i - FENSTER + 1):i + 1]
        v = _verlust(teil)
        if v is None or v >= 1:
            continue
        soh = soh_aus_verlust(v, annahme)
        if not SOH_MIN <= soh <= SOH_MAX:
            continue
        erg.append({"monat": liste[i]["monat"], "soh": round(soh, 1),
                    "unten": round(soh_aus_verlust(v, min(annahme + band, 99)), 1),
                    "oben": round(soh_aus_verlust(v, max(annahme - band, 0)), 1),
                    "monate": len(teil)})
    return erg


def kalibrieren(liste: list, messungen: list) -> dict | None:
    """Verlust-Annahme aus dem neuesten von Hand eingetragenen SoH: so gewaehlt, dass die
    Schaetzung im Monat der Messung genau den gemessenen Wert trifft. Grundlage sind die
    FENSTER Monate bis zur Messung (sonst die ersten danach). None, wenn es zu wenige
    Monate gibt oder die Annahme keine plausiblen Ladeverluste ergaebe."""
    for m in sorted(messungen, key=lambda x: x["datum"], reverse=True):
        monat = m["datum"][:7]
        vorher = [p for p in liste if p["monat"] <= monat][-FENSTER:]
        teil = vorher if len(vorher) >= MIN_MONATE else [p for p in liste if p["monat"] > monat][:FENSTER]
        if len(teil) < MIN_MONATE:
            continue
        v = _verlust(teil)
        if v is None:
            continue
        annahme = (1 - m["soh"] / 100 * (1 - v)) * 100
        if 0 <= annahme <= VERLUST_MAX:
            return {"annahme": round(annahme, 1), "messung": m}
    return None


def sensor_monate() -> list:
    """Monatsmittel des SoH-Sensors: [{monat, soh}] aufsteigend."""
    try:
        werte = json.loads(db.get_einstellung_str("soh_monate") or "{}")
    except ValueError:
        return []
    return [{"monat": m, "soh": v} for m, v in sorted(werte.items()) if v is not None]


def _soh_verlauf(start: datetime, ende: datetime) -> tuple:
    """Stundenwerte des SoH-Sensors aus der eingestellten Datenquelle, sonst aus HA.
    Rueckgabe: (werte, quelle)."""
    import akkuverbrauch
    import datenquellen
    from ha_client import HAClient, ha_verbindung
    cfg = db.get_ha_settings()
    try:
        dq = datenquellen.aus_einstellungen(cfg)
    except Exception:
        dq = None
    if dq is not None and dq.hat("soh"):
        try:
            werte = dq.stundenwerte("soh", start, ende, "mean")
            if werte:
                return werte, dq.name
        except Exception:
            pass
    entity = (datenquellen.namen_liste(cfg.get("ha_ev_soh")) or [""])[-1]
    verbindung = ha_verbindung(cfg)
    if not entity or verbindung is None:
        return [], None
    werte = akkuverbrauch._stundenwerte(HAClient(**verbindung), entity, start, ende,
                                        ("mean", "state"))
    return werte, "Home Assistant"


def soh_monatsmittel(werte: list) -> dict:
    """{monat: Mittel} aus [(zeit, wert)] – nur plausible Werte."""
    summen = {}
    for t, v in werte:
        if SOH_MIN - 10 <= v <= SOH_MAX:
            s = summen.setdefault(t[:7], [0.0, 0])
            s[0] += v
            s[1] += 1
    return {m: round(s / n, 1) for m, (s, n) in summen.items()}


def soh_aktualisieren(tage: int | None = SOH_SENSOR_TAGE) -> str:
    """Holt den SoH-Sensor (falls eingetragen) und merkt sich die Monatsmittel.
    tage=None: gesamte Historie ab dem ersten Fahrtenmonat. Rueckgabe: Kurzmeldung, leer
    ohne Sensor."""
    cfg = db.get_ha_settings()
    if not (cfg.get("ha_ev_soh") or cfg.get("fn_ev_soh")):
        return ""
    ende = datetime.now()
    if tage is None:
        monate = [f["monat"] for f in db.get_fahrten_monate()]
        start = (datetime.strptime(min(monate) + "-01", "%Y-%m-%d") if monate
                 else ende - timedelta(days=365))
    else:
        start = ende - timedelta(days=tage)
    werte, quelle = _soh_verlauf(start, ende)
    neu = soh_monatsmittel(werte)
    if not neu:
        return _("SoH-Sensor: keine Werte")
    try:
        alt = json.loads(db.get_einstellung_str("soh_monate") or "{}")
    except ValueError:
        alt = {}
    alt.update(neu)
    db.set_einstellung("soh_monate", json.dumps(alt, sort_keys=True))
    return _("SoH-Sensor: {0} Monat(e) aus {1}", len(neu), quelle)


def trend(punkte: list) -> float | None:
    """Lineare Aenderung des SoH in Prozentpunkten je Jahr aus [(date, soh)] –
    erst ab zwei Punkten, die mindestens 90 Tage auseinanderliegen."""
    if len(punkte) < 2:
        return None
    t0 = min(d for d, _w in punkte)
    xs = [_jahre(t0, d) for d, _w in punkte]
    ys = [w for _d, w in punkte]
    if max(xs) - min(xs) < 90 / 365.25:
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    nenner = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / nenner if nenner else None


# ── Reichweite ───────────────────────────────────────────────────────────────

def reichweite_monate(akku_monate: list, kap: float) -> list:
    """Reichweite je Monat aus dem Verbrauch laut Auto-Akku (akkuverbrauch.pro_monat):
    [{monat, verbrauch, km_100, km_80_10}]. km_100 = Kapazitaet ÷ Verbrauch × 100,
    gleichbedeutend mit km je Prozent Akku × 100."""
    return [{"monat": a["monat"], "verbrauch": a["verbrauch"],
             "km_100": round(kap / a["verbrauch"] * 100),
             "km_80_10": round(kap / a["verbrauch"] * 100 * 0.7)}
            for a in akku_monate if a.get("verbrauch")]


def _monat_plus(monat: str, n: int) -> str:
    i = int(monat[:4]) * 12 + int(monat[5:7]) - 1 + n
    return f"{i // 12}-{i % 12 + 1:02d}"


def reichweite_prognose(rm: list, ab: str, anzahl: int = 12) -> list:
    """Reichweite der naechsten `anzahl` Monate ab `ab` ('YYYY-MM'): Ø desselben
    Kalendermonats aus den Vorjahren, sonst Ø aller Monate. [{monat, km_100, basis}]."""
    if not rm:
        return []
    alle = sum(r["km_100"] for r in rm) / len(rm)
    erg = []
    for i in range(anzahl):
        m = _monat_plus(ab, i)
        gleich = [r["km_100"] for r in rm if r["monat"][5:7] == m[5:7]]
        erg.append({"monat": m, "km_100": round(sum(gleich) / len(gleich) if gleich else alle),
                    "basis": "monat" if gleich else "schnitt"})
    return erg


def saison(rm: list) -> dict:
    """Ø Reichweite im Sommer (Jun–Aug) und Winter (Dez–Feb) – None ohne Monate."""
    def schnitt(monate):
        werte = [r["km_100"] for r in rm if int(r["monat"][5:7]) in monate]
        return round(sum(werte) / len(werte)) if werte else None
    return {"sommer": schnitt((6, 7, 8)), "winter": schnitt((12, 1, 2))}


# ── km-Stand ─────────────────────────────────────────────────────────────────

def km_stand(abschnitte: list | None = None) -> float | None:
    """Aktueller Kilometerstand: der hoehere aus dem letzten Fahrtabschnitt und aus km bei
    Kauf plus den Monats-km seit dem Kauf – so bleibt er aktuell, auch wenn der Akkustand
    eine Weile fehlt. None ohne Daten."""
    abschnitte = db.get_akku_abschnitte(limit=1) if abschnitte is None else abschnitte
    aus_akku = max((a["km_ende"] for a in abschnitte), default=None)
    kauf = db.get_ha_settings()["kauf_monat"]
    fahrten = [f for f in db.get_fahrten_alle_als_liste() if f["datum"][:7] >= kauf]
    summe = ((db.get_einstellung("km_bei_kauf") or 0.0) + sum(f["km"] for f in fahrten)
             if fahrten else None)
    werte = [w for w in (aus_akku, summe) if w is not None]
    return max(werte) if werte else None


def km_pro_tag(fahrten: list | None = None, monate: int = 12) -> float | None:
    """Ø km je Tag der letzten `monate` Monate mit km (ohne den laufenden Monat)."""
    fahrten = db.get_fahrten_alle_als_liste() if fahrten is None else fahrten
    jetzt = date.today().strftime("%Y-%m")
    liste = sorted((f for f in fahrten if f["datum"][:7] < jetzt and f["km"] > 0),
                   key=lambda f: f["datum"])[-monate:]
    tage = sum(calendar.monthrange(int(f["datum"][:4]), int(f["datum"][5:7]))[1] for f in liste)
    return sum(f["km"] for f in liste) / tage if tage else None


# ── Gesamtauswertung ─────────────────────────────────────────────────────────

def auswertung(heute: date | None = None) -> dict:
    """Alles fuer die Akku-Seite und die Dashboard-Kacheln – fuer das aktuelle Fahrzeug
    (in der Gesamtsicht je Fahrzeug mit db.fahrzeug_kontext aufrufen)."""
    import akkuverbrauch
    import zeitraum
    heute = heute or date.today()
    kap = kapazitaet()
    g = garantie()
    abschnitte = db.get_akku_abschnitte()
    ladungen = ladungen_aus_abschnitten(abschnitte)

    daten = zeitraum.laden()
    werte = zeitraum.monatswerte(zeitraum.aufloesen(zeitraum.ALLES), daten)
    liste = paare(werte)
    lade_kwh = {w["monat"]: w["kwh"] for w in werte if w["kwh"]}

    # SoH: Annahme (geeicht durch einen von Hand eingetragenen Wert), Schaetzung, Messwerte
    messungen = db.get_soh_messungen()
    sensor = sensor_monate()
    annahme = verlust_annahme()
    kal = kalibrieren(liste, messungen)
    band = BAND
    if kal:
        annahme, band = kal["annahme"], BAND_KALIBRIERT
    geschaetzt = schaetzung(liste, annahme, band)

    gemessen = ([(m["datum"], float(m["soh"]), "hand") for m in messungen]
                + [(s["monat"] + "-15", float(s["soh"]), "sensor") for s in sensor])
    gemessen.sort()
    if gemessen:
        datum, wert, quelle = gemessen[-1]
        soh = {"wert": wert, "quelle": quelle, "datum": datum, "band": None}
    elif geschaetzt:
        s = geschaetzt[-1]
        soh = {"wert": s["soh"], "quelle": "geschaetzt", "datum": s["monat"],
               "band": (s["unten"], s["oben"])}
    else:
        soh = None

    # Alterung: aus Messwerten, sonst aus der Schaetzung
    punkte = [(date.fromisoformat(d[:10]), w) for d, w, _q in gemessen]
    trend_quelle = "gemessen"
    jahrestrend = trend(punkte)
    if jahrestrend is None:
        punkte = [(_monat_datum(s["monat"]), s["soh"]) for s in geschaetzt]
        jahrestrend = trend(punkte)
        trend_quelle = "geschaetzt"
    if jahrestrend is None:
        trend_quelle = None

    ez = zeitraum.erstzulassung()
    beginn = date.fromisoformat(ez) if ez else None
    referenz = None
    if beginn:
        referenz = {"beginn": ez,
                    "heute": round(100 - REFERENZ_PRO_JAHR * max(0.0, _jahre(beginn, heute)), 1)}

    # Garantie: Ende nach Jahren ab Erstzulassung oder bei Erreichen der km – was zuerst kommt
    stand = km_stand(abschnitte)
    je_tag = km_pro_tag(daten["fahrten"])
    prognose = None
    if beginn and soh:
        ende = date(beginn.year + int(g["jahre"]), beginn.month, min(beginn.day, 28))
        grund = "jahre"
        if stand is not None and je_tag:
            bis_km = heute + timedelta(days=max(0.0, (g["km"] - stand) / je_tag))
            if bis_km < ende:
                ende, grund = bis_km, "km"
        rate = jahrestrend if jahrestrend is not None and jahrestrend < 0 else -REFERENZ_PRO_JAHR
        ab = date.fromisoformat(soh["datum"][:10] if len(soh["datum"]) >= 10
                                else soh["datum"] + "-15")
        wert = soh["wert"] + rate * max(0.0, _jahre(ab, ende))
        prognose = {"ende": ende.isoformat(), "grund": grund, "soh": round(wert, 1),
                    "rate": rate, "aus_referenz": not (jahrestrend is not None and jahrestrend < 0),
                    "ok": wert >= g["soh"], "vorbei": ende <= heute}

    rm = reichweite_monate(akkuverbrauch.pro_monat(), kap)
    voraus = reichweite_prognose(rm, heute.strftime("%Y-%m"))
    return {
        "kapazitaet": kap,
        "soh": soh,
        "nutzbar": round(kap * soh["wert"] / 100, 1) if soh else None,
        "annahme": annahme,
        "annahme_eingestellt": verlust_annahme(),
        "kalibriert": kal,
        "band": band,
        "schaetzung": geschaetzt,
        "paare": len(liste),
        "sensor": sensor,
        "messungen": messungen,
        "trend": jahrestrend,
        "trend_quelle": trend_quelle,
        "referenz": referenz,
        "garantie": g,
        "prognose": prognose,
        "km_stand": stand,
        "km_pro_tag": je_tag,
        "ladungen": ladungen,
        "zyklen": zyklen(ladungen, lade_kwh, kap, annahme),
        "km_gesamt": sum(f["km"] for f in daten["fahrten"]),
        "reichweite": {"monate": rm, "prognose": voraus, "saison": saison(rm),
                       "jetzt": voraus[0]["km_100"] if voraus else None},
        "abschnitte": len(abschnitte),
    }


def live(reichweite_100: float | None) -> dict:
    """Akkustand und Reichweite laut Auto jetzt (Home Assistant), dazu die Reichweite aus
    dem Verbrauch. Leer ohne Verbindung oder Sensor."""
    import datenquellen
    from ha_client import HAClient, ha_verbindung
    cfg = db.get_ha_settings()
    verbindung = ha_verbindung(cfg)
    soc_entity = (datenquellen.namen_liste(cfg.get("ha_ev_battery")) or [""])[-1]
    if verbindung is None or not soc_entity:
        return {}
    try:
        client = HAClient(**verbindung)
        soc = client.get_current_state(soc_entity)
        range_entity = (datenquellen.namen_liste(cfg.get("ha_ev_range")) or [""])[-1]
        auto = client.get_current_state(range_entity) if range_entity else None
    except Exception:
        return {}
    if soc is None:
        return {}
    return {"soc": soc, "auto_km": auto,
            "km": round(soc / 100 * reichweite_100) if reichweite_100 else None}
