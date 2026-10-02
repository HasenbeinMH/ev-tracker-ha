# -*- coding: utf-8 -*-
"""
Test der Amortisation (Mehrpreis des E-Autos gegen die aufsummierte Gesamt-Ersparnis).

Legt ein Jahr Testdaten ueber die Formular-Endpunkte an, traegt Kaufpreise ein und prueft
Rechnung, Prognose, Sonderfaelle (amortisiert, kein Mehrpreis, Prognose zu weit),
Dashboard-Anzeige in Deutsch und Englisch und die Gesamtsicht mehrerer Fahrzeuge.
Laeuft gegen eine eigene Test-DB in einem temporaeren Ordner.

Aufruf (aus dem Repo-Ordner):
    python tests/amortisation_test.py
"""
import os, sys, tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_amortisation_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, zeitraum, charts

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def nah(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


def preise(eauto="", verbrenner="", foerderung=""):
    return c.post("/einstellungen/anschaffung", data={
        "eauto": eauto, "verbrenner": verbrenner, "foerderung": foerderung},
        follow_redirects=False)


# ── Leere Datenbank ──────────────────────────────────────────────────────────
r = c.get("/")
check("Leere DB: Dashboard laedt", r.status_code == 200, f"HTTP {r.status_code}")
check("Leere DB: keine Amortisation ohne Kaufpreis", 'id="amortisation"' not in r.text)
r = c.get("/einstellungen")
check("Einstellungen: Abschnitt Anschaffung", 'id="anschaffung"' in r.text)
preise("42.000", "40.000", "1.000")
r = c.get("/")
check("Kaufpreis ohne Fahrdaten: Dashboard laedt", r.status_code == 200, f"HTTP {r.status_code}")
check("Kaufpreis ohne Fahrdaten: Rechnung ohne Fehler",
      zeitraum.amortisation(zeitraum.laden())["erspart"] == 0)

# ── Testdaten: 2025, je Monat 1.000 km, 150 kWh oeffentlich zu 50 ct ──────────
db.set_einstellung("benziner_verbrauch", 7.0)
MONATE = [f"2025-{m:02d}" for m in range(1, 13)]
for m in MONATE:
    c.post("/fahrten", data={"monat": m, "km": "1000"}, follow_redirects=False)
    c.post("/benzin", data={"monat": m, "preis": "1,80"}, follow_redirects=False)
    c.post("/laden", data={"datum": m + "-15", "kwh": "150", "preis_kwh": "50",
                           "blockier": "", "anbieter": "EnBW", "leistung": "150",
                           "ladetyp": "DC"}, follow_redirects=False)
c.post("/steuer/kfz", data={"betrag": "120"}, follow_redirects=False)
c.post("/steuer/thg", data={"datum": "2025-06-10", "betrag": "120", "anbieter": "ADAC"},
       follow_redirects=False)

# je Monat: Benzin 1.000/100 × 7 × 1,80 = 126 €, Strom 75 € -> 51 €, Steuer 10 € -> 61 €
# Jahr: 12 × 61 + 120 THG = 852 €
daten = zeitraum.laden()
reihe = zeitraum.ersparnis_je_monat(daten)
kz = zeitraum.kennzahlen(zeitraum.aufloesen("alles"), daten)
check("Monatsreihe: 12 Monate", sorted(reihe) == MONATE, str(sorted(reihe)))
check("Monatsreihe: Juni mit THG", nah(reihe["2025-06"], 181), f'{reihe["2025-06"]:.2f}')
check("Summe der Monate = Gesamt-Ersparnis des Dashboards",
      nah(sum(reihe.values()), kz["ersparnis_gesamt"]),
      f'{sum(reihe.values()):.2f} / {kz["ersparnis_gesamt"]:.2f}')
check("Gesamt-Ersparnis 852 €", nah(kz["ersparnis_gesamt"], 852), f'{kz["ersparnis_gesamt"]:.2f}')

# ── Mehrpreis 1.000 €: noch nicht amortisiert, Prognose ───────────────────────
a = zeitraum.amortisation(daten)
check("Mehrpreis 42.000 − 40.000 − 1.000 = 1.000", nah(a["mehrpreis"], 1000), str(a["mehrpreis"]))
check("Anteil 85,2 %", nah(a["anteil"], 85.2), f'{a["anteil"]:.2f}')
check("Rest 148 €", nah(a["rest"], 148), f'{a["rest"]:.2f}')
check("Noch nicht amortisiert", a["erreicht"] is None and a["ueberschuss"] is None)
check("Ø je Monat 71 € (12 abgeschlossene Monate)",
      nah(a["je_monat"], 71) and a["basis_monate"] == 12, f'{a["je_monat"]:.2f} / {a["basis_monate"]}')
check("Prognose: 3 Monate nach Dezember 2025 = 2026-03",
      a["prognose_monate"] == 3 and a["prognose"] == "2026-03",
      f'{a["prognose_monate"]} / {a["prognose"]}')
check("Kumuliert endet bei 852 €", nah(a["kumuliert"][-1], 852), str(a["kumuliert"][-1]))

opt = charts.chart_amortisation(a)
check("Diagramm: 12 Monate + 3 Prognose", len(opt["xAxis"]["data"]) == 15
      and opt["xAxis"]["data"][-1] == "2026-03", str(opt["xAxis"]["data"][-3:]))
check("Diagramm: Prognose erreicht den Mehrpreis",
      opt["series"][2]["data"][-1] >= 1000, str(opt["series"][2]["data"][-1]))

r = c.get("/")
check("Dashboard: Abschnitt Amortisation", 'id="amortisation"' in r.text)
check("Dashboard: 85 % hereingeholt", "85 % hereingeholt" in r.text)
check("Dashboard: Prognose 03/2026", "03/2026" in r.text)
check("Dashboard: Diagramm-Daten", 'id="opt-amortisation"' in r.text)
r = c.get("/?zeitraum=2025-Q1")
check("Anderer Zeitraum: Amortisation bleibt beim Gesamtwert", "85 % hereingeholt" in r.text)

# ── Mehrpreis 500 €: amortisiert ──────────────────────────────────────────────
preise("40.500", "40.000", "")
a = zeitraum.amortisation(zeitraum.laden())
# kumuliert: Jan–Mai 5 × 61 = 305, Juni + 181 = 486, Juli + 61 = 547 -> Juli
check("Amortisiert im Juli 2025", a["erreicht"] == "2025-07", str(a["erreicht"]))
check("352 € im Plus", nah(a["ueberschuss"], 352), str(a["ueberschuss"]))
check("Keine Prognose noetig", a["prognose"] is None)
check("Dashboard: Amortisiert seit 07/2025", "Amortisiert seit 07/2025" in c.get("/").text)

# ── Foerderung hoeher als der Mehrpreis ───────────────────────────────────────
preise("40.000", "38.000", "3.000")
a = zeitraum.amortisation(zeitraum.laden())
check("Kein Mehrpreis erkannt", a["kein_mehrpreis"] and a["anteil"] is None)
check("Dashboard: Kein Mehrpreis", "Kein Mehrpreis" in c.get("/").text)

# ── Prognose ueber 15 Jahre ───────────────────────────────────────────────────
preise("1.000.000", "0", "0")
a = zeitraum.amortisation(zeitraum.laden())
check("Prognose zu weit", a["zu_weit"] and a["prognose"] is None)
check("Dashboard: mehr als 15 Jahre", "mehr als 15 Jahre" in c.get("/").text)

# ── Kaufpreis leeren blendet aus, Eingaben bleiben formatiert ─────────────────
preise("42.000", "40.000", "1.000")
r = c.get("/einstellungen")
check("Einstellungen: Werte im deutschen Format", 'value="42.000"' in r.text
      and "Mehrpreis: 1.000 €" in r.text)
check("Ungueltige Eingabe aendert nichts",
      preise("abc", "40.000", "1.000").status_code == 303
      and db.get_einstellung("anschaffung_eauto") == 42000)
preise("", "40.000", "1.000")
check("Leerer Kaufpreis: ausgeblendet", zeitraum.amortisation(zeitraum.laden()) is None
      and 'id="amortisation"' not in c.get("/").text)

# ── Englisch ─────────────────────────────────────────────────────────────────
preise("42.000", "40.000", "1.000")
c.post("/einstellungen/sprache", data={"sprache": "en"}, follow_redirects=False)
r = c.get("/")
check("Englisch: Dashboard", "Payback of the extra cost" in r.text and "85 % recovered" in r.text)
check("Englisch: keine deutschen Reste", "hereingeholt" not in r.text and "Mehrpreis" not in r.text)
check("Englisch: Einstellungen", "Purchase price EV" in c.get("/einstellungen").text)
c.post("/einstellungen/sprache", data={"sprache": "de"}, follow_redirects=False)

# ── Gesamtsicht: nur Fahrzeuge mit Kaufpreis zaehlen ─────────────────────────
einzeln = zeitraum.laden()
zweit = {**einzeln, "anschaffung": {"eauto": 30000.0, "verbrenner": 29500.0,
                                    "foerderung": 0.0, "mehrpreis": 500.0}}
ohne = {**einzeln, "anschaffung": None}
gesamt = {"fahrzeuge": [({"id": 1, "name": "Auto A"}, einzeln),
                        ({"id": 2, "name": "Auto B"}, zweit),
                        ({"id": 3, "name": "Auto C"}, ohne)]}
a = zeitraum.amortisation(gesamt)
check("Gesamtsicht: Mehrpreise addiert", nah(a["mehrpreis"], 1500), str(a["mehrpreis"]))
check("Gesamtsicht: Ersparnis nur der Fahrzeuge mit Kaufpreis", nah(a["erspart"], 2 * 852),
      str(a["erspart"]))
check("Gesamtsicht: Namen", a["fahrzeuge"] == ["Auto A", "Auto B"] and a["ohne"] == ["Auto C"])
check("Gesamtsicht ohne Kaufpreise: ausgeblendet",
      zeitraum.amortisation({"fahrzeuge": [({"id": 3, "name": "C"}, ohne)]}) is None)

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
