# -*- coding: utf-8 -*-
"""
Test der Datenbank-Anbindungen (datenquellen.py) gegen ECHTE Server in Docker.

Startet InfluxDB 1.8, InfluxDB 2.7, TimescaleDB (PostgreSQL mit LTSS-Tabelle),
VictoriaMetrics und Prometheus als Container, fuellt sie mit denselben Testdaten
wie tests/datenquellen_test.py (so, wie die jeweilige HA-Integration sie ablegt)
und prueft Verbindungstest, Monatswerte und Stundenwerte.

Voraussetzung: Docker laeuft, Python-Paket pg8000 installiert.
Aufruf (aus dem Repo-Ordner):
    python tests/datenquellen_docker_test.py            # Container danach entfernen
    python tests/datenquellen_docker_test.py --behalten # Container laufen lassen
Beim ersten Lauf laedt Docker die Images (zusammen etwa 1 GB).
"""
import json, os, subprocess, sys, tempfile, time, urllib.error, urllib.request
from datetime import datetime, timedelta, timezone

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
sys.path.insert(0, REPO)
import datenquellen

BEHALTEN = "--behalten" in sys.argv
UTC = timezone.utc
PRAEFIX = "evtest-"
ERG = []


def check(bereich, test, ok, detail=""):
    ERG.append((bereich, test, bool(ok), detail))
    print(("  ok    " if ok else "  FEHLER") + f" [{bereich}] {test}" + ("" if ok else f" – {detail}"))


def nah(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


def docker(*args, pruefen=True):
    r = subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8")
    if pruefen and r.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args)}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def http(url, daten=None, kopf=None, methode=None):
    req = urllib.request.Request(url, data=daten, headers=kopf or {}, method=methode)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def warten(name, pruefung, sekunden=120):
    ende = time.time() + sekunden
    fehler = None
    while time.time() < ende:
        try:
            if pruefung():
                return
        except Exception as e:
            fehler = e
        time.sleep(2)
    raise RuntimeError(f"{name} nicht bereit: {fehler}")


# ── Testdaten wie in datenquellen_test.py ────────────────────────────────────
STUNDEN = [datetime(2025, 12, 1) + timedelta(hours=h) for h in range(100 * 24)]
# kurz: (Entity-ID, Friendly Name, Einheit/Measurement, Prometheus-Metrik, Funktion)
SENSOREN = {
    "odo":     ("sensor.odo", "Kilometerstand", "km", "homeassistant_sensor_distance_km",
                lambda i, t: 10000 + i * 40 / 24),
    "wallbox": ("sensor.wallbox", "Wallbox Energie", "kWh", "homeassistant_sensor_energy_kwh",
                lambda i, t: 500 + i * 6 / 24),
    "pv":      ("sensor.pv", "PV ins Auto", "kWh", "homeassistant_sensor_energy_kwh",
                lambda i, t: round(8 * t.hour / 23, 4)),
    "benzin1": ("sensor.benzin1", "Benzin Aral", "EUR/L", "homeassistant_sensor_monetary_eur_per_l",
                lambda i, t: 1.75 if 6 <= t.hour < 22 else 0.0),
    "benzin2": ("sensor.benzin2", "Benzin Shell", "EUR/L", "homeassistant_sensor_monetary_eur_per_l",
                lambda i, t: 1.80 if 6 <= t.hour < 22 else 0.0),
    "soc":     ("sensor.soc", "Akkustand", "%", "homeassistant_sensor_battery_percent",
                lambda i, t: 50 + (t.hour % 12) * 2),
}
PUNKTE = {k: [(t.astimezone().astimezone(UTC), s[4](i, t)) for i, t in enumerate(STUNDEN)]
          for k, s in SENSOREN.items()}

