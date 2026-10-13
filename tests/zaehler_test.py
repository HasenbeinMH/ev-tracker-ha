# -*- coding: utf-8 -*-
"""
Test: Zaehler-Resets (zaehler.py) – Zaehler, die taeglich/monatlich zurueckgesetzt werden,
und kurze Aussetzer fortlaufender Zaehler.

Anlass: evcc-Sensor "…_monatlich" stand bei 50.21 kWh, die App zeigte fuer den Monat 17.36
(= 50.21 − 32.85 vom Vormonat). Geprueft werden die Rechenfunktion, die HA-API (Statistik
und History-Fallback), die Datenbank-Quellen und die Diagnose samt Spaltenwahl.
Laeuft gegen eine eigene Test-DB; HA und Datenbank werden durch Attrappen ersetzt.

Aufruf (aus dem Repo-Ordner):
    python tests/zaehler_test.py
"""
import os, sys, tempfile
from datetime import datetime, timedelta

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_zaehler_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, datenquellen, zaehler
from ha_client import HAClient

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


# ── Rechenfunktion ───────────────────────────────────────────────────────────
v = zaehler.verbrauch
check("Fortlaufend: Ende minus Vorwert", v([105, 110, 120], 100) == (20.0, None), v([105, 110, 120], 100))
check("Monatsreset: 32.85 -> 0 -> 50.21 = 50.21", v([0, 25, 50.21], 32.85) == (50.21, 0),
      v([0, 25, 50.21], 32.85))
wert, reset = v([3, 5, 0.1, 2, 0, 4], 1)
check("Tagesresets: Zuwaechse aufsummiert", round(wert, 3) == 4 + 0.1 + 1.9 + 4 and reset == 2, (wert, reset))
check("Aussetzer auf 0 (gleich wieder alter Stand) ist kein Reset",
      v([12000, 0, 12001, 12005], 11990) == (15.0, None), v([12000, 0, 12001, 12005], 11990))
check("Kleiner Ruecksprung: kein Reset, ignoriert", v([100, 99.5, 101], 98) == (3.0, None),
      v([100, 99.5, 101], 98))
check("Leere Reihe", v([], 5) == (None, None) and v([]) == (None, None))
check("Ohne Vorwert: erster Wert ist die Basis", v([10, 0, 7]) == (7.0, 1), v([10, 0, 7]))
check("Zeitstempel als Reset-Zeitpunkt", v([("t1", 30), ("t2", 0), ("t3", 4)])[1] == "t2")
fm = zaehler.fortlaufend_machen([("a", 5), ("b", 8), ("c", 0.2), ("d", 3), ("e", 3)])
check("Stundenreihe fortlaufend gemacht",
      [w for _, w in fm] == [5.0, 8.0, 8.2, 11.0, 11.0], fm)

# ── HA-API: Langzeitstatistik ────────────────────────────────────────────────
# Sensor mit state_class "total" ohne last_reset: HA zaehlt den Reset als Abnahme (sum -32.85)
def statistik(reset_als_abnahme=True):
    rows, s = [], 500.0
    def row(t, st):
        return {"start": t.isoformat(), "sum": round(s, 3), "state": st}
    rows.append(row(datetime(2026, 9, 30, 22), 32.85))
    rows.append(row(datetime(2026, 9, 30, 23), 32.85))
    if reset_als_abnahme:
        s -= 32.85
    rows.append(row(datetime(2026, 10, 1, 0), 0.0))
    s += 50.21
    rows.append(row(datetime(2026, 10, 3, 22), 50.21))
    rows.append(row(datetime(2026, 10, 12, 20), 50.21))
    return rows

ha = HAClient("http://x", "t")
ha._get_statistics = lambda ids, *a, **k: {ids[0]: statistik()}
check("Statistik, mit Reset-Erkennung: 50.21 statt 17.36", ha.get_month_delta("sensor.x", 2026, 10, True) == 50.21,
      ha.get_month_delta("sensor.x", 2026, 10, True))
check("Statistik, Reset-Zeitpunkt gemerkt", str(ha.letzter_reset).startswith("2026-10-01T00"), ha.letzter_reset)
check("Statistik, Summen-Modus ebenso", ha.get_month_sum_from_daily("sensor.x", 2026, 10, True) == 50.21)
check("Statistik, ohne Reset-Erkennung (km): bisheriges Ergebnis", ha.get_month_delta("sensor.x", 2026, 10) == 17.36)
check("Statistik, Kosten mit Reset brauchen keinen Vorwert",
      ha.get_month_value_stats("sensor.x", 2026, 10, "delta", braucht_vorwert=True, reset_erkennen=True) == 50.21)
