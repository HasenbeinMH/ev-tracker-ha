# -*- coding: utf-8 -*-
"""
Test "Mehrere Fahrzeuge" (3.0).

Grundlage ist die Test-Datenbank des Funktionstests (20 Monate, ein Fahrzeug). Geprueft wird:
  - Umschalten auf "Mehrere": Sicherung, Umbau, Zeilen/Summen und Kennzahlen unveraendert
  - zweites Fahrzeug: eigene Daten, Gesamtsicht = Summe, Formulare, Push, Import-Verteilung
  - gemeinsame Grundgebuehr und Wallbox nach km, eigene Zaehler, Ausblenden, Hauptfahrzeug
  - Umschalten 1 -> 2 -> 1 -> 2 loescht nichts (Zeilen und Summen aller Tabellen gleich)
  - Loeschen nur mit Namensbestaetigung, Abbruch des Umbaus rollt zurueck
  - Einstellungs-Export/-Import mit Fahrzeugen
Laeuft gegen Kopien in einem temporaeren Ordner.

Aufruf (aus dem Repo-Ordner):  python tests/fahrzeuge_test.py
"""
import json, os, re, shutil, sqlite3, subprocess, sys, tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
sys.path.insert(0, HIER)
import migrationstest  # db_fuellen, tabellen, vergleich

TMP = tempfile.mkdtemp(prefix="ev_fahrzeuge_")
DB_PFAD, _lauf = migrationstest.db_fuellen(REPO, TMP)
GRUND = os.path.join(TMP, "grundlage.db")          # unveraenderte Kopie (Stand 2, ein Fahrzeug)
shutil.copy(DB_PFAD, GRUND)
os.environ["EV_TRACKER_DB"] = DB_PFAD
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, zeitraum, berichte, heimladung, charts

c = TestClient(webapp.app)
ERG = []
ZEITRAEUME = ("alles", "2025", "2026", "2025-Q3", "2026-Q1", "2025-S", "2025-W")


def check(bereich, test, ok, detail=""):
    ERG.append((bereich, test, bool(ok), detail))


