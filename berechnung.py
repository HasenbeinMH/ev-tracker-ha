"""
Zentrale Berechnungslogik: Benzin-Äquivalent, CO2- und Kosten-Ersparnis.
Die Zeitraum-Kennzahlen (Dashboard, Statistik) stehen in zeitraum.py.
"""
import calendar

import database as db

BENZINPREIS_FALLBACK = 1.80  # €/L wenn keine Monatspreise erfasst sind
NETZPREIS_FALLBACK = 30.0    # ct/kWh wenn noch kein Stromtarif erfasst ist
NETZBEZUG = "Privat – Netzbezug"

# Vergleichsfahrzeug. Gerechnet wird fuer beide gleich (Liter × Preis, Liter × CO2-Faktor);
# es unterscheiden sich nur die Beschriftung und der Standard-CO2-Faktor.
# Intern heissen Tabellen und Schluessel weiter "benzin" – sie meinen den Kraftstoff.
KRAFTSTOFFE = {
    "benzin": {"art": "benzin", "name": "Benzin", "fahrzeug": "Benziner",
               "fahrzeug_gen": "Benziners", "co2_standard": 2.37},
    "diesel": {"art": "diesel", "name": "Diesel", "fahrzeug": "Diesel",
               "fahrzeug_gen": "Diesels", "co2_standard": 2.65},
    # LPG wird wie Benzin und Diesel in Litern getankt und bezahlt
    "autogas": {"art": "autogas", "name": "Autogas", "fahrzeug": "Autogas-Auto",
                "fahrzeug_gen": "Autogas-Autos", "co2_standard": 1.64},
}


def kraftstoff(art: str | None = None) -> dict:
    """Beschriftungen des Vergleichsfahrzeugs; ohne `art` aus den Einstellungen."""
    if art is None:
        art = db.get_config()["kraftstoff"]
    return KRAFTSTOFFE.get(art, KRAFTSTOFFE["benzin"])

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


# Dynamischer Tarif: Kommt zum Netz-kWh-Zaehler ein Kostenzaehler (EUR) aus HA, zaehlen
# die tatsaechlichen Kosten des Monats. Die Notiz der Monatssumme bekommt diesen Zusatz –
# so bleibt sichtbar, woher der Preis stammt, und die Neubewertung laesst sie in Ruhe.
DYNAMISCH_NOTIZ = "dynamischer Tarif"
# Ein Monatsmittel ausserhalb dieses Bereichs (ct/kWh) passt nicht zu den kWh – etwa weil
# der Kostenzaehler einen anderen Zeitraum erfasst hat. Dann gilt der feste Tarif.
DYNAMISCH_MIN_CT = 0.0
DYNAMISCH_MAX_CT = 150.0


def heimpreis(kwh: float, kosten: float | None, tarif_ct: float) -> tuple:
    """Preis der Netz-Monatssumme: (ct/kWh, Gesamtpreis €, Hinweis).

    Mit plausiblen Kosten aus dem Kostenzaehler gilt deren Mittel (Hinweis
    DYNAMISCH_NOTIZ), sonst der Tarif des Monats (Hinweis None bzw. der Grund,
    warum die Kosten nicht passten)."""
    if kosten is not None and kwh > 0:
        ct = kosten / kwh * 100
        if DYNAMISCH_MIN_CT < ct <= DYNAMISCH_MAX_CT:
            return round(ct, 2), round(kosten, 2), DYNAMISCH_NOTIZ
        return (tarif_ct, round(kwh * tarif_ct / 100, 2),
                f"Kosten {kosten:.2f} € ergeben {ct:.1f} ct/kWh – unplausibel, fester Tarif")
    return tarif_ct, round(kwh * tarif_ct / 100, 2), None


def ist_dynamisch(ladung: dict) -> bool:
    return DYNAMISCH_NOTIZ in (ladung.get("notiz") or "")


def netzpreis_tag(datum: str, tarife: list) -> float:
    """Strompreis (ct/kWh) an einem Tag 'YYYY-MM-DD' – fuer einzelne Heimladungen.
    Vor dem ersten erfassten Tarif gilt der aelteste."""
    if not tarife:
        return NETZPREIS_FALLBACK
    sortiert = sorted(tarife, key=lambda t: t["gueltig_ab"])
    gueltig = [t for t in sortiert if t["gueltig_ab"] <= datum]
    return (gueltig[-1] if gueltig else sortiert[0])["preis_kwh"]


# Einzelne Heimladungen, die Home Assistant am Ladeende schickt (heimladung.py)
PUSH_NOTIZ = "HA-Ladung"


def ist_push(ladung: dict) -> bool:
    return (ladung.get("notiz") or "").startswith(PUSH_NOTIZ)


