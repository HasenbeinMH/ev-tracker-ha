"""
Zentrale Berechnungslogik: Benzin-Äquivalent, CO2- und Kosten-Ersparnis.
Die Zeitraum-Kennzahlen (Dashboard, Statistik) stehen in zeitraum.py.
"""
import calendar

import database as db

BENZINPREIS_FALLBACK = 1.80  # €/L wenn keine Monatspreise erfasst sind
NETZPREIS_FALLBACK = 30.0    # ct/kWh wenn noch kein Stromtarif erfasst ist
NETZBEZUG = "Privat – Netzbezug"

# Stromquelle je Ladevorgang, abgeleitet aus dem Anbieter (Namen aus database.py).
# Alle uebrigen Anbieter gelten als oeffentliches Laden.
STROMQUELLEN = {"Privat – PV": "PV-Strom", "Privat – Netzbezug": "Netzbezug"}
OEFFENTLICH = "Öffentlich"


def stromquelle(anbieter: str) -> str:
    return STROMQUELLEN.get(anbieter, OEFFENTLICH)


def netzpreis_monat(monat: str, tarife: list) -> float:
    """Strompreis (ct/kWh) fuer den Netzbezug eines Monats 'YYYY-MM'.

    Heimladungen liegen nur als Monatssumme vor. Bewertet wird deshalb mit dem
    Tarif, der im Monat galt – bei einem Wechsel mitten im Monat tagesgenau
    gewichtet. Tage vor dem ersten erfassten Tarif bekommen den aeltesten Tarif.
    """
    if not tarife:
        return NETZPREIS_FALLBACK
    sortiert = sorted(tarife, key=lambda t: t["gueltig_ab"])
    tage = calendar.monthrange(int(monat[:4]), int(monat[5:7]))[1]
    summe = 0.0
    for tag in range(1, tage + 1):
        datum = f"{monat}-{tag:02d}"
        gueltig = [t for t in sortiert if t["gueltig_ab"] <= datum]
        summe += (gueltig[-1] if gueltig else sortiert[0])["preis_kwh"]
    return round(summe / tage, 2)


def ist_heim_import(ladung: dict) -> bool:
    """Monatssumme aus dem HA-Import (Zeitraum-Import oder naechtlicher Abruf)?"""
    notiz = ladung.get("notiz") or ""
    return notiz.startswith("Import ") or notiz.startswith(db.AUTO_NOTIZ)


def heimladungen_neu_bewerten() -> int:
    """Bewertet importierte Netzbezug-Monatssummen mit dem Tarif ihres Monats neu –
    noetig, wenn ein Stromtarif nachgetragen, geaendert oder geloescht wird.
    Von Hand erfasste Ladevorgaenge bleiben unberuehrt. Rueckgabe: Anzahl geaendert."""
    tarife = db.get_stromtarife()
    geaendert = 0
    for l in db.get_ladevorgaenge(limit=100000):
        if l["anbieter"] != NETZBEZUG or not ist_heim_import(l):
            continue
        ct = netzpreis_monat(l["datum"][:7], tarife)
        if abs((l["preis_kwh"] or 0) - ct) > 0.001:
            db.set_ladepreis(l["id"], ct, round(l["menge_kwh"] * ct / 100, 2))
            geaendert += 1
    return geaendert


def benzin_liter(km: float, benziner_verbrauch: float) -> float:
    """Liter Benzin, die ein Vergleichs-Benziner für km gebraucht hätte."""
    return (km / 100) * benziner_verbrauch


def co2_kg(liter: float, co2_faktor: float) -> float:
    """kg CO2 für die angegebene Litermenge Benzin."""
    return liter * co2_faktor


def durchschnitt_benzinpreis(benzinpreise: list[dict]) -> float:
    """Ø-Preis über alle erfassten Monatspreise (oder Fallback).
    Nur noch Ersatzwert fuer Monate ohne eigenen Benzinpreis."""
    if not benzinpreise:
        return BENZINPREIS_FALLBACK
    return sum(d["preis_liter"] for d in benzinpreise) / len(benzinpreise)


def benzin_kosten(km_je_monat: dict, preise: dict, benziner_verbrauch: float,
                  ersatzpreis: float) -> float:
    """Fiktive Benzinkosten Monat fuer Monat: km des Monats × Preis desselben Monats.

    `km_je_monat` und `preise` sind {'YYYY-MM': wert}. Monate ohne Benzinpreis
    bekommen `ersatzpreis`. So ergibt die Summe der Monatswerte (Diagramm,
    Monatsberichte) genau den Wert des Zeitraums (Kachel, Jahresbericht).
    """
    return sum(benzin_liter(km, benziner_verbrauch) * preise.get(m, ersatzpreis)
               for m, km in km_je_monat.items())


def verbrauch_pro_monat() -> list:
    """Verbrauch je Monat in kWh/100km, nur Monate mit km und Ladung.
    Rueckgabe: [{"monat", "km", "kwh", "verbrauch"}] aufsteigend nach Monat."""
    fahrten = {f["monat"]: f["km"] for f in db.get_fahrten_monate()}
    kwh_je_monat = {}
    for l in db.get_ladevorgaenge(limit=100000):
        monat = (l["datum"] or "")[:7]
        kwh_je_monat[monat] = kwh_je_monat.get(monat, 0.0) + l["menge_kwh"]

    ergebnis = []
    for monat in sorted(set(fahrten) & set(kwh_je_monat)):
        km, kwh = fahrten[monat], kwh_je_monat[monat]
        if km > 0 and kwh > 0:
            ergebnis.append({"monat": monat, "km": km, "kwh": kwh,
                             "verbrauch": kwh / km * 100})
    return ergebnis


def verbrauch_statistik() -> dict:
    """Bester, schlechtester und durchschnittlicher Monatsverbrauch.

    Der Durchschnitt ist gewichtet (Gesamt-kWh / Gesamt-km), damit lange Monate
    staerker zaehlen als kurze.
    """
    monate = verbrauch_pro_monat()
    if not monate:
        return {"monate": [], "niedrigster": None, "hoechster": None,
                "schnitt": None, "schnitt_ungewichtet": None}

    gesamt_km = sum(m["km"] for m in monate)
    gesamt_kwh = sum(m["kwh"] for m in monate)
    return {
        "monate": monate,
        "niedrigster": min(monate, key=lambda m: m["verbrauch"]),
        "hoechster": max(monate, key=lambda m: m["verbrauch"]),
        "schnitt": gesamt_kwh / gesamt_km * 100 if gesamt_km else None,
        "schnitt_ungewichtet": sum(m["verbrauch"] for m in monate) / len(monate),
    }
