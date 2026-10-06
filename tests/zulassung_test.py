# -*- coding: utf-8 -*-
"""
Test: Erstzulassung, Zulassung auf den Halter (Gebrauchtwagen) und km-Stand bei Kauf.

- Monate vor der Zulassung zaehlen nicht (KFZ-Steuer-Ersparnis, Monatsanzahl,
  Amortisation), der Zulassungsmonat tagesgenau anteilig
- Gebrauchtwagen: es zaehlt die Zulassung auf den Halter; die Erstzulassung bestimmt den
  Vorschlag fuer das Ende der Steuerbefreiung
- km im Kaufmonat = Kilometerstand am Monatsende − km-Stand bei Kauf
Laeuft gegen eine eigene Test-DB; Datenbank und HA werden durch Attrappen ersetzt.

Aufruf (aus dem Repo-Ordner):
    python tests/zulassung_test.py
"""
import os, sys, tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_zulassung_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, zeitraum

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def nah(a, b, tol=0.01):
    return a is not None and abs(a - b) <= tol


def anschaffung(**werte):
    return c.post("/einstellungen/anschaffung", data={"eauto": "", **werte},
                  follow_redirects=False)


# ── Testdaten: 2025, je Monat 1.000 km, Steuer Verbrenner 120 €/Jahr ──────────
for m in range(1, 13):
    c.post("/fahrten", data={"monat": f"2025-{m:02d}", "km": "1000"}, follow_redirects=False)
c.post("/steuer/kfz", data={"betrag": "120"}, follow_redirects=False)


def kz(schluessel):
    return zeitraum.kennzahlen(zeitraum.aufloesen(schluessel), zeitraum.laden())


k = kz("2025")
check("Ohne Zulassung: 12 Monate, 120 € Steuer", k["monate"] == 12 and nah(k["kfz_steuer"], 120),
      f'{k["monate"]} / {k["kfz_steuer"]:.2f}')

# ── Neuwagen, Erstzulassung 16.05.2025: Mai 16/31, Juni–Dez voll ───────────────
r = anschaffung(erstzulassung="2025-05-16")
check("Speichern Erstzulassung", r.status_code == 303 and zeitraum.erstzulassung() == "2025-05-16")
anteil = 16 / 31 + 7
k = kz("2025")
check("Jahr 2025: Monate ab Mai", k["monate"] == 8, str(k["monate"]))
check("Jahr 2025: Steuer tagesgenau anteilig", nah(k["kfz_steuer"], 120 * anteil / 12),
      f'{k["kfz_steuer"]:.2f} / soll {120 * anteil / 12:.2f}')
check("Q1 2025: keine Monate, keine Steuer", kz("2025-Q1")["monate"] == 0
      and nah(kz("2025-Q1")["kfz_steuer"], 0))
k = kz("alles")
check("Gesamt: Steuer ab Zulassung", nah(k["kfz_steuer"], 120 * anteil / 12), f'{k["kfz_steuer"]:.2f}')
reihe = zeitraum.ersparnis_je_monat(zeitraum.laden())
check("Amortisationsreihe beginnt im Mai", min(reihe) == "2025-05", min(reihe))
r = c.get("/?zeitraum=2025")
check("Dashboard: 7,5 Monate", "anteilig für 7,5 Monate" in r.text)
check("Einstellungen zeigen das Datum", 'value="2025-05-16"' in c.get("/einstellungen").text)
r = c.get("/steuer")
check("Steuerseite: Vorschlag steuerpflichtig ab 05/2035",
      'value="2035-05"' in r.text and "05/2035" in r.text)

# ── Gebrauchtwagen: Erstzulassung 2022, auf mich zugelassen 01.09.2025 ────────
anschaffung(erstzulassung="2022-03-10", zulassung_eigen="2025-09-01", km_bei_kauf="35.000")
k = kz("2025")
check("Gebraucht: Steuer ab eigener Zulassung (4 Monate)",
      k["monate"] == 4 and nah(k["kfz_steuer"], 40), f'{k["monate"]} / {k["kfz_steuer"]:.2f}')
check("Gebraucht: Vorschlag aus der Erstzulassung (03/2032)",
      'value="2032-03"' in c.get("/steuer").text)
check("Gebraucht: km bei Kauf gespeichert", db.get_einstellung("km_bei_kauf") == 35000)
check("Steuerfrei bis: laengstens Ende 2035", zeitraum.steuerfrei_bis("2029-06-01") == "2036-01")
check("Steuerfrei bis: Zulassung nach 2030 sofort", zeitraum.steuerfrei_bis("2031-02-03") == "2031-02")

# ── km im Kaufmonat aus dem Kilometerstand ───────────────────────────────────
class Quelle:
    name = "Testquelle"
    grund = {}

    def monatswert(self, key, j, m):
        self.grund[key] = "kein Wert vor dem Monat (nötig für die Differenz)"
        return None

    def beschreibung(self, key):
        return "Test"

    def monat_stand(self, key, j, m):
        return 36_234.0 if (j, m) == (2025, 9) else None


cfg = db.get_ha_settings()
check("HA-Einstellungen: Kaufmonat und km", cfg["kauf_monat"] == "2025-09"
      and cfg["km_bei_kauf"] == 35000, f'{cfg["kauf_monat"]} {cfg["km_bei_kauf"]}')
w = webapp._fetch_monat(None, Quelle(), cfg, 2025, 9, nur=("km",))
check("Kaufmonat: Stand Monatsende − km bei Kauf", nah(w["km"], 1234) and not w["_grund"],
      str(w))
w = webapp._fetch_monat(None, Quelle(), cfg, 2025, 10, nur=("km",))
check("Anderer Monat: unveraendert", w["km"] is None, str(w))

# ── Simulationsmodus: noch kein E-Auto, Zulassung gilt nicht ──────────────────
db.set_einstellung("simulation", "1")
check("Simulation: alle 12 Monate", kz("2025")["monate"] == 12)
db.set_einstellung("simulation", "0")

# ── Leeren: wieder alle Monate ───────────────────────────────────────────────
anschaffung(erstzulassung="", zulassung_eigen="", km_bei_kauf="")
k = kz("2025")
check("Ohne Datum wieder 12 Monate", k["monate"] == 12 and nah(k["kfz_steuer"], 120))

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
