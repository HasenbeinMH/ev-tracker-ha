# -*- coding: utf-8 -*-
"""
Test: Fahrtenbuch (fahrtenbuch.py) – Erkennung mit echtem 30-Minuten-Takt eines Kia EV3,
Pausen unter/ueber der Grenze, Mindeststrecke, Motor-Sensor, Handy-Positionen (Zeiten
verfeinern, Start/Ziel), Mitschnitt des Standorts, Neuberechnen behaelt Kategorie und
Notiz, CSV, Seiten und Einstellungen.

Laeuft gegen eine eigene Test-DB; Home Assistant wird durch eine Attrappe ersetzt.

Aufruf (aus dem Repo-Ordner):
    python tests/fahrtenbuch_test.py
"""
import os, sys, tempfile
from datetime import datetime, timedelta

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_fahrtenbuch_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, fahrtenbuch as fb, module

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def kurz(liste):
    return [(f["start"][11:], f["ende"][11:], f["km"]) for f in liste]


# Echte Historie eines Kia EV3 am 30.10.2026 (Abfrage alle 30 Minuten)
KM = [("2026-10-30T00:00", 239.8), ("2026-10-30T08:03", 247.2), ("2026-10-30T08:33", 291.1),
      ("2026-10-30T09:03", 321.2), ("2026-10-30T09:33", 330.9), ("2026-10-30T14:33", 338.3),
      ("2026-10-30T15:03", 350.8), ("2026-10-30T15:33", 386.9), ("2026-10-30T16:03", 418.2),
      ("2026-10-30T16:33", 425.6)]
MOTOR = [("2026-10-30T00:00", False), ("2026-10-30T08:03", True), ("2026-10-30T09:33", False),
         ("2026-10-30T14:33", True), ("2026-10-30T17:03", False)]
SOC = [("2026-10-30T00:00", 100.0), ("2026-10-30T09:33", 80.0), ("2026-10-30T17:03", 55.0)]

check("EV3 mit Motor-Sensor: zwei Fahrten", kurz(fb.fahrten(KM, motor=MOTOR)) ==
      [("08:03", "09:33", 91.1), ("14:33", "17:03", 94.7)], str(kurz(fb.fahrten(KM, motor=MOTOR))))
check("Nur Kilometerstand: dieselben Fahrten", kurz(fb.fahrten(KM)) ==
      [("08:03", "09:33", 91.1), ("14:33", "16:33", 94.7)])
f = fb.fahrten(KM, soc=SOC, motor=MOTOR, kapazitaet=81.4)[0]
check("Akku und kWh je Fahrt", f["soc_start"] == 100 and f["soc_ende"] == 80 and abs(f["kwh"] - 16.28) < 0.01, str(f))
check("Mindeststrecke", fb.fahrten([("2026-10-30T08:00", 10.0), ("2026-10-30T08:30", 10.3)]) == [])
check("Lange Pause ohne Belege trennt erst nach Pause + Takt",
      len(fb.fahrten([("2026-10-30T08:00", 0.0), ("2026-10-30T08:30", 10.0), ("2026-10-30T09:25", 20.0)])) == 1
      and len(fb.fahrten([("2026-10-30T08:00", 0.0), ("2026-10-30T08:30", 10.0), ("2026-10-30T09:35", 20.0)])) == 2)
check("Pausengrenze einstellbar", len(fb.fahrten(KM, motor=MOTOR, pause_min=400)) == 1)

# Handy-Positionen: ungenaue Zeiten des Autos verfeinern, Start und Ziel
ORTE = [{"zeit": "2026-10-29T20:00", "lat": 51.0, "lon": 6.0, "zone": "home"},
        {"zeit": "2026-10-30T07:41", "lat": 51.01, "lon": 6.0, "zone": None},
        {"zeit": "2026-10-30T08:10", "lat": 51.1, "lon": 6.2, "zone": None},
        {"zeit": "2026-10-30T09:12", "lat": 51.3, "lon": 6.5, "zone": "Arbeit"},
        {"zeit": "2026-10-30T14:20", "lat": 51.31, "lon": 6.5, "zone": None},
        {"zeit": "2026-10-30T16:40", "lat": 51.0, "lon": 6.0, "zone": "home"}]
mit = fb.fahrten(KM, motor=MOTOR, orte=ORTE)
check("Handy: Abfahrt und Ankunft genauer", kurz(mit) == [("07:41", "09:12", 91.1), ("14:20", "16:40", 94.7)],
      str(kurz(mit)))
check("Handy: Start und Ziel", [(x["start_ort"], x["ziel_ort"]) for x in mit] ==
      [("home", "Arbeit"), ("Arbeit", "home")])
check("Ort fuer die Anzeige", fb.ort_text(mit[0], "start") == "Zuhause"
      and fb.ort_text({"ziel_lat": 51.123456, "ziel_lon": 6.5}, "ziel") == "51.1235, 6.5000")

# Dichte Handy-Positionen: 20 Minuten Pause verbinden, 45 Minuten trennen
km2 = [("2026-10-31T00:00", 0.0), ("2026-10-31T08:30", 20.0), ("2026-10-31T09:30", 40.0),
       ("2026-10-31T10:30", 60.0)]
