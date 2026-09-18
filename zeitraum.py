# -*- coding: utf-8 -*-
"""
Zeitraeume fuer Dashboard und Statistikseite: Gesamt, Jahre, Quartale.

Ein Zeitraum wird ueber einen Schluessel angesprochen:
    "alles"      – gesamter Datenbestand
    "2025"       – Kalenderjahr
    "2025-Q3"    – Quartal
    "2025-S"     – Sommerhalbjahr April bis September 2025
    "2025-W"     – Winterhalbjahr Oktober 2025 bis Maerz 2026
Sommer und Winter sind beim E-Auto die interessanteste Gegenueberstellung:
Heizung, Akkutemperatur und Winterreifen treiben den Verbrauch im Winter hoch.

Alle Daten werden auf Monatsebene zugeordnet (km und Benzinpreise liegen nur
monatlich vor), Ladungen und THG ueber die ersten sieben Zeichen ihres Datums.

KFZ-Steuer: Im Gesamtzeitraum zaehlt sie wie bisher einmal voll. Fuer Jahre
und Quartale wird sie nach Monaten anteilig gerechnet (Monate ÷ 12) – sonst
waere die Steuer-Ersparnis eines Quartals so hoch wie die eines ganzen Jahres.
"""
import re
from datetime import date

import database as db
import berechnung

ALLES = "alles"
_JAHR = re.compile(r"^(\d{4})$")
_QUARTAL = re.compile(r"^(\d{4})-Q([1-4])$")
_HALBJAHR = re.compile(r"^(\d{4})-([SW])$")


# ── Zeitraum aufloesen ───────────────────────────────────────────────────────

def aufloesen(schluessel: str | None) -> dict:
    """Schluessel -> {schluessel, titel, von, bis} mit von/bis als 'YYYY-MM'
    (None beim Gesamtzeitraum). Unbekannte Schluessel ergeben den Gesamtzeitraum."""
    s = (schluessel or "").strip()
    if m := _JAHR.match(s):
        j = m.group(1)
        return {"schluessel": s, "titel": j, "von": f"{j}-01", "bis": f"{j}-12"}
    if m := _QUARTAL.match(s):
        j, q = m.group(1), int(m.group(2))
        return {"schluessel": s, "titel": f"Q{q} {j}",
                "von": f"{j}-{3 * q - 2:02d}", "bis": f"{j}-{3 * q:02d}"}
    if m := _HALBJAHR.match(s):
        j = int(m.group(1))
        if m.group(2) == "S":
            return {"schluessel": s, "titel": f"Sommer {j}",
                    "von": f"{j}-04", "bis": f"{j}-09"}
        return {"schluessel": s, "titel": f"Winter {j}/{(j + 1) % 100:02d}",
                "von": f"{j}-10", "bis": f"{j + 1}-03"}
    return {"schluessel": ALLES, "titel": "Gesamter Zeitraum", "von": None, "bis": None}


def enthaelt(z: dict, datum: str) -> bool:
    """Liegt ein Datum ('YYYY-MM' oder 'YYYY-MM-DD') im Zeitraum?"""
    monat = (datum or "")[:7]
    if z["von"] is None:
        return True
    return z["von"] <= monat <= z["bis"]


def _monatsfolge(von: str, bis: str) -> list:
    j, m = int(von[:4]), int(von[5:7])
    ende = (int(bis[:4]), int(bis[5:7]))
    folge = []
    while (j, m) <= ende:
        folge.append(f"{j}-{m:02d}")
        j, m = (j, m + 1) if m < 12 else (j + 1, 1)
    return folge


def monate(z: dict, daten: dict) -> list:
    """Monate des Zeitraums bis einschliesslich des laufenden Monats.
    Beim Gesamtzeitraum: vom ersten bis zum letzten Monat mit Daten."""
    heute = date.today().strftime("%Y-%m")
    if z["von"] is None:
        vorhanden = _datenmonate(daten)
        if not vorhanden:
            return []
        return _monatsfolge(vorhanden[0], vorhanden[-1])
    if z["von"] > heute:
        return []
    return _monatsfolge(z["von"], min(z["bis"], heute))


