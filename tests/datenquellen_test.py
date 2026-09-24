# -*- coding: utf-8 -*-
"""
Test der Datenbank-Anbindungen (datenquellen.py) gegen nachgebaute Server.

Fuer InfluxDB 1.x/2.x, PostgreSQL (LTSS) und Prometheus wertet je ein kleiner
Nachbau die tatsaechlich gesendeten Abfragen aus (Zeitraum, Sensor, Aggregat)
und antwortet im Format des echten Servers. Geprueft werden Monatswerte,
Stundenwerte, Verbindungstest und die Einbindung in Import, Akkuverbrauch und
Einstellungen. Nicht geprueft: ob ein echter Server die Abfragesyntax akzeptiert.

Aufruf (aus dem Repo-Ordner):  python tests/datenquellen_test.py
"""
import csv, io, json, os, re, shutil, sys, tempfile, types, urllib.parse
from datetime import datetime, timedelta, timezone

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_tracker_dq_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

ERG = []


def check(bereich, test, ok, detail=""):
    ERG.append((bereich, test, bool(ok), detail))


def nah(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


# ── Testdaten: stuendlich 1.12.2025 – 10.3.2026, Ortszeit ────────────────────
# (vor der Sommerzeit, damit jede Stunde eindeutig ist)
UTC = timezone.utc
STUNDEN = [datetime(2025, 12, 1) + timedelta(hours=h) for h in range(100 * 24)]
DATEN = {}      # kennung -> [(utc-datetime, wert oder Text)]


def reihe(kennung, fn):
    DATEN[kennung] = [(t.astimezone().astimezone(UTC), fn(i, t)) for i, t in enumerate(STUNDEN)]


reihe("odo", lambda i, t: 10000 + i * 40 / 24)                     # 40 km/Tag
reihe("wallbox", lambda i, t: 500 + i * 6 / 24)                    # 6 kWh/Tag, fortlaufend
reihe("pv", lambda i, t: round(8 * t.hour / 23, 4))                # taeglich 0 -> 8 kWh
reihe("benzin1", lambda i, t: 1.75 if 6 <= t.hour < 22 else 0.0)   # nachts 0
reihe("benzin2", lambda i, t: 1.80 if 6 <= t.hour < 22 else 0.0)
reihe("soc", lambda i, t: 50 + (t.hour % 12) * 2)
DATEN["odo"].insert(5, (DATEN["odo"][5][0] + timedelta(minutes=1), "unavailable"))  # Textzustand

# Zuordnung wie in den Einstellungen: Entity-IDs (HA/PG/Prometheus), Friendly Names (Influx)
ENT = {"ha_odometer": "sensor.odo", "ha_wallbox_energy": "sensor.wallbox",
       "ha_pv_production": "sensor.pv", "ha_tankerkoenig": "sensor.benzin1",
       "ha_tankerkoenig_2": "sensor.benzin2", "ha_ev_battery": "sensor.soc"}
FN = {"fn_odometer": "Kilometerstand", "fn_wallbox_energy": "Wallbox Energie",
      "fn_pv_production": "PV ins Auto", "fn_tankerkoenig": "Benzin Aral",
      "fn_tankerkoenig_2": "Benzin Shell", "fn_ev_battery": "Akkustand"}
MEAS = {"odo": "km", "wallbox": "kWh", "pv": "kWh", "benzin1": "EUR/L", "benzin2": "EUR/L",
        "soc": "%"}
NAME_ZU = {v: k.split("_", 1)[1] for k, v in FN.items()}
KURZ = {"odometer": "odo", "wallbox_energy": "wallbox", "pv_production": "pv",
        "tankerkoenig": "benzin1", "tankerkoenig_2": "benzin2", "ev_battery": "soc"}


def aus_name(fn):
    return KURZ[NAME_ZU[fn]]


def aus_entity(e):
    return e.split(".", 1)[1]


def zahlen(kennung, von, bis, inkl_von=False):
    """Numerische Punkte in (von, bis] (bzw. [von, bis))."""
    werte = []
    for t, v in DATEN[kennung]:
        if not isinstance(v, (int, float)):
            continue
        if (von <= t < bis) if inkl_von else (von < t <= bis):
            werte.append((t, float(v)))
    return werte


def stundenweise(punkte, agg):
    eimer = {}
    for t, v in punkte:
        eimer.setdefault(t.replace(minute=0, second=0, microsecond=0), []).append(v)
    return [(h, (vs[-1] if agg == "last" else sum(vs) / len(vs))) for h, vs in sorted(eimer.items())]


def ts(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


# ── Nachbau-Server ───────────────────────────────────────────────────────────
ANFRAGEN = []


def fake_http(url, daten=None, kopf=None, user="", passwort="", timeout=None):
    ANFRAGEN.append((url, daten, kopf, user, passwort))
    teile = urllib.parse.urlsplit(url)
    q = dict(urllib.parse.parse_qsl(teile.query))
    if teile.path == "/query":                                    # InfluxDB 1.x
        return json.dumps(influx1(q["q"])).encode()
    if teile.path == "/api/v2/query":                             # InfluxDB 2.x
        return influx2(daten.decode()).encode()
    if teile.path.startswith("/api/v1/"):                         # Prometheus
        return json.dumps(prometheus(teile.path, q)).encode()
    raise ConnectionError("unbekannter Pfad " + url)


def influx1(q):
    if q == "SHOW DATABASES":
        return {"results": [{"series": [{"name": "databases", "columns": ["name"],
                                         "values": [["_internal"], ["home_assistant"]]}]}]}
    m = re.match(r'SELECT (?:(\w+)\()?"value"\)? FROM "([^"]+)" WHERE "([^"]+)" = \'([^\']+)\' '
                 r"AND time (>=?) '([^']+)' AND time <= '([^']+)'( GROUP BY time\(1h\) fill\(none\))?$", q)
    assert m, "InfluxQL nicht erkannt: " + q
    agg, meas, tag, wert, op, a, b, gruppe = m.groups()
    assert tag == "friendly_name", tag
    k = aus_name(wert)
    assert MEAS[k] == meas, (meas, k)
    punkte = [(t, v) for t, v in zahlen(k, ts(a) - timedelta(seconds=1), ts(b))
              if op == ">=" or t > ts(a)]
    if gruppe:
        zeilen = stundenweise(punkte, agg)
    elif agg == "last":
        zeilen = punkte[-1:]
    else:
        zeilen = punkte
    spalte = agg or "value"
    return {"results": [{"statement_id": 0, "series": [{
        "name": meas, "columns": ["time", spalte],
        "values": [[int(t.timestamp()), v] for t, v in zeilen]}] if zeilen else []}]}


def influx2(flux):
    if "range(start: -1m)" in flux:
        assert 'from(bucket: "home_assistant")' in flux
        return ",result,table\n"
    m = re.search(r'range\(start: (\S+), stop: (\S+)\)', flux)
    a, b = ts(m.group(1)), ts(m.group(2))
    meas = re.search(r'r\._measurement == "([^"]+)"', flux).group(1)
    tag, wert = re.search(r'r\["([^"]+)"\] == "([^"]+)"', flux).groups()
    assert 'r._field == "value"' in flux and tag == "friendly_name"
    k = aus_name(wert)
    assert MEAS[k] == meas
    punkte = zahlen(k, a, b, inkl_von=True)            # Flux: start inklusive, stop exklusiv
    if "|> last()" in flux:
        punkte = punkte[-1:]
    elif "aggregateWindow" in flux:
        fn = re.search(r"fn: (\w+)", flux).group(1)
        assert 'timeSrc: "_start"' in flux
        punkte = stundenweise(punkte, fn)
    # Antwort mit Annotationen und zwei Tabellen, wie InfluxDB sie schicken kann
    halb = len(punkte) // 2
    aus = io.StringIO()
    w = csv.writer(aus, lineterminator="\r\n")
    for nr, teil in enumerate([punkte[:halb], punkte[halb:]]):
        if not teil:
            continue
        w.writerow(["#datatype", "string", "long", "dateTime:RFC3339", "double", "string"])
        w.writerow(["", "result", "table", "_time", "_value", "_measurement"])
        for t, v in teil:
            w.writerow(["", "_result", nr, t.strftime("%Y-%m-%dT%H:%M:%S.123456789Z"), v, meas])
        w.writerow([])
    return aus.getvalue()


def prometheus(pfad, q):
    ausdruck = q["query"]
    if ausdruck == "vector(1)":
        return {"status": "success", "data": {"resultType": "vector",
                                              "result": [{"metric": {}, "value": [0, "1"]}]}}
    m = re.match(r'(\w+)\((\{.*\})\[(\d+)([smh])\]\)$', ausdruck)
    assert m, "PromQL nicht erkannt: " + ausdruck
    fn, sel, n, einheit = m.groups()
    assert 'homeassistant_sensor_' in sel
    k = aus_entity(re.search(r'entity="([^"]+)"', sel).group(1))
    fenster = timedelta(seconds=int(n) * {"s": 1, "m": 60, "h": 3600}[einheit])

    def werten(t):
        p = zahlen(k, t - fenster, t)
        if not p:
            return None
        return p[-1][1] if fn == "last_over_time" else sum(v for _, v in p) / len(p)

    if pfad.endswith("/query"):
        v = werten(datetime.fromtimestamp(float(q["time"]), UTC))
        res = [] if v is None else [{"metric": {"entity": "x"}, "value": [q["time"], str(v)]}]
        return {"status": "success", "data": {"resultType": "vector", "result": res}}
    start, ende, schritt = float(q["start"]), float(q["end"]), int(float(q["step"]))
    werte, t = [], start
    while t <= ende + 1e-6:
        v = werten(datetime.fromtimestamp(t, UTC))
        if v is not None:
            werte.append([t, str(v)])
        t += schritt
    assert len(werte) <= 11000, "Prometheus-Grenze ueberschritten"
    res = [{"metric": {"entity": "x"}, "values": werte}] if werte else []
    return {"status": "success", "data": {"resultType": "matrix", "result": res}}


class FakePG:
    """pg8000.native.Connection-Nachbau: erkennt die fuenf Abfragen der LTSS-Anbindung."""
    VERBINDUNGEN = []

    def __init__(self, **kw):
        FakePG.VERBINDUNGEN.append(kw)

    def close(self):
        pass

    def run(self, sql, **p):
        if sql.startswith("SET TIME ZONE"):
            return []
        if sql.startswith("SELECT 1 FROM"):
            assert "ltss" in sql
            return [[1]]
        assert "state ~ '^-?[0-9]+(\\.[0-9]+)?$'" in sql, sql
        k = aus_entity(p["e"])
        inkl = "time >= :von" in sql
        punkte = [(t, v) for t, v in zahlen(k, p["von"] - timedelta(seconds=1), p["bis"])
                  if inkl or t > p["von"]]
        if "ORDER BY time DESC LIMIT 1" in sql:
            return [[punkte[-1][1]]] if punkte else []
        if sql.startswith("SELECT time, state"):
            return [[t, v] for t, v in punkte]
        if "DISTINCT ON" in sql:
            return [[t, v] for t, v in stundenweise(punkte, "last")]
        if "avg(state::float)" in sql:
            return [[t, v] for t, v in stundenweise(punkte, "mean")]
        raise AssertionError("SQL nicht erkannt: " + sql)


pg_modul = types.ModuleType("pg8000")
pg_modul.native = types.SimpleNamespace(Connection=FakePG)
sys.modules["pg8000"] = pg_modul
sys.modules["pg8000.native"] = pg_modul.native

import datenquellen
datenquellen._http = fake_http

BASIS = {**ENT, **FN,
         "influx_url": "http://influx", "influx_port": "8086", "influx_database": "home_assistant",
         "influx_user": "leser", "influx_password": "geheim", "influx_tag": "friendly_name",
         "influx_measurement_km": "km", "influx_measurement_kwh": "kWh",
         "influx_measurement_eur_l": "EUR/L", "influx_measurement_prozent": "%",
         "influx2_url": "http://influx2:8086", "influx2_org": "zuhause",
         "influx2_bucket": "home_assistant", "influx2_token": "tok123",
         "pg_host": "pg", "pg_port": "5432", "pg_database": "homeassistant", "pg_user": "ha",
         "pg_password": "pw", "pg_tabelle": "ltss",
         "prom_url": "http://prom:9090", "prom_user": "", "prom_password": "", "prom_selektor": ""}

# ── Erwartungswerte Februar 2026 ─────────────────────────────────────────────
SOLL = {"km": 28 * 40, "wallbox": 28 * 6, "pv": 28 * 8, "benzin": 1.775}
TAG = (datetime(2026, 2, 10), datetime(2026, 2, 10, 23, 59))

for typ in datenquellen.QUELLEN:
    dq = datenquellen.aus_einstellungen({**BASIS, "datasource": typ})
    name = dq.name
    ok, text = dq.test()
    check(name, "Verbindungstest", ok, text)
    for key, soll in SOLL.items():
        ist = dq.monatswert(key, 2026, 2)
        check(name, f"Monatswert {key} 02/2026", nah(ist, soll, 0.01), f"{ist} / soll {soll}")
    ist = dq.monatswert("km", 2025, 11)
    check(name, "Monat ohne Daten -> None (HA-API uebernimmt)", ist is None, str(ist))
    ist = dq.monatswert("km", 2025, 12)
    check(name, "Erster Monat: Wert um Mitternacht am 1. zaehlt als Vorwert",
          nah(ist, 31 * 40, 0.01), str(ist))
    soc = dq.stundenwerte("soc", *TAG, "mean")
    erwartet = [(f"2026-02-10T{h:02d}:00", 50 + (h % 12) * 2) for h in range(24)]
    check(name, "Stundenwerte Akkustand (Ortszeit, 24 Werte)",
          [(a, round(b, 3)) for a, b in soc] == erwartet,
          f"{len(soc)} Werte, erste {soc[:2]}")
    km = dq.stundenwerte("km", *TAG, "last")
    check(name, "Stundenwerte km-Stand (letzter Wert je Stunde)",
          len(km) == 24 and nah(km[1][1] - km[0][1], 40 / 24, 0.001), f"{km[:2]}")

# Zugangsdaten landen dort, wo sie hingehoeren
auth1 = [a for a in ANFRAGEN if "/query?" in a[0] and "influx:8086" in a[0]]
check("InfluxDB 1.x", "Basic-Auth mit Benutzer/Passwort", auth1 and auth1[0][3:] == ("leser", "geheim"))
auth2 = [a for a in ANFRAGEN if "/api/v2/query" in a[0]]
check("InfluxDB 2.x", "Token-Header und Organisation",
      auth2 and auth2[0][2]["Authorization"] == "Token tok123" and "org=zuhause" in auth2[0][0])
check("PostgreSQL", "Verbindungsparameter",
      FakePG.VERBINDUNGEN[0] == {"user": "ha", "password": "pw", "host": "pg", "port": 5432,
                                 "database": "homeassistant", "timeout": 15},
      str(FakePG.VERBINDUNGEN[0]))

# InfluxDB mit Tag entity_id statt friendly_name
dq = datenquellen.aus_einstellungen({**BASIS, "datasource": "influxdb", "influx_tag": "entity_id"})
ANFRAGEN.clear()
try:
    dq._letzter("km", "odo", datetime(2026, 1, 1).astimezone(), datetime(2026, 2, 1).astimezone())
except AssertionError:
    pass
check("InfluxDB 1.x", "Tag einstellbar (entity_id)", 'WHERE "entity_id" = ' in
      urllib.parse.unquote_plus(ANFRAGEN[0][0]))

# Sonderzeichen werden maskiert
dq = datenquellen.aus_einstellungen({**BASIS, "datasource": "influxdb2"})
flux = dq._basis("km", 'Kilo"meter\\', datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC))
check("InfluxDB 2.x", "Anfuehrungszeichen im Namen maskiert", '"Kilo\\"meter\\\\"' in flux)
try:
    datenquellen.aus_einstellungen({**BASIS, "datasource": "postgres", "pg_tabelle": "ltss; DROP"})
    check("PostgreSQL", "Ungueltiger Tabellenname wirft Fehler", False)
except ValueError:
    check("PostgreSQL", "Ungueltiger Tabellenname wirft Fehler", True)

# Prometheus: langer Zeitraum wird in Stuecke geteilt (max. 11.000 Punkte)
dq = datenquellen.aus_einstellungen({**BASIS, "datasource": "prometheus"})
dq.MAX_PUNKTE = 500
lang = dq.stundenwerte("soc", datetime(2025, 12, 2), datetime(2026, 3, 1), "mean")
check("Prometheus", "Langer Zeitraum in Stuecken, lueckenlos",
      len(lang) == len({a for a, _ in lang}) and len(lang) >= 89 * 24 - 2, f"{len(lang)} Stunden")

# Fehler: nicht erreichbar -> Test meldet es, Monatswert None
datenquellen._http = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("nicht erreichbar (refused)"))
for typ in ("influxdb", "influxdb2", "prometheus"):
    dq = datenquellen.aus_einstellungen({**BASIS, "datasource": typ})
    ok, text = dq.test()
    check(dq.name, "Nicht erreichbar -> verstaendliche Meldung", not ok and "nicht erreichbar" in text, text)
    check(dq.name, "Nicht erreichbar -> Monatswert None", dq.monatswert("km", 2026, 2) is None)