dicht = ([{"zeit": "2026-10-31T07:00", "lat": 51.0, "lon": 6.0, "zone": "home"}]
         + [{"zeit": f"2026-10-31T08:{m:02d}", "lat": 51.0 + m / 1000, "lon": 6.0, "zone": None} for m in range(5, 30, 5)]
         + [{"zeit": "2026-10-31T08:30", "lat": 51.2, "lon": 6.0, "zone": None}]
         + [{"zeit": f"2026-10-31T08:{m:02d}", "lat": 51.2 + (m - 50) / 1000, "lon": 6.0, "zone": None} for m in range(50, 60, 5)]
         + [{"zeit": f"2026-10-31T09:{m:02d}", "lat": 51.21 + m / 1000, "lon": 6.0, "zone": None} for m in range(0, 30, 5)]
         + [{"zeit": "2026-10-31T09:30", "lat": 51.3, "lon": 6.0, "zone": "Arbeit"},
            {"zeit": "2026-10-31T10:15", "lat": 51.31, "lon": 6.0, "zone": None},
            {"zeit": "2026-10-31T10:30", "lat": 51.4, "lon": 6.0, "zone": None}])
check("Meldetakt des Handys geschaetzt", fb.ort_takt(dicht) == 5.0)
check("20 min Pause verbunden, 45 min getrennt", kurz(fb.fahrten(km2, orte=dicht)) ==
      [("08:05", "09:30", 40.0), ("10:15", "10:30", 20.0)], str(kurz(fb.fahrten(km2, orte=dicht))))

# ── Standort mitschreiben ────────────────────────────────────────────────────
class FakeHA:
    pos = {"state": "home", "attributes": {"latitude": 51.0, "longitude": 6.0}}

    def __init__(self, **kw):
        pass

    def get_state_full(self, entity):
        return FakeHA.pos if entity == "device_tracker.handy" else None

    def get_history_full(self, entity, start, ende, attribute=True):
        heute = datetime.now().strftime("%Y-%m-%d")
        if entity == "sensor.km":
            return [{"state": str(v), "last_changed": f"{heute}T{t[11:]}:00"} for t, v in KM]
        if entity == "binary_sensor.motor":
            return [{"state": "on" if v else "off", "last_changed": f"{heute}T{t[11:]}:00"} for t, v in MOTOR]
        return []


import ha_client
ha_client.HAClient = FakeHA
db.save_ha_settings({"ha_url": "http://ha.test:8123", "ha_token": "x", "ha_odometer": "sensor.km",
                     "ha_ev_battery": "", "ha_ev_fahrt": "binary_sensor.motor",
                     "ha_ev_ort": "device_tracker.auto_fehlt | device_tracker.handy"})
client = FakeHA()
check("Mitschnitt: erste Position gespeichert", fb.ort_merken(1, client) and len(db.get_orte("2000")) == 1)
check("Mitschnitt: unveraendert nicht doppelt", not fb.ort_merken(1, client))
FakeHA.pos = {"state": "not_home", "attributes": {"latitude": 51.01, "longitude": 6.0}}
check("Mitschnitt: neue Position", fb.ort_merken(1, client) and db.get_orte("2000")[-1]["zone"] is None)
db.add_ort("2000-01-01T00:00", 1.0, 1.0, None)
check("Aufraeumen nach 30 Tagen", db.orte_aufraeumen((datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M")) == 1)

# ── Erkennen aus der Historie, Neuberechnen behaelt Kategorie und Notiz ──────
c.post("/einstellungen/module", data={"akku": "1", "profil": "1", "fahrtenbuch": "1"}, follow_redirects=False)
check("Modul an", module.an("fahrtenbuch"))
meldung = fb.aktualisieren(tage=1)
liste = db.get_fahrten()
check("Aus der Historie erkannt", kurz(liste) == [("08:03", "09:33", 91.1), ("14:33", "17:03", 94.7)],
      f"{meldung} / {kurz(liste)}")
monat = liste[0]["start"][:7]
c.post("/fahrtenbuch/update", data={"start": liste[0]["start"], "kategorie": "arbeitsweg",
                                    "notiz": "Büro", "monat": monat}, follow_redirects=False)
fb.aktualisieren(tage=1)
erste = db.get_fahrten()[0]
check("Neuberechnen behaelt Kategorie und Notiz", erste["kategorie"] == "arbeitsweg" and erste["notiz"] == "Büro",
      str(erste))
r = c.get(f"/fahrtenbuch?monat={monat}")
check("Seite Fahrtenbuch", r.status_code == 200 and "Büro" in r.text and "91,1" in r.text, f"HTTP {r.status_code}")
r = c.get(f"/fahrtenbuch/csv?monat={monat}")
check("CSV", r.status_code == 200 and r.text.startswith("﻿") and "Arbeitsweg" in r.text
      and "91,1" in r.text, r.text[:120])
r = c.get("/profil")
check("Profil: Abschnitt Fahrten", r.status_code == 200 and "opt-fk-1" in r.text)
r = c.post("/einstellungen/fahrtenbuch", data={"pause_min": "45", "min_km": "1,5", "adressen": ""},
           follow_redirects=False)
e = fb.einstellungen()
check("Einstellungen Fahrtenbuch", e == {"pause_min": 45, "min_km": 1.5, "adressen": False}, str(e))

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
