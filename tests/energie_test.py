# -*- coding: utf-8 -*-
"""
Test: Energie-Aufteilung (energie.py) – Attribute der Fahrstatistik einlesen (echte Werte
eines Kia EV3), laufenden Tag ueberschreiben, Nachholen aus der Historie (Attrappe),
Anteile, Kosten, Seite, Statistik und Monatsbericht.

Laeuft gegen eine eigene Test-DB; Home Assistant wird durch eine Attrappe ersetzt.

Aufruf (aus dem Repo-Ordner):
    python tests/energie_test.py
"""
import os, sys, tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_energie_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, energie, module, berichte

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def nah(a, b, tol=0.05):
    return a is not None and b is not None and abs(a - b) <= tol


# Echte Attribute von sensor.ev3_tagliche_fahrstatistik (Kia EV3, 30.10.2026, gekuerzt)
ATTR = {
    "2026-10-30": {"total_consumed": 24383, "engine_consumption": 21536, "climate_consumption": 1837,
                   "onboard_electronics_consumption": 1010, "battery_care_consumption": 0,
                   "regenerated_energy": 7849, "distance": 185.8000030517578},
    "2026-10-29": {"total_consumed": 5958, "engine_consumption": 4880, "climate_consumption": 678,
                   "onboard_electronics_consumption": 400, "battery_care_consumption": 0,
                   "regenerated_energy": 2816, "distance": 53.40000915527344},
    "2026-10-25": {"total_consumed": 10, "engine_consumption": 0, "climate_consumption": 0,
                   "onboard_electronics_consumption": 10, "battery_care_consumption": 0,
                   "regenerated_energy": 0, "distance": 0},
    "2026-10-24": {"total_consumed": 245, "engine_consumption": 8, "climate_consumption": 207,
                   "onboard_electronics_consumption": 30, "battery_care_consumption": 0,
                   "regenerated_energy": 0, "distance": 0.100006103515625},
    "unit_of_measurement": "d", "friendly_name": "EV3 Tägliche Fahrstatistik",
    "2026-10-20": {"total_consumed": "kaputt"},
    "2026-10-19": {"total_consumed": -5, "distance": 3},
}

tage = energie.tage_aus_attributen(ATTR)
check("Tage aus den Attributen, Kaputtes faellt weg", sorted(tage) == ["2026-10-24", "2026-10-25",
      "2026-10-29", "2026-10-30"], str(sorted(tage)))
check("Werte uebernommen", tage["2026-10-30"] == {"km": 185.8, "gesamt_wh": 24383.0, "antrieb_wh": 21536.0,
      "klima_wh": 1837.0, "elektronik_wh": 1010.0, "batterie_wh": 0.0, "rekuperation_wh": 7849.0},
      str(tage["2026-10-30"]))

s = energie.summe(list({"datum": d, **w} for d, w in tage.items()))
check("Bordcomputer = Gesamt ÷ km", nah(s["bordcomputer"], 30596 / 239.3 / 10, 0.01), str(s["bordcomputer"]))
check("Anteile ergeben 100 %", nah(sum(s["anteile"].values()), 100, 0.01))
check("Anteil Klima", nah(s["anteile"]["klima_wh"], 2722 / 30596 * 100, 0.01))
check("Standverbrauch: Tage unter 1 km", s["stand_tage"] == 2 and s["stand_wh"] == 255)
check("Rekuperation im Verhaeltnis zum Antrieb", nah(s["rekuperation_anteil"], 10665 / 26424 * 100, 0.01))
k = energie.kosten([{"datum": d, **w} for d, w in tage.items()], {"2026-10": 30.0, "_schnitt": 25.0})
check("Kosten = kWh × Monatspreis", nah(k["klima_wh"], 2.722 * 0.30, 0.001), str(k))
check("Saison: Winter ohne Daten", energie.saison(energie.je_monat(
    [{"datum": d, **w} for d, w in tage.items()]))["winter"] is None)


# ── Abruf aus HA (Attrappe) ──────────────────────────────────────────────────
class FakeHA:
    def __init__(self, **kw):
        pass

    def get_state_full(self, entity):
        return {"state": "4", "attributes": {"2026-10-30": dict(ATTR["2026-10-30"], distance=190.0,
                                                               total_consumed=25000, engine_consumption=22153)}}

    def get_history_full(self, entity, start, ende, attribute=True):
        alt = {"2026-10-10": dict(ATTR["2026-10-29"]), "2026-10-30": dict(ATTR["2026-10-30"])}
        return [{"state": "9", "attributes": alt}]

    def _get(self, pfad, timeout=15):
        return ZUSTAENDE


ZUSTAENDE = [{"entity_id": "sensor.ev3_kilometerzahler", "state": "425.6", "attributes": {"unit_of_measurement": "km"}},
             {"entity_id": "sensor.ev3_tagliche_fahrstatistik", "state": "9",
              "attributes": dict(ATTR, unit_of_measurement="d")},
             {"entity_id": "sensor.kalender", "state": "1", "attributes": {"2026-10-30": "Termin"}}]


