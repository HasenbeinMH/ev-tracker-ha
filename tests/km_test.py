# -*- coding: utf-8 -*-
"""
Test: Monate mit Ladungen, aber ohne km (Hinweis auf dem Dashboard) und das Nachziehen
der km nach einer Ladung aus Home Assistant (/api/ladung).

Typischer Fall: Anfang Oktober sind Ladungen schon da (Push), die km kommen erst mit dem
naechtlichen Abruf – bis dahin fehlt dem Monat der Vergleich zum Verbrenner.
Laeuft gegen eine eigene Test-DB; die Datenquelle wird durch eine Attrappe ersetzt.

Aufruf (aus dem Repo-Ordner):
    python tests/km_test.py
"""
import os, sys, tempfile, threading, time

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_km_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, zeitraum, heimladung, datenquellen

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def km_von(monat):
    return {f["datum"]: f["km"] for f in db.get_fahrten_alle_als_liste()}.get(monat)


# ── Kennzahlen: Monate ohne km ───────────────────────────────────────────────
c.post("/fahrten", data={"monat": "2026-09", "km": "1200"}, follow_redirects=False)
for datum in ("2026-09-10", "2026-10-02"):
    c.post("/laden", data={"datum": datum, "kwh": "30", "preis_kwh": "40", "anbieter": "EnBW"},
           follow_redirects=False)
daten = zeitraum.laden()
kz = zeitraum.kennzahlen(zeitraum.aufloesen("alles"), daten)
check("Oktober: Ladung ohne km erkannt", kz["ohne_km"] == ["2026-10"], str(kz["ohne_km"]))
check("Verbrauch nur aus September", kz["verbrauch"] is not None and abs(kz["verbrauch"] - 2.5) < 0.01,
      str(kz["verbrauch"]))
kz_q3 = zeitraum.kennzahlen(zeitraum.aufloesen("2026-Q3"), daten)
check("Q3 ohne Hinweis", kz_q3["ohne_km"] == [])
html = c.get("/").text
check("Dashboard: Hinweis fuer 10/2026", 'id="ohne-km"' in html and "10/2026: Ladungen, aber noch keine km" in html)

# Grundgebuehr allein (0 kWh) zaehlt nicht als Ladung ohne km
c.post("/ladetarife", data={"anbieter": "EnBW", "tarif_name": "M", "gueltig_ab": "2026-06-01",
                            "preis_ac": "40", "grundgebuehr": "5"})
kz = zeitraum.kennzahlen(zeitraum.aufloesen("alles"), zeitraum.laden())
check("Grundgebuehr-Monate ohne Ladung kein Hinweis", kz["ohne_km"] == ["2026-10"], str(kz["ohne_km"]))

# Mehrere Monate: Aufzaehlung
c.post("/laden", data={"datum": "2026-05-03", "kwh": "20", "preis_kwh": "40", "anbieter": "EnBW"},
       follow_redirects=False)
html = c.get("/").text
check("Dashboard: mehrere Monate aufgezaehlt", "In 2 Monaten Ladungen, aber keine km (05/2026, 10/2026)" in html)
c.post("/fahrten", data={"monat": "2026-05", "km": "800"}, follow_redirects=False)

# ── km nachziehen ────────────────────────────────────────────────────────────
class Quelle:
    """Attrappe der Datenquelle: liefert km je Monat aus einem dict."""
    name = "TestDB"
    km = {}

    def __init__(self, cfg=None):
        self.grund = {}

    def monatswert(self, schluessel, jahr, monat):
        if schluessel != "km":
            return None
        wert = Quelle.km.get(f"{jahr}-{monat:02d}")
        if wert is None:
            self.grund[schluessel] = "keine Werte im Monat"
        return wert

    def beschreibung(self, schluessel):
        return "sensor.km"


datenquellen.aus_einstellungen = lambda cfg: Quelle()
Quelle.km = {"2026-10": 214.0}
km = webapp._km_nachziehen("2026-10", 1)
check("Nachziehen: km geschrieben", km == 214.0 and km_von("2026-10") == 214.0, f"{km} / {km_von('2026-10')}")
kz = zeitraum.kennzahlen(zeitraum.aufloesen("alles"), zeitraum.laden())
check("Danach kein Monat ohne km", kz["ohne_km"] == [], str(kz["ohne_km"]))
check("Dashboard danach ohne Hinweis", 'id="ohne-km"' not in c.get("/").text)

Quelle.km = {"2026-10": 300.0}
check("Sperre: zweiter Abruf innerhalb von 10 Minuten entfaellt",
      webapp._km_nachziehen("2026-10", 1) is None and km_von("2026-10") == 214.0)
webapp._km_zuletzt.clear()
check("Nach Ablauf der Sperre: neuer Stand", webapp._km_nachziehen("2026-10", 1) == 300.0
      and km_von("2026-10") == 300.0)

webapp._km_zuletzt.clear()
Quelle.km = {}
check("Kein Wert: nichts ueberschrieben", webapp._km_nachziehen("2026-10", 1) is None
      and km_von("2026-10") == 300.0)
log = c.get("/api/import/log").text
check("Protokoll nennt den Grund", "km nach Ladung aus HA nicht gelesen" in log
      and "keine Werte im Monat" in log, log[-400:])

webapp._km_zuletzt.clear()
Quelle.km = {"2026-10": 350.0}
db.set_einstellung("auto_import", "0")
aus = webapp._km_nachziehen("2026-10", 1)
check("Automatischer Abruf aus: kein Nachziehen", aus is None and km_von("2026-10") == 300.0, str(aus))
db.set_einstellung("auto_import", "1")

# ── Push-Ladung startet das Nachziehen ───────────────────────────────────────
aufrufe = []
fertig = threading.Event()
webapp._km_nachziehen = lambda monat, fid: (aufrufe.append((monat, fid)), fertig.set())
token = heimladung.token_neu()
r = c.post("/api/ladung", json={"start": "2026-10-03T21:15", "ende": "2026-10-03T23:40",
                                "kwh_netz": 11.5}, headers={"Authorization": f"Bearer {token}"})
fertig.wait(5)
check("Push-Ladung angenommen", r.status_code == 200 and r.json().get("ok"), r.text[:200])
check("Push-Ladung zieht km des Monats nach", aufrufe == [("2026-10", 1)], str(aufrufe))

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
