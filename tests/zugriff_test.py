# -*- coding: utf-8 -*-
"""
Test: Zugriff im Add-on und Maskieren fremder Texte.

Anlass: Sicherheitspruefung fuer den Add-on-Betrieb.
  1. Im Add-on nimmt die App nur Anfragen ueber Ingress (Supervisor 172.30.32.2) an –
     andere Add-ons im internen Netz kaemen sonst ohne HA-Anmeldung durch. Ausnahme:
     /api/ladung (eigener Bearer-Token).
  2. Heikle Aktionen (Zugangsdaten, Backup zurueckspielen, Datenbank leeren) nur fuer
     HA-Admins. Ohne Benutzerkennung oder ohne lesbare Benutzerliste wird nicht gesperrt.
  3. Namen von Anbietern und Fahrzeugen landen maskiert im Monatsbericht (HTML).
  4. Der Export des Einstellungs-Werkzeugs "ohne Secrets" nutzt dieselbe Liste wie die Web-App.
Laeuft gegen eine eigene Test-DB; HA wird durch eine Attrappe ersetzt.

Aufruf (aus dem Repo-Ordner):
    python tests/zugriff_test.py
"""
import json, os, sys, tempfile
from datetime import datetime

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_zugriff_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import berichte
import database as db
import heimladung
import settings_tool

ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


INGRESS = ("172.30.32.2", 50000)
anderes_addon = TestClient(webapp.app, client=("172.30.33.5", 50000))
ingress = TestClient(webapp.app, client=INGRESS)

# ── Standalone/Tests: kein Filter ────────────────────────────────────────────
check("Ohne Add-on: Seite von beliebiger Adresse", anderes_addon.get("/einstellungen").status_code == 200)

# ── Add-on: nur ueber Ingress ────────────────────────────────────────────────
webapp.IST_ADDON = True
r = anderes_addon.get("/einstellungen")
check("Add-on: anderes Add-on bekommt 403", r.status_code == 403, r.status_code)
check("Add-on: auch API gesperrt", anderes_addon.post("/api/reset").status_code == 403)
check("Add-on: ueber Ingress erreichbar", ingress.get("/einstellungen").status_code == 200)
heimladung.token_neu()
r = anderes_addon.post("/api/ladung", json={})
check("Add-on: /api/ladung ohne Ingress erreichbar (Token-Pruefung greift)", r.status_code == 401, r.status_code)


# ── Admin-Pruefung ───────────────────────────────────────────────────────────
BENUTZER = [{"id": "eigentuemer", "is_owner": True, "group_ids": ["system-users"]},
            {"id": "admin", "is_owner": False, "group_ids": ["system-admin"]},
            {"id": "nutzer", "is_owner": False, "group_ids": ["system-users"]}]
aufrufe = []


class HAAttrappe:
    fehler = None

    def __init__(self, **verbindung):
        pass

    def benutzer(self):
        aufrufe.append(1)
        if HAAttrappe.fehler:
            raise ConnectionError(HAAttrappe.fehler)
        return BENUTZER


webapp.HAClient = HAAttrappe
webapp._ha_verbindung = lambda cfg: {"url": "http://supervisor/core", "token": "t"}


def neu_laden():
    webapp._admin_cache.update(zeit=None, rechte=None)


def als(benutzer):
    return {"X-Remote-User-Id": benutzer} if benutzer else {}


neu_laden()
r = ingress.post("/api/reset", headers=als("nutzer"), data={"bereiche": "fahrten", "bestaetigt": "ja"})
check("Nicht-Admin: Reset gesperrt (403, Meldung)",
      r.status_code == 403 and "Administratoren" in r.json().get("error", ""), (r.status_code, r.text[:200]))
r = ingress.post("/api/backup/restore", headers=als("nutzer"),
                 files={"datei": ("x.db", b"kaputt")}, data={"bestaetigt": "ja"})
check("Nicht-Admin: Backup zurueckspielen gesperrt", r.status_code == 403, r.status_code)
r = ingress.get("/api/settings/export", params={"secrets": 1}, headers={**als("nutzer"),
                "Referer": "http://ha/api/hassio_ingress/abc/einstellungen"}, follow_redirects=False)