# HA rechnet den Reset richtig (total_increasing): Ergebnis gleich
ha._get_statistics = lambda ids, *a, **k: {ids[0]: statistik(False)}
check("Statistik, HA-sum korrekt: ebenfalls 50.21", ha.get_month_delta("sensor.x", 2026, 10, True) == 50.21)
# Fortlaufender Zaehler: unveraendert ueber sum
fortl = [{"start": datetime(2026, 9, 30, 23).isoformat(), "sum": 1000.0, "state": 1000.0},
         {"start": datetime(2026, 10, 5, 12).isoformat(), "sum": 1040.5, "state": 1040.5},
         {"start": datetime(2026, 10, 30, 12).isoformat(), "sum": 1100.25, "state": 1100.25}]
ha._get_statistics = lambda ids, *a, **k: {ids[0]: fortl}
check("Statistik, fortlaufender Zaehler unveraendert", ha.get_month_delta("sensor.x", 2026, 10, True) == 100.25
      and ha.letzter_reset is None, (ha.get_month_delta("sensor.x", 2026, 10, True), ha.letzter_reset))

# Fortlaufender Zaehler (total_increasing) mit zwei Aussetzern auf 0 innerhalb je einer Stunde:
# HA bucht jedes Mal den ganzen Stand auf die sum (Meldung: 563.236 bei Stand 309.27)
def aussetzer_statistik():
    rows, s = [], 1000.0
    def row(t, st):
        return {"start": t.isoformat(), "sum": round(s, 4), "state": st}
    rows.append(row(datetime(2026, 9, 30, 23), 254.0))
    rows.append(row(datetime(2026, 10, 2, 10), 254.0))
    s += 254.0
    rows.append(row(datetime(2026, 10, 4, 3), 254.0))
    s += 50.21
    rows.append(row(datetime(2026, 10, 5, 22), 304.21))
    s += 253.97
    rows.append(row(datetime(2026, 10, 8, 5), 304.21))
    s += 5.06
    rows.append(row(datetime(2026, 10, 12, 20), 309.27))
    return rows

ha._get_statistics = lambda ids, *a, **k: {ids[0]: aussetzer_statistik()}
check("Aussetzer: ohne Erkennung = HA-sum wie gemeldet (563.24)",
      ha.get_month_delta("sensor.x", 2026, 10) == 563.24)
check("Aussetzer: mit Erkennung rechnet mit den Staenden (55.27)", ha.get_month_delta("sensor.x", 2026, 10, True) == 55.27
      and ha.sum_verworfen == 563.24, (ha.get_month_delta("sensor.x", 2026, 10, True), ha.sum_verworfen))
check("Aussetzer ueber mehrere Werte (0, 0, alter Stand) ist kein Reset",
      v([254, 0, 0, 0, 254.5, 260], 254) == (6.0, None), v([254, 0, 0, 0, 254.5, 260], 254))
check("Monatsreset mit mehreren Nullen bleibt Reset", v([0, 0, 0, 0.78, 50.21], 32.85) == (50.21, 0),
      v([0, 0, 0, 0.78, 50.21], 32.85))

# ── HA-API: History-Fallback ─────────────────────────────────────────────────
def history(eid, start, ende):
    if start.month == 10:
        return [{"state": "0", "last_changed": "2026-10-01T00:00:01"},
                {"state": "unavailable", "last_changed": "2026-10-02T10:00:00"},
                {"state": "25.0", "last_changed": "2026-10-03T19:00:00"},
                {"state": "50.21", "last_changed": "2026-10-03T23:00:00"}]
    if start.month == 9:
        return [{"state": "10", "last_changed": "2026-09-10T00:00:00"},
                {"state": "32.85", "last_changed": "2026-09-25T00:00:00"}]
    return []

ha = HAClient("http://x", "t")
ha._get_statistics = lambda *a, **k: {}
ha.get_history_period = history
check("History, mit Reset-Erkennung: 50.21", ha.get_month_delta("sensor.x", 2026, 10, True) == 50.21,
      ha.get_month_delta("sensor.x", 2026, 10, True))
check("History, ohne Reset-Erkennung: bisheriges Ergebnis (17.4)", ha.get_month_delta("sensor.x", 2026, 10) == 17.4)