def _datenmonate(daten: dict) -> list:
    alle = {f["datum"][:7] for f in daten["fahrten"]}
    alle |= {l["datum"][:7] for l in daten["lade"]}
    alle |= {b["monat"][:7] for b in daten["benzin"]}
    alle |= {t["datum"][:7] for t in daten["thg"]}
    return sorted(m for m in alle if m)


def optionen(daten: dict) -> list:
    """Auswahl fuers Dropdown: [(gruppe, [(schluessel, beschriftung), ...]), ...]."""
    heute = date.today()
    jahre = {int(m[:4]) for m in _datenmonate(daten)} | {heute.year, heute.year - 1}
    gruppen = [("", [(ALLES, "Gesamter Zeitraum")]),
               ("Jahre", [(str(j), str(j)) for j in sorted(jahre, reverse=True)])]
    aktuelles_q = (heute.month - 1) // 3 + 1
    for jahr, bis_q in ((heute.year, aktuelles_q), (heute.year - 1, 4)):
        gruppen.append((f"Quartale {jahr}",
                        [(f"{jahr}-Q{q}", f"Q{q} {jahr}") for q in range(bis_q, 0, -1)]))

    # Sommer (Apr–Sep) und Winter (Okt–Mär), neueste zuerst, nur bereits begonnene
    halbjahre = []
    for j in sorted(jahre, reverse=True):
        for art in ("W", "S"):
            z = aufloesen(f"{j}-{art}")
            if z["von"] <= heute.strftime("%Y-%m"):
                halbjahre.append((z["schluessel"], z["titel"]))
    gruppen.append(("Sommer (Apr–Sep) / Winter (Okt–Mär)", halbjahre))
    return gruppen


# ── Daten laden und filtern ──────────────────────────────────────────────────

def laden() -> dict:
    """Alle Rohdaten einmal aus der DB (fuer mehrere Zeitraeume wiederverwendbar)."""
    import akkuverbrauch
    return {
        "fahrten": db.get_fahrten_alle_als_liste(),
        "lade": db.get_ladevorgaenge(limit=100000),
        "benzin": db.get_benzinpreise(),
        "thg": sorted(db.get_thg_eintraege(), key=lambda t: t["datum"]),
        "stromtarife": db.get_stromtarife(),
        "akku": akkuverbrauch.pro_monat(),
        "cfg": db.get_config(),
        "kfz_steuer": db.get_einstellung("kfz_steuer_benziner") or 0.0,
    }


def filtern(z: dict, daten: dict) -> dict:
    """Die Rohdaten eingeschraenkt auf den Zeitraum (Stromtarife bleiben vollstaendig –
    der beim Zeitraumbeginn gueltige Tarif liegt meist davor)."""
    return {
        **daten,
        "fahrten": [f for f in daten["fahrten"] if enthaelt(z, f["datum"])],
        "lade": [l for l in daten["lade"] if enthaelt(z, l["datum"])],
        "benzin": [b for b in daten["benzin"] if enthaelt(z, b["monat"])],
        "thg": [t for t in daten["thg"] if enthaelt(z, t["datum"])],
        "akku": [a for a in daten["akku"] if enthaelt(z, a["monat"])],
    }


# ── Kennzahlen ───────────────────────────────────────────────────────────────