datenquellen._http = fake_http
check("Allgemein", "Datenquelle 'ha' -> keine Datenbank", datenquellen.aus_einstellungen({"datasource": "ha"}) is None)

# ── Einbindung in die App ────────────────────────────────────────────────────
from fastapi.testclient import TestClient
import app as webapp
import database as db
import akkuverbrauch

c = TestClient(webapp.app)
db.save_ha_settings({**BASIS, "ha_url": "", "ha_token": ""})

for typ, name in datenquellen.QUELLEN.items():
    db.save_ha_settings({"datasource": typ})
    werte = webapp._fetch_monat(None, datenquellen.aus_einstellungen(db.get_ha_settings()),
                                db.get_ha_settings(), 2026, 2)
    check("App", f"Import-Werte aus {name}",
          all(nah(werte[k], v, 0.01) for k, v in SOLL.items()), str(werte))
    r = c.post(f"/api/test/{typ}")
    check("App", f"Knopf 'testen' {name}", r.status_code == 200 and r.json()["ok"], r.text[:100])
    v = akkuverbrauch.verlaeufe(*TAG)
    check("App", f"Akkuverbrauch liest aus {name}", v["quelle"] == name and len(v["soc"]) == 24,
          f'{v["quelle"]} / {len(v["soc"])} / {v["meldung"]}')
    r = c.get("/import")
    check("App", f"Importseite nennt {name}", r.status_code == 200 and name in r.text)
    r = c.post("/api/import/start", data={"von_monat": 2, "von_jahr": 2026, "bis_monat": 2,
                                          "bis_jahr": 2026})
    check("App", f"Zeitraum-Import startet mit {name} ohne HA", r.status_code == 200, r.text[:80])
    import time as _t
    for _ in range(50):
        job = c.get(f"/api/import/status/{r.json()['job_id']}").json()
        if job["done"]:
            break
        _t.sleep(0.2)
    zeile = job["rows"][0] if job.get("rows") else {}
    check("App", f"Vorschau nennt Quelle und Herkunft je Wert ({name})",
          job.get("quelle", "").startswith(name)
          and all(zeile.get("_quelle", {}).get(k) == name for k in SOLL),
          f'{job.get("quelle")} / {zeile.get("_quelle")}')

