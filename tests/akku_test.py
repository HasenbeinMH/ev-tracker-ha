# -*- coding: utf-8 -*-
"""
Test: Akku-Gesundheit, Ladezyklen und Reichweite (akku.py), Tages-km (akkuverbrauch.tages_km)
und die Akku-Seite mit den von Hand eingetragenen SoH-Werten.

Laeuft gegen eine eigene Test-DB; Home Assistant wird nicht gebraucht.

Aufruf (aus dem Repo-Ordner):
    python tests/akku_test.py
"""
import os, sys, tempfile
from datetime import date

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_akku_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, akku, akkuverbrauch

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def nah(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


def abschnitt(start, ende, soc_a, soc_e, km_a, km_e):
    return {"start": start, "ende": ende, "soc_start": soc_a, "soc_ende": soc_e,
            "km_start": km_a, "km_ende": km_e, "kwh": round((soc_a - soc_e) / 100 * 58.3, 2),
            "km": km_e - km_a, "laufend": 0}


# ── Ladungen und Zyklen ──────────────────────────────────────────────────────
ab = [abschnitt("2026-02-01T08:00", "2026-02-05T18:00", 90, 40, 1000, 1200),
      abschnitt("2026-02-06T07:00", "2026-02-10T18:00", 85, 30, 1200, 1400),
      abschnitt("2026-03-01T07:00", "2026-03-04T18:00", 80, 50, 1400, 1500)]
lad = akku.ladungen_aus_abschnitten(list(reversed(ab)))      # Reihenfolge egal
check("Ladungen zwischen den Abschnitten", [(l["von"], l["bis"], l["anstieg"]) for l in lad]
      == [(40, 85, 45), (30, 80, 50)], str(lad))
check("Ladebeginn = Ende des Abschnitts davor", lad[0]["start"] == "2026-02-05T18:00")
z = akku.zyklen(lad, {"2026-01": 58.3, "2026-02": 99.0}, kap=58.3, verlust=10)
check("Vollzyklen aus dem Akkustand plus geschaetzter Vormonat", nah(z["vollzyklen"], 0.95 + 0.9), str(z))
check("Nur Monate vor dem ersten Akkustand geschaetzt", z["geschaetzte_monate"] == 1)
check("Zyklen je Jahr", nah(z["je_jahr"]["2026"], 1.9, 0.06), str(z["je_jahr"]))
check("Ladefenster: Ø von/bis", nah(z["von_schnitt"], 35) and nah(z["bis_schnitt"], 82.5))
check("Ladefenster: Anteile", z["anteil_voll"] == 0 and z["anteil_tief"][20.0] == 0
      and z["anteil_tief"][10.0] == 0)
check("Ladefenster: Klassen", z["von_klassen"] == [0, 1, 1, 0, 0] and z["bis_klassen"] == [0, 0, 0, 0, 2],
      f'{z["von_klassen"]} {z["bis_klassen"]}')
check("Keine Ladungen: keine Zyklen", akku.zyklen([], {}, kap=58.3)["vollzyklen"] == 0)

# ── SoH-Schaetzung ───────────────────────────────────────────────────────────
# Verbrauch laut Akku 98 % des Verbrauchs laut Wallbox -> gemessene Verluste 2 %
mw = [{"monat": f"2026-0{i}", "km": 1000, "_kwh_v": 200.0, "km_akku": 1000, "kwh_akku": 196.0}
      for i in range(1, 5)]
liste = akku.paare(mw + [{"monat": "2026-05", "km": 0, "_kwh_v": 0, "km_akku": None, "kwh_akku": None}])
check("Paare: nur Monate mit beiden Werten", len(liste) == 4)
s = akku.schaetzung(liste, 10.0)
check("Schaetzung erst ab 3 Monaten", [x["monat"] for x in s] == ["2026-03", "2026-04"], str(s))
check("SoH = (1 − Annahme) ÷ (1 − gemessen)", nah(s[-1]["soh"], 0.9 / 0.98 * 100), str(s[-1]))
check("Spanne ± 5 Prozentpunkte", nah(s[-1]["unten"], 0.85 / 0.98 * 100) and nah(s[-1]["oben"], 0.95 / 0.98 * 100))
check("Unplausibel faellt weg", akku.schaetzung(akku.paare(
    [{**m, "kwh_akku": 120.0} for m in mw]), 10.0) == [])
kal = akku.kalibrieren(liste, [{"datum": "2026-04-20", "soh": 95.0}])
check("Kalibrieren: Annahme trifft den Messwert", kal and nah(kal["annahme"], (1 - 0.95 * 0.98) * 100, 0.06),
      str(kal))
check("Kalibrieren: Schaetzung danach = Messwert",
      nah(akku.schaetzung(liste, kal["annahme"])[-1]["soh"], 95.0, 0.1))
check("Kalibrieren ohne genug Monate", akku.kalibrieren(liste[:2], [{"datum": "2026-02-01", "soh": 95}]) is None)

# ── Trend und Reichweite ─────────────────────────────────────────────────────
check("Trend in %/Jahr", nah(akku.trend([(date(2025, 1, 1), 100.0), (date(2026, 1, 1), 98.0)]), -2.0, 0.01))
check("Trend braucht 90 Tage", akku.trend([(date(2026, 1, 1), 100), (date(2026, 2, 1), 99)]) is None)
rm = akku.reichweite_monate([{"monat": "2025-01", "verbrauch": 20.0}, {"monat": "2025-07", "verbrauch": 14.0}], 58.3)
check("Reichweite = Kapazitaet ÷ Verbrauch, Fenster 80 → 20 %", rm[0]["km_100"] == 292
      and rm[0]["km_fenster"] == 175, str(rm))
rm_f = akku.reichweite_monate([{"monat": "2025-01", "verbrauch": 20.0}], 58.3, (90, 10))
check("Eigenes Fenster 90 → 10 %", rm_f[0]["km_fenster"] == 233, str(rm_f))
pg = akku.reichweite_prognose(rm, "2026-01")
check("Prognose: gleicher Monat, sonst Ø", pg[0] == {"monat": "2026-01", "km_100": 292, "km_fenster": 175, "basis": "monat"}
      and pg[1]["basis"] == "schnitt" and pg[1]["km_100"] == round((292 + 416) / 2) and pg[6]["km_100"] == 416,
      str(pg[:7]))
check("Sommer/Winter", akku.saison(rm) == {"sommer": 416, "winter": 292})

# ── Tages-km ─────────────────────────────────────────────────────────────────
tk = akkuverbrauch.tages_km([("2026-10-01T10:00", 1000.0), ("2026-10-01T20:00", 1010.0),
                             ("2026-10-03T09:00", 1050.0), ("2026-10-03T22:00", 1060.0),
                             ("2026-10-04T08:00", 1055.0), ("2026-10-05T08:00", 9999.0)])
check("Tages-km: Luecke 0, Spruenge ausgefiltert",
      tk == {"2026-10-02": 0.0, "2026-10-03": 50.0, "2026-10-04": 0.0, "2026-10-05": 0.0}, str(tk))

# ── Datenbank und Seite ──────────────────────────────────────────────────────
r = c.get("/akku")
check("Akku-Seite ohne Daten", r.status_code == 200 and "Noch kein SoH" in r.text, f"HTTP {r.status_code}")

r = c.post("/akku/soh", data={"datum": "2026-04-20", "soh": "95,0", "km_stand": "12.500",
                              "quelle": "werkstatt", "notiz": "Inspektion"}, follow_redirects=False)
m = db.get_soh_messungen()
check("SoH von Hand gespeichert", r.status_code == 303 and len(m) == 1 and m[0]["soh"] == 95.0
      and m[0]["km_stand"] == 12500 and m[0]["quelle"] == "werkstatt", str(m))
c.post("/akku/soh", data={"datum": "2026-04-21", "soh": "150"}, follow_redirects=False)
c.post("/akku/soh", data={"datum": "", "soh": "90"}, follow_redirects=False)
check("Unplausibler SoH und fehlendes Datum werden nicht gespeichert", len(db.get_soh_messungen()) == 1)
c.post("/akku/soh/update", data={"id": m[0]["id"], "datum": "2026-04-20", "soh": "94,5",
                                 "quelle": "unbekannt"}, follow_redirects=False)
m = db.get_soh_messungen()
check("SoH bearbeitet, unbekannte Quelle -> sonstiges", m[0]["soh"] == 94.5 and m[0]["quelle"] == "sonstiges", str(m))
r = c.get(f"/akku?bearbeiten={m[0]['id']}")
check("Bearbeiten fuellt das Formular", 'action="akku/soh/update"' in r.text and "94,5" in r.text)

# Fahrtabschnitte und Monatswerte fuer die Schaetzung
db.ersetze_akku_abschnitte(None, ab)
for monat in ("2026-01", "2026-02", "2026-03", "2026-04"):
    c.post("/fahrten", data={"monat": monat, "km": "1000"}, follow_redirects=False)
db.set_einstellung("erstzulassung", "2025-01-15")
a = akku.auswertung(heute=date(2026, 10, 1))
check("Auswertung: SoH aus dem Handwert", a["soh"]["quelle"] == "hand" and a["soh"]["wert"] == 94.5, str(a["soh"]))
check("Auswertung: nutzbare Kapazitaet", nah(a["nutzbar"], 58.3 * 0.945, 0.06))
check("Auswertung: km-Stand – der hoehere aus Akkustand und Monats-km", a["km_stand"] == 4000,
      str(a["km_stand"]))
db.set_einstellung("km_bei_kauf", 3000)
check("km-Stand: km bei Kauf plus Monats-km ab dem Kauf", akku.km_stand() == 7000, str(akku.km_stand()))
db.set_einstellung("km_bei_kauf", 0)
check("Auswertung: Vergleichskurve ab Erstzulassung", a["referenz"] and nah(a["referenz"]["heute"],
      100 - 1.8 * (date(2026, 10, 1) - date(2025, 1, 15)).days / 365.25, 0.06), str(a["referenz"]))
check("Auswertung: Garantie-Prognose mit Vergleichswert", a["prognose"] and a["prognose"]["aus_referenz"]
      and a["prognose"]["ende"] == "2033-01-15" and a["prognose"]["ok"], str(a["prognose"]))

r = c.post("/akku/einstellungen", data={"verlust": "8", "garantie_jahre": "10", "garantie_km": "200.000",
                                        "garantie_soh": "70"}, follow_redirects=False)
check("Einstellungen gespeichert", akku.verlust_annahme() == 8 and akku.garantie()["km"] == 200000
      and akku.garantie()["jahre"] == 10, str(akku.garantie()))
c.post("/akku/einstellungen", data={"verlust": "50"}, follow_redirects=False)
check("Unplausible Annahme bleibt beim alten Wert", akku.verlust_annahme() == 8)
c.post("/akku/einstellungen", data={"verlust": "", "garantie_jahre": "", "garantie_km": "", "garantie_soh": ""},
       follow_redirects=False)
check("Leer = Standard", akku.verlust_annahme() == akku.VERLUST_STANDARD
      and akku.garantie() == akku.GARANTIE_STANDARD)

r = c.get("/akku")
check("Akku-Seite mit Daten", r.status_code == 200 and "opt-soh-1" in r.text and "Vollzyklen" in r.text
      and "94,5" in r.text, f"HTTP {r.status_code}")
c.post("/akku/soh/delete", data={"id": m[0]["id"]}, follow_redirects=False)
check("SoH geloescht", db.get_soh_messungen() == [])
check("Neue Tabellen gehoeren je Fahrzeug", {"fahrten_tag", "soh_messung"} <= set(db.FAHRZEUG_TABELLEN))

# Sensor-Monatsmittel
mittel = akku.soh_monatsmittel([("2026-09-01T00:00", 97.0), ("2026-09-02T00:00", 96.0),
                                ("2026-10-01T00:00", 0.0)])
check("SoH-Sensor: Monatsmittel ohne Ausreisser", mittel == {"2026-09": 96.5}, str(mittel))

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