# Umbenannter Sensor: derselbe Kilometerstand heisst bis Mitte Februar "KM Alt", danach "KM Neu"
UMBENENNUNG = datetime(2026, 2, 15).astimezone().astimezone(UTC)
SENSOREN["km_alt"] = ("sensor.km_alt", "KM Alt", "km", "homeassistant_sensor_distance_km", None)
SENSOREN["km_neu"] = ("sensor.km_neu", "KM Neu", "km", "homeassistant_sensor_distance_km", None)
PUNKTE["km_alt"] = [p for p in PUNKTE["odo"] if p[0] < UMBENENNUNG]
PUNKTE["km_neu"] = [p for p in PUNKTE["odo"] if p[0] >= UMBENENNUNG]
# Kilometerstand mit Luecke Januar/Februar (Auto faehrt weiter, es wird nur nichts gespeichert)
LUECKE_VON = datetime(2026, 1, 1).astimezone().astimezone(UTC)
LUECKE_BIS = datetime(2026, 3, 2).astimezone().astimezone(UTC)   # Stand um Mitternacht am 1.3. fehlt auch
SENSOREN["km_luecke"] = ("sensor.km_luecke", "KM Luecke", "km", "homeassistant_sensor_distance_km", None)
PUNKTE["km_luecke"] = [p for p in PUNKTE["odo"] if p[0] < LUECKE_VON or p[0] >= LUECKE_BIS]

CFG = {"ha_odometer": "sensor.odo", "ha_wallbox_energy": "sensor.wallbox",
       "ha_pv_production": "sensor.pv", "ha_tankerkoenig": "sensor.benzin1",
       "ha_tankerkoenig_2": "sensor.benzin2", "ha_ev_battery": "sensor.soc",
       "fn_odometer": "Kilometerstand", "fn_wallbox_energy": "Wallbox Energie",
       "fn_pv_production": "PV ins Auto", "fn_tankerkoenig": "Benzin Aral",
       "fn_tankerkoenig_2": "Benzin Shell", "fn_ev_battery": "Akkustand",
       "influx_tag": "friendly_name", "influx_measurement_km": "km",
       "influx_measurement_kwh": "kWh", "influx_measurement_eur_l": "EUR/L",
       "influx_measurement_prozent": "%",
       "influx_url": "http://127.0.0.1", "influx_port": "18086", "influx_database": "home_assistant",
       "influx_user": "leser", "influx_password": "geheim",
       "influx2_url": "http://127.0.0.1:18087", "influx2_org": "zuhause",
       "influx2_bucket": "home_assistant", "influx2_token": "tok123",
       "pg_host": "127.0.0.1", "pg_port": "15432", "pg_database": "homeassistant",
       "pg_user": "leser", "pg_password": "geheim", "pg_tabelle": "ltss",
       "prom_url": "http://127.0.0.1:19090", "prom_selektor": ""}


def lp_esc(s):
    return s.replace(",", r"\,").replace(" ", r"\ ").replace("=", r"\=")


def zeilenprotokoll():
    """Line Protocol wie die HA-Integration InfluxDB (Measurement = Einheit)."""
    zeilen = []
    for k, (ent, fn, meas, _, _) in SENSOREN.items():
        for t, v in PUNKTE[k]:
            zeilen.append(f"{lp_esc(meas)},domain=sensor,entity_id={ent.split('.', 1)[1]},"
                          f"friendly_name={lp_esc(fn)} value={float(v)} {int(t.timestamp())}")
    return "\n".join(zeilen).encode()


def openmetrics(ms=False):
    """Prometheus-Textformat wie die HA-Integration prometheus, plus Stoer-Metrik unit_info."""
    familien = {}
    for k, (ent, fn, _, metrik, _) in SENSOREN.items():
        labels = f'domain="sensor",entity="{ent}",friendly_name="{fn}"'
        for t, v in PUNKTE[k]:
            ts = int(t.timestamp() * 1000) if ms else int(t.timestamp())
            familien.setdefault(metrik, []).append(f"{metrik}{{{labels}}} {float(v)} {ts}")
            if k == "odo":   # darf der Standard-Selektor nicht treffen
                familien.setdefault("homeassistant_sensor_unit_info", []).append(
                    f'homeassistant_sensor_unit_info{{{labels},unit="km"}} 1 {ts}')
    zeilen = []
    for name, werte in familien.items():
        if not ms:
            zeilen.append(f"# TYPE {name} gauge")
        zeilen += werte
    if not ms:
        zeilen.append("# EOF")
    return "\n".join(zeilen) + "\n"


