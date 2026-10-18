# -*- coding: utf-8 -*-
"""
Test: Diagnose-Paket (diagnose.py, /api/diagnose/paket).

Anlass: Bei Importproblemen reicht ein Datenbank-Backup nicht – es zeigt nur das Ergebnis,
nicht die Zaehlerstaende aus HA. Das Paket bringt Datenbank, Importprotokoll und
HA-Rohdaten mit; Zugangsdaten duerfen darin nicht stehen, auch nicht in freien Seiten der
Datei. Nebenbei: der Einstellungs-Export "ohne Token/Passwort" enthielt das Mail-Passwort.
Laeuft gegen eine eigene Test-DB; HA wird durch eine Attrappe ersetzt.

Aufruf (aus dem Repo-Ordner):
    python tests/diagnose_test.py
"""
import io, json, os, sqlite3, sys, tempfile, zipfile
from datetime import datetime

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_diagnose_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, diagnose
from ha_client import HAClient

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


GEHEIMNISSE = {"ha_token": "GEHEIM-HA-TOKEN-123", "mail_passwort": "GEHEIM-MAIL-456",
               "push_token": "GEHEIM-PUSH-789", "influx2_token": "GEHEIM-INFLUX-0"}
db.set_einstellungen({**GEHEIMNISSE, "mail_empfaenger": "jemand@example.org",
                      "ha_wallbox_energy": "sensor.evcc_monatlich",
                      "ha_odometer": "sensor.km_alt | sensor.km",
                      "ha_wallbox_energy@2": "sensor.wallbox_auto2",
                      "ha_tankerkoenig": ""})
with open(webapp.IMPORT_LOG_DATEI, "w", encoding="utf-8") as f:
    f.write("[2026-10-01 03:00:00] Wallbox: 62.92 kWh\n")


# ── Sensoren aus den Einstellungen ───────────────────────────────────────────
s = diagnose.sensoren(db.get_alle_einstellungen())
check("Sensoren: alle eingetragenen, auch umbenannte und je Fahrzeug",
      set(s) >= {"sensor.evcc_monatlich", "sensor.km_alt", "sensor.km", "sensor.wallbox_auto2"}, s)
check("Sensoren: Herkunft vermerkt", s["sensor.wallbox_auto2"] == ["ha_wallbox_energy@2"], s)


# ── HA-Attrappe ──────────────────────────────────────────────────────────────
class HAAttrappe(HAClient):
    def __init__(self):
        super().__init__("http://x", "t")
        self.history_aufrufe = []
    def _get_statistics(self, ids, start, ende, period="hour"):
        return {eid: [{"start": "2026-09-30T23:00:00", "state": 32.85, "sum": 100.0},
                      {"start": "2026-10-01T00:00:00", "state": 0.0, "sum": 100.0}]
                for eid in ids if eid != "sensor.km_alt"}
    def _get(self, pfad):
        if pfad.endswith("sensor.km_alt"):
            raise ValueError("404 nicht gefunden")
        return {"state": "95.77", "last_changed": "2026-10-18T10:00:00",
                "attributes": {"unit_of_measurement": "kWh", "state_class": "total_increasing"}}
    def get_history_period(self, eid, start, ende):
        self.history_aufrufe.append((eid, start, ende))
        return [{"state": "32.85", "last_changed": "2026-09-30T22:00:00"},
                {"state": "0", "last_changed": "2026-10-01T00:00:02"}]


ha = HAAttrappe()
roh = diagnose.ha_rohdaten(ha, s, monate=3, jetzt=datetime(2026, 10, 18, 12))
e = roh["sensoren"]["sensor.evcc_monatlich"]
check("Rohdaten: Zustand mit state_class", e["zustand"]["attribute"]["state_class"] == "total_increasing", e["zustand"])
check("Rohdaten: Stundenstatistik", len(e["statistik_stunden"]) == 2 and e["statistik_stunden"][0]["state"] == 32.85)
check("Rohdaten: History je Monatswechsel (Aug, Sep, Okt)",
      list(e["history_monatswechsel"]) == ["2026-08", "2026-09", "2026-10"], list(e["history_monatswechsel"]))
