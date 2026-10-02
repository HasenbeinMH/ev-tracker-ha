# -*- coding: utf-8 -*-
"""
Einzelne Heimladungen, die Home Assistant am Ladeende schickt (POST /api/ladung).

HA misst mit denselben Zaehlern wie der Monatsimport (Netz ins Auto, PV ins Auto und
optional Kosten Netz ins Auto) und schickt je Ladung die Differenzen seit Ladebeginn.
Daraus werden bis zu zwei Ladevorgaenge mit Tagesdatum (Netz und PV).

Der Monatsimport legt danach nur noch den Rest an: Zaehlerwert des Monats minus die
geschickten Ladungen. So wird nichts doppelt gezaehlt, und eine Ladung, deren Senden
fehlschlug, fehlt nicht – sie steckt im Rest (mit dem Preis des Monats).

Dieselbe Ladung darf mehrfach ankommen: Kennung ist der Ladebeginn.
Vorlage fuer HA: vorlagen/homeassistant/ev_ladung_senden.yaml.
"""
import hmac
import re
import secrets
from datetime import datetime

import berechnung
import database as db

PV = "Privat – PV"
TOKEN_KEY = "push_token"
# Mehr passt in keinen Autoakku – vermutlich ein falscher Startwert in HA
MAX_KWH = 200.0
MAX_KOSTEN = 500.0
# Kleinere Reste der Monatssumme (Rundung, Standby der Wallbox) werden nicht gespeichert
MIN_REST_KWH = 0.5


class UngueltigeLadung(ValueError):
    pass


# ── Token ────────────────────────────────────────────────────────────────────

def token() -> str:
    return db.get_einstellung_str(TOKEN_KEY) or ""


def token_neu() -> str:
    t = secrets.token_urlsafe(24)
    db.set_einstellung(TOKEN_KEY, t)
    return t


def token_ok(gesendet: str | None) -> bool:
    t = token()
    return bool(t) and hmac.compare_digest(t.encode(), (gesendet or "").encode())


# ── Annehmen ─────────────────────────────────────────────────────────────────

