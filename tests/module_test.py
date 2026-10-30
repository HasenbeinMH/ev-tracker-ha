# -*- coding: utf-8 -*-
"""
Test: Module (module.py) – Standards, Schalter, Menue, Umleitung der Seiten, Dashboard-
Filter, Einstellungen; Daten bleiben beim Ausschalten erhalten.

Laeuft gegen eine eigene Test-DB; Home Assistant wird nicht gebraucht.

Aufruf (aus dem Repo-Ordner):
    python tests/module_test.py
"""
import os, sys, tempfile, json

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_module_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, module, dashboard_layout as dl

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


# ── Standards ────────────────────────────────────────────────────────────────
check("Standard: Akku und Profil an, Rest aus", module.alle() ==
      {"akku": True, "profil": True, "leasing": False, "energie": False, "fahrtenbuch": False},
      str(module.alle()))
db.set_einstellung("leasing_aktiv", "1")
db.save_ha_settings({"ha_ev_tagesstatistik": "sensor.ev3_tagliche_fahrstatistik"})
check("Standard folgt Leasing-Vertrag und Fahrstatistik", module.an("leasing") and module.an("energie"))
db.set_einstellung("leasing_aktiv", "0")
db.save_ha_settings({"ha_ev_tagesstatistik": ""})

# ── Menue und Seiten ─────────────────────────────────────────────────────────
html = c.get("/").text
check("Menue: Akku und Profil, ohne Energie und Fahrtenbuch",
      'href="akku"' in html and 'href="profil"' in html
      and 'href="energie"' not in html and 'href="fahrtenbuch"' not in html)
r = c.get("/energie", follow_redirects=False)
check("Ausgeschaltetes Modul leitet um", r.status_code == 303
      and r.headers["location"].startswith("einstellungen?meldung=") and r.headers["location"].endswith("#module"),
      r.headers.get("location"))
r = c.post("/fahrtenbuch/neu", follow_redirects=False)
check("Formular eines ausgeschalteten Moduls: 404", r.status_code == 404)

r = c.post("/einstellungen/module", data={"profil": "1", "energie": "1", "fahrtenbuch": "1"},
           follow_redirects=False)
check("Schalter gespeichert", r.status_code == 303 and module.alle() ==
      {"akku": False, "profil": True, "leasing": False, "energie": True, "fahrtenbuch": True},
      str(module.alle()))
html = c.get("/").text
check("Menue folgt den Schaltern", 'href="akku"' not in html and 'href="energie"' in html
      and 'href="fahrtenbuch"' in html)
check("Seiten der eingeschalteten Module laden",
      all(c.get(p).status_code == 200 for p in ("/energie", "/fahrtenbuch", "/profil")))
check("Akku-Seite leitet um", c.get("/akku", follow_redirects=False).status_code == 303)

# ── Einstellungen ────────────────────────────────────────────────────────────
html = c.get("/einstellungen").text
check("Einstellungen: Abschnitt Module mit Karten", 'id="module"' in html and html.count('class="modul-karte') == 5)
check("Einstellungen: Sensoren nur eingeschalteter Module", 'name="ha_ev_tagesstatistik"' in html
      and 'name="ha_ev_ort"' in html and 'name="ha_ev_soh"' not in html)
check("Einstellungen: Fahrtenbuch-Abschnitt, kein Leasing", 'id="fahrtenbuch"' in html and 'id="leasing"' not in html)

# ── Dashboard ────────────────────────────────────────────────────────────────
layout = dl.standard()
for k in layout["kacheln"]:
    if k["id"] in ("soh", "klima_anteil"):
        k["an"] = True
c.post("/api/dashboard/layout", json=dl.ohne(layout, module.ausgeblendet()))
gespeichert = dl.laden()
check("Ausgeblendete Kacheln behalten Wert und Platz beim Speichern",
      next(k for k in gespeichert["kacheln"] if k["id"] == "soh")["an"] is False
      and [k["id"] for k in gespeichert["kacheln"]] == [k["id"] for k in dl.standard()["kacheln"]],
      str([k["id"] for k in gespeichert["kacheln"]]))
html = c.get("/").text
check("Dashboard: Akku-Kacheln fehlen, Energie-Kachel da",
      'data-id="soh"' not in html and 'data-id="klima_anteil"' in html)

# ── Daten bleiben ────────────────────────────────────────────────────────────
db.add_soh_messung({"datum": "2026-10-01", "soh": 97.0, "quelle": "obd"})
c.post("/einstellungen/module", data={"akku": "1"}, follow_redirects=False)
check("Daten eines aus- und wieder eingeschalteten Moduls bleiben", len(db.get_soh_messungen()) == 1
      and c.get("/akku").status_code == 200)

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