check("Rohdaten: Monatswechsel vom Vorabend an",
      any(st == datetime(2026, 9, 30, 20) for _e, st, _x in ha.history_aufrufe), ha.history_aufrufe[:3])
check("Rohdaten: Fehler eines Sensors bricht nicht ab",
      "fehler" in roh["sensoren"]["sensor.km_alt"]["zustand"] and "sensor.km" in roh["sensoren"])


# ── Endpunkt ────────────────────────────────────────────────────────────────
alt_client = webapp._ha_client
webapp._ha_client = lambda: HAAttrappe()
r = c.get("/api/diagnose/paket")
webapp._ha_client = alt_client
check("Paket: Download als ZIP", r.status_code == 200 and r.headers["content-type"] == "application/zip"
      and "ev_tracker_diagnose_" in r.headers.get("content-disposition", ""), r.status_code)

z = zipfile.ZipFile(io.BytesIO(r.content))
check("Paket: Inhalt", set(z.namelist()) == {"ev_tracker.db", "import.log", "info.json", "ha_rohdaten.json"},
      z.namelist())
check("Paket: Importprotokoll", "62.92" in z.read("import.log").decode("utf-8"))
info = json.loads(z.read("info.json"))
check("Paket: Version und geleerte Schluessel", info["version"] == webapp.VERSION
      and {"ha_token", "mail_passwort", "push_token", "mail_empfaenger"} <= set(info["geleert"]), info)
check("Paket: HA-Rohdaten", "sensor.evcc_monatlich" in json.loads(z.read("ha_rohdaten.json"))["sensoren"])

roh_db = z.read("ev_tracker.db")
pfad = os.path.join(TESTDIR, "aus_paket.db")
with open(pfad, "wb") as f:
    f.write(roh_db)
con = sqlite3.connect(pfad)
werte = dict(con.execute("SELECT key, value FROM einstellungen").fetchall())
con.close()
check("Paket-DB: Zugangsdaten leer", all(werte.get(k) == "" for k in GEHEIMNISSE), {k: werte.get(k) for k in GEHEIMNISSE})
check("Paket-DB: Mail-Adresse leer", werte.get("mail_empfaenger") == "")
check("Paket-DB: Sensoren bleiben", werte.get("ha_wallbox_energy") == "sensor.evcc_monatlich")
check("Paket-DB: Geheimnisse auch nicht in freien Seiten",
      not any(v.encode() in roh_db for v in GEHEIMNISSE.values()))
check("Original-DB unveraendert", db.get_alle_einstellungen()["ha_token"] == "GEHEIM-HA-TOKEN-123")

# Ohne HA: Paket trotzdem, mit Hinweis
webapp._ha_client = lambda: None
z = zipfile.ZipFile(io.BytesIO(c.get("/api/diagnose/paket").content))
webapp._ha_client = alt_client
check("Ohne HA: Paket mit Hinweis", "hinweis" in json.loads(z.read("ha_rohdaten.json")))

check("Backup-Seite: Knopf", "api/diagnose/paket" in c.get("/backup").text)
seite = c.get("/backup").text
check("Backup-Seite: Mailvorlage an den Support", "diagnoseMail()" in seite
      and diagnose.SUPPORT_MAIL in seite and 'id="diagnose-text"' in seite)
alt_mail, diagnose.SUPPORT_MAIL = diagnose.SUPPORT_MAIL, ""
check("Backup-Seite: ohne Support-Adresse kein Mailknopf", "diagnoseMail()" not in c.get("/backup").text)
diagnose.SUPPORT_MAIL = alt_mail

# ── Einstellungs-Export ohne Zugangsdaten ────────────────────────────────────
ex = c.get("/api/settings/export", params={"secrets": 0}).json()["einstellungen"]
check("Export ohne Zugangsdaten: auch ohne Mail-Passwort",
      not any(k in ex for k in GEHEIMNISSE), [k for k in GEHEIMNISSE if k in ex])

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
