# -*- coding: utf-8 -*-
"""
Funktions- und Plausibilitaetstest EV Tracker mit Testdaten.

Legt 20 Monate Testdaten ueber die echten Formular-Endpunkte an, ruft alle Seiten auf
und vergleicht die Kennzahlen mit unabhaengig nachgerechneten Erwartungswerten.
Laeuft gegen eine eigene Test-DB in einem temporaeren Ordner – die echte
ev_tracker.db bleibt unberuehrt. Home Assistant wird nicht gebraucht.

Aufruf (aus dem Repo-Ordner):
    pip install -r webapp/requirements-web.txt httpx
    python tests/funktionstest.py

Ergebnis: Anzahl bestandener Pruefungen, Details zu Fehlern, Exit-Code 1 bei Fehlern.
Einige Erwartungen haengen vom heutigen Datum ab (laufendes Jahr, Tarif-Monate) und
sind auf Testdaten bis August 2026 ausgelegt.
"""
import os, sys, io, json, re, sqlite3, tempfile, shutil
from datetime import date

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_tracker_test_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, berechnung, zeitraum, berichte, ladetarife, unterhalt
import akkuverbrauch, ladeerkennung, pdf_parser

c = TestClient(webapp.app)
ERG = []          # (bereich, test, ok, detail)


def check(bereich, test, ok, detail=""):
    ERG.append((bereich, test, bool(ok), detail))


