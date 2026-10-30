# -*- coding: utf-8 -*-
"""
Test: Liste der Ladevorgaenge – Teile einer Heimladung (PV und Netz) stehen als eine Zeile
mit aufklappbaren Teilen; Loeschen der Zeile loescht alle Teile.

Laeuft gegen eine eigene Test-DB; Home Assistant wird nicht gebraucht.

Aufruf (aus dem Repo-Ordner):
    python tests/laden_liste_test.py
"""
import os, sys, tempfile, re

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_ladeliste_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, heimladung

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


heimladung.annehmen({"start": "2026-10-30T17:33", "ende": "2026-10-30T19:25",
                     "kwh_netz": 29.42, "kwh_pv": 0.66})
heimladung.annehmen({"start": "2026-10-29T17:37", "ende": "2026-10-29T18:50", "kwh_netz": 19.47})
db.upsert_auto_ladevorgang("2026-09-01", 100.0, 30.0, 30.0, "Privat – Netzbezug", db.AUTO_NOTIZ)
db.upsert_auto_ladevorgang("2026-09-01", 50.0, 12.0, 6.0, "Privat – PV", db.AUTO_NOTIZ)
c.post("/laden", data={"datum": "2026-10-12", "kwh": "30", "preis_kwh": "50", "anbieter": "EnBW"},
       follow_redirects=False)

g = webapp._lade_gruppen(db.get_ladevorgaenge())
teile = sorted(len(x["teile"]) for x in g)
check("Gruppen: zwei Paare, zwei einzelne", teile == [1, 1, 2, 2], str(teile))
paar = next(x for x in g if x["kopf"]["datum"] == "2026-10-30")
k = paar["kopf"]
check("Summenzeile: kWh, Kosten, Mischpreis", abs(k["menge_kwh"] - 30.08) < 0.001
      and abs(k["gesamtpreis"] - sum(t["gesamtpreis"] for t in paar["teile"])) < 0.001
      and abs(k["preis_kwh"] - k["gesamtpreis"] / 30.08 * 100) < 0.001, str(k))
check("Summenzeile: PV-Anteil", abs(k["pv_anteil"] - 0.66 / 30.08 * 100) < 0.01)
check("Netz zuerst", paar["teile"][0]["anbieter"] == "Privat – Netzbezug")
monat = next(x for x in g if x["kopf"]["datum"] == "2026-09-01")
check("Monatssumme aus PV und Netz zusammengefasst", len(monat["teile"]) == 2
      and monat["kopf"]["menge_kwh"] == 150)

# Anzahl der Ladevorgaenge in Statistik und Bericht: so viele wie Zeilen in der Liste
import berechnung, zeitraum, berichte
check("Anzahl wie Zeilen der Liste", berechnung.anzahl_ladungen(berechnung.ladevorgaenge()) == len(g) == 4,
      str(len(g)))
kz = zeitraum.kennzahlen(zeitraum.aufloesen("2026"), zeitraum.laden())
check("Statistik zaehlt die Teile einer Ladung einmal (6 Eintraege, 4 Ladungen)",
      kz["ladevorgaenge"] == 4, str(kz["ladevorgaenge"]))
check("Monatsbericht zaehlt die Monatssumme einmal",
      berichte.monatsbericht(2026, 9)["daten"]["ladevorgaenge"] == 1)

r = c.get("/laden")
html = r.text
check("Seite: Summenzeilen mit Pfeil", r.status_code == 200 and html.count('class="lade-gruppe"') == 2
      and html.count('class="aufklappen"') == 2)
check("Seite: Teile eingeklappt", len(re.findall(r'class="lade-teil" data-gruppe="g\d+" hidden', html)) == 4)

ids = [t["id"] for t in paar["teile"]]
r = c.post("/laden/delete", data={"id": ids}, follow_redirects=False)
rest = {l["id"] for l in db.get_ladevorgaenge()}
check("Loeschen der Zeile loescht beide Teile", r.status_code == 303 and not set(ids) & rest
      and len(rest) == 4, str(rest))
einzeln = next(l for l in db.get_ladevorgaenge() if l["anbieter"] == "EnBW")
c.post("/laden/delete", data={"id": einzeln["id"]}, follow_redirects=False)
check("Einzelnes Loeschen wie bisher", len(db.get_ladevorgaenge()) == 3)

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