def nah(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


def kennzahlen(fid=None):
    """Kennzahlen aller Zeitraeume fuer ein Fahrzeug (None = aktueller Kontext)."""
    from contextlib import nullcontext
    with (db.fahrzeug_kontext(fid) if fid is not None else nullcontext()):
        d = zeitraum.laden()
        return {k: zeitraum.kennzahlen(zeitraum.aufloesen(k), d) for k in ZEITRAEUME}


def ohne_intern(k):
    return {x: v for x, v in k.items() if not x.startswith("_") and x != "je_fahrzeug"}


def sichtbarer_text(html):
    """Text ohne Skripte und Tags – fuer "sieht gleich aus"."""
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    # Sprachumschalter DE | EN ist gewollt neu (3.1) – kein Unterschied im Sinne dieses Vergleichs
    html = re.sub(r'<form class="sprachwahl".*?</form>', " ", html, flags=re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


SEITEN = ["/", "/statistik", "/fahrten", "/laden", "/benzin", "/stromtarif", "/ladetarife",
          "/steuer", "/instandhaltung", "/versicherung", "/import", "/rechnung", "/berichte",
          "/backup", "/einstellungen", "/einrichtung", "/hilfe", "/?zeitraum=2025",
          "/statistik?a=2025-S&b=2025-W"]
HAUPTSEITEN = ["/", "/statistik", "/fahrten", "/laden", "/benzin", "/stromtarif", "/ladetarife",
               "/steuer", "/instandhaltung", "/versicherung", "/berichte", "/rechnung"]

# ── 1. Ein Fahrzeug: Ausgangslage ─────────────────────────────────────────────
k_vorher = kennzahlen()
km1_vorher = {f["monat"]: f["km"] for f in db.get_fahrten_monate()}
tab_vorher = migrationstest.tabellen(DB_PFAD)
html_vorher = {s: sichtbarer_text(c.get(s).text) for s in HAUPTSEITEN}
check("Ein Fahrzeug", "Standard: ein Fahrzeug, Struktur-Stand 2",
      not db.mehrere_fahrzeuge() and db.schema_stand() == 2, str(db.schema_stand()))
r = c.get("/")
check("Ein Fahrzeug", "Kein Fahrzeug-Umschalter, kein Fahrzeugfeld",
      'class="fz-wahl"' not in r.text and 'name="fahrzeug_id"' not in c.get("/laden").text)
check("Ein Fahrzeug", "Einstellungen zeigen den Schalter", "Wie viele E-Autos" in c.get("/einstellungen").text)

# ── 2. Umschalten auf "Mehrere" ───────────────────────────────────────────────
vorher_sicherungen = {f for f in os.listdir(TMP) if f.startswith("vor_mehrere_fahrzeuge")}
r = c.post("/einstellungen/fahrzeuge/modus", data={"modus": "mehrere"}, follow_redirects=False)
neue = {f for f in os.listdir(TMP) if f.startswith("vor_mehrere_fahrzeuge")} - vorher_sicherungen
check("Umschalten", "Mehrere eingeschaltet, Struktur-Stand 3",
      r.status_code == 303 and db.mehrere_fahrzeuge() and db.schema_stand() == 3,
      f"{r.status_code} {db.schema_stand()}")
check("Umschalten", "Sicherung vor dem Umbau angelegt", len(neue) == 1, str(neue))
with sqlite3.connect(os.path.join(TMP, next(iter(neue)))) as k:
    st = k.execute("SELECT value FROM einstellungen WHERE key='schema_version'").fetchone()[0]
check("Umschalten", "Sicherung ist der Stand vor dem Umbau (2)", st == "2", st)
abw = migrationstest.vergleich(tab_vorher, migrationstest.tabellen(DB_PFAD))
check("Umschalten", "Zeilenzahl und Summen jeder Tabelle unveraendert", not abw, "; ".join(abw[:5]))
abw = migrationstest.vergleich(k_vorher, kennzahlen())
check("Umschalten", "Kennzahlen mit nur einem Fahrzeug unveraendert", not abw, "; ".join(abw[:5]))
with sqlite3.connect(DB_PFAD) as k:
    sql = k.execute("SELECT sql FROM sqlite_master WHERE name='fahrten_monat'").fetchone()[0]
check("Umschalten", "fahrten_monat eindeutig je Fahrzeug und Monat", "UNIQUE (fahrzeug_id, monat)" in sql, sql)
r = c.post("/einstellungen/fahrzeuge/modus", data={"modus": "mehrere"}, follow_redirects=False)
check("Umschalten", "Erneutes Einschalten baut nicht noch einmal um (keine weitere Sicherung)",
      len({f for f in os.listdir(TMP) if f.startswith("vor_mehrere_fahrzeuge")} - vorher_sicherungen) == 1)

# ── 3. Zweites Fahrzeug ───────────────────────────────────────────────────────
r = c.post("/einstellungen/fahrzeuge/neu", data={"name": "Zweitwagen"}, follow_redirects=False)
F2 = max(f["id"] for f in db.fahrzeuge(alle=True))
check("Fahrzeug 2", "Anlegen waehlt das neue Fahrzeug aus",
      r.status_code == 303 and f"fahrzeug={F2}" in r.headers["location"], r.headers.get("location"))
with db.fahrzeug_kontext(F2):
    check("Fahrzeug 2", "Neues Fahrzeug ohne fremde Sensoren und Steuer",
          db.get_ha_settings()["ha_odometer"] == "" and (db.get_einstellung("kfz_steuer_benziner") or 0) == 0,
          db.get_ha_settings()["ha_odometer"])
    check("Fahrzeug 2", "Vergleichswerte vom Hauptfahrzeug uebernommen (Benzin, 7,0 L)",
          db.get_config()["kraftstoff"] == "benzin" and db.get_config()["benziner_verbrauch"] == 7.0)
check("Fahrzeug 2", "Fahrzeug 1 behaelt seine Einstellungen",
      db.get_ha_settings(1)["ha_odometer"] != "" and db.get_einstellung_str("fahrzeug_name") == "Test EV",
      db.get_einstellung_str("fahrzeug_name"))

c.get(f"/?fahrzeug={F2}")                                  # Auswahl per Cookie
F2_KM = {"2026-06": 800.0, "2026-07": 900.0, "2026-08": 700.0}
for m, km in F2_KM.items():
    c.post("/fahrten", data={"monat": m, "km": str(km)}, follow_redirects=False)
c.post("/einstellungen/parameter", data={
    "fahrzeug_id": str(F2), "fahrzeug_name": "Zweitwagen", "kraftstoff": "diesel",
    "benziner_verbrauch": "5,0", "ev_verbrauch": "16", "pv_preis": "13", "co2_benzin": "2,65",
    "kfz_steuer": "120"}, follow_redirects=False)
c.post("/laden", data={"datum": "2026-07-10", "kwh": "40", "preis_kwh": "50", "anbieter": "EnBW",
                       "ladetyp": "DC", "leistung": "150"}, follow_redirects=False)
c.post("/steuer/thg", data={"datum": "2026-07-01", "betrag": "60", "anbieter": "ADAC"},
       follow_redirects=False)

with db.fahrzeug_kontext(1):
    km1 = {f["monat"]: f["km"] for f in db.get_fahrten_monate()}
with db.fahrzeug_kontext(F2):
    km2 = {f["monat"]: f["km"] for f in db.get_fahrten_monate()}
    lade2 = db.get_ladevorgaenge(limit=1000)
    cfg2 = db.get_config()
check("Fahrzeug 2", "km nur beim gewaehlten Fahrzeug, Fahrzeug 1 unveraendert",
      km2 == F2_KM and km1 == km1_vorher, f"{km2} / {len(km1)} Monate")
check("Fahrzeug 2", "Ladung und Vergleichswerte beim Fahrzeug 2",
      len(lade2) == 1 and lade2[0]["menge_kwh"] == 40 and cfg2["benziner_verbrauch"] == 5.0
      and cfg2["kraftstoff"] == "diesel", f"{len(lade2)} {cfg2['benziner_verbrauch']}")
with db.fahrzeug_kontext(1):
    check("Fahrzeug 2", "Vergleichswerte von Fahrzeug 1 unveraendert",
          db.get_config()["benziner_verbrauch"] == 7.0 and db.get_config()["kraftstoff"] == "benzin")

# Kennzahlen je Fahrzeug und Summe
k1, k2, ka = kennzahlen(1), kennzahlen(F2), kennzahlen(db.ALLE)
for z in ZEITRAEUME:
    s = {x: k1[z][x] + k2[z][x] for x in ("gesamt_km", "gesamt_kwh", "strom_kosten", "benzin_kosten",
                                           "ersparnis_kraft", "kfz_steuer", "thg_gesamt",
                                           "ersparnis_gesamt", "co2_gespart", "liter")}
    abw = [x for x in s if not nah(s[x], ka[z][x], 0.02)]
    check(f"Gesamtsicht {z}", "Summen = Fahrzeug 1 + Fahrzeug 2", not abw,
          ", ".join(f"{x}: {s[x]:.2f} / {ka[z][x]:.2f}" for x in abw))
    if ka[z]["gesamt_kwh"]:
        check(f"Gesamtsicht {z}", "Ø Strompreis aus den Summen (nicht gemittelt)",
              nah(ka[z]["strompreis_ct"], ka[z]["strom_kosten"] / ka[z]["gesamt_kwh"] * 100, 0.001))
k2a = k2["alles"]
soll_benzin2 = sum(km / 100 * 5.0 * p["preis_liter"] for m, km in F2_KM.items()
                   for p in db.get_benzinpreise() if p["monat"] == m)
check("Fahrzeug 2", "Diesel-Vergleich mit 5,0 L/100 km und Monatspreisen",
      nah(k2a["benzin_kosten"], soll_benzin2), f'{k2a["benzin_kosten"]:.2f} / {soll_benzin2:.2f}')
check("Fahrzeug 2", "KFZ-Steuer nur fuer die eigenen 3 Monate (120 €/Jahr)",
      nah(k2a["kfz_steuer"], 120 * 3 / 12) and k2a["monate"] == 3, f'{k2a["kfz_steuer"]} {k2a["monate"]}')
check("Fahrzeug 2", "CO2 mit Diesel-Faktor 2,65",
      nah(k2a["co2_gespart"], sum(F2_KM.values()) / 100 * 5.0 * 2.65, 0.1), f'{k2a["co2_gespart"]:.1f}')

# Gemeinsame Grundgebuehr (EnBW M, 5,99 €) nach km verteilt
gebuehren = {}
for fid in (1, F2):
    with db.fahrzeug_kontext(fid):
        import ladetarife
        gebuehren[fid] = {e["datum"][:7]: e["gesamtpreis"] for e in ladetarife.grundgebuehr_eintraege()}
m = "2026-07"
anteil2 = 900 / (km1[m] + 900)
check("Grundgebuehr", "Gemeinsamer Tarif im Juli nach km geteilt",
      nah(gebuehren[F2][m], round(5.99 * anteil2, 2)) and nah(gebuehren[1][m] + gebuehren[F2][m], 5.99, 0.011),
      f"{gebuehren[1][m]} + {gebuehren[F2][m]}")
check("Grundgebuehr", "Monat ohne km von Fahrzeug 2: alles bei Fahrzeug 1",
      nah(gebuehren[1]["2025-05"], 5.99) and nah(gebuehren[F2]["2025-05"], 0.0),
      f'{gebuehren[1]["2025-05"]} / {gebuehren[F2]["2025-05"]}')

# Gesamtsicht im Browser-HTML
c.get("/?fahrzeug=alle")
r = c.get("/")
check("Gesamtsicht", "Dashboard: Tabelle je Fahrzeug, Name „Alle Fahrzeuge“",
      "Je Fahrzeug" in r.text and "Zweitwagen" in r.text and "Alle Fahrzeuge" in r.text)
with db.fahrzeug_kontext(db.ALLE):
    daten = zeitraum.laden()
    f_all = zeitraum.filtern(zeitraum.aufloesen("alles"), daten)
    ch = charts.chart_monatliche_ersparnis(f_all["fahrten"], f_all["benzin"], f_all["lade"],
                                           liter_je_monat=daten["liter_je_monat"])
summe_chart = sum(ch["series"][2]["data"])
check("Gesamtsicht", "Diagramm Monats-Ersparnis = Kachel Kraftstoff-Ersparnis",
      abs(summe_chart - ka["alles"]["ersparnis_kraft"]) < 1.0,
      f'{summe_chart:.2f} / {ka["alles"]["ersparnis_kraft"]:.2f}')
with db.fahrzeug_kontext(db.ALLE):
    wa = zeitraum.monatswerte(zeitraum.aufloesen("2026"), zeitraum.laden())
check("Gesamtsicht", "Statistik-Monatswerte summieren sich auf die Kennzahlen",
      nah(sum(w["km"] for w in wa), ka["2026"]["gesamt_km"], 0.5)
      and nah(sum(w["strom_kosten"] for w in wa), ka["2026"]["strom_kosten"], 0.5),
      f'{sum(w["km"] for w in wa)} / {ka["2026"]["gesamt_km"]}')
fehler = []
for wahl in ("1", str(F2), "alle"):
    c.get(f"/?fahrzeug={wahl}")
    fehler += [f"{wahl}{s}" for s in SEITEN if c.get(s).status_code != 200]
check("Seiten", "Alle Seiten laden fuer Fahrzeug 1, Fahrzeug 2 und Alle", not fehler, str(fehler))
c.get("/?fahrzeug=alle")
r = c.get("/laden")
check("Formulare", "Gesamtsicht: Fahrzeug muss im Formular gewaehlt werden",
      re.search(r'name="fahrzeug_id"\s+required', r.text) is not None and "– wählen –" in r.text)
with db.fahrzeug_kontext(db.ALLE):
    mb = berichte.monatsbericht(2026, 7)
check("Berichte", "Monatsbericht Gesamtsicht: Summe und je Fahrzeug",
      len(mb["daten"]["je_fahrzeug"]) == 2
      and nah(mb["daten"]["km"], km1["2026-07"] + 900) and "alle Fahrzeuge" in mb["titel"],
      f'{mb["daten"]["km"]} {mb["titel"]}')
check("Berichte", "Mail-HTML enthaelt Abschnitt „Je Fahrzeug“", "Je Fahrzeug" in berichte.als_html(mb))

# Formular mit Fahrzeugauswahl in der Gesamtsicht
c.post("/steuer/thg", data={"datum": "2026-08-02", "betrag": "11", "anbieter": "X",
                            "fahrzeug_id": str(F2)}, follow_redirects=False)
with db.fahrzeug_kontext(F2):
    check("Formulare", "THG in der Gesamtsicht mit Fahrzeugauswahl -> Fahrzeug 2",
          any(t["betrag"] == 11 for t in db.get_thg_eintraege()))
# Ladung umhaengen (Bearbeiten in der Gesamtsicht)
with db.fahrzeug_kontext(F2):
    lid = db.get_ladevorgaenge()[0]["id"]
r = c.post("/laden/update", data={"id": lid, "datum": "2026-07-10", "kwh": "40", "preis_kwh": "50",
                                  "anbieter": "EnBW", "ladetyp": "DC", "fahrzeug_id": "1"})
with db.fahrzeug_kontext(1):
    umgehaengt = any(l["id"] == lid for l in db.get_ladevorgaenge(limit=10000))
c.post("/laden/update", data={"id": lid, "datum": "2026-07-10", "kwh": "40", "preis_kwh": "50",
                              "anbieter": "EnBW", "ladetyp": "DC", "fahrzeug_id": str(F2)})
with db.fahrzeug_kontext(F2):
    zurueck = any(l["id"] == lid for l in db.get_ladevorgaenge())
check("Formulare", "Ladung laesst sich einem anderen Fahrzeug zuordnen und zurueck", umgehaengt and zurueck)
c.get(f"/?fahrzeug={F2}")
c.post("/laden/update", data={"id": lid, "datum": "2026-07-10", "kwh": "41", "preis_kwh": "50",
                              "anbieter": "EnBW", "ladetyp": "DC"})
with db.fahrzeug_kontext(F2):
    l = next(l for l in db.get_ladevorgaenge() if l["id"] == lid)
check("Formulare", "Bearbeiten ohne Fahrzeugfeld behaelt die Zuordnung", l["menge_kwh"] == 41, str(l["menge_kwh"]))

# Versicherung je Fahrzeug
c.post("/versicherung", data={"fahrzeug": "Zweitwagen", "gesellschaft": "HUK", "gueltig_ab": "2026-06-01",
                              "deckung": "Haftpflicht", "grundbeitrag": "300", "fahrzeug_id": str(F2)},
       follow_redirects=False)
with db.fahrzeug_kontext(1):
    v1 = db.get_versicherungen()
with db.fahrzeug_kontext(F2):
    v2 = db.get_versicherungen()
with db.fahrzeug_kontext(db.ALLE):
    va = db.get_versicherungen()
check("Versicherung", "Vertrag je Fahrzeug, Gesamtsicht zeigt alle",
      len(v2) == 1 and all(v["fahrzeug_id"] != F2 for v in v1) and len(va) == len(v1) + 1,
      f"{len(v1)} / {len(v2)} / {len(va)}")

# Push mit Fahrzeug
c.post("/einstellungen/push-token", data={"aktion": "neu"}, follow_redirects=False)
token = heimladung.token()
KOPF = {"Authorization": f"Bearer {token}"}
for wert in ("Zweitwagen", str(F2), float(F2)):
    r = c.post("/api/ladung", json={"start": "2026-08-05T20:00", "ende": "2026-08-05T23:00",
                                    "kwh_netz": 10, "kwh_pv": 2, "fahrzeug": wert}, headers=KOPF)
    check("Push", f"Fahrzeug-Angabe {wert!r} -> Fahrzeug 2",
          r.status_code == 200 and r.json()["fahrzeug"] == F2, f"{r.status_code} {r.text[:120]}")
with db.fahrzeug_kontext(F2):
    push2 = [l for l in db.get_ladevorgaenge() if l["extern_id"]]
check("Push", "Dreimal dieselbe Ladung: nur einmal gespeichert (Kennung mit Fahrzeug)",
      len(push2) == 2 and all(l["extern_id"].endswith((f"@{F2}:netz", f"@{F2}:pv")) for l in push2),
      str([l["extern_id"] for l in push2]))
r = c.post("/api/ladung", json={"start": "2026-08-06T20:00", "kwh_netz": 5, "fahrzeug": "Gibtsnicht"},
           headers=KOPF)
check("Push", "Unbekanntes Fahrzeug abgelehnt (422)", r.status_code == 422, str(r.status_code))
r = c.post("/api/ladung", json={"start": "2026-08-06T21:00", "kwh_netz": 5}, headers=KOPF)
check("Push", "Ohne Angabe -> Hauptfahrzeug", r.status_code == 200 and r.json()["fahrzeug"] == 1, r.text[:100])

# Gemeinsame Wallbox: Rest nach km, Push-Ladungen der Gruppe vorher abgezogen
km_je = db.get_fahrten_je_fahrzeug()
teile = heimladung.verteilen("2026-08", "Privat – Netzbezug", 200.0, None, 30.0, [1, F2], km_je)
push_netz = db.summe_extern("2026-08", "Privat – Netzbezug", [1, F2])[0]
rest = 200.0 - push_netz
a2 = km_je[F2]["2026-08"] / (km_je[1]["2026-08"] + km_je[F2]["2026-08"])
t = dict(teile)
check("Wallbox", "Gemeinsame Wallbox: Push abgezogen, Rest nach km verteilt",
      nah(t[F2]["kwh"], round(rest * a2, 3), 0.002) and nah(t[1]["kwh"] + t[F2]["kwh"], rest, 0.002),
      f"Rest {rest}, {t[1]['kwh']} + {t[F2]['kwh']}")
check("Wallbox", "Notiz nennt den Anteil", "% nach km" in t[F2]["zusatz"], t[F2]["zusatz"])
r = c.post("/api/import/apply", json={"rows": [{"monat": "2026-08", "wallbox": "200", "pv": ""}],
                                      "fahrzeug_id": str(F2)})
# nur die neuen, nach km aufgeteilten Eintraege (der Funktionstest hat eigene Importe)
neu_imp = lambda l: (l["notiz"] or "").startswith("Import 2026-08") and "% nach km" in l["notiz"]
with db.fahrzeug_kontext(F2):
    imp2 = [l for l in db.get_ladevorgaenge() if neu_imp(l)]
with db.fahrzeug_kontext(1):
    imp1 = [l for l in db.get_ladevorgaenge(limit=10000) if neu_imp(l)]
check("Wallbox", "Zeitraum-Import verteilt die gemeinsame Wallbox auf beide Fahrzeuge",
      len(imp1) == 1 and len(imp2) == 1 and nah(imp1[0]["menge_kwh"] + imp2[0]["menge_kwh"], rest, 0.002),
      f"{[l['menge_kwh'] for l in imp1]} / {[l['menge_kwh'] for l in imp2]}")
c.post("/einstellungen/fahrzeuge/aendern", data={"id": F2, "name": "Zweitwagen", "heimladung": "eigen",
                                                 "aktiv": "1"}, follow_redirects=False)
check("Wallbox", "Eigene Zaehler: Fahrzeug bildet eine eigene Gruppe",
      heimladung.gruppe(F2) == [F2] and heimladung.gruppe(1) == [1], str(heimladung.gruppe(1)))
c.get(f"/?fahrzeug={F2}")
c.post("/einstellungen/ha", data={"fahrzeug_id": str(F2), "ha_wallbox_energy": "sensor.wb2",
                                  "ha_odometer": "sensor.km2"}, follow_redirects=False)
check("Wallbox", "Eigene Zaehler werden je Fahrzeug gespeichert, gemeinsame bleiben",
      db.get_ha_settings(F2, eigene_zaehler=True)["ha_wallbox_energy"] == "sensor.wb2"
      and db.get_ha_settings(1)["ha_wallbox_energy"] != "sensor.wb2"
      and db.get_ha_settings(F2)["ha_odometer"] == "sensor.km2",
      db.get_ha_settings(1)["ha_wallbox_energy"])
c.post("/einstellungen/fahrzeuge/aendern", data={"id": F2, "name": "Zweitwagen", "heimladung": "km",
                                                 "aktiv": "1"}, follow_redirects=False)

# ── 3b. Zuordnung ueber den Akkustand (Modus "akku") ────────────────────────
H = heimladung
d = H.stunden_deltas([("2026-08-01T00:00", 100.0), ("2026-08-01T01:00", 107.0),
                      ("2026-08-01T02:00", 3.0), ("2026-08-01T03:00", 10.0)])
check("Akkustand", "Stundenzuwachs aus dem Zaehler, Ruecksprung (Reset) zaehlt 0",
      d == {"2026-08-01T01": 7.0, "2026-08-01T03": 7.0}, str(d))
# Auto 1 laedt in der Nacht 3./4., Auto 2 in der Nacht 10./11.; am 20. laden beide gleichzeitig
deltas = {}
for tag, stunden in (("03", range(22, 24)), ("04", range(0, 4)), ("10", range(21, 24)),
                     ("11", range(0, 3)), ("20", range(1, 3))):
    for h in stunden:
        deltas[f"2026-08-{tag}T{h:02d}"] = 7.0
fenster = {1: [("2026-08-03T22:00", "2026-08-04T03:00"), ("2026-08-20T01:00", "2026-08-20T02:00")],
           F2: [("2026-08-10T21:00", "2026-08-11T02:00"), ("2026-08-20T01:00", "2026-08-20T02:00")]}
z = H.zuordnen_akku(deltas, fenster)
check("Akkustand", "Getrennte Naechte: je Auto genau seine Stunden",
      nah(z["je"][1], 6 * 7.0) and nah(z["je"][F2], 6 * 7.0), str(z))
check("Akkustand", "Gleichzeitiges Laden bleibt im Rest, Summe = Zaehler",
      nah(z["rest"], 2 * 7.0) and nah(z["je"][1] + z["je"][F2] + z["rest"], sum(deltas.values())), str(z))
spaet = {1: [("2026-08-04T05:00", "2026-08-04T06:00")]}   # Cloud meldet den Akkustand spaeter
z2 = H.zuordnen_akku({"2026-08-04T03": 7.0, "2026-08-04T02": 7.0}, spaet)
check("Akkustand", f"Verspaeteter Akkustand: {H.TOLERANZ_STUNDEN} h Spielraum",
      nah(z2["je"][1], 7.0) and nah(z2["rest"], 7.0), str(z2))
z3 = H.zuordnen_akku(deltas, fenster, ausgelassen={"2026-08-03T22", "2026-08-03T23"})
check("Akkustand", "Push-Stunden werden ausgelassen", nah(z3["je"][1], 4 * 7.0), str(z3))
z4 = H.zuordnen_akku(deltas, {1: [], F2: []})
check("Akkustand", "Ohne Ladefenster: alles im Rest", nah(z4["rest"], sum(deltas.values())), str(z4))
# Push-Ladung ueber Mitternacht (aus Abschnitt Push: 2026-08-05 20:00–23:00 bei Fahrzeug 2)
c.post("/api/ladung", json={"start": "2026-08-06T23:15", "ende": "2026-08-07T01:40",
                            "kwh_netz": 9, "fahrzeug": str(F2)}, headers=KOPF)
ps = H.push_stunden("2026-08", [1, F2])
check("Akkustand", "Push-Zeiten aus der Notiz, auch ueber Mitternacht",
      {"2026-08-05T20", "2026-08-05T23", "2026-08-06T23", "2026-08-07T00", "2026-08-07T01"} <= ps,
      str(sorted(ps)))
# verteilen mit Akku-Anteilen: zugeordneter Teil + Rest nach km, Summe bleibt
v = dict(H.verteilen("2026-08", "Privat – Netzbezug", 200.0, None, 30.0, [1, F2],
                     db.get_fahrten_je_fahrzeug(), akku={1: 0.5, F2: 0.3}))
rest_v = v[1]["kwh"] + v[F2]["kwh"]
km_je = db.get_fahrten_je_fahrzeug()
k2 = km_je[F2]["2026-08"] / (km_je[1]["2026-08"] + km_je[F2]["2026-08"])
soll2 = (0.3 + 0.2 * k2)
check("Akkustand", "Verteilen: Akku-Anteil + Rest nach km, Summe = Monatsrest",
      nah(v[F2]["anteil"], soll2, 0.0001) and nah(v[1]["anteil"] + v[F2]["anteil"], 1.0, 0.0001),
      f'{v[F2]["anteil"]:.4f} / {soll2:.4f}')
check("Akkustand", "Notiz nennt Akkustand und km", "über Akkustand" in v[F2]["zusatz"]
      and "nach km" in v[F2]["zusatz"], v[F2]["zusatz"])

# Ende zu Ende: Modus akku, Akkuverlauf und Wallbox-Stunden ersetzt
import ladeerkennung
for fid in (1, F2):
    c.post("/einstellungen/fahrzeuge/aendern", data={"id": fid, "heimladung": "akku", "aktiv": "1",
           "name": "Test EV" if fid == 1 else "Zweitwagen", **({"haupt": "1"} if fid == 1 else {})},
           follow_redirects=False)


def _soc_reihe(lade_stunden):
    """Akkustand je Stunde im August wie im echten Leben: steigt in den Ladestunden, faellt
    beim Fahren in Spruengen (8 und 17 Uhr), steht sonst still."""
    import datetime as _d
    reihe, wert, t = [], 50.0, _d.datetime(2026, 8, 1)
    while t.month == 8:
        k = t.strftime("%Y-%m-%dT%H")
        if k in lade_stunden:
            wert = min(100.0, wert + 10)
        elif t.hour in (8, 17):
            wert = max(10.0, wert - 6)
        reihe.append((t.strftime("%Y-%m-%dT%H:%M"), wert))
        t += _d.timedelta(hours=1)
    return reihe


SOC = {1: _soc_reihe({f"2026-08-03T{h}" for h in ("22", "23")} | {f"2026-08-04T0{h}" for h in "0123"}),
       F2: _soc_reihe({f"2026-08-10T{h}" for h in ("21", "22", "23")} | {f"2026-08-11T0{h}" for h in "012"})}
_orig_verlauf = ladeerkennung.batterie_verlauf
ladeerkennung.batterie_verlauf = lambda j, m: SOC.get(db.aktuelles_fahrzeug(), [])
zaehler, stand, t_ = [], 1000.0, None
import datetime as _dt2
t_ = _dt2.datetime(2026, 8, 1)
while t_.month == 8:
    stand += deltas.get(t_.strftime("%Y-%m-%dT%H"), 0.0)
    zaehler.append((t_.strftime("%Y-%m-%dT%H:%M"), stand))
    t_ += _dt2.timedelta(hours=1)
quelle = lambda key, a, b: zaehler if key == "wallbox" else []
anteile, hinweis = H.akku_anteile("2026-08", [1, F2], quelle)
check("Akkustand", "Ende zu Ende: Anteile aus Akkuverlauf und Wallbox-Stunden",
      nah(anteile["wallbox"][1], 6 / 14, 0.02) and nah(anteile["wallbox"][F2], 6 / 14, 0.02),
      f"{anteile} {hinweis}")
check("Akkustand", "Hinweis fuers Protokoll", "über Akkustand" in hinweis, hinweis)
ladeerkennung.batterie_verlauf = lambda j, m: []
anteile0, hinweis0 = H.akku_anteile("2026-08", [1, F2], quelle)
check("Akkustand", "Ohne Akkuwerte: keine Anteile, Rueckfall nach km",
      anteile0 == {} and "nach km" in hinweis0, hinweis0)
ladeerkennung.batterie_verlauf = lambda j, m: SOC.get(db.aktuelles_fahrzeug(), [])
_orig_quelle = webapp._wallbox_quelle
webapp._wallbox_quelle = lambda: quelle
r = c.post("/api/import/apply", json={"rows": [{"monat": "2026-08", "wallbox": "98", "pv": ""}],
                                      "fahrzeug_id": "1"})
neu_akku = lambda l: (l["notiz"] or "").startswith("Import 2026-08") and "über Akkustand" in l["notiz"]
with db.fahrzeug_kontext(1):
    ia1 = [l for l in db.get_ladevorgaenge(limit=10000) if neu_akku(l)]
with db.fahrzeug_kontext(F2):
    ia2 = [l for l in db.get_ladevorgaenge() if neu_akku(l)]
rest_ia = 98 - db.summe_extern("2026-08", "Privat – Netzbezug", [1, F2])[0]
check("Akkustand", "Zeitraum-Import mit Modus akku: beide Fahrzeuge, Summe = Rest des Zaehlers",
      len(ia1) == 1 and len(ia2) == 1 and nah(ia1[0]["menge_kwh"] + ia2[0]["menge_kwh"], rest_ia, 0.002),
      f"{[l['menge_kwh'] for l in ia1]} / {[l['menge_kwh'] for l in ia2]} / Rest {rest_ia}")
check("Akkustand", "Protokoll nennt die Zuordnung", any("Akkustand" in x for x in r.json()["log"]),
      str(r.json()["log"])[:200])
ladeerkennung.batterie_verlauf = _orig_verlauf
webapp._wallbox_quelle = _orig_quelle
r = c.get("/einstellungen")
check("Akkustand", "Einstellungen bieten den Modus an", "Zuordnung über den Akkustand" in r.text)
check("Akkustand", "Warnung: Modus Akkustand ohne Batteriesensor (Zweitwagen)",
      "Kein\n        Batteriesensor eingetragen" in r.text or "Batteriesensor eingetragen" in r.text)
for fid in (1, F2):
    c.post("/einstellungen/fahrzeuge/aendern", data={"id": fid, "heimladung": "km", "aktiv": "1",
           "name": "Test EV" if fid == 1 else "Zweitwagen", **({"haupt": "1"} if fid == 1 else {})},
           follow_redirects=False)

# ── 4. Umschalten 1 -> 2 -> 1 -> 2: nichts geht verloren ──────────────────────
tab = migrationstest.tabellen(DB_PFAD)
k_mehr = {fid: kennzahlen(fid) for fid in (1, F2)}
c.post("/einstellungen/fahrzeuge/modus", data={"modus": "ein", "haupt": "1"}, follow_redirects=False)
check("Schalter", "Ein Fahrzeug: Hauptfahrzeug 1, Zweitwagen nur ausgeblendet",
      not db.mehrere_fahrzeuge() and db.sichtbare_ids() == [1] and len(db.fahrzeuge(alle=True)) == 2)
r = c.get("/")
check("Schalter", "Ein Fahrzeug: kein Umschalter, Hinweis auf ausgeblendete Fahrzeuge",
      'class="fz-wahl"' not in r.text and "ausgeblendet" in c.get("/einstellungen").text)
html_ein = {s: sichtbarer_text(c.get(s).text) for s in HAUPTSEITEN}
r = c.post("/api/ladung", json={"start": "2026-08-07T20:00", "kwh_netz": 5, "fahrzeug": "Zweitwagen"},
           headers=KOPF)
check("Schalter", "Ein Fahrzeug: Push fuer ausgeblendetes Fahrzeug abgelehnt (422)",
      r.status_code == 422 and "ausgeblendet" in r.json()["error"], r.text[:120])
c.post("/einstellungen/fahrzeuge/modus", data={"modus": "mehrere"}, follow_redirects=False)
c.post("/einstellungen/fahrzeuge/modus", data={"modus": "ein", "haupt": str(F2)}, follow_redirects=False)
check("Schalter", "Ein Fahrzeug mit anderem Hauptfahrzeug zeigt dessen Daten",
      db.sichtbare_ids() == [F2] and kennzahlen()["alles"]["gesamt_km"] == sum(F2_KM.values()),
      str(kennzahlen()["alles"]["gesamt_km"]))
c.post("/einstellungen/fahrzeuge/modus", data={"modus": "mehrere"}, follow_redirects=False)
c.post("/einstellungen/fahrzeuge/aendern", data={"id": 1, "name": "Test EV", "heimladung": "km",
                                                 "aktiv": "1", "haupt": "1"}, follow_redirects=False)
abw = migrationstest.vergleich(tab, migrationstest.tabellen(DB_PFAD))
check("Schalter", "1 -> 2 -> 1 -> 2: Zeilen und Summen aller Tabellen unveraendert", not abw, "; ".join(abw[:5]))
abw = [x for fid in (1, F2) for x in migrationstest.vergleich(k_mehr[fid], kennzahlen(fid))]
check("Schalter", "1 -> 2 -> 1 -> 2: Kennzahlen beider Fahrzeuge unveraendert", not abw, "; ".join(abw[:5]))

# Ausblenden bei "Mehrere"
c.post("/einstellungen/fahrzeuge/aendern", data={"id": F2, "name": "Zweitwagen", "heimladung": "km"},
       follow_redirects=False)
daten_tab = lambda t: {k: v for k, v in t.items() if k != "fahrzeug"}   # aktiv-Spalte aendert sich
check("Ausblenden", "Ausgeblendet: nicht mehr sichtbar, Daten bleiben",
      db.sichtbare_ids() == [1]
      and not migrationstest.vergleich(daten_tab(tab), daten_tab(migrationstest.tabellen(DB_PFAD))),
      str(db.sichtbare_ids()))
r = c.post("/einstellungen/fahrzeuge/aendern", data={"id": 1, "name": "Test EV", "heimladung": "km"},
           follow_redirects=False)
check("Ausblenden", "Hauptfahrzeug laesst sich nicht ausblenden",
      "nicht+ausgeblendet" in r.headers["location"] or "kann+nicht" in r.headers["location"],
      r.headers["location"])
c.post("/einstellungen/fahrzeuge/aendern", data={"id": F2, "name": "Zweitwagen", "heimladung": "km",
                                                 "aktiv": "1"}, follow_redirects=False)
# Regression: Einblenden eines ausgeblendeten Fahrzeugs schrieb dessen Namen ins Hauptfahrzeug
check("Ausblenden", "Wieder einblenden: Namen beider Fahrzeuge richtig",
      [f["name"] for f in db.fahrzeuge(alle=True)] == ["Test EV", "Zweitwagen"]
      and db.sichtbare_ids() == [1, F2], str([f["name"] for f in db.fahrzeuge(alle=True)]))
with db.fahrzeug_kontext(F2):
    check("Ausblenden", "Ausdruecklicher Kontext trifft auch ein ausgeblendetes Fahrzeug",
          db.aktuelles_fahrzeug() == F2)

# Messdaten zuruecksetzen nur fuer das gewaehlte Fahrzeug
c.get(f"/?fahrzeug={F2}")
with db.fahrzeug_kontext(1):
    thg1 = len(db.get_thg_eintraege())
r = c.post("/api/reset", data={"bereiche": "thg", "bestaetigt": "ja", "fahrzeug_id": str(F2)})
with db.fahrzeug_kontext(1):
    thg1_nach = len(db.get_thg_eintraege())
with db.fahrzeug_kontext(F2):
    thg2_nach = len(db.get_thg_eintraege())
check("Zuruecksetzen", "Nur THG von Fahrzeug 2 geloescht, Fahrzeug 1 unberuehrt",
      thg2_nach == 0 and thg1_nach == thg1, f"{thg1} -> {thg1_nach} / {thg2_nach}")

# Status-Puffer: Aenderung ueber eine fremde Verbindung wird sofort gesehen
vorher_modus = db.mehrere_fahrzeuge()
with sqlite3.connect(DB_PFAD) as k:
    k.execute("UPDATE einstellungen SET value='0' WHERE key='mehrere_fahrzeuge'")
gesehen = db.mehrere_fahrzeuge()
with sqlite3.connect(DB_PFAD) as k:
    k.execute("UPDATE einstellungen SET value='1' WHERE key='mehrere_fahrzeuge'")
check("Puffer", "Aenderung von aussen wird sofort erkannt (kein veralteter Status)",
      vorher_modus and not gesehen and db.mehrere_fahrzeuge())

# ── 5. Einstellungen exportieren / importieren ────────────────────────────────
r = c.get("/api/settings/export?secrets=0")
export = r.json()
check("Export", "Export enthaelt Fahrzeugliste und Schluessel @2",
      len(export["fahrzeuge"]) == 2 and f"fahrzeug_name@{F2}" in export["einstellungen"])
code = (
    "import os, sys, json\n"
    f"os.environ['EV_TRACKER_DB'] = {os.path.join(TMP, 'frisch.db')!r}\n"
    f"sys.path[:0] = [{REPO!r}, {os.path.join(REPO, 'webapp')!r}]\n"
    "from fastapi.testclient import TestClient\n"
    "import app as webapp, database as db\n"
    "c = TestClient(webapp.app)\n"
    f"r = c.post('/api/settings/import', files={{'datei': ('e.json', {json.dumps(export)!r}.encode())}})\n"
    "print(json.dumps({'status': r.status_code, 'mehrere': db.mehrere_fahrzeuge(),"
    " 'schema': db.schema_stand(), 'fahrzeuge': [f['name'] for f in db.fahrzeuge(alle=True)]}))\n")
p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO,
                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
try:
    imp = json.loads(p.stdout.strip().splitlines()[-1])
except Exception:
    imp = {"fehler": p.stderr[-600:]}
check("Import", "Import in frische Datenbank: Umbau, mehrere Fahrzeuge, beide Namen",
      imp.get("status") == 200 and imp.get("mehrere") and imp.get("schema") == 3
      and imp.get("fahrzeuge") == ["Test EV", "Zweitwagen"], str(imp))

# ── 6. Loeschen nur mit Namensbestaetigung ────────────────────────────────────
r = c.post("/einstellungen/fahrzeuge/loeschen", data={"id": F2, "bestaetigung": "zweitwagen"},
           follow_redirects=False)
check("Loeschen", "Falscher Name: nichts geloescht", F2 in [f["id"] for f in db.fahrzeuge(alle=True)]
      and "passt+nicht" in r.headers["location"], r.headers["location"])
r = c.post("/einstellungen/fahrzeuge/loeschen", data={"id": 1, "bestaetigung": "Test EV"},
           follow_redirects=False)
check("Loeschen", "Hauptfahrzeug laesst sich nicht loeschen", 1 in [f["id"] for f in db.fahrzeuge(alle=True)])
vor = migrationstest.tabellen(DB_PFAD)
sich_vorher = {f for f in os.listdir(TMP) if f.startswith("vor_fahrzeug_loeschen")}
r = c.post("/einstellungen/fahrzeuge/loeschen", data={"id": F2, "bestaetigung": "Zweitwagen"},
           follow_redirects=False)
nach = migrationstest.tabellen(DB_PFAD)
check("Loeschen", "Richtiger Name: Fahrzeug 2 mit seinen Daten geloescht, Sicherung angelegt",
      F2 not in [f["id"] for f in db.fahrzeuge(alle=True)]
      and len({f for f in os.listdir(TMP) if f.startswith("vor_fahrzeug_loeschen")} - sich_vorher) == 1
      and nach["fahrten_monat"]["zeilen"] == vor["fahrten_monat"]["zeilen"] - 3,
      f'{vor["fahrten_monat"]["zeilen"]} -> {nach["fahrten_monat"]["zeilen"]}')
with db.fahrzeug_kontext(1):
    km1_nach = {f["monat"]: f["km"] for f in db.get_fahrten_monate()}
check("Loeschen", "Daten von Fahrzeug 1 unberuehrt", km1_nach == km1)
check("Loeschen", "Einstellungen @2 entfernt",
      not any(k.endswith(f"@{F2}") for k in db.get_alle_einstellungen()))

# ── 7. Abbruch des Umbaus rollt zurueck ───────────────────────────────────────
abbruch = os.path.join(TMP, "abbruch.db")
shutil.copy(GRUND, abbruch)
code = (
    "import os, sys, json, sqlite3\n"
    f"os.environ['EV_TRACKER_DB'] = {abbruch!r}\n"
    f"sys.path[:0] = [{REPO!r}]\n"
    "import database as db\n"
    "db.init_db()\n"
    "try:\n"
    "    db.struktur_mehrere_fahrzeuge(_fehler_nach='fahrten'); fehler = None\n"
    "except Exception as e:\n"
    "    fehler = str(e)\n"
    "k = sqlite3.connect(db.DB_PATH)\n"
    "sql = k.execute(\"SELECT sql FROM sqlite_master WHERE name='fahrten_monat'\").fetchone()[0]\n"
    "rest = [r[0] for r in k.execute(\"SELECT name FROM sqlite_master WHERE name LIKE '%_neu'\")]\n"
    "print(json.dumps({'fehler': fehler, 'schema': db.schema_stand(), 'sql': sql, 'rest': rest}))\n")
p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO,
                   env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
ab = json.loads(p.stdout.strip().splitlines()[-1])
tab_grund = migrationstest.tabellen(GRUND)
tab_ab = migrationstest.tabellen(abbruch)
abw = migrationstest.vergleich(tab_grund, tab_ab)
check("Abbruch", "Fehler mitten im Umbau wird gemeldet", ab["fehler"] and "Testfehler" in ab["fehler"], str(ab))
check("Abbruch", "Zurueckgerollt: Stand 2, alte Eindeutigkeit, keine Reste",
      ab["schema"] == 2 and "monat TEXT NOT NULL UNIQUE" in ab["sql"] and not ab["rest"], str(ab))
check("Abbruch", "Zeilen und Summen wie vorher", not abw, "; ".join(abw[:5]))

# ── 8. Ein Fahrzeug: sichtbarer Inhalt wie vor 3.0 (Version 2.16) ──────────────
def html_mit_code(code_dir, db_pfad):
    skript = (
        "import os, sys, json, re\n"
        f"os.environ['EV_TRACKER_DB'] = {db_pfad!r}\n"
        f"sys.path[:0] = [{code_dir!r}, {os.path.join(code_dir, 'webapp')!r}]\n"
        "from fastapi.testclient import TestClient\n"
        "import app as webapp\n"
        "c = TestClient(webapp.app)\n"
        f"seiten = {HAUPTSEITEN!r}\n"
        "print(json.dumps({s: c.get(s).text for s in seiten}))\n")
    p = subprocess.run([sys.executable, "-c", skript], capture_output=True, text=True, cwd=code_dir,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if p.returncode:
        raise RuntimeError(p.stderr[-800:])
    return {s: sichtbarer_text(h) for s, h in json.loads(p.stdout.strip().splitlines()[-1]).items()}


alt_commit = subprocess.run(["git", "log", "--format=%h", "-n1", "--grep=^Version 2.16"], cwd=REPO,
                            capture_output=True, text=True).stdout.strip()
if alt_commit:
    wt = os.path.join(TMP, "wt_216")
    subprocess.run(["git", "worktree", "add", "--detach", wt, alt_commit], cwd=REPO, capture_output=True)
    try:
        a, b = os.path.join(TMP, "html_a.db"), os.path.join(TMP, "html_b.db")
        shutil.copy(GRUND, a)
        shutil.copy(GRUND, b)
        alt_html = html_mit_code(wt, a)
        neu_html = html_mit_code(REPO, b)
        versions = re.compile(r"v\d+\.\d+\.\d+")
        unterschiede = [s for s in HAUPTSEITEN
                        if versions.sub("v", alt_html[s]) != versions.sub("v", neu_html[s])]
        check("Wie vorher", f"Ein Fahrzeug: sichtbarer Text von {len(HAUPTSEITEN)} Hauptseiten wie 2.16",
              not unterschiede, ", ".join(unterschiede))
        for s in unterschiede[:3]:
            x, y = versions.sub("v", alt_html[s]), versions.sub("v", neu_html[s])
            i = next((n for n in range(min(len(x), len(y))) if x[n] != y[n]), min(len(x), len(y)))
            check("Wie vorher", f"  Abweichung {s}", False, f"2.16: …{x[max(0, i - 80):i + 80]}… / 3.0: …{y[max(0, i - 80):i + 80]}…")
        # Downgrade-Schutz: 2.16 oeffnet eine umgebaute Datenbank nur lesend
        skript = (
            "import os, sys, json\n"
            f"os.environ['EV_TRACKER_DB'] = {DB_PFAD!r}\n"
            f"sys.path[:0] = [{wt!r}, {os.path.join(wt, 'webapp')!r}]\n"
            "from fastapi.testclient import TestClient\n"
            "import app as webapp, database as db\n"
            "c = TestClient(webapp.app)\n"
            "r = c.post('/fahrten', data={'monat': '2026-08', 'km': '1'}, follow_redirects=False)\n"
            "print(json.dumps({'gesperrt': db.SCHEMA_ZU_NEU, 'status': r.status_code,"
            " 'banner': 'Nur lesbar' in c.get('/').text}))\n")
        shutil.copy(DB_PFAD, DB_PFAD + ".vor_downgrade")
        p = subprocess.run([sys.executable, "-c", skript], capture_output=True, text=True, cwd=wt,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        dg = json.loads(p.stdout.strip().splitlines()[-1])
        check("Downgrade", "2.16 oeffnet die umgebaute Datenbank nur lesend",
              dg["gesperrt"] == 3 and dg["status"] == 303 and dg["banner"], str(dg))
        check("Downgrade", "2.16 hat nichts veraendert",
              not migrationstest.vergleich(migrationstest.tabellen(DB_PFAD + ".vor_downgrade"),
                                           migrationstest.tabellen(DB_PFAD)))
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=REPO, capture_output=True)
        subprocess.run(["git", "worktree", "prune"], cwd=REPO, capture_output=True)
else:
    check("Wie vorher", "Commit „Version 2.16“ gefunden", False)

# ── Ausgabe ──────────────────────────────────────────────────────────────────
shutil.rmtree(TMP, ignore_errors=True)
ok_n = sum(1 for e in ERG if e[2])
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
for b_, t_, ok, d_ in ERG:
    if not ok:
        print(f"FEHLER  [{b_}] {t_}\n        {d_}")
sys.exit(0 if ok_n == len(ERG) else 1)