# Rueckfall auf HA wird als "HA-API" gekennzeichnet, nichts geliefert -> None
class FakeHA:
    def get_month_delta(self, eid, y, m):
        return 999.0 if eid == "sensor.odo" else None
    get_month_sum_from_daily = get_month_delta
    def get_month_avg_multi(self, ids, y, m):
        return None
leer = datenquellen.aus_einstellungen({"datasource": "influxdb", "influx_url": "http://influx"})
werte = webapp._fetch_monat(FakeHA(), leer, {**ENT, "datasource": "influxdb"}, 2026, 2)
check("App", "Rueckfall auf HA als 'HA-API' gekennzeichnet",
      werte["km"] == 999.0 and werte["_quelle"]["km"] == "HA-API" and werte["_quelle"]["benzin"] is None,
      str(werte))
check("App", "Protokollzeile nennt Herkunft",
      webapp._rohwerte_text(werte).startswith("km=999.0 (HA-API) · PV kWh=—"), webapp._rohwerte_text(werte))
r = c.post("/api/import/apply", json={"quelle": "InfluxDB 1.x, fehlende Werte aus der HA-API", "rows": [
    {"monat": "2031-05", "km": "1200", "benzin": "1,799",
     "_quelle": {"km": "InfluxDB 1.x", "benzin": "von Hand"}}]}).json()