def nah(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


SEITEN = ["/", "/statistik", "/hilfe", "/fahrten", "/laden", "/benzin", "/stromtarif",
          "/ladetarife", "/steuer", "/instandhaltung", "/versicherung", "/import",
          "/rechnung", "/berichte", "/backup", "/einstellungen",
          "/?zeitraum=2025", "/?zeitraum=2026-Q1", "/?zeitraum=2025-S", "/?zeitraum=2025-W",
          "/?zeitraum=quatsch", "/statistik?a=2025-S&b=2025-W"]

# ── 1. Leere Datenbank: alle Seiten muessen ohne Fehler laden ─────────────────
for s in SEITEN:
    r = c.get(s)
    check("Leere DB", f"GET {s}", r.status_code == 200, f"HTTP {r.status_code}")
r = c.get("/api/bericht/vorschau?typ=monat&jahr=2026&monat=8")
check("Leere DB", "Monatsbericht-Vorschau", r.status_code == 200, f"HTTP {r.status_code}")
r = c.get("/api/bericht/vorschau?typ=jahr&jahr=2025")
check("Leere DB", "Jahresbericht-Vorschau", r.status_code == 200, f"HTTP {r.status_code}")

# ── 2. Testdaten ueber die echten Formular-Endpunkte anlegen ─────────────────
BENZ_L = 7.0
KFZ = 180.0
PV_CT = 13.0
MONATE = [f"2025-{m:02d}" for m in range(1, 13)] + [f"2026-{m:02d}" for m in range(1, 9)]
KM = dict(zip(MONATE, [980, 1050, 1210, 1340, 1420, 1510, 1620, 1480, 1300, 1180, 1020, 960,
                       900, 990, 1150, 1290, 1400, 1550, 1700, 1450]))
BENZIN = dict(zip(MONATE, [1.742, 1.761, 1.789, 1.812, 1.798, 1.771, 1.749, 1.733, 1.719, 1.705,
                           1.722, 1.738, 1.755, 1.779, 1.801, 1.824, 1.811, 1.793, 1.776, 1.759]))
# Heimladung je Monat: (Netz kWh, PV kWh) – Winter mehr Netz, Sommer mehr PV
HEIM = dict(zip(MONATE, [(150, 10), (155, 15), (150, 45), (120, 90), (90, 130), (70, 160),
                         (80, 175), (85, 140), (110, 90), (140, 40), (150, 15), (155, 10),
                         (145, 10), (150, 18), (150, 50), (115, 100), (90, 140), (75, 170),
                         (85, 190), (90, 150)]))
STROMTARIFE = [("2024-06-01", 32.0, "Grundversorgung 24"), ("2026-01-01", 28.5, "Oekostrom 26")]


def netz_ct_am(monat):
    return max((t for t in STROMTARIFE if t[0] <= monat + "-01"), key=lambda t: t[0])[1]


# Oeffentliche Ladungen: (datum, kwh, ct, blockier, anbieter, kw, typ)
OEFF = [("2025-03-14", 32.4, 59.0, None, "EnBW", 150, "DC"),
        ("2025-05-20", 18.2, 49.0, 3.60, "medl", 22, "AC"),
        ("2025-07-05", 41.0, 69.0, None, "EnBW", 150, "DC"),
        ("2025-07-06", 38.5, 69.0, None, "EnBW", 150, "DC"),
        ("2025-08-18", 22.0, 79.0, None, "Ionity", 300, "DC"),
        ("2025-12-23", 35.3, 59.0, 6.00, "EnBW", 50, "DC"),
        ("2026-03-02", 20.7, 55.0, None, "EnBW", 11, "AC"),
        ("2026-07-10", 44.2, 65.0, None, "EnBW", 150, "DC"),
        ("2026-07-24", 30.0, 45.0, None, "ARAL Pulse", 150, "DC"),
        ("2026-08-20", 25.5, 65.0, 2.40, "EnBW", 150, "DC")]

for t in STROMTARIFE:
    c.post("/stromtarif", data={"gueltig_ab": t[0], "preis": str(t[1]).replace(".", ","),
                                "name": t[2]}, follow_redirects=False)
for m in MONATE:
    c.post("/fahrten", data={"monat": m, "km": str(KM[m])}, follow_redirects=False)
    c.post("/benzin", data={"monat": m, "preis": str(BENZIN[m]).replace(".", ",")},
           follow_redirects=False)
for d, kwh, ct, bl, anb, kw, typ in OEFF:
    c.post("/laden", data={"datum": d, "kwh": str(kwh).replace(".", ","), "preis_kwh": str(ct),
                           "blockier": (str(bl).replace(".", ",") if bl else ""),
                           "anbieter": anb, "leistung": str(kw), "ladetyp": typ},
           follow_redirects=False)
# Heimladung ueber den Zeitraum-Import (wie "HA Import -> Uebernehmen")
r = c.post("/api/import/apply", json={"rows": [
    {"monat": m, "km": "", "benzin": "", "pv": HEIM[m][1], "wallbox": HEIM[m][0]}
    for m in MONATE]})
check("HA-Import", "Import uebernehmen (apply)", r.status_code == 200, f"HTTP {r.status_code}")
# Nochmal -> alles muss als Duplikat uebersprungen werden
r = c.post("/api/import/apply", json={"rows": [
    {"monat": m, "pv": HEIM[m][1], "wallbox": HEIM[m][0]} for m in MONATE]})
anz_lade = len(db.get_ladevorgaenge(limit=100000))
check("HA-Import", "Doppelter Import erzeugt keine Duplikate",
      anz_lade == len(OEFF) + 2 * len(MONATE), f"{anz_lade} Ladevorgaenge")

c.post("/steuer/kfz", data={"betrag": "180"}, follow_redirects=False)
c.post("/steuer/thg", data={"datum": "2025-03-15", "betrag": "85", "anbieter": "ADAC"},
       follow_redirects=False)
c.post("/steuer/thg", data={"datum": "2026-04-10", "betrag": "70,50", "anbieter": "ADAC"},
       follow_redirects=False)
THG = [("2025-03-15", 85.0), ("2026-04-10", 70.5)]

# Ladetarif EnBW mit Preisaenderung
for gab, ac, dc in [("2025-03-01", "59", "69"), ("2026-02-01", "55", "65")]:
    c.post("/ladetarife", data={"anbieter": "EnBW", "tarif_name": "M", "gueltig_ab": gab,
                                "preis_ac": ac, "preis_dc": dc, "grundgebuehr": "5,99",
                                "blockier_ct_min": "10", "blockier_ab_min": "240"},
           follow_redirects=False)

# Instandhaltung
INST = [("2025-04-02", "Reifen", 640.0), ("2025-11-20", "Inspektion / Wartung", 189.0),
        ("2026-05-12", "HU / AU", 142.5)]
for d, k, b in INST:
    c.post("/instandhaltung", data={"datum": d, "kategorie": k, "betrag": str(b).replace(".", ","),
                                    "werkstatt": "Test"}, follow_redirects=False)

# Versicherung: 2025 und 2026 fuers selbe Auto
for gab, gbis, grund, fs in [("2025-01-01", "2025-12-31", "612,40", "18"),
                             ("2026-01-01", "", "589,10", "18")]:
    c.post("/versicherung", data={"fahrzeug": "Test-EV", "gesellschaft": "HUK",
                                  "gueltig_ab": gab, "gueltig_bis": gbis, "deckung": "Vollkasko",
                                  "grundbeitrag": grund, "fahrerschutz": fs,
                                  "werkstattbindung": "-40", "jahreslaufleistung": "15000"},
           follow_redirects=False)

# ── 3. Erwartungswerte unabhaengig nachrechnen ───────────────────────────────
ladungen = []   # (datum, kwh, kosten, quelle)
for m in MONATE:
    netz, pv = HEIM[m]
    ladungen.append((m + "-01", netz, round(netz * netz_ct_am(m) / 100, 2), "Netzbezug"))
    ladungen.append((m + "-01", pv, round(pv * PV_CT / 100, 2), "PV-Strom"))
for d, kwh, ct, bl, *_ in OEFF:
    ladungen.append((d, kwh, round(kwh * ct / 100 + (bl or 0), 2), "Öffentlich"))


def erwartet(monate_zr, kfz_monate):
    km = sum(KM[m] for m in monate_zr)
    lad = [l for l in ladungen if l[0][:7] in monate_zr]
    kwh = sum(l[1] for l in lad)
    kosten = sum(l[2] for l in lad)
    # korrekt: Benzinkosten Monat fuer Monat mit dem Preis des Monats
    benzin_exakt = sum(KM[m] / 100 * BENZ_L * BENZIN[m] for m in monate_zr)
    # so rechnet die App: Gesamt-km x ungewichteter Durchschnittspreis
    avg = sum(BENZIN[m] for m in monate_zr) / len(monate_zr)
    benzin_app = km / 100 * BENZ_L * avg
    thg = sum(b for d, b in THG if d[:7] in monate_zr)
    return dict(km=km, kwh=kwh, kosten=kosten, benzin_exakt=benzin_exakt,
                benzin_app=benzin_app, thg=thg, kfz=KFZ * kfz_monate / 12,
                co2=km / 100 * BENZ_L * 2.37)


# Tatsaechlich gespeicherte Heimladungs-Preise pruefen (Tarif je Monat?)
falsch_tarif = []
for l in db.get_ladevorgaenge(limit=100000):
    if l["anbieter"] == "Privat – Netzbezug":
        soll = netz_ct_am(l["datum"][:7])
        if abs(l["preis_kwh"] - soll) > 0.001:
            falsch_tarif.append(f'{l["datum"][:7]}: {l["preis_kwh"]} statt {soll} ct')
check("HA-Import", "Netzbezug wird mit dem im Monat gueltigen Stromtarif bewertet",
      not falsch_tarif,
      f"{len(falsch_tarif)} Monate falsch bewertet, z.B. {falsch_tarif[:2]}" if falsch_tarif else "")
# Tarif nachtragen (Wechsel am 15.07.2025) -> importierte Monate werden neu bewertet
def netz_preis(monat):
    return next(l["preis_kwh"] for l in db.get_ladevorgaenge(limit=100000)
                if l["anbieter"] == "Privat – Netzbezug" and l["datum"].startswith(monat))
c.post("/stromtarif", data={"gueltig_ab": "2025-07-15", "preis": "30"}, follow_redirects=False)
soll_jul = round((14 * 32 + 17 * 30) / 31, 2)
check("Stromtarif", "Nachgetragener Tarif: Juli 2025 tagesgenau gewichtet",
      nah(netz_preis("2025-07"), soll_jul, 0.001), f'{netz_preis("2025-07")} / soll {soll_jul}')
check("Stromtarif", "Nachgetragener Tarif: Aug 2025 = 30 ct, Juni unveraendert 32 ct",
      netz_preis("2025-08") == 30 and netz_preis("2025-06") == 32)
tid = next(t["id"] for t in db.get_stromtarife() if t["gueltig_ab"] == "2025-07-15")
c.post("/stromtarif/delete", data={"id": tid}, follow_redirects=False)
check("Stromtarif", "Tarif geloescht -> wieder 32 ct", netz_preis("2025-08") == 32)
manuell = [l for l in db.get_ladevorgaenge(limit=100000) if l["anbieter"] == "medl"]
check("Stromtarif", "Manuelle Ladevorgaenge bleiben unberuehrt", manuell and manuell[0]["preis_kwh"] == 49)
check("Stromtarif", "Kein Tarif erfasst -> Fallback 30 ct", berechnung.netzpreis_monat("2025-01", []) == 30.0)

e1 = db.upsert_auto_ladevorgang("2031-02-01", 100, 30.0, 30.0, "Privat – Netzbezug")
e2 = db.upsert_auto_ladevorgang("2031-02-01", 100, 30.0, 30.0, "Privat – Netzbezug")
e3 = db.upsert_auto_ladevorgang("2031-02-01", 100, 28.5, 28.5, "Privat – Netzbezug")
check("HA-Import", "Naechtlicher Abruf: neu / unveraendert / Preis aktualisiert",
      (e1, e2, e3) == ("neu", "unveraendert", "aktualisiert"), str((e1, e2, e3)))
db.delete_ladevorgang(next(l["id"] for l in db.get_ladevorgaenge() if l["datum"] == "2031-02-01"))

# fuer die weiteren Checks die App-Bewertung uebernehmen
ladungen = [(l["datum"], l["menge_kwh"], l["gesamtpreis"], berechnung.stromquelle(l["anbieter"]))
            for l in db.get_ladevorgaenge(limit=100000)]

daten = zeitraum.laden()
heute = date.today()
FAELLE = {
    "alles": (MONATE, None),
    "2025": ([m for m in MONATE if m.startswith("2025")], 12),
    "2026": ([m for m in MONATE if m.startswith("2026")], heute.month if heute.year == 2026 else 12),
    "2025-Q3": (["2025-07", "2025-08", "2025-09"], 3),
    "2026-Q1": (["2026-01", "2026-02", "2026-03"], 3),
    "2025-S": ([f"2025-{m:02d}" for m in range(4, 10)], 6),
    "2025-W": (["2025-10", "2025-11", "2025-12", "2026-01", "2026-02", "2026-03"], 6),
}
for key, (mon, kfz_mon) in FAELLE.items():
    kz = zeitraum.kennzahlen(zeitraum.aufloesen(key), daten)
    e = erwartet(mon, kfz_mon if kfz_mon else 12)
    b = f"Kennzahlen {key}"
    check(b, "Gesamt-km", nah(kz["gesamt_km"], e["km"]), f'{kz["gesamt_km"]} / soll {e["km"]}')
    check(b, "Geladene kWh", nah(kz["gesamt_kwh"], e["kwh"]), f'{kz["gesamt_kwh"]:.1f} / soll {e["kwh"]:.1f}')
    check(b, "Stromkosten", nah(kz["strom_kosten"], e["kosten"]), f'{kz["strom_kosten"]:.2f} / soll {e["kosten"]:.2f}')
    diff = kz["benzin_kosten"] - e["benzin_exakt"]
    check(b, "Benziner-Kosten = Summe(km x Monatspreis)", abs(diff) < 1.0,
          f'App {kz["benzin_kosten"]:.2f} € / monatsgenau {e["benzin_exakt"]:.2f} € (Abw. {diff:+.2f} €)')
    check(b, "THG", nah(kz["thg_gesamt"], e["thg"]), f'{kz["thg_gesamt"]} / soll {e["thg"]}')
    if key == "alles":
        soll_kfz = KFZ * len(MONATE) / 12
        check(b, "KFZ-Steuer-Ersparnis ueber Gesamtzeitraum anteilig", nah(kz["kfz_steuer"], soll_kfz),
              f'App {kz["kfz_steuer"]:.2f} € fuer {len(MONATE)} Monate / soll {soll_kfz:.2f} €')
    else:
        check(b, "KFZ-Steuer anteilig", nah(kz["kfz_steuer"], e["kfz"]),
              f'{kz["kfz_steuer"]:.2f} / soll {e["kfz"]:.2f} ({kz["monate"]} Monate)')
    check(b, "CO2", nah(kz["co2_gespart"], e["co2"], 0.1), f'{kz["co2_gespart"]:.1f} / soll {e["co2"]:.1f}')
    check(b, "Gesamt-Ersparnis = Kraftstoff + KFZ + THG",
          nah(kz["ersparnis_gesamt"], kz["ersparnis_kraft"] + kz["kfz_steuer"] + kz["thg_gesamt"]))
    ant = sum(v for v in kz["anteile"].values() if v)
    check(b, "Stromquellen-Anteile summieren auf 100 %", nah(ant, 100, 0.01), f"{ant:.2f} %")
    # Plausibilitaet
    check(b, "Verbrauch laut Ladung plausibel (12–30 kWh/100km)",
          kz["verbrauch"] and 12 <= kz["verbrauch"] <= 30, f'{kz["verbrauch"]:.1f} kWh/100km')
    check(b, "Ø Strompreis plausibel (10–60 ct)", kz["strompreis_ct"] and 10 <= kz["strompreis_ct"] <= 60,
          f'{kz["strompreis_ct"]:.1f} ct/kWh')

kz_all = zeitraum.kennzahlen(zeitraum.aufloesen("alles"), daten)

# Monatschart-Summe vs. Kennzahl Kraftstoff-Ersparnis
f_all = zeitraum.filtern(zeitraum.aufloesen("alles"), daten)
ch = webapp.charts.chart_monatliche_ersparnis(f_all["fahrten"], f_all["benzin"], f_all["lade"])
summe_chart = sum(ch["series"][2]["data"])
check("Konsistenz", "Summe Monats-Ersparnis (Chart) = Kraftstoff-Ersparnis (Kachel)",
      abs(summe_chart - kz_all["ersparnis_kraft"]) < 1.0,
      f'Chart {summe_chart:.2f} € / Kachel {kz_all["ersparnis_kraft"]:.2f} €')

# Monat ohne Benzinpreis: Kachel und Diagramm muessen weiter uebereinstimmen
db.delete_benzinpreis("2026-05")
d2 = zeitraum.laden()
k2 = zeitraum.kennzahlen(zeitraum.aufloesen("alles"), d2)
f2 = zeitraum.filtern(zeitraum.aufloesen("alles"), d2)
ch2 = webapp.charts.chart_monatliche_ersparnis(
    f2["fahrten"], f2["benzin"], f2["lade"],
    ersatzpreis=berechnung.durchschnitt_benzinpreis(d2["benzin"]))
check("Konsistenz", "Monat ohne Benzinpreis: Diagramm-Summe = Kachel, Monat bleibt im Diagramm",
      abs(sum(ch2["series"][2]["data"]) - k2["ersparnis_kraft"]) < 0.5
      and "2026-05" in ch2["xAxis"]["data"],
      f'{sum(ch2["series"][2]["data"]):.2f} / {k2["ersparnis_kraft"]:.2f}')
db.set_benzinpreis("2026-05", BENZIN["2026-05"])
ch3 = webapp.charts.chart_monatliche_ersparnis(f_all["fahrten"], [], f_all["lade"])
check("Konsistenz", "Ganz ohne Benzinpreise: Diagramm mit Ersatzpreis 1,80 €/L", "series" in ch3)
avg_soll = e_all = sum(KM[m] / 100 * BENZ_L * BENZIN[m] for m in MONATE) / (sum(KM.values()) / 100 * BENZ_L)
check("Konsistenz", "Ø Benzinpreis km-gewichtet", nah(kz_all["avg_benzin"], avg_soll, 0.0001),
      f'{kz_all["avg_benzin"]:.4f} / soll {avg_soll:.4f}')

# Jahr 2025 + Jahr 2026 = Gesamt ? (2026 zaehlt KFZ bis zum laufenden Monat, Gesamt nur
# bis zum letzten Datenmonat -> Differenz = KFZ der Monate ohne Daten)
k25 = zeitraum.kennzahlen(zeitraum.aufloesen("2025"), daten)
k26 = zeitraum.kennzahlen(zeitraum.aufloesen("2026"), daten)
kfz_leer = KFZ * (k26["monate"] - 8) / 12
check("Konsistenz", "Ersparnis 2025 + 2026 = Gesamt (bis auf KFZ der datenlosen Monate)",
      abs(k25["ersparnis_gesamt"] + k26["ersparnis_gesamt"] - kfz_leer - kz_all["ersparnis_gesamt"]) < 5.0,
      f'{k25["ersparnis_gesamt"]:.2f} + {k26["ersparnis_gesamt"]:.2f} = '
      f'{k25["ersparnis_gesamt"] + k26["ersparnis_gesamt"]:.2f} / Gesamt {kz_all["ersparnis_gesamt"]:.2f}')

# Dashboard-HTML zeigt die Werte
html = c.get("/?zeitraum=alles").text
for label, wert, st in [("Gesamt-Ersparnis", kz_all["ersparnis_gesamt"], 2),
                        ("Strecke", kz_all["gesamt_km"], 0), ("kWh", kz_all["gesamt_kwh"], 1)]:
    check("Dashboard", f"{label} wird angezeigt ({berichte.fmt(wert, st)})",
          berichte.fmt(wert, st) in html)
check("Dashboard", "Zeitraum-Cookie wird gesetzt",
      "zeitraum=2025" in c.get("/?zeitraum=2025").headers.get("set-cookie", ""))

# ── 4. Alle Seiten mit Daten ────────────────────────────────────────────────
for s in SEITEN:
    r = c.get(s)
    check("Seiten mit Daten", f"GET {s}", r.status_code == 200, f"HTTP {r.status_code}")

# ── 5. Verbrauch ────────────────────────────────────────────────────────────
vs = berechnung.verbrauch_statistik()
check("Verbrauch", "Niedrigster <= Schnitt <= Hoechster",
      vs["niedrigster"]["verbrauch"] <= vs["schnitt"] <= vs["hoechster"]["verbrauch"],
      f'{vs["niedrigster"]["verbrauch"]:.1f} / {vs["schnitt"]:.1f} / {vs["hoechster"]["verbrauch"]:.1f}')

# ── 6. Laden: Blockiergebuehr, Update, Komma/Tausenderpunkt ────────────────
l_med = [l for l in db.get_ladevorgaenge() if l["anbieter"] == "medl"][0]
check("Laden", "Gesamtpreis = kWh x ct + Blockiergebuehr",
      nah(l_med["gesamtpreis"], round(18.2 * 0.49 + 3.6, 2)), f'{l_med["gesamtpreis"]}')
r = c.post("/laden/update", data={"id": l_med["id"], "datum": "2025-05-20", "kwh": "20",
                                  "preis_kwh": "49", "anbieter": "medl", "blockier": "3,6"})
check("Laden", "Bearbeiten speichert neu berechneten Preis",
      r.status_code == 200 and nah(db.get_ladevorgang(l_med["id"])["gesamtpreis"], 13.4))
c.post("/laden/update", data={"id": l_med["id"], "datum": "2025-05-20", "kwh": "18,2",
                              "preis_kwh": "49", "anbieter": "medl", "blockier": "3,6"})
r = c.post("/laden/update", data={"id": l_med["id"], "datum": "2025-05-20", "kwh": "abc",
                                  "anbieter": "medl"})
check("Laden", "Ungueltige kWh beim Bearbeiten -> Fehler 400", r.status_code == 400)
P = webapp.parse_de
for eingabe, kw, soll in [("12,5", {}, 12.5), ("12.5", {}, 12.5), ("1,789", {}, 1.789),
                          ("1.789", {}, 1.789), ("1.234", {"tausender": True}, 1234),
                          ("1.234,5", {}, 1234.5), ("1.234.567", {}, 1234567),
                          ("13.40", {"tausender": True}, 13.4), ("-40", {"tausender": True}, -40),
                          ("1 234", {"tausender": True}, 1234), ("abc", {}, None), ("", {}, None)]:
    check("Eingabe", f"parse_de({eingabe!r}, {kw}) = {soll}", P(eingabe, **kw) == soll,
          f"ergibt {P(eingabe, **kw)}")
c.post("/fahrten", data={"monat": "2031-01", "km": "1.234"}, follow_redirects=False)
check("Eingabe", "Fahrten: '1.234' km wird als 1234 km gespeichert",
      {f["monat"]: f["km"] for f in db.get_fahrten_monate()}.get("2031-01") == 1234)
db.delete_fahrt_monat("2031-01")
c.post("/benzin", data={"monat": "2031-01", "preis": "1.789"}, follow_redirects=False)
check("Eingabe", "Benzin: '1.789' bleibt 1,789 €/L",
      {b["monat"]: b["preis_liter"] for b in db.get_benzinpreise()}.get("2031-01") == 1.789)
db.delete_benzinpreis("2031-01")
c.post("/fahrten", data={"monat": "2030-01", "km": "-50"}, follow_redirects=False)
check("Eingabe", "Negative km werden abgewiesen",
      "2030-01" not in {f["monat"] for f in db.get_fahrten_monate()})

# ── 7. Ladetarife ───────────────────────────────────────────────────────────
sd = ladetarife.seite_daten()
mon = [z for z in sd["monate"] if z["anbieter"] == "EnBW"]
erster, heute_m = "2025-03", heute.strftime("%Y-%m")
anz_soll = len(zeitraum._monatsfolge(erster, heute_m))
check("Ladetarife", "Grundgebuehr in jedem Monat seit Tarifbeginn", len(mon) == anz_soll,
      f"{len(mon)} Monate / soll {anz_soll}")
z_jul = next(z for z in mon if z["monat"] == "2025-07")
soll = (41.0 * 0.69 + 38.5 * 0.69 + 5.99) / 79.5 * 100
check("Ladetarife", "Effektivpreis Juli 2025 inkl. Grundgebuehr", nah(z_jul["effektiv_ct"], soll, 0.05),
      f'{z_jul["effektiv_ct"]:.2f} / soll {soll:.2f} ct')
check("Ladetarife", "Preisaenderung -4 ct erkannt",
      any(t["diff_ac"] == -4.0 for t in sd["tarife"]))
check("Ladetarife", "Tarifwechsel ab 02/2026 greift",
      next(z for z in mon if z["monat"] == "2026-03")["tarif_ct"] == 55.0)
lhtml = c.get("/laden").text
check("Ladetarife", "Vorbelegung auf /laden mit aktuellem Abo-Preis (55/65)",
      '"ac": 55.0' in lhtml or "55.0" in lhtml)

# ── 8. Instandhaltung / Versicherung ───────────────────────────────────────
ih = unterhalt.instandhaltung_daten()
soll = sum(b for *_, b in INST) / sum(KM.values()) * 100
check("Instandhaltung", "€/100 km gesamt", nah(ih["je_100km"], soll, 0.001),
      f'{ih["je_100km"]:.2f} / soll {soll:.2f} €/100km')
check("Instandhaltung", "Kategorie-Anteile = 100 %",
      nah(sum(k["anteil"] for k in ih["kategorien"]), 100))
vd = unterhalt.versicherung_daten()
akt = vd["aktuell"][0] if vd["aktuell"] else None
check("Versicherung", "Aktiver Vertrag = 2026", akt and akt["gueltig_ab"] == "2026-01-01")
check("Versicherung", "Jahresbeitrag inkl. Bausteine (589,10+18-40)",
      akt and nah(akt["gesamt"], 567.10), f'{akt and akt["gesamt"]}')
check("Versicherung", "Aenderung zum Vorjahr -23,30 €", akt and nah(akt["diff"], -23.30),
      f'{akt and akt["diff"]}')
km12_soll = sum(KM[m] for m in MONATE if m >= "2025-09")  # letzte 12 abgeschl. Monate (Sep25–Aug26)
check("Versicherung", "Hochgerechnete Jahres-km (letzte 12 Monate)",
      vd["km_jahr"] and nah(vd["km_jahr"], km12_soll, 1), f'{vd["km_jahr"]} / soll {km12_soll}')

# ── 9. Berichte ─────────────────────────────────────────────────────────────
mb = berichte.monatsbericht(2026, 8)
e = erwartet(["2026-08"], 1)
check("Berichte", "Monatsbericht 08/2026 km/kWh/Kosten",
      nah(mb["daten"]["km"], e["km"]) and nah(mb["daten"]["kwh"], e["kwh"])
      and nah(mb["daten"]["strom_kosten"], e["kosten"]))
check("Berichte", "Monatsbericht Ersparnis", nah(mb["daten"]["ersparnis"], e["benzin_exakt"] - e["kosten"]),
      f'{mb["daten"]["ersparnis"]:.2f} / soll {e["benzin_exakt"] - e["kosten"]:.2f}')
jb = berichte.jahresbericht(2025)
s_mon = sum(m["ersparnis"] for m in jb["monate"])
check("Berichte", "Jahresbericht: Summe Monate = Jahres-Ersparnis",
      abs(s_mon - jb["daten"]["ersparnis"]) < 1.0,
      f'Monate {s_mon:.2f} € / Jahr {jb["daten"]["ersparnis"]:.2f} €')
check("Berichte", "Jahresbericht 2025 Ersparnis = Dashboard 2025 Kraftstoff-Ersparnis",
      nah(jb["daten"]["ersparnis"], k25["ersparnis_kraft"], 0.05),
      f'{jb["daten"]["ersparnis"]:.2f} / {k25["ersparnis_kraft"]:.2f}')
html_b = berichte.als_html(jb)
check("Berichte", "HTML-Bericht enthaelt 12 Monatszeilen", html_b.count("<tr><td>") >= 12 + 10)
txt = berichte.als_text(mb)
check("Berichte", "Textfassung erzeugt", "Ersparnis" in txt)
r = c.get("/api/bericht/pruefung?jahr=2026&monat=8")
check("Berichte", "Abschlusspruefung 08/2026 ohne HA -> bereit", r.status_code == 200 and r.json()["bereit"],
      json.dumps(r.json().get("offen"), ensure_ascii=False))

# ── 10. Ladeerkennung (synthetischer Akkuverlauf) ───────────────────────────
v = []
soc = 80.0
for tag in range(1, 32):
    for h in range(24):
        t = f"2026-08-{tag:02d}T{h:02d}:00"
        if tag in (3, 10, 17, 24, 31) and 1 <= h <= 6:   # naechtliche Heimladung
            soc += 8
        elif tag == 20 and h == 11:                       # Akku leerfahren vor DC-Ladung
            soc -= 40
        elif tag == 20 and 12 <= h <= 13:                 # oeffentliche DC-Ladung (+40 %)
            soc += 20
        elif 7 <= h <= 18:
            soc -= 0.6
        v.append((t, round(min(soc, 100), 1)))
        soc = min(soc, 100)
erk = ladeerkennung.erkenne_ladungen(v, 5, 58.3)
check("Ladeerkennung", "Erkennt 6 Ladungen (5x Heim, 1x DC)", len(erk) == 6,
      f"{len(erk)}: " + ", ".join(f'{x["datum"][8:]}.={x["kwh"]}kWh' for x in erk))
heim_erk = sum(x["kwh"] for x in erk if x["datum"] != "2026-08-20")
dc_erk = next(x["kwh"] for x in erk if x["datum"] == "2026-08-20")
# Realistische Erfassung: Heim-Monatssumme am 1. = erkannte kWh + 10 % Ladeverluste
heim = [{"datum": "2026-08-01", "menge_kwh": heim_erk * 0.8, "anbieter": "Privat – Netzbezug"},
        {"datum": "2026-08-01", "menge_kwh": heim_erk * 0.3, "anbieter": "Privat – PV"}]
dc = {"datum": "2026-08-20", "menge_kwh": 25.5, "anbieter": "EnBW"}
f, z = ladeerkennung.zuordnen(erk, heim + [dc])
check("Ladeerkennung", "Alles erfasst -> keine Meldung (5 Heimladungen ueber Monatssumme)",
      not f and z == 5, f"fehlend {len(f)}, zuhause {z}")
f, z = ladeerkennung.zuordnen(erk, heim)
check("Ladeerkennung", "DC-Beleg fehlt -> genau diese Ladung wird gemeldet",
      len(f) == 1 and f[0]["datum"] == "2026-08-20", f"fehlend {[x['datum'] for x in f]}")
f, z = ladeerkennung.zuordnen(erk, [dc])
check("Ladeerkennung", "Keine Heimladung erfasst -> 5 fehlend", len(f) == 5, f"fehlend {len(f)}")
orig = ladeerkennung.batterie_verlauf
ladeerkennung.batterie_verlauf = lambda j, m: v
pm = ladeerkennung.pruefe_monat(2026, 8)
ladeerkennung.batterie_verlauf = orig
check("Ladeerkennung", "pruefe_monat mit Test-DB laeuft", pm["status"] in ("ok", "fehlend"), pm["meldung"])

# ── 11. Verbrauch aus dem Akkustand ─────────────────────────────────────────
km_v, soc_v = [], []
km, soc = 10000.0, 90.0
for tag in range(1, 11):
    for h in range(24):
        t = f"2026-08-{tag:02d}T{h:02d}:00"
        if tag % 3 == 0 and h in (1, 2, 3, 4):
            soc += 12
        elif 8 <= h <= 9:
            soc -= 4.5; km += 30    # 60 km/Tag, 9 % Akku
        soc_v.append((t, soc)); km_v.append((t, km))
ab = akkuverbrauch.berechne_abschnitte(soc_v, km_v, 60.0, 5)
ok = all(nah(a["kwh"] / a["km"] * 100, 4.5 / 100 * 60 / 30 * 100, 0.3) for a in ab if a["km"] >= 5)
check("Akkuverbrauch", "Abschnitte zwischen Ladungen erkannt", len(ab) >= 3, f"{len(ab)} Abschnitte")
check("Akkuverbrauch", "Verbrauch je Abschnitt = 9 kWh/100km (Testprofil)", ok,
      ", ".join(f'{a["kwh"] / a["km"] * 100:.1f}' for a in ab if a["km"]))
db.ersetze_akku_abschnitte(None, [dict(a) for a in ab])
pmon = akkuverbrauch.pro_monat()
check("Akkuverbrauch", "Monatswert gespeichert", pmon and pmon[0]["monat"] == "2026-08",
      json.dumps(pmon))
r = c.get("/fahrten")
check("Akkuverbrauch", "Fahrten-Seite mit Akku-Abschnitten", r.status_code == 200)
r = c.post("/fahrten/akku", data={"zeitraum": "45"}, follow_redirects=False)
check("Akkuverbrauch", "Neu berechnen ohne HA -> verstaendliche Meldung", r.status_code == 303,
      r.headers.get("location", "")[:120])
# Add-on-Modus simulieren: Supervisor vorhanden, kein eigener Token
import ha_client
ha_client.IST_ADDON = True
os.environ["SUPERVISOR_TOKEN"] = "dummy"
genutzt = []
_stunden = akkuverbrauch._stundenwerte
akkuverbrauch._stundenwerte = lambda client, *a, **k: genutzt.append((client.url, client.ws_pfad)) or []
res = akkuverbrauch.verlaeufe(__import__("datetime").datetime(2026, 8, 1),
                              __import__("datetime").datetime(2026, 8, 2))
akkuverbrauch._stundenwerte = _stunden
client, _ = ladeerkennung._client()
check("Add-on", "Akkuverbrauch nutzt im Add-on den Supervisor-Zugang",
      genutzt and genutzt[0] == ("http://supervisor/core", "/websocket"), f'{genutzt} / "{res["meldung"]}"')
check("Add-on", "Ladeerkennung nutzt im Add-on den Supervisor-Zugang",
      client is not None and client.url == "http://supervisor/core")
check("Add-on", "Import nutzt weiterhin den Supervisor-Zugang",
      webapp._ha_verbindung(db.get_ha_settings())["url"] == "http://supervisor/core")
ha_client.IST_ADDON = False
os.environ.pop("SUPERVISOR_TOKEN")
check("Add-on", "Standalone ohne Token -> keine Verbindung", ladeerkennung._client()[0] is None)

# ── 12. Rechnungs-Parser (Text) ─────────────────────────────────────────────
t_enbw = ("EnBW mobility+ Rechnung\n15.03.2026  Schnellader Berlin  45,20 kWh  150 kW  0,59 €/kWh  26,67 €\n"
          "22.03.2026  Ladepunkt Essen  11,00 kWh  11 kW  0,59 €/kWh  6,49 €\n")
a, vg = pdf_parser.parse_rechnung_text(t_enbw)
check("Rechnung", "EnBW-Text: 2 Vorgaenge erkannt", a == "EnBW" and len(vg) == 2,
      "; ".join(f"{x.datum} {x.menge_kwh} kWh {x.gesamtpreis} € {x.ladetyp}" for x in vg))
check("Rechnung", "EnBW: DC/AC nach Leistung", [x.ladetyp for x in vg] == ["DC", "AC"],
      str([x.ladetyp for x in vg]))
t_medl = "medl GmbH\n05.02.2026 Ladesäule Rathaus 18,40 kWh 39 ct/kWh 7,18 €\n"
a, vg = pdf_parser.parse_rechnung_text(t_medl)
check("Rechnung", "medl-Text: Preis in ct erkannt", a == "medl" and vg and nah(vg[0].preis_kwh, 39),
      "; ".join(f"{x.datum} {x.menge_kwh} kWh {x.preis_kwh} ct {x.gesamtpreis} €" for x in vg))
t_ewe = "EWE go Abrechnung\n12.03.2026 14:32  Ladestation Oldenburg  32,50 kWh  0,4200 €/kWh  13,65 €\n"
a, vg = pdf_parser.parse_rechnung_text(t_ewe)
check("Rechnung", "EWE go: Vorgang korrekt", vg and nah(vg[0].menge_kwh, 32.5) and nah(vg[0].gesamtpreis, 13.65),
      "; ".join(f"{x.datum} {x.menge_kwh} kWh {x.preis_kwh} ct {x.gesamtpreis} €" for x in vg))
r = c.post("/api/rechnung/parse", data={"text": t_enbw})
check("Rechnung", "API parse", r.status_code == 200 and len(r.json()["vorgaenge"]) == 2)
rows = r.json()["vorgaenge"]
r1 = c.post("/api/rechnung/apply", json={"rows": rows}).json()
r2 = c.post("/api/rechnung/apply", json={"rows": rows}).json()
check("Rechnung", "Uebernehmen + Duplikatschutz", len(r1["log"]) == 2 and all("übersprungen" in x for x in r2["log"]),
      f'{r1["log"]} / {r2["log"]}')

# ── 13. Einstellungen Export/Import ────────────────────────────────────────
c.post("/einstellungen/parameter", data={"benziner_verbrauch": "7", "ev_verbrauch": "16,5",
                                         "pv_preis": "13", "co2_benzin": "2,37", "kfz_steuer": "180",
                                         "fahrzeug_name": "Test EV"}, follow_redirects=False)
check("Einstellungen", "Parameter speichern (Komma)", db.get_config()["ev_verbrauch"] == 16.5)
exp = c.get("/api/settings/export?secrets=0")
check("Einstellungen", "Export ohne Zugangsdaten", exp.status_code == 200 and "ha_token" not in exp.json()["einstellungen"])
db.set_einstellung("ev_verbrauch_default", "20")
r = c.post("/api/settings/import", files={"datei": ("e.json", exp.content, "application/json")})
check("Einstellungen", "Import stellt Werte wieder her", r.status_code == 200 and db.get_config()["ev_verbrauch"] == 16.5)
r = c.post("/api/settings/import", files={"datei": ("x.json", b'{"a":1}', "application/json")})
check("Einstellungen", "Fremde JSON wird abgelehnt", r.status_code == 400)
c.post("/einstellungen/anbieter", data={"name": "Tesla SuC", "gruenstrom": "1"}, follow_redirects=False)
check("Einstellungen", "Anbieter anlegen", any(a["name"] == "Tesla SuC" for a in db.get_lade_anbieter()))

# ── 14. Backup / Restore / Reset ────────────────────────────────────────────
r = c.get("/api/backup")
check("Backup", "Standalone ohne Token -> 403", r.status_code == 403)
webapp.IST_ADDON = True
r = c.get("/api/backup")
webapp.IST_ADDON = False
check("Backup", "Add-on: DB-Download", r.status_code == 200 and r.content.startswith(b"SQLite format 3"),
      f"{len(r.content)} Bytes")
dump = r.content
anz_vorher = db.zaehle_messdaten()
r = c.post("/api/reset", data={"bereiche": "laden,thg", "bestaetigt": "ja"})
check("Backup", "Reset Ladevorgaenge+THG", r.status_code == 200 and db.zaehle_messdaten()["laden"] == 0
      and db.zaehle_messdaten()["fahrten"] == anz_vorher["fahrten"], r.json().get("meldung", ""))
r = c.post("/api/reset", data={"bereiche": "laden", "bestaetigt": ""})
check("Backup", "Reset ohne Bestaetigung abgelehnt", r.status_code == 400)
r = c.post("/api/backup/restore", files={"datei": ("b.db", dump)}, data={"bestaetigt": "ja"})
check("Backup", "Restore stellt Daten wieder her", r.status_code == 200 and db.zaehle_messdaten() == anz_vorher,
      str(db.zaehle_messdaten()))
r = c.post("/api/backup/restore", files={"datei": ("b.db", b"kein sqlite")}, data={"bestaetigt": "ja"})
check("Backup", "Restore mit falscher Datei abgelehnt", r.status_code == 400)
check("Backup", "Sicherungskopien vor Reset/Restore angelegt",
      any(f.startswith("vor_reset") for f in os.listdir(TESTDIR))
      and any(f.startswith("vor_restore") for f in os.listdir(TESTDIR)))

# ── 15. Auto-Bild ───────────────────────────────────────────────────────────
r = c.post("/api/auto-bild", files={"bild": ("a.gif", b"GIF89a", "image/gif")})
check("Fahrzeugbild", "Falsches Format abgelehnt", r.status_code == 400)
r = c.post("/api/auto-bild", files={"bild": ("a.png", b"\x89PNG\r\n\x1a\nxx", "image/png")})
check("Fahrzeugbild", "PNG hochladen + ausliefern", r.status_code == 200 and c.get("/api/auto-bild").content.startswith(b"\x89PNG"))
c.post("/api/auto-bild/reset")
check("Fahrzeugbild", "Zuruecksetzen auf Standardbild", c.get("/api/auto-bild").headers["content-type"] == "image/jpeg")

# ── 16. Ohne HA: Import-Start / Auto-Import sauber abgewiesen ───────────────
r = c.post("/api/import/start", data={"von_monat": 1, "von_jahr": 2026, "bis_monat": 2, "bis_jahr": 2026})
check("HA-Import", "Start ohne Datenquelle -> Fehlermeldung", r.status_code == 400, r.text[:80])
r = c.post("/api/import/auto")
check("HA-Import", "Auto-Import ohne Datenquelle -> Meldung, kein Absturz", r.status_code == 200,
      str(r.json().get("protokoll")))
r = c.get("/api/import/log")
check("HA-Import", "Importprotokoll lesbar", r.status_code == 200 and r.json()["zeilen"])

# ── 17. Dynamischer Stromtarif (Kostenzaehler "Netz ins Auto") ─────────────
ct, gesamt, hinweis = berechnung.heimpreis(100, 23.4, 30.0)
check("Dyn. Tarif", "Kosten ÷ kWh = Monatspreis", ct == 23.4 and gesamt == 23.4
      and hinweis == berechnung.DYNAMISCH_NOTIZ, f"{ct} {gesamt} {hinweis}")
ct, gesamt, hinweis = berechnung.heimpreis(100, None, 30.0)
check("Dyn. Tarif", "Ohne Kosten -> Tarif", ct == 30.0 and gesamt == 30.0 and hinweis is None)
ct, gesamt, hinweis = berechnung.heimpreis(100, 400.0, 30.0)
check("Dyn. Tarif", "Unplausible Kosten (400 ct/kWh) -> Tarif mit Hinweis",
      ct == 30.0 and hinweis and "unplausibel" in hinweis, str(hinweis))


def netz_ladung(monat):
    return next((l for l in db.get_ladevorgaenge(limit=100000)
                 if l["datum"] == monat + "-01" and l["anbieter"] == berechnung.NETZBEZUG), None)


tarif_2027 = berechnung.netzpreis_monat("2027-01", db.get_stromtarife())
r = c.post("/api/import/apply", json={"rows": [
    {"monat": "2027-01", "wallbox": "120", "kosten": "26,40"},
    {"monat": "2027-02", "wallbox": "100", "kosten": "999"},
    {"monat": "2027-03", "wallbox": "80"}]})
l1, l2, l3 = netz_ladung("2027-01"), netz_ladung("2027-02"), netz_ladung("2027-03")
check("Dyn. Tarif", "Import mit Kosten: 26,40 € / 120 kWh = 22 ct, Notiz",
      l1 and nah(l1["preis_kwh"], 22.0) and nah(l1["gesamtpreis"], 26.4)
      and berechnung.ist_dynamisch(l1), str(l1))
check("Dyn. Tarif", "Import mit unplausiblen Kosten -> Stromtarif",
      l2 and nah(l2["preis_kwh"], tarif_2027) and not berechnung.ist_dynamisch(l2), str(l2))
check("Dyn. Tarif", "Import ohne Kosten -> Stromtarif",
      l3 and nah(l3["preis_kwh"], tarif_2027), str(l3))
check("Dyn. Tarif", "Protokoll nennt den Preis", any("22.0 ct/kWh" in z for z in r.json()["log"]),
      str(r.json()["log"]))
c.post("/stromtarif", data={"gueltig_ab": "2027-01-01", "preis": "40", "name": "Test 27"},
       follow_redirects=False)
l1, l3 = netz_ladung("2027-01"), netz_ladung("2027-03")
check("Dyn. Tarif", "Neuer Tarif: dynamischer Monat bleibt, fester wird neu bewertet",
      nah(l1["preis_kwh"], 22.0) and nah(l3["preis_kwh"], 40.0), f"{l1['preis_kwh']} / {l3['preis_kwh']}")

# Naechtlicher Abruf mit Kostenzaehler (Abruf nachgestellt, ohne HA)
_orig = (webapp._fetch_monat, webapp._ha_verbindung, webapp.HAClient)
FAKE = {(2027, 4): {"wallbox": 50.0, "kosten": 12.5}, (2027, 5): {"wallbox": 60.0, "kosten": None}}
webapp._ha_verbindung = lambda cfg: {"url": "http://x", "token": "t"}
webapp.HAClient = lambda **k: object()
webapp._fetch_monat = lambda client, quelle, cfg, y, m: {
    "km": None, "pv": None, "benzin": None, **FAKE[(y, m)],
    "_quelle": {k: "HA-API" for k in webapp.IMPORT_WERTE}, "_grund": {}}
try:
    webapp._auto_import([(2027, 4), (2027, 5)], quelle="test")
    l4, l5 = netz_ladung("2027-04"), netz_ladung("2027-05")
    check("Dyn. Tarif", "Auto-Import: 12,50 € / 50 kWh = 25 ct, dynamisch",
          l4 and nah(l4["preis_kwh"], 25.0) and berechnung.ist_dynamisch(l4)
          and l4["notiz"].startswith(db.AUTO_NOTIZ), str(l4))
    check("Dyn. Tarif", "Auto-Import ohne Kosten -> Stromtarif",
          l5 and nah(l5["preis_kwh"], 40.0) and not berechnung.ist_dynamisch(l5), str(l5))
    FAKE[(2027, 4)]["kosten"] = None        # Kostenwert faellt spaeter weg -> zurueck zum Tarif
    webapp._auto_import([(2027, 4)], quelle="test")
    l4 = netz_ladung("2027-04")
    check("Dyn. Tarif", "Auto-Import aktualisiert Preis und Notiz derselben Zeile",
          nah(l4["preis_kwh"], 40.0) and not berechnung.ist_dynamisch(l4)
          and sum(1 for l in db.get_ladevorgaenge(limit=100000) if l["datum"] == "2027-04-01") == 1,
          str(l4))
finally:
    webapp._fetch_monat, webapp._ha_verbindung, webapp.HAClient = _orig

db.save_ha_settings({"ha_wallbox_cost": "sensor.ev_ladung_netz_kosten"})
r = c.get("/import")
check("Dyn. Tarif", "Importseite zeigt Spalte Netz € mit Kostenzaehler",
      r.status_code == 200 and "Netz €" in r.text)
r = c.get("/einstellungen")
check("Dyn. Tarif", "Einstellungen: Zeile Kosten Netz ins Auto",
      "ha_wallbox_cost" in r.text and "sensor.ev_ladung_netz_kosten" in r.text)
r = c.get("/einrichtung")
check("Dyn. Tarif", "Einrichtung laedt", r.status_code == 200)

# ── Ausgabe ────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[2])
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
for b, t, ok, d in ERG:
    if not ok:
        print(f"FEHLER  [{b}] {t}\n        {d}")
print()
# Kennzahlen-Uebersicht zum Plausibilisieren von Hand
for key in ("alles", "2025", "2026", "2025-S", "2025-W"):
    kz = zeitraum.kennzahlen(zeitraum.aufloesen(key), zeitraum.laden())
    print(f'{kz["titel"]:<20} km={kz["gesamt_km"]:>6.0f} kWh={kz["gesamt_kwh"]:>7.1f} '
          f'Strom={kz["strom_kosten"]:>7.2f} Benzin={kz["benzin_kosten"]:>7.2f} '
          f'Ersp={kz["ersparnis_gesamt"]:>7.2f} Verbr={kz["verbrauch"]:.1f} ct={kz["strompreis_ct"]:.1f} '
          f'100km={kz["kosten_pro_100km"]:.2f}€ PV={kz["anteile"]["PV-Strom"]:.0f}%')

shutil.rmtree(TESTDIR, ignore_errors=True)
sys.exit(0 if ok_n == len(ERG) else 1)