check("Nicht-Admin: Export mit Zugangsdaten -> zurueck mit Banner",
      r.status_code == 303 and r.headers["location"].endswith("/einstellungen?nur_admin=1"),
      (r.status_code, r.headers.get("location")))
r = ingress.get("/api/settings/export", params={"secrets": 0}, headers=als("nutzer"))
check("Nicht-Admin: Export ohne Zugangsdaten erlaubt", r.status_code == 200 and "einstellungen" in r.json())
r = ingress.post("/einstellungen/ha", headers={**als("nutzer"), "Referer": "http://ha/x/einstellungen"},
                 data={"ha_url": "http://boese"}, follow_redirects=False)
check("Nicht-Admin: HA-Verbindung aendern gesperrt",
      r.status_code == 303 and "nur_admin=1" in r.headers["location"]
      and db.get_ha_settings().get("ha_url") != "http://boese", r.headers.get("location"))
check("Nicht-Admin: normale Aktionen erlaubt",
      ingress.post("/stromtarif", headers=als("nutzer"), follow_redirects=False,
                   data={"gueltig_ab": "2026-01-01", "preis": "30"}).status_code != 403)
check("Banner wird angezeigt", "Nicht ausgeführt" in ingress.get("/einstellungen?nur_admin=1").text)
check("Banner sonst nicht", "Nicht ausgeführt" not in ingress.get("/einstellungen").text)

for wer in ("eigentuemer", "admin"):
    r = ingress.get("/api/settings/export", params={"secrets": 1}, headers=als(wer))
    check(f"{wer}: Export mit Zugangsdaten erlaubt", r.status_code == 200 and r.json()["enthaelt_zugangsdaten"])
check("Benutzerliste nur einmal gelesen (gemerkt)", len(aufrufe) == 1, len(aufrufe))

r = ingress.get("/api/settings/export", params={"secrets": 1})
check("Ohne Benutzerkennung: nicht gesperrt", r.status_code == 200)
r = ingress.get("/api/settings/export", params={"secrets": 1}, headers=als("neu-angelegt"))
check("Unbekannter Benutzer: nicht gesperrt", r.status_code == 200)

neu_laden()
HAAttrappe.fehler = "Supervisor nicht erreichbar"
r = ingress.get("/api/settings/export", params={"secrets": 1}, headers=als("nutzer"))
check("Benutzerliste nicht lesbar: nicht gesperrt (kein Aussperren)", r.status_code == 200)
HAAttrappe.fehler = None
neu_laden()

webapp.IST_ADDON = False
r = anderes_addon.get("/api/settings/export", params={"secrets": 1}, headers=als("nutzer"))
check("Ohne Add-on: keine Admin-Pruefung", r.status_code == 200)


# ── Monatsbericht: Namen maskiert ────────────────────────────────────────────
BOESE = '<img src=x onerror="alert(1)">'
jetzt = datetime.now()
db.add_lade_anbieter(BOESE)
db.add_ladevorgang(f"{jetzt:%Y-%m}-01", 20, 0.4, 8, BOESE, 11, "AC")
seite = TestClient(webapp.app).get("/api/bericht/vorschau",
                                   params={"jahr": jetzt.year, "monat": jetzt.month}).text
check("Bericht: Anbietername maskiert", BOESE not in seite and "&lt;img src=x" in seite,
      seite[seite.find("Anbieter"):][:300])
html = berichte.als_html({**berichte.monatsbericht(jetzt.year, jetzt.month),
                          "titel": "<b>Titel</b>", "hinweis": "Auto <i>1</i>: fehlt"})
check("Bericht: Titel und Hinweis maskiert",
      "<b>Titel</b>" not in html and "&lt;b&gt;Titel" in html and "&lt;i&gt;1" in html)


# ── Einstellungs-Werkzeug: Export ohne Secrets ───────────────────────────────
db.set_einstellungen({"mail_passwort": "GEHEIM-MAIL", "ha_token": "GEHEIM-HA"})
ziel = os.path.join(TESTDIR, "export.json")
settings_tool.exportieren(ziel, mit_secrets=False)
with open(ziel, encoding="utf-8") as f:
    werte = json.load(f)["einstellungen"]
check("Werkzeug: Export ohne Secrets ohne Mail-Passwort, Token, Push-Token",
      not {"mail_passwort", "ha_token", "push_token"} & set(werte), sorted(werte)[:5])


# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