check("App", "Uebernehmen: Protokoll mit Herkunft und 'von Hand'",
      r["log"] == ["2031-05: 1200 km (InfluxDB 1.x), 1.799 €/L (von Hand)"], str(r["log"]))
db.delete_fahrt_monat("2031-05")
db.delete_benzinpreis("2031-05")

# Suche in der Datenbank: Schnittstelle (die Abfragen selbst prueft der Docker-Test)
alt_suche = datenquellen.InfluxDB1.suche
datenquellen.InfluxDB1.suche = lambda self, b: [
    {"kennung": "Kilometerstand", "name": "Kilometerstand", "einheit": "km",
     "von": datetime(2025, 12, 1, tzinfo=UTC), "bis": None}] if b == "kilo" else []
db.save_ha_settings({"datasource": "influxdb"})
r = c.get("/api/datenbank/suche", params={"q": "kilo"}).json()
check("App", "Datenbanksuche: Treffer, Spalte, Monatsformat",
      r.get("spalte") == "name" and r["treffer"][0]["von"] == "12/2025" and r["treffer"][0]["bis"] is None,
      str(r))
datenquellen.InfluxDB1.suche = lambda self, b: (_ for _ in ()).throw(ConnectionError("nicht erreichbar (x)"))
r = c.get("/api/datenbank/suche", params={"q": "kilo"})
check("App", "Datenbanksuche: Fehler -> 400 mit Meldung",
      r.status_code == 400 and "nicht erreichbar" in r.json()["error"], r.text[:80])
