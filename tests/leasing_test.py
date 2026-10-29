# -*- coding: utf-8 -*-
"""
Test: Leasing-Kilometer (leasing.py) – Soll, Ist, Prognose, Freigrenze, Euro –, die
Einstellungen, die Karte auf der Seite Fahrten, der Dashboard-Bereich und der Monatsbericht.

Laeuft gegen eine eigene Test-DB; Home Assistant wird nicht gebraucht.

Aufruf (aus dem Repo-Ordner):
    python tests/leasing_test.py
"""
import os, sys, tempfile, json
from datetime import date

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_leasing_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, leasing, berichte, dashboard_layout

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def nah(a, b, tol=0.5):
    return a is not None and b is not None and abs(a - b) <= tol


V = {"start": date(2025, 1, 1), "ende": date(2028, 1, 1), "km_jahr": 15000.0, "km_start": 0.0,
     "toleranz": 2500.0, "mehr_ct": 8.0, "minder_ct": 4.0}
# 2025 jeden Monat 1.700 km -> ab 2026 je Monat wie im Vorjahr
FAHRTEN = [{"datum": f"2025-{m:02d}", "km": 1700.0} for m in range(1, 13)]

l = leasing.auswertung(heute=date(2026, 1, 1), v=V, fahrten=FAHRTEN, stand=20400.0)
check("Vertrags-km", nah(l["vertrag_km"], 15000 * 1095 / 365.25))
check("Soll heute", nah(l["soll"], 15000 * 365 / 365.25))
check("Ist aus dem km-Stand", l["ist"] == 20400 and nah(l["differenz"], 20400 - 15000 * 365 / 365.25))
# Rest: 2026 je Monat 1.700 km (ohne 1.1.), 2027 und der 1.1.2028 ohne Vorjahr -> Ø km je Tag
rest_2026 = 12 * 1700 - 1700 / 31
je_tag = 20400 / 365        # Ø der letzten 12 Monate mit km (alle aus 2025)
erwartet = 20400 + rest_2026 + 366 * je_tag
check("Prognose saisonal, sonst Ø", nah(l["prognose"], erwartet, 1), f'{l["prognose"]:.1f} / {erwartet:.1f}')
mehr = erwartet - l["vertrag_km"] - 2500
check("Mehr-km nach Freigrenze", nah(l["mehr_km"], mehr, 1) and nah(l["mehr_eur"], mehr * 0.08, 0.1)
      and l["minder_km"] == 0, f'{l["mehr_km"]:.0f}')
check("Anteile", nah(l["anteil_zeit"], 365 / 1095 * 100, 0.01))
check("Noch je Monat moeglich", l["noch_je_monat"] is not None
      and nah(l["noch_je_monat"], (l["vertrag_km"] + 2500 - 20400) / (730 / (365.25 / 12)), 0.5))
check("Verlauf aus den Monats-km, letzter = Ist", l["verlauf"][0] == {"monat": "2025-01", "km": 1700}
      and l["verlauf"][-1]["km"] == 20400, str(l["verlauf"][-2:]))

# Wenig gefahren: Minder-km
wenig = [{"datum": f"2025-{m:02d}", "km": 500.0} for m in range(1, 13)]
l2 = leasing.auswertung(heute=date(2026, 1, 1), v=V, fahrten=wenig, stand=6000.0)
check("Minder-km", l2["minder_km"] > 0 and l2["mehr_km"] == 0
      and nah(l2["minder_eur"], l2["minder_km"] * 0.04, 0.01), f'{l2["prognose"]:.0f}')
# Innerhalb der Freigrenze
genau = [{"datum": f"2025-{m:02d}", "km": 1250.0} for m in range(1, 13)]
l3 = leasing.auswertung(heute=date(2026, 1, 1), v=V, fahrten=genau, stand=15000.0)
check("Innerhalb der Freigrenze", l3["mehr_km"] == 0 and l3["minder_km"] == 0, f'{l3["ueber"]:.0f}')
# Vertrag beendet
l4 = leasing.auswertung(heute=date(2028, 3, 1), v=V, fahrten=FAHRTEN, stand=50000.0)
check("Nach Vertragsende: Prognose = Ist", l4["beendet"] and l4["prognose"] == 50000
      and l4["noch_je_monat"] is None)
# Startmonat anteilig ohne km-Stand
mitte = {**V, "start": date(2025, 1, 16)}
l5 = leasing.auswertung(heute=date(2025, 2, 28), v=mitte, fahrten=[{"datum": "2025-01", "km": 3100.0},
                                                                    {"datum": "2025-02", "km": 1000.0}],
                        stand=None)
check("Ohne km-Stand: Monats-km, Startmonat anteilig", nah(l5["ist"], 1600 + 1000), str(l5["ist"]))

# ── Einstellungen, Seiten, Bericht ───────────────────────────────────────────
check("Ohne Vertrag nichts", leasing.vertrag() is None and leasing.auswertung() is None)
r = c.post("/einstellungen/leasing", data={"aktiv": "1", "start": "2025-01-01", "ende": "2028-01-01",
                                           "km_jahr": "15.000", "km_start": "", "toleranz_km": "2.500",
                                           "mehr_ct": "8", "minder_ct": "4,5"}, follow_redirects=False)
v = leasing.vertrag()
check("Einstellungen gespeichert", r.status_code == 303 and v and v["km_jahr"] == 15000
      and v["toleranz"] == 2500 and v["minder_ct"] == 4.5 and v["km_start"] == 0, str(v))
r = c.get("/einstellungen")
check("Einstellungen zeigen den Vertrag", 'value="15.000"' in r.text and 'value="2025-01-01"' in r.text)
for m in range(1, 13):
    c.post("/fahrten", data={"monat": f"2025-{m:02d}", "km": "1700"}, follow_redirects=False)
r = c.get("/fahrten")
check("Fahrten: Leasing-Karte", r.status_code == 200 and 'id="leasing"' in r.text
      and "opt-leasing-1" in r.text, f"HTTP {r.status_code}")
layout = dashboard_layout.standard()
for b in layout["bereiche"]:
    b["an"] = b["id"] == "leasing" or b["an"]
c.post("/api/dashboard/layout", json=layout)
r = c.get("/")
check("Dashboard: Leasing-Bereich", r.status_code == 200 and "Leasing-Kilometer" in r.text
      and "20.400 von" in r.text, f"HTTP {r.status_code}")
b = berichte.monatsbericht(2025, 12)
check("Monatsbericht mit Leasing", b["leasing"] and "Leasing" in berichte.als_text(b)
      and "Leasing-Kilometer" in berichte.als_html(b))
c.post("/einstellungen/leasing", data={"start": "2025-01-01"}, follow_redirects=False)
check("Ausgeschaltet", leasing.vertrag() is None and berichte.monatsbericht(2025, 12)["leasing"] == [])

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