def ist_heim_import(ladung: dict) -> bool:
    """Monatssumme aus dem HA-Import (Zeitraum-Import oder naechtlicher Abruf)?"""
    notiz = ladung.get("notiz") or ""
    return notiz.startswith("Import ") or notiz.startswith(db.AUTO_NOTIZ)


def heimladungen_neu_bewerten() -> int:
    """Bewertet importierte Netzbezug-Monatssummen mit dem Tarif ihres Monats und von
    HA geschickte Einzelladungen mit dem Tarif ihres Tages neu – noetig, wenn ein
    Stromtarif nachgetragen, geaendert oder geloescht wird.
    Von Hand erfasste und mit dem dynamischen Tarif bewertete Ladevorgaenge bleiben
    unberuehrt. Rueckgabe: Anzahl geaendert."""
    tarife = db.get_stromtarife()
    geaendert = 0
    for l in db.get_ladevorgaenge(limit=100000):
        if (l["anbieter"] != NETZBEZUG or ist_dynamisch(l)
                or not (ist_heim_import(l) or ist_push(l))):
            continue
        ct = (netzpreis_tag(l["datum"], tarife) if ist_push(l)
              else netzpreis_monat(l["datum"][:7], tarife))
        if abs((l["preis_kwh"] or 0) - ct) > 0.001:
            db.set_ladepreis(l["id"], ct, round(l["menge_kwh"] * ct / 100, 2))
            geaendert += 1
    return geaendert


SIM_OEFFENTLICH = "Öffentlich (Simulation)"


def simulierte_ladungen(cfg: dict | None = None, fahrten: list | None = None,
                        tarife: list | None = None) -> list:
    """Ladungen, die ein E-Auto fuer die gefahrenen km gebraucht haette – je Monat bis zu
    drei Eintraege (PV, Netz, oeffentlich) nach den eingestellten Anteilen, datiert auf den
    Monatsersten. Energie = km ÷ 100 × EV-Verbrauch × (1 + Ladeverluste). Die Eintraege
    haben dieselben Felder wie gespeicherte Ladevorgaenge, werden aber nie gespeichert:
    so rechnen alle Auswertungen unveraendert, und nach dem Kauf bleibt die Simulation
    als Prognose zum Vergleich erhalten."""
    cfg = cfg or db.get_config()
    fahrten = db.get_fahrten_monate() if fahrten is None else fahrten
    tarife = db.get_stromtarife() if tarife is None else tarife
    anteile = [("Privat – PV", cfg["sim_anteil_pv"], lambda m: cfg["pv_preis_ct"], "AC"),
               (NETZBEZUG, cfg["sim_anteil_netz"], lambda m: netzpreis_monat(m, tarife), "AC"),
               (SIM_OEFFENTLICH, cfg["sim_anteil_oeffentlich"],
                lambda m: cfg["sim_preis_oeffentlich"], "DC")]
    summe = sum(max(a, 0) for _, a, _, _ in anteile)
    if summe <= 0:                      # nichts eingestellt: alles zuhause aus dem Netz
        anteile, summe = [(NETZBEZUG, 100.0, anteile[1][2], "AC")], 100.0
    ladungen = []
    for f in sorted(fahrten, key=lambda f: f["monat"]):
        km = f.get("km") or 0.0
        if km <= 0:
            continue
        kwh = km / 100 * cfg["ev_verbrauch"] * (1 + cfg["sim_ladeverlust"] / 100)
        for anbieter, anteil, preis, typ in anteile:
            if anteil <= 0:
                continue
            menge = kwh * anteil / summe
            ct = preis(f["monat"])
            ladungen.append({
                "id": None, "datum": f"{f['monat']}-01", "menge_kwh": round(menge, 3),
                "preis_kwh": ct, "gesamtpreis": round(menge * ct / 100, 2),
                "anbieter": anbieter, "ladeleistung_kw": None, "ladetyp": typ,
                "notiz": "Simulation", "blockiergebuehr": None, "simuliert": True})
    return ladungen


def ladevorgaenge(von: str | None = None, bis: str | None = None) -> list:
    """Ladevorgaenge fuer die Auswertungen: im Simulationsmodus die aus den km
    gerechneten, sonst die gespeicherten. von/bis 'YYYY-MM-DD' (inklusive)."""
    cfg = db.get_config()
    if not cfg["simulation"]:
        if von is None and bis is None:
            return db.get_ladevorgaenge(limit=100000)
        return db.get_ladevorgaenge_zeitraum(von or "0000-00-00", bis or "9999-12-31")
    return [l for l in simulierte_ladungen(cfg)
            if (von is None or l["datum"] >= von) and (bis is None or l["datum"] <= bis)]


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
    for l in ladevorgaenge():
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