datenquellen.InfluxDB1.suche = alt_suche
db.save_ha_settings({"datasource": "ha"})
r = c.get("/api/datenbank/suche", params={"q": "kilo"})
check("App", "Datenbanksuche ohne Datenbank -> Hinweis", r.status_code == 400, r.text[:80])
check("App", "Knopf 'In Datenbank suchen' auf der Einstellungsseite",
      "sucheDatenbank()" in c.get("/einstellungen").text)

r = c.post("/api/test/influx")
check("App", "Alter Knopfname /api/test/influx funktioniert", r.json().get("ok"), r.text[:80])
check("App", "Unbekannte Quelle -> 404", c.post("/api/test/oracle").status_code == 404)

# Einstellungen: Seite, Speichern, geheime Felder, Export
db.save_ha_settings({"datasource": "influxdb2"})
html = c.get("/einstellungen").text
check("Einstellungen", "Alle Quellen in der Auswahl",
      all(f'value="{t}"' in html for t in datenquellen.QUELLEN), "")
check("Einstellungen", "Verbindungsbloecke vorhanden",
      all(f'data-quelle="{t}"' in html for t in ("influxdb2", "postgres", "prometheus")))
form = {k: v for k, v in BASIS.items()}
form.update({"datasource": "postgres", "pg_host": "db.local", "pg_password": "",
             "influx2_token": "", "prom_password": "neu"})