# ── Datenbank-Quellen ────────────────────────────────────────────────────────
class Attrappe(datenquellen.Datenquelle):
    typ = "postgres"
    def __init__(self, cfg, werte):
        super().__init__(cfg)
        self.werte = werte          # [(datetime, wert)]
    def _letzter(self, schl, kennung, von, bis):
        w = [x for x in self.werte if von < x[0] <= bis]
        return w[-1] if w else None
    def _werte(self, schl, kennung, von, bis):
        return [x for x in self.werte if von < x[0] <= bis]

def t(tag, monat=10, stunde=12):
    # 30 s nach der vollen Stunde – ein Wert genau um Mitternacht zaehlt noch zum Vormonat
    return datetime(2026, monat, tag, stunde, 0, 30).astimezone()

monatlich = [(t(25, 9), 32.85), (t(1, 10, 0), 0.0), (t(3, 10, 19), 25.0), (t(3, 10, 23), 50.21)]
cfg = {"ha_wallbox_energy": "sensor.x"}
dq = Attrappe(cfg, monatlich)
check("Datenbank, Netz ins Auto: 50.21", dq.monatswert("wallbox", 2026, 10) == 50.21, (dq.monatswert("wallbox", 2026, 10), dq.grund))
check("Datenbank, Reset vermerkt", dq.reset_bei.get("wallbox") is not None)
# Reset im Monat nach langer Luecke: kein Lueckenfehler, denn der Vorwert zaehlt nicht
dq = Attrappe(cfg, [(t(1, 6), 80.0), (t(1, 10, 0), 0.0), (t(20, 10), 12.5)])
check("Datenbank, Reset nach Luecke liefert trotzdem", dq.monatswert("wallbox", 2026, 10) == 12.5,
      (dq.monatswert("wallbox", 2026, 10), dq.grund))
dq = Attrappe(cfg, [(t(28, 9), 1000.0), (t(5, 10), 1010.0), (t(30, 10), 1042.0)])
check("Datenbank, fortlaufender Zaehler unveraendert", dq.monatswert("wallbox", 2026, 10) == 42.0
      and "wallbox" not in dq.reset_bei)
dq = Attrappe({"ha_odometer": "sensor.km"}, [(t(28, 9), 5000.0), (t(5, 10), 0.0), (t(30, 10), 5600.0)])
check("Kilometerstand bleibt fortlaufend (Aussetzer kein Reset)", dq.monatswert("km", 2026, 10) == 600.0,
      dq.monatswert("km", 2026, 10))

seite = c.get("/einstellungen").text
check("Einstellungsseite ohne Zaehlerart und evcc-Knopf", 'name="art_' not in seite and "evcc" not in seite)

# ── Diagnose ────────────────────────────────────────────────────────────────
class HAAttrappe(HAClient):
    def __init__(self, zustaende=None):
        super().__init__("http://x", "t")
        self.zustaende = zustaende or []
        self._get_statistics = lambda ids, *a, **k: {ids[0]: statistik()}
    def _get(self, pfad):
        if pfad == "/api/states":
            return self.zustaende
        return {"state": "50.21", "attributes": {"unit_of_measurement": "kWh", "state_class": "total",
                "friendly_name": "EVCC Energie aus dem Netz Monatlich"}}

alt_client = webapp._ha_client
webapp._ha_client = lambda: HAAttrappe()
d = c.get("/api/diagnose", params={"entity": "sensor.evcc_energie_aus_dem_netz_monatlich",
                                   "jahr": 2026, "monat": 10}).json()
check("Diagnose: Oktober 50.21 mit Reset", d["monate"][0]["delta"] == 50.21 and d["monate"][0]["reset"],
      d["monate"][0])
check("Diagnose: nicht eingetragen, kWh -> Spalte Delta", d["genutzt"] == "delta" and d["zeile"] == "", d.get("genutzt"))
db.save_ha_settings({"ha_tankerkoenig": "sensor.preis", "ha_pv_production": "sensor.pv"})
check("Diagnose: als Preissensor eingetragen -> Mittelwert",
      c.get("/api/diagnose", params={"entity": "sensor.preis", "jahr": 2026, "monat": 10}).json()["genutzt"] == "mittel")
check("Diagnose: als PV eingetragen -> Summe",
      c.get("/api/diagnose", params={"entity": "sensor.pv", "jahr": 2026, "monat": 10}).json()["genutzt"] == "summe")
check("Diagnose: Spalte aus der Einheit", webapp._diagnose_spalte(None, "€/L") == "mittel"
      and webapp._diagnose_spalte(None, "%") == "" and webapp._diagnose_spalte(None, "W") is None)

webapp._ha_client = alt_client

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
