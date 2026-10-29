# -*- coding: utf-8 -*-
"""
Test: Nutzungsprofil, Ladeprofil und Jahresvergleich (profil.py) und die Seite /profil.

Laeuft gegen eine eigene Test-DB; Home Assistant wird nicht gebraucht.

Aufruf (aus dem Repo-Ordner):
    python tests/profil_test.py
"""
import os, sys, tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_profil_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, profil, zeitraum

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def nah(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


r = c.get("/profil")
check("Profil-Seite ohne Daten", r.status_code == 200 and "Noch keine km je Tag" in r.text,
      f"HTTP {r.status_code}")

# ── Nutzungsprofil ───────────────────────────────────────────────────────────
# Zwei Wochen ab Montag, 5.10.2026: werktags 30 km, samstags 250 km, sonntags nichts
tage = []
for i in range(14):
    tag = f"2026-10-{5 + i:02d}"
    km = 30.0 if i % 7 < 5 else (250.0 if i % 7 == 5 else 0.0)
    tage.append({"datum": tag, "km": km})
n = profil.nutzung(tage, reichweite_100=400)
check("Ø km je Wochentag", n["je_wochentag"] == [30, 30, 30, 30, 30, 250, 0], str(n["je_wochentag"]))
check("Anteil Fahrtage", nah(n["anteil_fahrtage"], 12 / 14 * 100), str(n["anteil_fahrtage"]))
check("Ø je Tag und je Fahrtag", nah(n["km_je_tag"], 800 / 14) and nah(n["km_je_fahrtag"], 800 / 12))
check("Klassen", n["klassen"] == [2, 0, 10, 0, 0, 2], str(n["klassen"]))
check("Laengster Tag", n["laengster"] == {"datum": "2026-10-10", "km": 250.0})
check("Langstrecke je Jahr", n["langstrecke"] == {"2026": 2})
check("95-%-Quantil und Akku", nah(n["quantil_km"], 250) and nah(n["quantil_akku"], 62.5), str(n))
check("Keine Tage -> None", profil.nutzung([]) is None)

# ── Ladeprofil ───────────────────────────────────────────────────────────────
ladungen = [{"start": "2026-10-05T22:00", "anstieg": 40}, {"start": "2026-10-10T13:00", "anstieg": 30},
            {"start": "kaputt", "anstieg": 5}]
lv = [{"anbieter": "Privat – PV", "menge_kwh": 100, "ladetyp": "AC"},
      {"anbieter": "Privat – Netzbezug", "menge_kwh": 50, "ladetyp": "AC"},
      {"anbieter": "EnBW", "menge_kwh": 30, "ladetyp": "DC"},
      {"anbieter": "EnBW", "menge_kwh": 20, "ladetyp": "AC"},
      {"anbieter": "EnBW", "menge_kwh": 0, "ladetyp": "AC"}]
l = profil.laden(ladungen, lv)
check("Ladungen nach Wochentag und Stunde", l["je_wochentag"][0] == 1 and l["je_wochentag"][5] == 1
      and l["je_stunde"][22] == 1 and l["je_stunde"][13] == 1 and sum(l["je_stunde"]) == 2)
check("Anteil zuhause und DC", nah(l["anteil_zuhause"], 75) and nah(l["anteil_dc"], 60), str(l))
check("Ladungen unterwegs (ohne Grundgebuehr)", l["unterwegs"] == 2)

# ── Jahresvergleich ──────────────────────────────────────────────────────────
for monat, km in (("2025-01", 1000), ("2025-02", 800), ("2026-01", 1200)):
    c.post("/fahrten", data={"monat": monat, "km": str(km)}, follow_redirects=False)
for datum in ("2025-01-10", "2026-01-12"):
    c.post("/laden", data={"datum": datum, "kwh": "200", "preis_kwh": "40", "anbieter": "EnBW"},
           follow_redirects=False)
jv = profil.jahresvergleich(zeitraum.laden())
check("Jahre", jv["jahre"] == ["2025", "2026"], str(jv["jahre"]))
check("km je Monat und Jahr", jv["werte"]["2025"]["km"][:3] == [1000, 800, None]
      and jv["werte"]["2026"]["km"][0] == 1200, str(jv["werte"]["2025"]["km"]))
check("Kosten je 100 km", nah(jv["werte"]["2025"]["kosten_100km"][0], 8.0), str(jv["werte"]["2025"]["kosten_100km"]))
check("Kennzahlen je Jahr", jv["kennzahlen"]["2025"]["gesamt_km"] == 1800)

# Tages-km in der Datenbank, Seite mit Daten
db.ersetze_fahrten_tag(None, {t["datum"]: t["km"] for t in tage})
check("Tages-km gespeichert", len(db.get_fahrten_tage()) == 14)
db.ersetze_fahrten_tag("2026-10-15", {"2026-10-15": 99.0})
tage_db = db.get_fahrten_tage()
check("Ersetzen ab Datum", len(tage_db) == 11 and tage_db[-1] == {"datum": "2026-10-15", "km": 99.0},
      str(tage_db[-3:]))
r = c.get("/profil")
check("Profil-Seite mit Daten", r.status_code == 200 and "opt-wt-1" in r.text and "jahre-km" in r.text
      and "2025" in r.text, f"HTTP {r.status_code}")

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
