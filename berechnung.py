"""
Zentrale Berechnungslogik: Benzin-Äquivalent, CO2- und Kosten-Ersparnis.
Eine Wahrheit für Dashboard, Fahrten-Tab und HA-Push.
"""
import database as db

BENZINPREIS_FALLBACK = 1.80  # €/L wenn keine Monatspreise erfasst sind

# Stromquelle je Ladevorgang, abgeleitet aus dem Anbieter (Namen aus database.py).
# Alle uebrigen Anbieter gelten als oeffentliches Laden.
STROMQUELLEN = {"Privat – PV": "PV-Strom", "Privat – Netzbezug": "Netzbezug"}
OEFFENTLICH = "Öffentlich"


def stromquelle(anbieter: str) -> str:
    return STROMQUELLEN.get(anbieter, OEFFENTLICH)


def benzin_liter(km: float, benziner_verbrauch: float) -> float:
    """Liter Benzin, die ein Vergleichs-Benziner für km gebraucht hätte."""
    return (km / 100) * benziner_verbrauch


def co2_kg(liter: float, co2_faktor: float) -> float:
    """kg CO2 für die angegebene Litermenge Benzin."""
    return liter * co2_faktor


def durchschnitt_benzinpreis(benzinpreise: list[dict]) -> float:
    """Ø-Preis über alle erfassten Monatspreise (oder Fallback)."""
    if not benzinpreise:
        return BENZINPREIS_FALLBACK
    return sum(d["preis_liter"] for d in benzinpreise) / len(benzinpreise)


def ersparnis_uebersicht() -> dict:
    """Berechnet alle Gesamt-Kennzahlen aus der Datenbank."""
    cfg = db.get_config()
    gesamt_km = db.get_fahrten_gesamt_km()
    gesamt_kwh, strom_kosten = db.get_lade_gesamt()
    thg_gesamt = db.get_thg_gesamt()
    kfz_steuer = db.get_einstellung("kfz_steuer_benziner") or 0.0

    avg_benzin = durchschnitt_benzinpreis(db.get_benzinpreise())
    liter = benzin_liter(gesamt_km, cfg["benziner_verbrauch"])
    benzin_kosten = liter * avg_benzin
    ersparnis_kraft = benzin_kosten - strom_kosten

    return {
        "gesamt_km":        gesamt_km,
        "gesamt_kwh":       gesamt_kwh,
        "strom_kosten":     strom_kosten,
        "benzin_kosten":    benzin_kosten,
        "avg_benzin":       avg_benzin,
        "thg_gesamt":       thg_gesamt,
        "kfz_steuer":       kfz_steuer,
        "ersparnis_kraft":  ersparnis_kraft,
        "ersparnis_gesamt": ersparnis_kraft + kfz_steuer + thg_gesamt,
        "co2_gespart":      co2_kg(liter, cfg["co2_faktor_benzin"]),
    }


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
