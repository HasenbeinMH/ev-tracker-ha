# -*- coding: utf-8 -*-
"""
Test: Zaehlerart (zaehler.py) – Zaehler, die taeglich/monatlich zurueckgesetzt werden.

Anlass: evcc-Sensor "…_monatlich" stand bei 50.21 kWh, die App zeigte fuer den Monat 17.36
(= 50.21 − 32.85 vom Vormonat). Geprueft werden die Rechenfunktion, die HA-API (Statistik
und History-Fallback), die Datenbank-Quellen, die Diagnose, das Speichern der Einstellung
und die Zuordnung der evcc-Sensoren.
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
check("Fortlaufend auch bei auto unveraendert", v([105, 110, 120], 100, "auto") == (20.0, None))
check("Monatsreset: 32.85 -> 0 -> 50.21 = 50.21", v([0, 25, 50.21], 32.85) == (50.21, 0),
      v([0, 25, 50.21], 32.85))
check("Monatsreset mit art fortlaufend = alter Fehler 17.36",
      round(v([0, 25, 50.21], 32.85, "fortlaufend")[0], 2) == 17.36)
wert, reset = v([3, 5, 0.1, 2, 0, 4], 1)
check("Tagesresets: Zuwaechse aufsummiert", round(wert, 3) == 4 + 0.1 + 1.9 + 4 and reset == 2, (wert, reset))
check("Aussetzer auf 0 (gleich wieder alter Stand) ist kein Reset",
      v([12000, 0, 12001, 12005], 11990) == (15.0, None), v([12000, 0, 12001, 12005], 11990))
check("Kleiner Ruecksprung bei auto: kein Reset, ignoriert", v([100, 99.5, 101], 98) == (3.0, None),
      v([100, 99.5, 101], 98))
check("Kleiner Ruecksprung bei reset: als Reset gewertet", v([100, 99.5, 101], 98, "reset")[1] == 1,
      v([100, 99.5, 101], 98, "reset"))
check("Leere Reihe", v([], 5) == (None, None) and v([]) == (None, None))
check("Ohne Vorwert: erster Wert ist die Basis", v([10, 0, 7]) == (7.0, 1), v([10, 0, 7]))
check("Zeitstempel als Reset-Zeitpunkt", v([("t1", 30), ("t2", 0), ("t3", 4)])[1] == "t2")
fm = zaehler.fortlaufend_machen([("a", 5), ("b", 8), ("c", 0.2), ("d", 3), ("e", 3)])
check("Stundenreihe fortlaufend gemacht",
      [w for _, w in fm] == [5.0, 8.0, 8.2, 11.0, 11.0], fm)
check("Stundenreihe bei fortlaufend unveraendert",
      zaehler.fortlaufend_machen([("a", 5), ("b", 1)], "fortlaufend") == [("a", 5), ("b", 1)])
check("Name deutet auf Reset", zaehler.name_setzt_zurueck("sensor.evcc_energie_aus_dem_netz_monatlich")
      and zaehler.name_setzt_zurueck("sensor.pv_energy_today")
      and not zaehler.name_setzt_zurueck("sensor.wallbox_energy_total"))
check("art_aus: leer/unbekannt = auto", zaehler.art_aus({}, "ha_wallbox_energy") == "auto"
      and zaehler.art_aus({"art_wallbox_energy": "quatsch"}, "ha_wallbox_energy") == "auto"
      and zaehler.art_aus({"art_wallbox_energy": "fortlaufend"}, "ha_wallbox_energy") == "fortlaufend")

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
check("Statistik, auto: 50.21 statt 17.36", ha.get_month_delta("sensor.x", 2026, 10, "auto") == 50.21,
      ha.get_month_delta("sensor.x", 2026, 10, "auto"))
check("Statistik, Reset-Zeitpunkt gemerkt", str(ha.letzter_reset).startswith("2026-10-01T00"), ha.letzter_reset)
check("Statistik, Summen-Modus ebenso", ha.get_month_sum_from_daily("sensor.x", 2026, 10, "auto") == 50.21)
check("Statistik, fortlaufend: bisheriges Ergebnis", ha.get_month_delta("sensor.x", 2026, 10, "fortlaufend") == 17.36)
check("Statistik, Kosten mit Reset brauchen keinen Vorwert",
      ha.get_month_value_stats("sensor.x", 2026, 10, "delta", braucht_vorwert=True, art="auto") == 50.21)
# HA rechnet den Reset richtig (total_increasing): Ergebnis gleich
ha._get_statistics = lambda ids, *a, **k: {ids[0]: statistik(False)}
check("Statistik, HA-sum korrekt: ebenfalls 50.21", ha.get_month_delta("sensor.x", 2026, 10, "auto") == 50.21)
# Fortlaufender Zaehler: unveraendert ueber sum
fortl = [{"start": datetime(2026, 9, 30, 23).isoformat(), "sum": 1000.0, "state": 1000.0},
         {"start": datetime(2026, 10, 5, 12).isoformat(), "sum": 1040.5, "state": 1040.5},
         {"start": datetime(2026, 10, 30, 12).isoformat(), "sum": 1100.25, "state": 1100.25}]
ha._get_statistics = lambda ids, *a, **k: {ids[0]: fortl}
check("Statistik, fortlaufender Zaehler unveraendert", ha.get_month_delta("sensor.x", 2026, 10, "auto") == 100.25
      and ha.letzter_reset is None, (ha.get_month_delta("sensor.x", 2026, 10, "auto"), ha.letzter_reset))

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
check("History, auto: 50.21", ha.get_month_delta("sensor.x", 2026, 10, "auto") == 50.21,
      ha.get_month_delta("sensor.x", 2026, 10, "auto"))
check("History, fortlaufend: bisheriges Ergebnis (17.4)", ha.get_month_delta("sensor.x", 2026, 10) == 17.4)

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
check("Datenbank, auto: 50.21", dq.monatswert("wallbox", 2026, 10) == 50.21, (dq.monatswert("wallbox", 2026, 10), dq.grund))
check("Datenbank, Reset vermerkt", dq.reset_bei.get("wallbox") is not None)
dq = Attrappe({**cfg, "art_wallbox_energy": "fortlaufend"}, monatlich)
check("Datenbank, fortlaufend: bisheriges Ergebnis", dq.monatswert("wallbox", 2026, 10) == 17.36,
      dq.monatswert("wallbox", 2026, 10))
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

# ── Einstellung speichern ────────────────────────────────────────────────────
check("Standard der Zaehlerart ist auto", db.get_ha_settings().get("art_wallbox_energy") == "auto")
r = c.post("/einstellungen/ha", data={"art_wallbox_energy": "reset", "art_pv_production": "fortlaufend"},
           follow_redirects=False)
cfg = db.get_ha_settings()
check("Zaehlerart wird gespeichert", r.status_code == 303 and cfg["art_wallbox_energy"] == "reset"
      and cfg["art_pv_production"] == "fortlaufend", cfg.get("art_wallbox_energy"))
seite = c.get("/einstellungen").text
check("Einstellungsseite zeigt die Auswahl", 'name="art_wallbox_energy"' in seite
      and "evccVorschlag()" in seite)

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
                                   "jahr": 2026, "monat": 10, "art": "auto"}).json()
check("Diagnose: Oktober 50.21 mit Reset", d["monate"][0]["delta"] == 50.21 and d["monate"][0]["reset"],
      d["monate"][0])
check("Diagnose: Hinweis, dass der Sensor zurueckgesetzt wird", d["setzt_zurueck"] and d["art"] == "auto")

# ── evcc-Zuordnung ───────────────────────────────────────────────────────────
def st(eid, state, einheit, name="", **attr):
    return {"entity_id": eid, "state": state,
            "attributes": {"unit_of_measurement": einheit, "friendly_name": name, **attr}}

zustaende = [
    st("sensor.evcc_energie_aus_dem_netz_monatlich", "50.21", "kWh", "EVCC Energie aus dem Netz Monatlich"),
    st("sensor.evcc_lp1_charge_grid_total", "1234.5", "kWh", "evcc Laden Netz gesamt"),
    st("sensor.evcc_lp1_charge_pv_total", "987.6", "kWh", "evcc Laden PV gesamt"),
    st("sensor.evcc_pv_energy", "15000", "kWh", "evcc PV Erzeugung"),
    st("sensor.evcc_grid_power", "320", "W", "evcc Netzleistung"),
    st("sensor.evcc_battery_soc", "80", "%", "evcc Home Battery SoC"),
    st("sensor.evcc_lp1_vehicle_soc", "64", "%", "evcc Fahrzeug SoC"),
    st("sensor.evcc_lp1_vehicle_odometer", "23456", "km", "evcc Kilometerstand"),
    st("sensor.evcc_lp1_vehicle_range", "310", "km", "evcc Reichweite"),
    st("sensor.evcc_tariff_grid", "0.31", "€/kWh", "evcc Netzpreis"),
    st("sensor.evcc_lp1_charge_cost_monthly", "12.40", "€", "evcc Ladekosten Monat", last_reset="2026-10-01"),
    st("sensor.wallbox_energy_total", "5000", "kWh", "Wallbox"),
]
zeilen = {z["ha_key"]: z["kandidaten"] for z in webapp.evcc_zuordnung(zustaende)}
def erster(k):
    return zeilen[k][0]["entity_id"] if zeilen.get(k) else None
check("evcc: Netz ins Auto – fortlaufender Zaehler vor monatlichem",
      erster("ha_wallbox_energy") == "sensor.evcc_lp1_charge_grid_total", zeilen.get("ha_wallbox_energy"))
check("evcc: monatlicher Zaehler als Alternative mit art reset",
      any(k["entity_id"] == "sensor.evcc_energie_aus_dem_netz_monatlich" and k["art"] == "reset"
          for k in zeilen["ha_wallbox_energy"]))
check("evcc: PV ins Auto ist der Ladezaehler, nicht die PV-Erzeugung",
      erster("ha_pv_production") == "sensor.evcc_lp1_charge_pv_total", zeilen.get("ha_pv_production"))
check("evcc: Akkustand des Autos, nicht des Hausspeichers",
      erster("ha_ev_battery") == "sensor.evcc_lp1_vehicle_soc", zeilen.get("ha_ev_battery"))
check("evcc: Kilometerstand, nicht Reichweite", erster("ha_odometer") == "sensor.evcc_lp1_vehicle_odometer"
      and len(zeilen["ha_odometer"]) == 1)
check("evcc: Kosten in €, nicht €/kWh, Zaehlerart reset",
      erster("ha_wallbox_cost") == "sensor.evcc_lp1_charge_cost_monthly"
      and zeilen["ha_wallbox_cost"][0]["art"] == "reset", zeilen.get("ha_wallbox_cost"))
check("evcc: Sensoren ohne evcc im Namen bleiben aussen vor",
      all(k["entity_id"] != "sensor.wallbox_energy_total" for ks in zeilen.values() for k in ks))
# Nur der monatliche Sensor des Melders: wird vorgeschlagen, mit Pruefhinweis
nur = {z["ha_key"]: z["kandidaten"] for z in webapp.evcc_zuordnung(zustaende[:1])}
check("evcc: Sensor des Melders wird mit Hinweis vorgeschlagen",
      nur["ha_wallbox_energy"] and nur["ha_wallbox_energy"][0]["art"] == "reset"
      and nur["ha_wallbox_energy"][0]["hinweis"], nur.get("ha_wallbox_energy"))
webapp._ha_client = lambda: HAAttrappe(zustaende)
r = c.get("/api/evcc_vorschlag").json()
check("evcc: API liefert Zeilen", r["anzahl"] == 11 and len(r["zeilen"]) == len(webapp.EVCC_ZEILEN), r.get("anzahl"))
webapp._ha_client = lambda: HAAttrappe([])
r = c.get("/api/evcc_vorschlag").json()
check("evcc: ohne evcc-Sensoren leere Vorschlaege", r["anzahl"] == 0
      and all(not z["kandidaten"] for z in r["zeilen"]))
webapp._ha_client = alt_client

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
