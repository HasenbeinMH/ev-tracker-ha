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

    datum = f"{start:%Y-%m-%d}"
    dauer_h = (ende - start).total_seconds() / 3600 if ende else 0
    leistung = round((netz + pv) / dauer_h, 1) if dauer_h > 0.05 else None
    zeit = f"{start:%H:%M}–{ende:%H:%M}" if ende else f"ab {start:%H:%M}"
    kennung = f"ha:{start:%Y-%m-%dT%H:%M}"
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
            f"{kennung}:{teil}", datum, round(kwh, 3), ct, gesamt, anbieter, leistung, notiz)
        teile.append({"teil": teil, "status": status, "id": lid, "kwh": round(kwh, 3),
                      "ct": ct, "gesamt": gesamt, "hinweis": hinweis})
    return {"ok": True, "datum": datum, "zeit": zeit, "teile": teile}


def protokoll_text(e: dict) -> str:
    teile = ", ".join(f"{t['teil']} {t['kwh']:.2f} kWh × {t['ct']:.1f} ct = {t['gesamt']:.2f} € "
                      f"({t['status']}{'; ' + t['hinweis'] if t['hinweis'] else ''})"
                      for t in e["teile"])
    return f"Ladung aus HA {e['datum']} {e['zeit']}: {teile}"


# ── Monatssumme = Rest ohne Einzelladungen ──────────────────────────────────

def monatssumme(monat: str, anbieter: str, kwh: float, kosten: float | None,
                ct_fest: float) -> dict:
    """Was vom Zaehlerwert eines Monats als Monatssumme gespeichert wird.

    Rueckgabe: {"kwh", "ct", "gesamt", "zusatz" (Notiz-Zusatz, "" oder " · …"),
    "text" (fuers Protokoll), "gepusht" (kWh aus Einzelladungen)} – bei kwh == 0 ist
    der Monat ganz durch Einzelladungen abgedeckt und keine Monatssumme noetig."""
    gepusht_kwh, gepusht_kosten = db.summe_extern(monat, anbieter)
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