def kennzahlen(z: dict, daten: dict) -> dict:
    """Kennzahlen eines Zeitraums. `daten` sind die ungefilterten Rohdaten.
    Die Schluessel der Gesamtwerte entsprechen berechnung.ersparnis_uebersicht()."""
    f = filtern(z, daten)
    cfg = daten["cfg"]
    mon = monate(z, daten)

    km = sum(x["km"] for x in f["fahrten"])
    kwh = sum(l["menge_kwh"] for l in f["lade"])
    strom_kosten = sum(l["gesamtpreis"] for l in f["lade"])
    thg = sum(t["betrag"] for t in f["thg"])

    if f["benzin"]:
        avg_benzin = sum(b["preis_liter"] for b in f["benzin"]) / len(f["benzin"])
    else:
        avg_benzin = berechnung.durchschnitt_benzinpreis(daten["benzin"])
    liter = berechnung.benzin_liter(km, cfg["benziner_verbrauch"])
    benzin_kosten = liter * avg_benzin
    ersparnis_kraft = benzin_kosten - strom_kosten

    if z["von"] is None:
        kfz = daten["kfz_steuer"]
    else:
        kfz = daten["kfz_steuer"] * len(mon) / 12

    # Verbrauch laut Ladung nur ueber Monate, in denen km und Ladung vorliegen
    km_m, kwh_m = {}, {}
    for x in f["fahrten"]:
        km_m[x["datum"][:7]] = km_m.get(x["datum"][:7], 0) + x["km"]
    for l in f["lade"]:
        kwh_m[l["datum"][:7]] = kwh_m.get(l["datum"][:7], 0) + l["menge_kwh"]
    beide = [m for m in km_m if m in kwh_m and km_m[m] > 0]
    v_km = sum(km_m[m] for m in beide)
    verbrauch = sum(kwh_m[m] for m in beide) / v_km * 100 if v_km else None

    a_km = sum(a["km"] for a in f["akku"])
    verbrauch_akku = sum(a["kwh"] for a in f["akku"]) / a_km * 100 if a_km else None

    quellen = {"PV-Strom": 0.0, "Netzbezug": 0.0, berechnung.OEFFENTLICH: 0.0}
    for l in f["lade"]:
        quellen[berechnung.stromquelle(l["anbieter"])] += l["menge_kwh"]

    return {
        "titel":            z["titel"],
        "monate":           len(mon),
        "gesamt_km":        km,
        "gesamt_kwh":       kwh,
        "ladevorgaenge":    len(f["lade"]),
        "strom_kosten":     strom_kosten,
        "benzin_kosten":    benzin_kosten,
        "avg_benzin":       avg_benzin,
        "liter":            liter,
        "thg_gesamt":       thg,
        "kfz_steuer":       kfz,
        "ersparnis_kraft":  ersparnis_kraft,
        "ersparnis_gesamt": ersparnis_kraft + kfz + thg,
        "co2_gespart":      berechnung.co2_kg(liter, cfg["co2_faktor_benzin"]),
        "verbrauch":        verbrauch,
        "verbrauch_akku":   verbrauch_akku,
        "kosten_pro_100km": strom_kosten / km * 100 if km and strom_kosten else None,
        "strompreis_ct":    strom_kosten / kwh * 100 if kwh else None,
        "anteile":          {q: (v / kwh * 100 if kwh else None) for q, v in quellen.items()},
    }


def vorlagen() -> list:
    """Haeufige Gegenueberstellungen fuer die Statistikseite: [(text, a, b), ...]."""
    heute = date.today()
    j, q = heute.year, (heute.month - 1) // 3 + 1
    # Juengster begonnener Sommer und Winter
    sommer = j if heute.month >= 4 else j - 1
    winter = j if heute.month >= 10 else j - 1
    return [
        (f"{j} gegen {j - 1}", str(j), str(j - 1)),
        (f"Q{q} {j} gegen Q{q} {j - 1}", f"{j}-Q{q}", f"{j - 1}-Q{q}"),
        (f"Sommer {sommer} gegen Winter {winter}/{(winter + 1) % 100:02d}",
         f"{sommer}-S", f"{winter}-W"),
        (f"Winter {winter}/{(winter + 1) % 100:02d} gegen Winter {winter - 1}/{winter % 100:02d}",
         f"{winter}-W", f"{winter - 1}-W"),
    ]