# ── Container ────────────────────────────────────────────────────────────────
CONTAINER = ["influx1", "influx2", "pg", "vm", "prom"]


def aufraeumen():
    for c in CONTAINER:
        docker("rm", "-f", PRAEFIX + c, pruefen=False)
    docker("volume", "rm", "-f", PRAEFIX + "promdaten", pruefen=False)


def starten():
    aufraeumen()
    print("Starte Container (beim ersten Mal werden Images geladen) …")
    docker("run", "-d", "--name", PRAEFIX + "influx1", "-p", "18086:8086",
           "-e", "INFLUXDB_DB=home_assistant", "-e", "INFLUXDB_HTTP_AUTH_ENABLED=true",
           "-e", "INFLUXDB_ADMIN_USER=admin", "-e", "INFLUXDB_ADMIN_PASSWORD=adminpw",
           "-e", "INFLUXDB_READ_USER=leser", "-e", "INFLUXDB_READ_USER_PASSWORD=geheim",
           "influxdb:1.8")
    docker("run", "-d", "--name", PRAEFIX + "influx2", "-p", "18087:8086",
           "-e", "DOCKER_INFLUXDB_INIT_MODE=setup", "-e", "DOCKER_INFLUXDB_INIT_USERNAME=admin",
           "-e", "DOCKER_INFLUXDB_INIT_PASSWORD=adminpw123", "-e", "DOCKER_INFLUXDB_INIT_ORG=zuhause",
           "-e", "DOCKER_INFLUXDB_INIT_BUCKET=home_assistant",
           "-e", "DOCKER_INFLUXDB_INIT_ADMIN_TOKEN=tok123", "influxdb:2.7")
    docker("run", "-d", "--name", PRAEFIX + "pg", "-p", "15432:5432",
           "-e", "POSTGRES_PASSWORD=adminpw", "-e", "POSTGRES_DB=homeassistant",
           "timescale/timescaledb:latest-pg16")
    docker("run", "-d", "--name", PRAEFIX + "vm", "-p", "18428:8428",
           "victoriametrics/victoria-metrics:latest", "-retentionPeriod=100y")

    # Prometheus: Daten per promtool als Bloecke einspielen, dann Server starten
    tmp = tempfile.mkdtemp(prefix="evtest_prom_")
    with open(os.path.join(tmp, "daten.om"), "w", encoding="utf-8", newline="\n") as f:
        f.write(openmetrics())
    docker("volume", "create", PRAEFIX + "promdaten")
    docker("run", "--rm", "-v", f"{tmp}:/import", "-v", f"{PRAEFIX}promdaten:/prometheus",
           "--entrypoint", "promtool", "prom/prometheus:latest",
           "tsdb", "create-blocks-from", "openmetrics", "/import/daten.om", "/prometheus")
    docker("run", "-d", "--name", PRAEFIX + "prom", "-p", "19090:9090",
           "-v", f"{PRAEFIX}promdaten:/prometheus", "prom/prometheus:latest",
           "--config.file=/etc/prometheus/prometheus.yml", "--storage.tsdb.path=/prometheus",
           "--storage.tsdb.retention.time=100y")