c.post("/einstellungen/ha", data=form, follow_redirects=False)
s = db.get_ha_settings()
check("Einstellungen", "Speichern: Quelle und Felder", s["datasource"] == "postgres" and s["pg_host"] == "db.local")
check("Einstellungen", "Leere Passwortfelder behalten alten Wert",
      s["pg_password"] == "pw" and s["influx2_token"] == "tok123" and s["prom_password"] == "neu",
      f'{s["pg_password"]} / {s["influx2_token"]} / {s["prom_password"]}')
c.post("/einstellungen/ha", data={**form, "datasource": "mysql"}, follow_redirects=False)
check("Einstellungen", "Ungueltige Quelle wird nicht gespeichert", db.get_ha_settings()["datasource"] == "postgres")
exp = c.get("/api/settings/export?secrets=0").json()["einstellungen"]
check("Einstellungen", "Export ohne Zugangsdaten enthaelt keine Datenbank-Passwoerter",
      not any(k in exp for k in ("pg_password", "influx2_token", "prom_password", "influx_password")))

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[2])
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
for b, t, ok, d in ERG:
    if not ok:
        print(f"FEHLER  [{b}] {t}\n        {d}")
shutil.rmtree(TESTDIR, ignore_errors=True)
sys.exit(0 if ok_n == len(ERG) else 1)
