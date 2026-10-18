# -*- coding: utf-8 -*-
"""
Test: nur eine importierte Monatssumme je Monat, Anbieter und Fahrzeug.

Anlass: Zeitraum-Import ("Import 2026-09") und naechtlicher Abruf ("Auto-Import HA")
erkannten die Monatssumme des anderen nicht – in einer Nutzer-Datenbank stand PV fuer
August zweimal (92,266 kWh), fuer September 44,429 (Teilmonat) und 73,381 kWh.
Geprueft werden die einmalige Bereinigung beim Start, beide Importe gegeneinander und
von Hand geaenderte Werte. Laeuft gegen eine eigene Test-DB.

Aufruf (aus dem Repo-Ordner):
    python tests/monatssumme_test.py
"""
import glob, os, sys, tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_monatssumme_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

import database as db

ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


PV, NETZ = "Privat – PV", "Privat – Netzbezug"


def summen(datum, anbieter=PV):
    return sorted((l["menge_kwh"], l["notiz"]) for l in db.get_ladevorgaenge(limit=100000)
                  if l["datum"] == datum and l["anbieter"] == anbieter)


# ── Datenbank wie beim Nutzer, vor dem Start der App ─────────────────────────
db.init_db()
db.add_ladevorgang("2026-08-01", 92.266, 5.0, 4.61, PV, 11, "AC", "Import 2026-08")
db.add_ladevorgang("2026-08-01", 92.266, 5.0, 4.61, PV, 11, "AC", db.AUTO_NOTIZ)
db.add_ladevorgang("2026-09-01", 44.429, 5.0, 2.22, PV, 11, "AC", "Import 2026-09")
db.add_ladevorgang("2026-09-01", 73.381, 5.0, 3.67, PV, 11, "AC", db.AUTO_NOTIZ)
db.add_ladevorgang("2026-07-01", 30.0, 32.0, 9.6, NETZ, 11, "AC", f"Import 2026-07 · {db.VON_HAND}")
db.add_ladevorgang("2026-07-01", 25.0, 32.0, 8.0, NETZ, 11, "AC", db.AUTO_NOTIZ)
# Von Hand erfasst, kein Import: bleibt immer
db.add_ladevorgang("2026-09-01", 36.7, 0.0, 0.0, PV, 11, "AC", "Garage Nachbar")
db.add_ladevorgang("2026-06-01", 51.373, 5.0, 2.57, PV, 11, "AC", "Import 2026-06")

check("Vorher: drei Monate doppelt erkannt", len(db.doppelte_monatssummen()) == 3, db.doppelte_monatssummen())

# ── Start der App: einmalige Bereinigung ─────────────────────────────────────
from fastapi.testclient import TestClient
import app as webapp
c = TestClient(webapp.app)

check("Bereinigung: August einmal", summen("2026-08-01") == [(92.266, db.AUTO_NOTIZ)], summen("2026-08-01"))
check("Bereinigung: September behaelt den spaeteren Wert und die Handladung",
      summen("2026-09-01") == [(36.7, "Garage Nachbar"), (73.381, db.AUTO_NOTIZ)], summen("2026-09-01"))
check("Bereinigung: von Hand geaenderter Wert bleibt", summen("2026-07-01", NETZ)
      == [(30.0, f"Import 2026-07 · {db.VON_HAND}")], summen("2026-07-01", NETZ))
check("Bereinigung: einzelne Monatssumme unberuehrt", summen("2026-06-01") == [(51.373, "Import 2026-06")])
check("Bereinigung: Sicherung angelegt", glob.glob(os.path.join(TESTDIR, "vor_bereinigung_*.db")))
with open(webapp.IMPORT_LOG_DATEI, encoding="utf-8") as f:
    log = f.read()
check("Bereinigung: im Importprotokoll", "Doppelte Monatssummen entfernt" in log
      and "2026-09: Privat – PV behalten 73.38 kWh, entfernt 44.43 kWh" in log, log)
check("Bereinigung: nur einmal", db.get_einstellung_str("migration_monatssumme_doppelt") == "1"
      and db.doppelte_monatssummen() == [])

# ── Zeitraum-Import und naechtlicher Abruf gegeneinander ─────────────────────
def zeitraum(monat, pv, quelle="HA-API"):
    r = c.post("/api/import/apply", json={"rows": [{"monat": monat, "pv": str(pv),
                                                    "_quelle": {"pv": quelle}}]})
    return r.json()["log"]

zeitraum("2026-11", 10.0)
check("Zeitraum-Import legt an", summen("2026-11-01") == [(10.0, "Import 2026-11")], summen("2026-11-01"))
check("Abruf ersetzt den Zeitraum-Import", db.upsert_auto_ladevorgang("2026-11-01", 12.0, 5.0, 0.6, PV)
      == "aktualisiert" and summen("2026-11-01") == [(12.0, db.AUTO_NOTIZ)], summen("2026-11-01"))
log = zeitraum("2026-11", 14.0)
check("Zeitraum-Import ersetzt den Abruf", summen("2026-11-01") == [(14.0, "Import 2026-11")]
      and "aktualisiert" in log[0], (summen("2026-11-01"), log))
check("Gleicher Wert noch einmal: unveraendert", "unveraendert" in zeitraum("2026-11", 14.0)[0])

zeitraum("2026-11", 20.0, "von Hand")
check("Von Hand geaendert: markiert", summen("2026-11-01") == [(20.0, f"Import 2026-11 · {db.VON_HAND}")],
      summen("2026-11-01"))
check("Abruf laesst den Wert von Hand", db.upsert_auto_ladevorgang("2026-11-01", 15.0, 5.0, 0.75, PV)
      == "von Hand" and summen("2026-11-01")[0][0] == 20.0, summen("2026-11-01"))
check("Einzelladungen decken den Monat: Wert von Hand bleibt",
      not db.delete_auto_ladevorgang("2026-11-01", PV) and summen("2026-11-01")[0][0] == 20.0)
zeitraum("2026-11", 18.0)
check("Neuer Zeitraum-Import ersetzt auch den Wert von Hand", summen("2026-11-01") == [(18.0, "Import 2026-11")])
check("Einzelladungen decken den Monat: Zeitraum-Summe entfernt",
      db.delete_auto_ladevorgang("2026-11-01", PV) and summen("2026-11-01") == [])

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