def befuellen():
    print("Warte auf die Server und spiele Testdaten ein …")
    # InfluxDB 1.8
    warten("InfluxDB 1.8", lambda: http("http://127.0.0.1:18086/ping") is not None)
    auth = "Basic " + __import__("base64").b64encode(b"admin:adminpw").decode()
    warten("InfluxDB 1.8 Schreibzugriff", lambda: http(
        "http://127.0.0.1:18086/write?db=home_assistant&precision=s", zeilenprotokoll(),
        {"Authorization": auth}) is not None)
    # InfluxDB 2.7
    warten("InfluxDB 2.7", lambda: json.loads(http("http://127.0.0.1:18087/health"))["status"] == "pass")
    warten("InfluxDB 2.7 Schreibzugriff", lambda: http(
        "http://127.0.0.1:18087/api/v2/write?org=zuhause&bucket=home_assistant&precision=s",
        zeilenprotokoll(), {"Authorization": "Token tok123"}) is not None)
    # TimescaleDB: LTSS-Tabelle wie die Integration sie anlegt, Lesebenutzer
    import pg8000.native

    def pg_admin():
        return pg8000.native.Connection(user="postgres", password="adminpw", host="127.0.0.1",
                                        port=15432, database="homeassistant", timeout=10)
    warten("TimescaleDB", lambda: pg_admin().run("SELECT 1") is not None)
    con = pg_admin()
    con.run("CREATE TABLE ltss (time TIMESTAMPTZ NOT NULL, entity_id VARCHAR(255), "
            "state VARCHAR(255), attributes JSONB, PRIMARY KEY (time, entity_id))")
    con.run("SELECT create_hypertable('ltss', 'time')")
    con.run("CREATE USER leser PASSWORD 'geheim'")
    con.run("GRANT SELECT ON ltss TO leser")
    for k, (ent, fn, meas, _, _) in SENSOREN.items():
        # Attribute wie HA sie mitschreibt (Einheit, Anzeigename)
        attr = json.dumps({"unit_of_measurement": meas, "friendly_name": fn})
        zeilen = [(t, ent, str(v)) for t, v in PUNKTE[k]]
        for i in range(0, len(zeilen), 500):
            teil = zeilen[i:i + 500]
            werte = ",".join(f"(:t{j}, :e{j}, :s{j}, CAST(:a AS jsonb))" for j in range(len(teil)))
            param = {"a": attr}
            for j, (t, e, s) in enumerate(teil):
                param.update({f"t{j}": t, f"e{j}": e, f"s{j}": s})
            con.run(f"INSERT INTO ltss (time, entity_id, state, attributes) VALUES {werte}", **param)
    # Reiner Text-Sensor: darf in der Suche nicht auftauchen
    con.run("INSERT INTO ltss VALUES (:t, 'sensor.odo_status', 'online', '{}')",
            t=PUNKTE["odo"][0][0])
    # Textzustand, der beim Lesen uebersprungen werden muss
    con.run("INSERT INTO ltss VALUES (:t, 'sensor.odo', 'unavailable', '{}')",
            t=PUNKTE["odo"][5][0] + timedelta(minutes=1))
    con.close()
    # VictoriaMetrics
    warten("VictoriaMetrics", lambda: http("http://127.0.0.1:18428/health") is not None)
    http("http://127.0.0.1:18428/api/v1/import/prometheus", openmetrics(ms=True).encode(),
         methode="POST")
    http("http://127.0.0.1:18428/internal/force_flush")
    # Prometheus
    warten("Prometheus", lambda: http("http://127.0.0.1:19090/-/ready") is not None)
    time.sleep(3)


# ── Pruefungen ───────────────────────────────────────────────────────────────
SOLL = {"km": 28 * 40, "wallbox": 28 * 6, "pv": 28 * 8, "benzin": 1.775}
TAG = (datetime(2026, 2, 10), datetime(2026, 2, 10, 23, 59))
QUELLEN = [("InfluxDB 1.8", {"datasource": "influxdb"}),
           ("InfluxDB 2.7", {"datasource": "influxdb2"}),
           ("TimescaleDB (LTSS)", {"datasource": "postgres"}),
           ("VictoriaMetrics", {"datasource": "prometheus", "prom_url": "http://127.0.0.1:18428"}),
           ("Prometheus", {"datasource": "prometheus"})]