def _zeit(wert, feld: str) -> datetime:
    """ISO-Zeit, mit oder ohne Zeitzone – gespeichert wird Ortszeit."""
    try:
        t = datetime.fromisoformat(str(wert).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise UngueltigeLadung(f"{feld}: keine gültige Zeit ({wert!r})") from None
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def _zahl(wert, feld: str, grenze: float, negativ: bool = False) -> float | None:
    if wert is None or (isinstance(wert, str) and wert.strip().lower() in ("", "none", "null",
                                                                            "unknown", "unavailable")):
        return None
    try:
        v = float(str(wert).replace(",", "."))
    except ValueError:
        raise UngueltigeLadung(f"{feld}: keine Zahl ({wert!r})") from None
    unten = -grenze if negativ else 0.0
    if v != v or not unten <= v <= grenze:
        raise UngueltigeLadung(f"{feld}: {v} liegt nicht zwischen {unten:g} und {grenze:g}")
    return v


def annehmen(daten: dict) -> dict:
    """Speichert eine Ladung aus HA. daten: start, ende (optional), kwh_netz, kwh_pv,
    kosten (optional, € fuer den Netzanteil). Wirft UngueltigeLadung."""
    if not isinstance(daten, dict):
        raise UngueltigeLadung("JSON-Objekt erwartet")
    start = _zeit(daten.get("start"), "start")
    ende = _zeit(daten["ende"], "ende") if daten.get("ende") else None
    if ende and ende < start:
        raise UngueltigeLadung("ende liegt vor start")
    netz = _zahl(daten.get("kwh_netz"), "kwh_netz", MAX_KWH) or 0.0
    pv = _zahl(daten.get("kwh_pv"), "kwh_pv", MAX_KWH) or 0.0
    kosten = _zahl(daten.get("kosten"), "kosten", MAX_KOSTEN, negativ=True)
    if netz + pv <= 0:
        raise UngueltigeLadung("keine Energie (kwh_netz und kwh_pv sind 0)")
    if netz + pv > MAX_KWH:
        raise UngueltigeLadung(f"{netz + pv:.1f} kWh in einer Ladung – mehr als {MAX_KWH:.0f}")

    fid = _fahrzeug(daten.get("fahrzeug"))
    datum = f"{start:%Y-%m-%d}"
    dauer_h = (ende - start).total_seconds() / 3600 if ende else 0
    leistung = round((netz + pv) / dauer_h, 1) if dauer_h > 0.05 else None
    zeit = f"{start:%H:%M}–{ende:%H:%M}" if ende else f"ab {start:%H:%M}"
    # Fahrzeug 1 behaelt die bisherige Kennung (erneutes Senden bleibt erkennbar)
    kennung = f"ha:{start:%Y-%m-%dT%H:%M}" + ("" if fid == 1 else f"@{fid}")
    tarife = db.get_stromtarife()
    pv_ct = db.get_einstellung("pv_preis_ct") or 13.0

    teile = []
    for teil, anbieter, kwh in (("netz", berechnung.NETZBEZUG, netz), ("pv", PV, pv)):
        if kwh <= 0:
            continue
        notiz, hinweis = f"{berechnung.PUSH_NOTIZ} {zeit}", None
        if teil == "netz":
            ct, gesamt, hinweis = berechnung.heimpreis(
                kwh, kosten, berechnung.netzpreis_tag(datum, tarife))
            if hinweis == berechnung.DYNAMISCH_NOTIZ:
                notiz += f" · {hinweis}"
                hinweis = None
        else:
            ct, gesamt = pv_ct, round(kwh * pv_ct / 100, 2)
        status, lid = db.upsert_extern_ladevorgang(
            f"{kennung}:{teil}", datum, round(kwh, 3), ct, gesamt, anbieter, leistung, notiz, fahrzeug_id=fid)
        teile.append({"teil": teil, "status": status, "id": lid, "kwh": round(kwh, 3),
                      "ct": ct, "gesamt": gesamt, "hinweis": hinweis})
    return {"ok": True, "datum": datum, "zeit": zeit, "teile": teile, "fahrzeug": fid}


def _fahrzeug(angabe) -> int:
    """Fahrzeug einer Push-Ladung: id oder Name; ohne Angabe das Hauptfahrzeug.
    Ein ausgeblendetes oder unbekanntes Fahrzeug wird abgelehnt – die Ladung soll nicht
    stillschweigend bei einem anderen Auto landen."""
    if angabe in (None, ""):
        return db.hauptfahrzeug()
    text = str(angabe).strip()
    # Home Assistant macht aus "2" eine Zahl (2 bzw. 2.0) – beides ist Fahrzeug 2
    if re.fullmatch(r"\d+\.0*", text):
        text = text.split(".")[0]
    alle = db.fahrzeuge(alle=True)
    fz = next((f for f in alle if str(f["id"]) == text or f["name"].casefold() == text.casefold()),
              None)
    if fz is None:
        raise UngueltigeLadung(f"Fahrzeug „{text}“ unbekannt")
    if fz["id"] not in db.sichtbare_ids():
        raise UngueltigeLadung(f"Fahrzeug „{fz['name']}“ ist ausgeblendet – Ladung nicht übernommen")
    return fz["id"]


def protokoll_text(e: dict) -> str:
    teile = ", ".join(f"{t['teil']} {t['kwh']:.2f} kWh × {t['ct']:.1f} ct = {t['gesamt']:.2f} € "
                      f"({t['status']}{'; ' + t['hinweis'] if t['hinweis'] else ''})"
                      for t in e["teile"])
    return f"Ladung aus HA {e['datum']} {e['zeit']}: {teile}"


# ── Monatssumme = Rest ohne Einzelladungen ──────────────────────────────────

def monatssumme(monat: str, anbieter: str, kwh: float, kosten: float | None,
                ct_fest: float, fahrzeug_ids: list | None = None) -> dict:
    """Was vom Zaehlerwert eines Monats als Monatssumme gespeichert wird.

    Rueckgabe: {"kwh", "ct", "gesamt", "zusatz" (Notiz-Zusatz, "" oder " · …"),
    "text" (fuers Protokoll), "gepusht" (kWh aus Einzelladungen)} – bei kwh == 0 ist
    der Monat ganz durch Einzelladungen abgedeckt und keine Monatssumme noetig."""
    gepusht_kwh, gepusht_kosten = db.summe_extern(monat, anbieter, fahrzeug_ids)
    zusatz, text = [], ""
    if gepusht_kwh > 0:
        rest = kwh - gepusht_kwh
        text = f", davon {gepusht_kwh:.1f} kWh als Einzelladungen"
        if rest < MIN_REST_KWH:
            return {"kwh": 0, "ct": ct_fest, "gesamt": 0.0, "zusatz": "", "gepusht": gepusht_kwh,
                    "text": text + " – kein Rest"}
        kwh = rest
        kosten = None if kosten is None else kosten - gepusht_kosten
        zusatz.append("Rest ohne Einzelladung")
        text += f", Rest {kwh:.1f} kWh"
    ct, gesamt = ct_fest, round(kwh * ct_fest / 100, 2)
    if anbieter == berechnung.NETZBEZUG:
        ct, gesamt, hinweis = berechnung.heimpreis(kwh, kosten, ct_fest)
        if hinweis == berechnung.DYNAMISCH_NOTIZ:
            zusatz.append(hinweis)
            text += f", {gesamt:.2f} € = {ct:.1f} ct/kWh"
        elif hinweis:
            text += f" ({hinweis})"
    return {"kwh": round(kwh, 3), "ct": ct, "gesamt": gesamt, "gepusht": gepusht_kwh,
            "zusatz": "".join(f" · {z}" for z in zusatz), "text": text}


# ── Mehrere Fahrzeuge: Zaehler einem oder mehreren Fahrzeugen zuordnen ────────

def gruppe(fahrzeug_id: int) -> list:
    """Fahrzeuge, die sich den Zaehler teilen, den `fahrzeug_id` nutzt: bei eigenen
    Zaehlern nur es selbst, sonst alle sichtbaren mit gemeinsamer Wallbox."""
    if not db.mehrere_fahrzeuge() or db.heimladung_modus(fahrzeug_id) == "eigen":
        return [fahrzeug_id]
    return [i for i in db.sichtbare_ids() if db.heimladung_modus(i) != "eigen"]


def verteilen(monat: str, anbieter: str, kwh: float, kosten: float | None, ct_fest: float,
              ids: list, km_je: dict | None = None, akku: dict | None = None) -> list:
    """Zaehlerwert eines Monats auf die Fahrzeuge `ids` verteilen.

    Erst werden die Einzelladungen (Push) aller dieser Fahrzeuge abgezogen. Vom Rest bekommt
    jedes Fahrzeug den Anteil, der ihm ueber den Akkustand zugeordnet wurde (`akku`:
    {id: 0…1}, siehe akku_anteile); was dann noch bleibt, wird nach dem km-Anteil im Monat
    aufgeteilt (ohne km zu gleichen Teilen).
    Rueckgabe: [(fahrzeug_id, summe)] mit summe wie bei monatssumme(); bei einem
    Fahrzeug genau monatssumme() – unveraendert gegenueber einem einzelnen Auto."""
    summe = monatssumme(monat, anbieter, kwh, kosten, ct_fest, ids)
    if len(ids) == 1:
        return [(ids[0], summe)]
    akku = {i: a for i, a in (akku or {}).items() if i in ids and a > 0}
    rest = max(0.0, 1 - sum(akku.values()))
    km_je = db.get_fahrten_je_fahrzeug() if km_je is None else km_je
    km = {i: km_je.get(i, {}).get(monat, 0) or 0 for i in ids}
    gesamt = sum(km.values())
    ergebnis = []
    for i in ids:
        km_anteil = km[i] / gesamt if gesamt > 0 else 1 / len(ids)
        anteil = akku.get(i, 0.0) + rest * km_anteil
        teil = dict(summe)
        teil["kwh"] = round(summe["kwh"] * anteil, 3)
        teil["gesamt"] = round(summe["gesamt"] * anteil, 2)
        if akku:
            herkunft = (f"{akku.get(i, 0) * 100:.0f} % über Akkustand, "
                        f"Rest {km_anteil * 100:.0f} % nach km")
        else:
            herkunft = f"{anteil * 100:.0f} % nach km"
        teil["zusatz"] = summe["zusatz"] + f" · {herkunft}"
        teil["text"] = summe["text"] + f", Anteil {anteil * 100:.0f} % ({herkunft})"
        teil["anteil"] = anteil
        ergebnis.append((i, teil))
    return ergebnis


# ── Zuordnung ueber den Akkustand (Modus "akku") ────────────────────────────

# Spielraum um das Ladefenster aus dem Akkustand: Stundenmittel und Hersteller-Clouds, die
# den Akkustand erst 15–60 Minuten spaeter melden
TOLERANZ_STUNDEN = 2
# Wallbox-Stunden mit weniger Energie zaehlen nicht (Standby, Rundung)
MIN_STUNDE_KWH = 0.05


def _stunde(zeit: str) -> str:
    return str(zeit)[:13]                      # 'YYYY-MM-DDTHH'


def stunden_deltas(werte: list) -> dict:
    """Fortlaufender Zaehler [(zeit, stand)] -> {stunde: Zuwachs}. Ruecksprung = Reset (0)."""
    deltas = {}
    werte = sorted((str(z)[:16], v) for z, v in werte if v is not None)
    for (_, vorher), (zeit, stand) in zip(werte, werte[1:]):
        d = stand - vorher
        if d > 0:
            deltas[_stunde(zeit)] = deltas.get(_stunde(zeit), 0.0) + d
    return deltas


def _fenster_stunden(start: str, ende: str, toleranz: int = TOLERANZ_STUNDEN) -> set:
    from datetime import timedelta
    try:
        a = datetime.fromisoformat(str(start)[:16]) - timedelta(hours=toleranz)
        b = datetime.fromisoformat(str(ende)[:16]) + timedelta(hours=toleranz)
    except ValueError:
        return set()
    stunden, t = set(), a.replace(minute=0)
    while t <= b:
        stunden.add(t.strftime("%Y-%m-%dT%H"))
        t += timedelta(hours=1)
    return stunden


def push_stunden(monat: str, ids: list) -> set:
    """Stunden, in denen eine Einzelladung (Push) dieser Fahrzeuge lief – sie ist schon
    erfasst und wird bei der Zuordnung ueber den Akkustand ausgelassen. Zeiten aus der
    Notiz „HA-Ladung 22:10–05:30“ (ueber Mitternacht = Folgetag)."""
    from datetime import timedelta
    stunden = set()
    for fid in ids:
        with db.fahrzeug_kontext(fid):
            for l in db.get_ladevorgaenge_zeitraum(f"{monat}-01", f"{monat}-31"):
                m = re.search(r"(\d{2}):(\d{2})(?:–(\d{2}):(\d{2}))?", l.get("notiz") or "")
                if not l.get("extern_id") or not m:
                    continue
                start = datetime.fromisoformat(f"{l['datum']}T{m.group(1)}:{m.group(2)}")
                if m.group(3):
                    ende = start.replace(hour=int(m.group(3)), minute=int(m.group(4)))
                    if ende < start:
                        ende += timedelta(days=1)
                else:
                    ende = start + timedelta(hours=1)
                stunden |= _fenster_stunden(start.isoformat(), ende.isoformat(), 0)
    return stunden


def zuordnen_akku(deltas: dict, fenster: dict, ausgelassen: set | None = None) -> dict:
    """Wallbox-Stunden den Fahrzeugen zuordnen – rein rechnend (ohne DB und HA).

    deltas:  {stunde 'YYYY-MM-DDTHH': kWh} der gemeinsamen Wallbox
    fenster: {fahrzeug_id: [(start, ende), …]} Ladefenster aus dem Akkustand (Modus "akku")
    ausgelassen: Stunden, die schon als Einzelladung erfasst sind (Push)
    Eine Stunde gehoert einem Fahrzeug, wenn genau eins in ihr (± Toleranz) geladen hat;
    keins oder mehrere -> Rest. Rueckgabe: {"je": {id: kWh}, "rest": kWh, "gesamt": kWh}."""
    ausgelassen = ausgelassen or set()
    stunden_je = {fid: set().union(*[_fenster_stunden(a, b) for a, b in liste]) if liste else set()
                  for fid, liste in fenster.items()}
    je = {fid: 0.0 for fid in fenster}
    rest = gesamt = 0.0
    for stunde, kwh in deltas.items():
        if stunde in ausgelassen or kwh < MIN_STUNDE_KWH:
            continue
        gesamt += kwh
        treffer = [fid for fid, st in stunden_je.items() if stunde in st]
        if len(treffer) == 1:
            je[treffer[0]] += kwh
        else:
            rest += kwh
    return {"je": je, "rest": rest, "gesamt": gesamt}


def akku_anteile(monat: str, ids: list, stundenwerte) -> tuple:
    """Anteile der Fahrzeuge mit Modus "akku" an der gemeinsamen Wallbox in einem Monat.

    stundenwerte(schluessel, start, ende) liefert die Stundenwerte des Zaehlers
    ("wallbox" bzw. "pv") als [(zeit, stand)]. Der Akkuverlauf kommt je Fahrzeug aus der
    Ladeerkennung. Rueckgabe: ({"wallbox": {id: anteil}, "pv": {...}}, Hinweistext) –
    bei fehlenden Daten leere Anteile (dann gilt "nach km")."""
    import calendar
    import ladeerkennung
    akku_ids = [i for i in ids if db.heimladung_modus(i) == "akku"]
    if not akku_ids:
        return {}, ""
    jahr, mon = int(monat[:4]), int(monat[5:7])
    start = datetime(jahr, mon, 1)
    ende = datetime(jahr, mon, calendar.monthrange(jahr, mon)[1], 23, 59, 59)
    fenster, ohne = {}, []
    for fid in akku_ids:
        with db.fahrzeug_kontext(fid):
            try:
                cfg = db.get_mail_settings()
                verlauf = ladeerkennung.batterie_verlauf(jahr, mon)
                ladungen = ladeerkennung.erkenne_ladungen(
                    verlauf, float(cfg.get("lade_min_anstieg") or ladeerkennung.MIN_ANSTIEG),
                    float(cfg.get("akku_kapazitaet_kwh") or 58.3))
            except Exception:
                verlauf, ladungen = [], []
        if not verlauf:
            ohne.append(fid)
        fenster[fid] = [(l["start"], l["ende"]) for l in ladungen if l.get("start")]
    if len(ohne) == len(akku_ids):
        return {}, "Akkustand: keine Akkuwerte – Aufteilung nach km"
    ausgelassen = push_stunden(monat, ids)
    anteile, hinweise = {}, []
    for schluessel in ("wallbox", "pv"):
        try:
            deltas = stunden_deltas(stundenwerte(schluessel, start, ende) or [])
        except Exception:
            deltas = {}
        z = zuordnen_akku(deltas, fenster, ausgelassen)
        if z["gesamt"] <= 0:
            continue
        anteile[schluessel] = {fid: kwh / z["gesamt"] for fid, kwh in z["je"].items()}
        hinweise.append(f"{schluessel} {100 - z['rest'] / z['gesamt'] * 100:.0f} % über Akkustand zugeordnet")
    if not anteile:
        return {}, "Akkustand: keine Stundenwerte der Wallbox – Aufteilung nach km"
    namen = {f["id"]: f["name"] for f in db.fahrzeuge(alle=True)}
    if ohne:
        hinweise.append("ohne Akkuwerte: " + ", ".join(namen.get(i, str(i)) for i in ohne))
    return anteile, "Akkustand: " + "; ".join(hinweise)