import ha_client
ha_client.HAClient = webapp.HAClient = FakeHA
db.save_ha_settings({"ha_url": "http://ha.test:8123", "ha_token": "x"})
check("Ohne Sensor: nichts", energie.aktualisieren() == "")
check("Kandidaten: nur Entities mit Tageswerten",
      energie.kandidaten(ZUSTAENDE) == ["sensor.ev3_tagliche_fahrstatistik"], str(energie.kandidaten(ZUSTAENDE)))
c.post("/einstellungen/module", data={"akku": "1", "profil": "1", "energie": "1"}, follow_redirects=False)
html = c.get("/einstellungen").text
check("Einstellungen: Fahrstatistik aus HA vorgeschlagen", "In Home Assistant gefunden:" in html
      and "sensor.ev3_tagliche_fahrstatistik</button>" in html and "sensor.kalender</button>" not in html)
check("Einstellungen: keine InfluxDB-Spalte fuer die Fahrstatistik", 'name="fn_ev_tagesstatistik"' not in html
      and "nur aus Home Assistant" in html)
db.save_ha_settings({"ha_ev_tagesstatistik": "sensor.ev3_tagliche_fahrstatistik"})
check("Eingetragen: kein Vorschlag mehr", "In Home Assistant gefunden:" not in c.get("/einstellungen").text)
meldung = energie.aktualisieren()
gespeichert = {t["datum"]: t for t in db.get_energie_tage()}
check("Naechtlicher Abruf: laufender Tag gespeichert", list(gespeichert) == ["2026-10-30"]
      and gespeichert["2026-10-30"]["km"] == 190.0, meldung)
meldung = energie.aktualisieren(nachholen=True)
gespeichert = {t["datum"]: t for t in db.get_energie_tage()}
check("Nachholen: aeltere Tage aus der Historie, aktueller Stand gewinnt",
      sorted(gespeichert) == ["2026-10-10", "2026-10-30"] and gespeichert["2026-10-30"]["km"] == 190.0,
      str(sorted(gespeichert)))

# ── Seite, Statistik, Bericht ────────────────────────────────────────────────
import charts
tage = [{"datum": d, "km": km, "gesamt_wh": wh, "antrieb_wh": wh * 0.8, "klima_wh": wh * 0.15,
         "elektronik_wh": wh * 0.05, "batterie_wh": 0.0, "rekuperation_wh": wh * 0.4}
        for d, km, wh in (("2026-10-22", 50.0, 6000.0), ("2026-10-24", 0.1, 245.0),
                          ("2026-10-30", 185.8, 24383.0))]
verlauf = energie.je_tag(tage)
opt = charts.chart_energie_monate(verlauf, je_tag=True)
rek = opt["series"][-1]
check("Verlauf je Tag: Tage unter 1 km fallen weg", opt["xAxis"]["data"] == ["2026-10-22", "2026-10-30"],
      str(opt["xAxis"]["data"]))
check("Rekuperation als Balken unter null im selben Stapel", rek["type"] == "bar" and rek["stack"] == "energie"
      and rek["data"] == [-4.8, -5.25], str(rek["data"]))
check("Verbraucher ueber null", all(v > 0 for serie in opt["series"][:3] for v in serie["data"]))
check("Modul an (Sensor eingetragen)", module.an("energie"))
r = c.get("/energie")
check("Seite Energie", r.status_code == 200 and "Verbrauch laut Bordcomputer" in r.text
      and "opt-monate-1" in r.text, f"HTTP {r.status_code}")
r = c.get("/energie?zeitraum=2026-Q4")
check("Seite mit Zeitraum", r.status_code == 200)
e = energie.auswertung(__import__("zeitraum").aufloesen("2026-Q4"))
check("Ein Monat im Zeitraum: Verlauf je Tag", e["je_tag"] and e["verlauf"][0].get("datum"), str(e["je_tag"]))
check("Seite: Titel je Tag", "Je Tag in kWh/100 km" in c.get("/energie").text)
r = c.get("/statistik?a=2026&b=2025")
check("Statistik: Zeile Bordcomputer", "Verbrauch laut Bordcomputer" in r.text)
b = berichte.monatsbericht(2026, 10)
check("Monatsbericht: Zeile Energie", b["energie"] and "Bordcomputer" in berichte.als_text(b)
      and "Energie nach Verbraucher" in berichte.als_html(b))
c.post("/einstellungen/module", data={"akku": "1", "profil": "1"}, follow_redirects=False)
check("Modul aus: keine Zeile im Bericht, keine Statistikzeile",
      berichte.monatsbericht(2026, 10)["energie"] == []
      and "Verbrauch laut Bordcomputer" not in c.get("/statistik?a=2026&b=2025").text)

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