def pruefen():
    for name, extra in QUELLEN:
        print(f"\n{name}")
        dq = datenquellen.aus_einstellungen({**CFG, **extra})
        ok, text = dq.test()
        check(name, "Verbindungstest", ok, text)
        for key, soll in SOLL.items():
            try:
                ist = dq.monat_mittel(key, dq.kennungen(key), 2026, 2) if key == "benzin" else (
                    dq.monat_summe(key, dq.kennungen(key), 2026, 2) if key in ("pv", "wallbox")
                    else dq.monat_delta(key, dq.kennungen(key), 2026, 2))
            except Exception as e:
                ist = f"Fehler: {e}"
            check(name, f"Monatswert {key} 02/2026",
                  isinstance(ist, float) and nah(ist, soll), f"{ist} / soll {soll}")
        ist = dq.monatswert("km", 2025, 11)
        check(name, "Monat ohne Daten -> None", ist is None, str(ist))
        try:
            soc = dq.stundenwerte("soc", *TAG, "mean")
            km = dq.stundenwerte("km", *TAG, "last")
        except Exception as e:
            soc, km = [], []
            check(name, "Stundenwerte abrufbar", False, str(e))
        erwartet = [(f"2026-02-10T{h:02d}:00", 50 + (h % 12) * 2) for h in range(24)]
        check(name, "Stundenwerte Akkustand (24 Werte, Ortszeit)",
              [(a, round(b, 3)) for a, b in soc] == erwartet, f"{len(soc)} Werte: {soc[:3]}")
        check(name, "Stundenwerte km-Stand", len(km) == 24 and nah(km[1][1] - km[0][1], 40 / 24, 0.001),
              f"{len(km)} Werte: {km[:2]}")
    for name, extra in QUELLEN[:2]:
        dq = datenquellen.aus_einstellungen({**CFG, **extra, "influx_tag": "entity_id",
                                             "fn_odometer": "odo"})
        ist = dq.monatswert("km", 2026, 2)
        check(name, "Tag entity_id (ohne 'sensor.')", nah(ist, SOLL["km"]), str(ist))
    # Umbenannter Sensor: beide Namen mit "|" -> lueckenlos, auch im Monat der Umbenennung
    print()
    for name, extra in QUELLEN:
        influx = extra["datasource"].startswith("influx")
        feld = "fn_odometer" if influx else "ha_odometer"
        beide = "KM Alt | KM Neu" if influx else "sensor.km_alt | sensor.km_neu"
        nur_neu = "KM Neu" if influx else "sensor.km_neu"
        dq = datenquellen.aus_einstellungen({**CFG, **extra, feld: beide})
        werte = {m: dq.monatswert("km", 2026, m) for m in (1, 2, 3)}
        soll = {1: 31 * 40, 2: 28 * 40}
        check(name, "Umbenennung: Jan und Feb (Monat der Umbenennung) mit beiden Namen",
              all(nah(werte[m], soll[m]) for m in soll), str(werte))
        check(name, "Umbenennung: Maerz aus dem neuen Namen", werte[3] and werte[3] > 0, str(werte[3]))
        dq = datenquellen.aus_einstellungen({**CFG, **extra, feld: nur_neu})
        ist = dq.monatswert("km", 2026, 1)
        check(name, "Nur neuer Name: Januar leer, Grund wird genannt",
              ist is None and dq.grund.get("km") == "keine Werte im Monat", f"{ist} / {dq.grund}")
        dq.monatswert("km", 2026, 2)
        check(name, "Nur neuer Name: Februar ohne Vorwert, Grund wird genannt",
              "kein Wert vor dem Monat" in dq.grund.get("km", ""), str(dq.grund))

    # Luecke: der erste Monat danach darf nicht die Strecke mehrerer Monate liefern
    print()
    for name, extra in QUELLEN:
        influx = extra["datasource"].startswith("influx")
        feld = "fn_odometer" if influx else "ha_odometer"
        dq = datenquellen.aus_einstellungen({**CFG, **extra,
                                             feld: "KM Luecke" if influx else "sensor.km_luecke"})
        ist = dq.monatswert("km", 2026, 3)
        check(name, "Luecke Jan/Feb: Maerz liefert nichts statt 3 Monate Strecke",
              ist is None and dq.grund.get("km", "").startswith("Lücke"), f"{ist} / {dq.grund}")
        print(f"          Grund: {dq.grund.get('km')}")
        check(name, "Luecke: Dezember davor unveraendert", nah(dq.monatswert("km", 2025, 12), (31 * 24 - 1) * 40 / 24),
              str(dq.grund))

    # Suche in der Datenbank
    print()
    for name, extra in QUELLEN:
        dq = datenquellen.aus_einstellungen({**CFG, **extra})
        influx = not dq.nutzt_entity_ids
        try:
            treffer = dq.suche("KILO" if influx else "ODO")       # Gross/klein egal
            alle = dq.suche("")
            leer = dq.suche('gibt%s_nicht"/')                     # Sonderzeichen
        except Exception as e:
            check(name, "Suche", False, dq.fehlertext(e))
            continue
        soll = "Kilometerstand" if influx else "sensor.odo"
        t = treffer[0] if treffer else {}
        check(name, f"Suche findet '{soll}'", [x["kennung"] for x in treffer] == [soll],
              str([x["kennung"] for x in treffer]))
        einheit_ok = ("km" in (t.get("einheit") or "") if name != "TimescaleDB (LTSS)"
                      else t.get("einheit") == "km" and t.get("name") == "Kilometerstand")
        check(name, "Suche liefert Einheit/Name", einheit_ok, str(t))
        if dq.typ != "prometheus":
            zeitraum = (t.get("von") and t["von"].astimezone().strftime("%Y-%m"),
                        t.get("bis") and t["bis"].astimezone().strftime("%Y-%m"))
            check(name, "Suche liefert Zeitraum 12/2025 – 03/2026",
                  zeitraum == ("2025-12", "2026-03"), str(zeitraum))
        check(name, "Leere Suche listet alle 9 Zahlen-Sensoren", len(alle) == 9,
              str([x["kennung"] for x in alle]))
        check(name, "Sonderzeichen im Suchbegriff -> keine Treffer, kein Fehler", leer == [], str(leer))

    # Fehlerfaelle mit echten Servern
    falsch = [("InfluxDB 1.8", {"datasource": "influxdb", "influx_password": "falsch"}),
              ("InfluxDB 2.7", {"datasource": "influxdb2", "influx2_token": "falsch"}),
              ("InfluxDB 2.7", {"datasource": "influxdb2", "influx2_bucket": "gibtsnicht"}),
              ("TimescaleDB (LTSS)", {"datasource": "postgres", "pg_password": "falsch"}),
              ("TimescaleDB (LTSS)", {"datasource": "postgres", "pg_tabelle": "gibtsnicht"}),
              ("TimescaleDB (LTSS)", {"datasource": "postgres", "pg_database": "gibtsnicht"}),
              ("Prometheus", {"datasource": "prometheus", "prom_url": "http://127.0.0.1:19999"})]
    print()
    for name, extra in falsch:
        ok, text = datenquellen.aus_einstellungen({**CFG, **extra}).test()
        check(name, f"Fehler erkannt ({', '.join(f'{k}={v}' for k, v in extra.items() if k != 'datasource')})",
              not ok, text)
        print(f"          Meldung: {text[:120]}")


if __name__ == "__main__":
    try:
        starten()
        befuellen()
        pruefen()
    finally:
        if not BEHALTEN:
            print("\nEntferne Container …")
            aufraeumen()
    ok_n = sum(1 for e in ERG if e[2])
    print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden")
    sys.exit(0 if ERG and ok_n == len(ERG) else 1)
