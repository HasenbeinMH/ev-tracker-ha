"""
Zentrale Berechnungslogik: Benzin-Äquivalent, CO2- und Kosten-Ersparnis.
Eine Wahrheit für Dashboard, Fahrten-Tab und HA-Push.
"""
import database as db

BENZINPREIS_FALLBACK = 1.80  # €/L wenn keine Monatspreise erfasst sind


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