# Zeilen der Vergleichstabelle:
# (Beschriftung, Schluessel in kennzahlen(), Nachkommastellen, Einheit, besser wenn …)
# besser: "hoch", "niedrig" oder None (neutral, keine Wertung)
VERGLEICH_ZEILEN = [
    ("Gefahrene Strecke", "gesamt_km", 0, "km", None),
    ("Ladevorgänge", "ladevorgaenge", 0, "", None),
    ("Geladene Energie", "gesamt_kwh", 1, "kWh", None),
    ("Verbrauch laut Ladung", "verbrauch", 1, "kWh/100 km", "niedrig"),
    ("Verbrauch laut Akku", "verbrauch_akku", 1, "kWh/100 km", "niedrig"),
    ("Stromkosten", "strom_kosten", 2, "€", "niedrig"),
    ("Kosten je 100 km", "kosten_pro_100km", 2, "€", "niedrig"),
    ("Ø Strompreis", "strompreis_ct", 1, "ct/kWh", "niedrig"),
    ("Anteil PV-Strom", ("anteile", "PV-Strom"), 0, "%", "hoch"),
    ("Anteil Netzbezug", ("anteile", "Netzbezug"), 0, "%", None),
    ("Anteil öffentlich", ("anteile", berechnung.OEFFENTLICH), 0, "%", None),
    ("Ø Benzinpreis", "avg_benzin", 3, "€/L", None),
    ("Benziner-Kosten (fiktiv)", "benzin_kosten", 2, "€", None),
    ("Kraftstoff-Ersparnis", "ersparnis_kraft", 2, "€", "hoch"),
    ("KFZ-Steuer-Ersparnis (anteilig)", "kfz_steuer", 2, "€", None),
    ("THG-Ertrag", "thg_gesamt", 2, "€", "hoch"),
    ("Gesamt-Ersparnis", "ersparnis_gesamt", 2, "€", "hoch"),
    ("CO2 vermieden", "co2_gespart", 0, "kg", "hoch"),
]


def vergleich_zeilen(ka: dict, kb: dict) -> list:
    """Tabellenzeilen A gegen B mit Differenz und Wertung (fuer das Template)."""
    from berichte import fmt
    zeilen = []
    for text, schluessel, stellen, einheit, besser in VERGLEICH_ZEILEN:
        if isinstance(schluessel, tuple):
            a, b = ka[schluessel[0]][schluessel[1]], kb[schluessel[0]][schluessel[1]]
        else:
            a, b = ka.get(schluessel), kb.get(schluessel)
        diff = prozent = None
        wertung = ""
        if a is not None and b is not None:
            diff = a - b
            if abs(diff) < 10 ** -stellen / 2:
                diff = 0.0
            prozent = diff / abs(b) * 100 if b else None
            if besser and diff:
                gut = (diff > 0) == (besser == "hoch")
                wertung = "besser" if gut else "schlechter"
        # Anteile vergleicht man in Prozentpunkten; eine relative Aenderung
        # ("+186 %" auf einen Anteil) waere eher verwirrend als hilfreich
        ist_anteil = einheit == "%"
        diff_einheit = "%-Pkt." if ist_anteil else einheit
        zeilen.append({
            "text": text,
            "a": fmt(a, stellen, einheit),
            "b": fmt(b, stellen, einheit),
            "diff": (("+" if diff > 0 else "−" if diff < 0 else "±")
                     + fmt(abs(diff), stellen, diff_einheit)) if diff is not None else "–",
            "prozent": (f"{prozent:+.0f} %".replace("-", "−"))
                       if prozent is not None and diff and not ist_anteil else "",
            "wertung": wertung,
        })
    return zeilen


def monatswerte(z: dict, daten: dict) -> list:
    """Werte je Monat des Zeitraums (fuer den Verlaufsvergleich auf der Statistikseite)."""
    f = filtern(z, daten)
    cfg = daten["cfg"]
    km_m = {x["datum"][:7]: x["km"] for x in f["fahrten"]}
    preis_m = {b["monat"][:7]: b["preis_liter"] for b in daten["benzin"]}
    avg = berechnung.durchschnitt_benzinpreis(daten["benzin"])
    akku_m = {a["monat"]: a["verbrauch"] for a in f["akku"]}
    kwh_m, kosten_m = {}, {}
    for l in f["lade"]:
        m = l["datum"][:7]
        kwh_m[m] = kwh_m.get(m, 0) + l["menge_kwh"]
        kosten_m[m] = kosten_m.get(m, 0) + l["gesamtpreis"]

    werte = []
    for m in monate(z, daten):
        km = km_m.get(m, 0.0)
        kwh = kwh_m.get(m, 0.0)
        kosten = kosten_m.get(m, 0.0)
        benzin = berechnung.benzin_liter(km, cfg["benziner_verbrauch"]) * preis_m.get(m, avg)
        werte.append({
            "monat": m,
            "km": round(km, 1),
            "kwh": round(kwh, 1),
            "strom_kosten": round(kosten, 2),
            "ersparnis": round(benzin - kosten, 2),
            "verbrauch": round(kwh / km * 100, 2) if km and kwh else None,
            "verbrauch_akku": akku_m.get(m),
        })
    return werte
