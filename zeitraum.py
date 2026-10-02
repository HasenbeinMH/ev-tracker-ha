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

KFZ-Steuer: ein Jahresbetrag, daher immer nach Monaten anteilig (Monate ÷ 12) –
auch im Gesamtzeitraum (erster bis letzter Monat mit Daten). Sonst waere die
Steuer-Ersparnis eines Quartals so hoch wie die eines ganzen Jahres, und
mehrere Jahre bekaemen die Steuer nur einmal gutgeschrieben.
Endet die Steuerbefreiung des E-Autos, wird dessen Jahressteuer ab dem
eingetragenen Monat ebenso anteilig abgezogen.
"""
import re
from datetime import date

import database as db
import berechnung
from i18n import _, N_

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
        return {"schluessel": s, "titel": _("Q{0} {1}", q, j),
                "von": f"{j}-{3 * q - 2:02d}", "bis": f"{j}-{3 * q:02d}"}
    if m := _HALBJAHR.match(s):
        j = int(m.group(1))
        if m.group(2) == "S":
            return {"schluessel": s, "titel": _("Sommer {0}", j),
                    "von": f"{j}-04", "bis": f"{j}-09"}
        return {"schluessel": s, "titel": _("Winter {0}/{1}", j, f"{(j + 1) % 100:02d}"),
                "von": f"{j}-10", "bis": f"{j + 1}-03"}
    return {"schluessel": ALLES, "titel": _("Gesamter Zeitraum"), "von": None, "bis": None}


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
    alle |= {l["datum"][:7] for l in berechnung.nur_ladungen(daten["lade"])}
    # Kraftstoffpreise gelten fuer alle Fahrzeuge – bei mehreren zaehlen fuer ein Fahrzeug
    # nur seine eigenen Monate (ein spaeter gekauftes Auto bekaeme sonst Steuer-Ersparnis
    # fuer Monate, in denen es noch gar nicht da war)
    if not daten.get("nur_eigene_monate"):
        alle |= {b["monat"][:7] for b in daten["benzin"]}
    alle |= {t["datum"][:7] for t in daten["thg"]}
    return sorted(m for m in alle if m)


def optionen(daten: dict) -> list:
    """Auswahl fuers Dropdown: [(gruppe, [(schluessel, beschriftung), ...]), ...]."""
    heute = date.today()
    jahre = {int(m[:4]) for m in _datenmonate(daten)} | {heute.year, heute.year - 1}
    gruppen = [("", [(ALLES, _("Gesamter Zeitraum"))]),
               (_("Jahre"), [(str(j), str(j)) for j in sorted(jahre, reverse=True)])]
    aktuelles_q = (heute.month - 1) // 3 + 1
    for jahr, bis_q in ((heute.year, aktuelles_q), (heute.year - 1, 4)):
        gruppen.append((_("Quartale {0}", jahr),
                        [(f"{jahr}-Q{q}", _("Q{0} {1}", q, jahr)) for q in range(bis_q, 0, -1)]))

    # Sommer (Apr–Sep) und Winter (Okt–Mär), neueste zuerst, nur bereits begonnene
    halbjahre = []
    for j in sorted(jahre, reverse=True):
        for art in ("W", "S"):
            z = aufloesen(f"{j}-{art}")
            if z["von"] <= heute.strftime("%Y-%m"):
                halbjahre.append((z["schluessel"], z["titel"]))
    gruppen.append((_("Sommer (Apr–Sep) / Winter (Okt–Mär)"), halbjahre))
    return gruppen


# ── Daten laden und filtern ──────────────────────────────────────────────────

def laden() -> dict:
    """Alle Rohdaten einmal aus der DB (fuer mehrere Zeitraeume wiederverwendbar).

    Gesamtsicht ueber mehrere Fahrzeuge: oben die zusammengefassten Rohdaten (fuer
    Diagramme und Zeitraum-Auswahl), unter "fahrzeuge" die Daten je Fahrzeug – die
    Kennzahlen werden je Fahrzeug mit dessen Vergleichswerten gerechnet und summiert."""
    daten = _laden_einzeln()
    if db.aktuelles_fahrzeug() is None:
        daten["fahrzeuge"] = []
        for fz in db.fahrzeuge():
            with db.fahrzeug_kontext(fz["id"]):
                daten["fahrzeuge"].append((fz, _laden_einzeln()))
    # Liter und CO2 des Vergleichs-Verbrenners je Monat – in der Gesamtsicht je Fahrzeug
    # mit dessen Verbrauch und CO2-Faktor, damit die Diagramme zu den Kennzahlen passen
    teile = [d for _f, d in daten["fahrzeuge"]] if daten.get("fahrzeuge") else [daten]
    daten["liter_je_monat"], daten["co2_je_monat"] = {}, {}
    for d in teile:
        for f in d["fahrten"]:
            m = f["datum"][:7]
            liter = berechnung.benzin_liter(f["km"], d["cfg"]["benziner_verbrauch"])
            daten["liter_je_monat"][m] = daten["liter_je_monat"].get(m, 0) + liter
            daten["co2_je_monat"][m] = (daten["co2_je_monat"].get(m, 0)
                                        + berechnung.co2_kg(liter, d["cfg"]["co2_faktor_benzin"]))
    return daten


def _laden_einzeln() -> dict:
    import akkuverbrauch
    return {
        "fahrten": db.get_fahrten_alle_als_liste(),
        # im Simulationsmodus aus den km gerechnet; "lade_sim" ist die Simulation immer –
        # nach dem Kauf die Prognose, gegen die die echten Werte verglichen werden
        "lade": berechnung.ladevorgaenge(),
        "lade_sim": berechnung.simulierte_ladungen(),
        "benzin": db.get_benzinpreise(),
        "thg": sorted(db.get_thg_eintraege(), key=lambda t: t["datum"]),
        "stromtarife": db.get_stromtarife(),
        "akku": akkuverbrauch.pro_monat(),
        "cfg": db.get_config(),
        "kfz_steuer": db.get_einstellung("kfz_steuer_benziner") or 0.0,
        "kfz_steuer_eauto": db.get_einstellung("kfz_steuer_eauto") or 0.0,
        "kfz_steuer_eauto_ab": db.get_einstellung_str("kfz_steuer_eauto_ab") or "",
        "anschaffung": anschaffung(),
        "fahrzeug_id": db.aktuelles_fahrzeug(),
        "nur_eigene_monate": (db.mehrere_fahrzeuge() and db.aktuelles_fahrzeug() is not None
                              and len(db.sichtbare_ids()) > 1),
    }


def filtern(z: dict, daten: dict) -> dict:
    """Die Rohdaten eingeschraenkt auf den Zeitraum (Stromtarife bleiben vollstaendig –
    der beim Zeitraumbeginn gueltige Tarif liegt meist davor)."""
    return {
        **daten,
        "fahrten": [f for f in daten["fahrten"] if enthaelt(z, f["datum"])],
        "lade": [l for l in daten["lade"] if enthaelt(z, l["datum"])],
        "lade_sim": [l for l in daten.get("lade_sim", []) if enthaelt(z, l["datum"])],
        "benzin": [b for b in daten["benzin"] if enthaelt(z, b["monat"])],
        "thg": [t for t in daten["thg"] if enthaelt(z, t["datum"])],
        "akku": [a for a in daten["akku"] if enthaelt(z, a["monat"])],
    }


# ── Kennzahlen ───────────────────────────────────────────────────────────────

def kennzahlen(z: dict, daten: dict) -> dict:
    """Kennzahlen eines Zeitraums. `daten` sind die ungefilterten Rohdaten."""
    if daten.get("fahrzeuge"):
        je = [(fz, kennzahlen(z, {**d, "lade": _ersetzt(daten, d)}))
              for fz, d in daten["fahrzeuge"]]
        summe = kennzahlen_summe([k for _f, k in je], z["titel"])
        summe["je_fahrzeug"] = [{"fahrzeug": fz, **k} for fz, k in je]
        return summe
    f = filtern(z, daten)
    cfg = daten["cfg"]
    mon = monate(z, daten)

    km = sum(x["km"] for x in f["fahrten"])
    kwh = sum(l["menge_kwh"] for l in f["lade"])
    strom_kosten = sum(l["gesamtpreis"] for l in f["lade"])
    thg = sum(t["betrag"] for t in f["thg"])

    # Benzinkosten Monat fuer Monat mit dem Preis des jeweiligen Monats; der Ø-Preis
    # ist damit km-gewichtet (ein Monat mit 3.000 km zaehlt mehr als einer mit 100 km)
    ersatz = berechnung.durchschnitt_benzinpreis(daten["benzin"])
    km_m = {}
    for x in f["fahrten"]:
        km_m[x["datum"][:7]] = km_m.get(x["datum"][:7], 0) + x["km"]
    preise = {b["monat"][:7]: b["preis_liter"] for b in daten["benzin"]}
    liter = berechnung.benzin_liter(km, cfg["benziner_verbrauch"])
    benzin_kosten = berechnung.benzin_kosten(km_m, preise, cfg["benziner_verbrauch"], ersatz)
    if liter:
        avg_benzin = benzin_kosten / liter
    elif f["benzin"]:
        avg_benzin = sum(b["preis_liter"] for b in f["benzin"]) / len(f["benzin"])
    else:
        avg_benzin = ersatz
    ersparnis_kraft = benzin_kosten - strom_kosten

    # Jahresbetrag, anteilig nach Monaten (Gesamtzeitraum: erster bis letzter Datenmonat)
    kfz_eauto = steuer_eauto(mon, daten)
    kfz = daten["kfz_steuer"] * len(mon) / 12 - kfz_eauto

    # Verbrauch laut Ladung nur ueber Monate, in denen km und Ladung vorliegen
    kwh_m = {}
    for l in f["lade"]:
        if l["menge_kwh"]:          # Grundgebuehr-Eintraege haben keine kWh
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
        # Zwischenwerte fuer die Summe ueber mehrere Fahrzeuge (kennzahlen_summe)
        "_v_km": v_km, "_v_kwh": sum(kwh_m[m] for m in beide),
        "_a_km": a_km, "_a_kwh": sum(a["kwh"] for a in f["akku"]),
        "_quellen": quellen,
        "titel":            z["titel"],
        "monate":           len(mon),
        "gesamt_km":        km,
        "gesamt_kwh":       kwh,
        "ladevorgaenge":    len(berechnung.nur_ladungen(f["lade"])),
        "strom_kosten":     strom_kosten,
        "benzin_kosten":    benzin_kosten,
        "avg_benzin":       avg_benzin,
        "liter":            liter,
        "thg_gesamt":       thg,
        "kfz_steuer":       kfz,
        "kfz_steuer_eauto": kfz_eauto,
        "ersparnis_kraft":  ersparnis_kraft,
        "ersparnis_gesamt": ersparnis_kraft + kfz + thg,
        "co2_gespart":      berechnung.co2_kg(liter, cfg["co2_faktor_benzin"]),
        "verbrauch":        verbrauch,
        "verbrauch_akku":   verbrauch_akku,
        "kosten_pro_100km": strom_kosten / km * 100 if km and strom_kosten else None,
        "ersparnis_100km":  ersparnis_kraft / km * 100 if km else None,
        "strompreis_ct":    strom_kosten / kwh * 100 if kwh else None,
        "anteile":          {q: (v / kwh * 100 if kwh else None) for q, v in quellen.items()},
    }


def steuer_eauto(mon: list, daten: dict) -> float:
    """KFZ-Steuer des E-Autos in den Monaten `mon`: Jahresbetrag anteilig, aber nur
    fuer Monate ab Ende der Steuerbefreiung ('YYYY-MM'; leer = alle Monate)."""
    betrag = daten.get("kfz_steuer_eauto") or 0.0
    if not betrag:
        return 0.0
    ab = (daten.get("kfz_steuer_eauto_ab") or "")[:7]
    return betrag * len([m for m in mon if m >= ab]) / 12


# ── Amortisation: wann hat sich der Mehrpreis des E-Autos bezahlt gemacht? ─────

PROGNOSE_BASIS_MONATE = 12      # Ø-Ersparnis der letzten abgeschlossenen Monate
PROGNOSE_MAX_MONATE = 15 * 12   # weiter wird nicht hochgerechnet


def anschaffung() -> dict | None:
    """Kaufpreise des aktuellen Fahrzeugs – None, solange kein Preis des E-Autos
    eingetragen ist. Mehrpreis = E-Auto − vergleichbarer Verbrenner − Foerderung."""
    eauto = db.get_einstellung("anschaffung_eauto") or 0.0
    if eauto <= 0:
        return None
    verbrenner = db.get_einstellung("anschaffung_verbrenner") or 0.0
    foerderung = db.get_einstellung("anschaffung_foerderung") or 0.0
    return {"eauto": eauto, "verbrenner": verbrenner, "foerderung": foerderung,
            "mehrpreis": eauto - verbrenner - foerderung}


def ersparnis_je_monat(daten: dict) -> dict:
    """Gesamt-Ersparnis (Kraftstoff + KFZ-Steuer + THG) je Monat ueber den ganzen
    Datenbestand. Die Summe ist genau die Gesamt-Ersparnis im Zeitraum "Gesamt"."""
    cfg = daten["cfg"]
    ersatz = berechnung.durchschnitt_benzinpreis(daten["benzin"])
    preise = {b["monat"][:7]: b["preis_liter"] for b in daten["benzin"]}
    werte = {m: daten["kfz_steuer"] / 12 - steuer_eauto([m], daten)
             for m in monate(aufloesen(ALLES), daten)}

    def dazu(m, betrag):
        werte[m] = werte.get(m, 0.0) + betrag

    for f in daten["fahrten"]:
        m = f["datum"][:7]
        dazu(m, berechnung.benzin_liter(f["km"], cfg["benziner_verbrauch"])
             * preise.get(m, ersatz))
    for l in daten["lade"]:
        dazu(l["datum"][:7], -l["gesamtpreis"])
    for t in daten["thg"]:
        dazu(t["datum"][:7], t["betrag"])
    return werte


def _monat_plus(monat: str, n: int) -> str:
    i = int(monat[:4]) * 12 + int(monat[5:7]) - 1 + n
    return f"{i // 12}-{i % 12 + 1:02d}"


def amortisation(daten: dict) -> dict | None:
    """Mehrpreis gegen die aufsummierte Gesamt-Ersparnis, unabhaengig vom gewaehlten
    Zeitraum. `daten` aus laden(). In der Gesamtsicht zaehlen nur Fahrzeuge mit
    eingetragenem Kaufpreis – Preise und Ersparnis werden addiert.
    None, solange kein Kaufpreis eingetragen ist."""
    namen, ohne = None, []
    if daten.get("fahrzeuge"):
        teile = [(fz, d) for fz, d in daten["fahrzeuge"] if d.get("anschaffung")]
        if not teile:
            return None
        namen = [fz["name"] for fz, _d in teile]
        ohne = [fz["name"] for fz, d in daten["fahrzeuge"] if not d.get("anschaffung")]
        a = {k: sum(d["anschaffung"][k] for _f, d in teile)
             for k in ("eauto", "verbrenner", "foerderung", "mehrpreis")}
        reihe = {}
        for _f, d in teile:
            for m, v in ersparnis_je_monat(d).items():
                reihe[m] = reihe.get(m, 0.0) + v
    else:
        a = daten.get("anschaffung")
        if not a:
            return None
        reihe = ersparnis_je_monat(daten)

    mehrpreis = a["mehrpreis"]
    folge = sorted(reihe)
    kumuliert, summe, erreicht = [], 0.0, None
    for m in folge:
        summe += reihe[m]
        kumuliert.append(round(summe, 2))
        if erreicht is None and summe >= mehrpreis:
            erreicht = m
    if summe < mehrpreis:
        erreicht = None             # zwischendurch erreicht, aktuell wieder darunter

    # Prognose aus dem Durchschnitt der letzten abgeschlossenen Monate (der laufende
    # Monat ist meist noch unvollstaendig und wuerde den Schnitt druecken)
    heute = date.today().strftime("%Y-%m")
    basis = [m for m in folge if m < heute][-PROGNOSE_BASIS_MONATE:] or folge[-PROGNOSE_BASIS_MONATE:]
    je_monat = sum(reihe[m] for m in basis) / len(basis) if basis else 0.0
    prognose, prognose_monate, zu_weit = None, None, False
    rest = max(mehrpreis - summe, 0.0)
    if erreicht is None and folge and je_monat > 0:
        n = -(-rest // je_monat)            # aufrunden
        if n > PROGNOSE_MAX_MONATE:
            zu_weit = True
        else:
            prognose_monate = int(n)
            prognose = _monat_plus(folge[-1], prognose_monate)

    return {
        **a,
        "erspart": summe,
        "anteil": summe / mehrpreis * 100 if mehrpreis > 0 else None,
        "rest": rest,
        "ueberschuss": summe - mehrpreis if summe >= mehrpreis else None,
        "erreicht": erreicht,
        "kein_mehrpreis": mehrpreis <= 0,
        "je_monat": je_monat,
        "basis_monate": len(basis),
        "prognose": prognose,
        "prognose_monate": prognose_monate,
        "zu_weit": zu_weit,
        "monate": folge,
        "kumuliert": kumuliert,
        "fahrzeuge": namen,
        "ohne": ohne,
    }


def _ersetzt(gesamt: dict, einzeln: dict) -> list:
    """Ladungen eines Fahrzeugs; wurden die Ladungen der Gesamtsicht ersetzt (Prognose
    aus der Simulation), die simulierten des Fahrzeugs."""
    if gesamt.get("lade") is gesamt.get("lade_sim"):
        return einzeln["lade_sim"]
    return einzeln["lade"]


# Kennzahlen, die sich ueber Fahrzeuge einfach addieren
_SUMMEN = ("gesamt_km", "gesamt_kwh", "ladevorgaenge", "strom_kosten", "benzin_kosten",
           "liter", "thg_gesamt", "kfz_steuer", "kfz_steuer_eauto", "ersparnis_kraft",
           "ersparnis_gesamt", "co2_gespart", "_v_km", "_v_kwh", "_a_km", "_a_kwh")


def kennzahlen_summe(liste: list, titel: str) -> dict:
    """Kennzahlen mehrerer Fahrzeuge zusammengefasst. Summen addiert; Verhaeltnisse
    (Verbrauch, ct/kWh, je 100 km, Anteile, Ø Kraftstoffpreis) aus den Summen neu
    gebildet – nie als Mittelwert der Fahrzeuge."""
    s = {k: sum(x.get(k) or 0 for x in liste) for k in _SUMMEN}
    quellen = {}
    for x in liste:
        for q, v in x["_quellen"].items():
            quellen[q] = quellen.get(q, 0) + v
    km, kwh, kosten = s["gesamt_km"], s["gesamt_kwh"], s["strom_kosten"]
    preise = [x["avg_benzin"] for x in liste if x.get("avg_benzin")]
    return {
        **s,
        "titel": titel,
        "monate": max((x["monate"] for x in liste), default=0),
        "avg_benzin": (s["benzin_kosten"] / s["liter"] if s["liter"]
                       else (preise[0] if preise else None)),
        "verbrauch": s["_v_kwh"] / s["_v_km"] * 100 if s["_v_km"] else None,
        "verbrauch_akku": s["_a_kwh"] / s["_a_km"] * 100 if s["_a_km"] else None,
        "kosten_pro_100km": kosten / km * 100 if km and kosten else None,
        "ersparnis_100km": s["ersparnis_kraft"] / km * 100 if km else None,
        "strompreis_ct": kosten / kwh * 100 if kwh else None,
        "anteile": {q: (v / kwh * 100 if kwh else None) for q, v in quellen.items()},
        "_quellen": quellen,
    }


def vorlagen() -> list:
    """Haeufige Gegenueberstellungen fuer die Statistikseite: [(text, a, b), ...]."""
    heute = date.today()
    j, q = heute.year, (heute.month - 1) // 3 + 1
    # Juengster begonnener Sommer und Winter
    sommer = j if heute.month >= 4 else j - 1
    winter = j if heute.month >= 10 else j - 1
    return [
        (_("{0} gegen {1}", j, j - 1), str(j), str(j - 1)),
        (_("{0} gegen {1}", _("Q{0} {1}", q, j), _("Q{0} {1}", q, j - 1)), f"{j}-Q{q}", f"{j - 1}-Q{q}"),
        (_("{0} gegen {1}", _("Sommer {0}", sommer), _("Winter {0}/{1}", winter, f"{(winter + 1) % 100:02d}")),
         f"{sommer}-S", f"{winter}-W"),
        (_("{0} gegen {1}", _("Winter {0}/{1}", winter, f"{(winter + 1) % 100:02d}"),
           _("Winter {0}/{1}", winter - 1, f"{winter % 100:02d}")),
         f"{winter}-W", f"{winter - 1}-W"),
    ]


# Zeilen der Vergleichstabelle:
# (Beschriftung – {name}/{fahrzeug} aus berechnung.KRAFTSTOFFE –, Schluessel in kennzahlen(), Nachkommastellen, Einheit, besser wenn …)
# besser: "hoch", "niedrig" oder None (neutral, keine Wertung). Summen, die mit der
# Strecke oder der Laenge des Zeitraums wachsen, bleiben neutral – weniger gefahren
# ist weder besser noch schlechter; gewertet werden nur streckenunabhaengige Werte.
VERGLEICH_ZEILEN = [
    (N_("Gefahrene Strecke"), "gesamt_km", 0, "km", None),
    (N_("Ladevorgänge"), "ladevorgaenge", 0, "", None),
    (N_("Geladene Energie"), "gesamt_kwh", 1, "kWh", None),
    (N_("Verbrauch laut Ladung"), "verbrauch", 1, "kWh/100 km", "niedrig"),
    (N_("Verbrauch laut Akku"), "verbrauch_akku", 1, "kWh/100 km", "niedrig"),
    (N_("Stromkosten"), "strom_kosten", 2, "€", None),
    (N_("Kosten je 100 km"), "kosten_pro_100km", 2, "€", "niedrig"),
    (N_("Ø Strompreis"), "strompreis_ct", 1, "ct/kWh", "niedrig"),
    (N_("Anteil PV-Strom"), ("anteile", "PV-Strom"), 0, "%", "hoch"),
    (N_("Anteil Netzbezug"), ("anteile", "Netzbezug"), 0, "%", "niedrig"),
    (N_("Anteil öffentlich"), ("anteile", berechnung.OEFFENTLICH), 0, "%", "niedrig"),
    (N_("Ø {name}preis"), "avg_benzin", 3, "€/L", None),
    (N_("{fahrzeug}-Kosten (fiktiv)"), "benzin_kosten", 2, "€", None),
    (N_("Kraftstoff-Ersparnis"), "ersparnis_kraft", 2, "€", None),
    (N_("Ersparnis je 100 km"), "ersparnis_100km", 2, "€", "hoch"),
    (N_("KFZ-Steuer-Ersparnis (anteilig)"), "kfz_steuer", 2, "€", None),
    (N_("davon KFZ-Steuer E-Auto"), "kfz_steuer_eauto", 2, "€", None),
    (N_("THG-Ertrag"), "thg_gesamt", 2, "€", None),
    (N_("Gesamt-Ersparnis"), "ersparnis_gesamt", 2, "€", None),
    (N_("CO2 vermieden"), "co2_gespart", 0, "kg", None),
]


# Zeilen fuer "Prognose gegen tatsaechlich" – nur was vom Laden abhaengt
PROGNOSE_ZEILEN = ("gesamt_kwh", "verbrauch", "strom_kosten", "kosten_pro_100km",
                   "strompreis_ct", "ersparnis_kraft", "ersparnis_100km")


def vergleich_zeilen(ka: dict, kb: dict, nur: tuple | None = None) -> list:
    """Tabellenzeilen A gegen B mit Differenz und Wertung (fuer das Template).
    nur: nur diese Schluessel aus VERGLEICH_ZEILEN."""
    from berichte import fmt
    kf = berechnung.kraftstoff()
    zeilen = []
    for text, schluessel, stellen, einheit, besser in VERGLEICH_ZEILEN:
        if nur is not None and schluessel not in nur:
            continue
        if isinstance(schluessel, tuple):
            a, b = ka[schluessel[0]][schluessel[1]], kb[schluessel[0]][schluessel[1]]
        else:
            a, b = ka.get(schluessel), kb.get(schluessel)
        if schluessel == "kfz_steuer_eauto" and not a and not b:
            continue        # solange das E-Auto steuerfrei ist, nur Rauschen
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
            "text": _(text).format(**kf),
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
    if daten.get("fahrzeuge"):
        return _monatswerte_summe(z, daten)
    f = filtern(z, daten)
    cfg = daten["cfg"]
    km_m = {x["datum"][:7]: x["km"] for x in f["fahrten"]}
    preis_m = {b["monat"][:7]: b["preis_liter"] for b in daten["benzin"]}
    avg = berechnung.durchschnitt_benzinpreis(daten["benzin"])
    akku_m = {a["monat"]: a for a in f["akku"]}
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
        # Der Akku-Teil hat eigene km: nur die gewerteten Fahrtabschnitte, nicht
        # die monatlich erfassten Gesamtkilometer. Nur so passen km, kWh und
        # Verbrauch in einer Zeile zusammen.
        a = akku_m.get(m)
        werte.append({
            "monat": m,
            "km": round(km, 1),
            "kwh": round(kwh, 1),
            "strom_kosten": round(kosten, 2),
            "ersparnis": round(benzin - kosten, 2),
            "verbrauch": round(kwh / km * 100, 2) if km and kwh else None,
            "km_akku": a["km"] if a else None,
            "kwh_akku": a["kwh"] if a else None,
            "verbrauch_akku": a["verbrauch"] if a else None,
        })
    return werte


def _monatswerte_summe(z: dict, daten: dict) -> list:
    """Monatswerte der Gesamtsicht: je Fahrzeug gerechnet, Monat fuer Monat addiert."""
    summe = {m: {"monat": m, "km": 0.0, "kwh": 0.0, "strom_kosten": 0.0, "ersparnis": 0.0,
                 "km_akku": None, "kwh_akku": None}
             for m in monate(z, daten)}
    for _f, d in daten["fahrzeuge"]:
        for w in monatswerte(z, d):
            s = summe.get(w["monat"])
            if s is None:
                continue
            for k in ("km", "kwh", "strom_kosten", "ersparnis"):
                s[k] += w[k]
            for k in ("km_akku", "kwh_akku"):
                if w[k]:
                    s[k] = (s[k] or 0) + w[k]
    werte = []
    for s in summe.values():
        werte.append({
            **s,
            "km": round(s["km"], 1), "kwh": round(s["kwh"], 1),
            "strom_kosten": round(s["strom_kosten"], 2), "ersparnis": round(s["ersparnis"], 2),
            "verbrauch": round(s["kwh"] / s["km"] * 100, 2) if s["km"] and s["kwh"] else None,
            "verbrauch_akku": (round(s["kwh_akku"] / s["km_akku"] * 100, 2)
                               if s["km_akku"] and s["kwh_akku"] else None),
        })
    return werte


def akku_monatszeilen(wa: list, wb: list) -> list:
    """Akku-Verbrauch Monat fuer Monat, beide Zeitraeume nebeneinander.

    Gepaart wie im Verlaufsdiagramm: erster Monat von A neben erstem von B.
    Die letzte Zeile ist die Summe – der Verbrauch darin ist ueber Σ kWh ÷ Σ km
    gewichtet, nicht der Mittelwert der Monatswerte.

    Leer, wenn in keinem der beiden Zeitraeume Akku-Daten liegen – eine Tabelle
    aus lauter Gedankenstrichen sagt weniger als ein Hinweis, woher sie kaemen.
    """
    from charts import monatskuerzel

    if not any(w["kwh_akku"] for w in wa + wb):
        return []

    def kuerzel(werte, i):
        if i >= len(werte):
            return None
        m = werte[i]["monat"]
        return f"{monatskuerzel(int(m[5:7]))} {m[2:4]}"

    def zelle(werte, i):
        if i >= len(werte):
            return {"km": None, "kwh": None, "verbrauch": None}
        w = werte[i]
        return {"km": w["km_akku"], "kwh": w["kwh_akku"], "verbrauch": w["verbrauch_akku"]}

    def summe(werte):
        km = sum(w["km_akku"] or 0 for w in werte)
        kwh = sum(w["kwh_akku"] or 0 for w in werte)
        return {"km": round(km, 1) if km else None,
                "kwh": round(kwh, 2) if kwh else None,
                "verbrauch": round(kwh / km * 100, 2) if km else None}

    zeilen = []
    for i in range(max(len(wa), len(wb))):
        ka, kb = kuerzel(wa, i), kuerzel(wb, i)
        zeilen.append({
            "monat": ka if ka == kb or kb is None else (kb if ka is None else f"{ka} · {kb}"),
            "a": zelle(wa, i), "b": zelle(wb, i), "summe": False,
        })
    if zeilen:
        zeilen.append({"monat": _("Summe"), "a": summe(wa), "b": summe(wb), "summe": True})
    return zeilen
