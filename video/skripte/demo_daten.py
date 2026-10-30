"""Demodaten fuer Screenshots und Video: Kia EV3, 01/2025 bis heute (10/2026).

Legt video/demo/ev_tracker.db neu an – die echte Datenbank bleibt unberuehrt.
Aufruf aus dem Repo-Ordner:  python video/skripte/demo_daten.py
"""
import os, sys, random, sqlite3
VIDEO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(VIDEO)
DB = os.path.join(VIDEO, "demo", "ev_tracker.db")
os.makedirs(os.path.dirname(DB), exist_ok=True)
if os.path.exists(DB):
    os.remove(DB)
os.environ["EV_TRACKER_DB"] = DB
sys.path[:0] = [REPO, os.path.join(REPO, "webapp")]
from fastapi.testclient import TestClient
import app as webapp
import database as db

c = TestClient(webapp.app)
random.seed(7)


def post(url, **daten):
    r = c.post(url, data=daten, follow_redirects=False)
    assert r.status_code in (200, 303), (url, r.status_code, r.text[:200])


post("/einstellungen/parameter", benziner_verbrauch="7,0", ev_verbrauch="16", pv_preis="12",
     co2_benzin="2,37", kfz_steuer="180", fahrzeug_name="Kia EV3", kraftstoff="benzin")
post("/einstellungen/anschaffung", eauto="44.990", verbrenner="36.500", foerderung="3.000",
     erstzulassung="2025-01-10", zulassung_eigen="", km_bei_kauf="12")
c.post("/api/auto-bild/galerie", data={"datei": "kia-ev3-orange.jpg"})

post("/stromtarif", gueltig_ab="2024-06-01", preis="31,5", name="Ökostrom 24")
post("/stromtarif", gueltig_ab="2026-01-01", preis="29,9", name="Ökostrom 26")

# Ladetarife: EnBW-Abo (abgeschlossen) und Ionity nur zum Vergleich
post("/ladetarife", anbieter="EnBW", tarif_name="mobility+ M", gueltig_ab="2025-01-01",
     preis_ac="39", preis_dc="49", grundgebuehr="5,99")
post("/ladetarife", anbieter="EnBW", tarif_name="mobility+ M", gueltig_ab="2026-02-01",
     preis_ac="42", preis_dc="52", grundgebuehr="5,99")
post("/ladetarife", anbieter="EnBW", tarif_name="Ad-hoc", gueltig_ab="2025-01-01",
     preis_ac="54", preis_dc="64", nur_vergleich="1")

monate = [f"{j}-{m:02d}" for j in (2025, 2026) for m in range(1, 13) if f"{j}-{m:02d}" <= "2026-09"]
rows = []
for m in monate:
    mon = int(m[5:7])
    sommer = mon in range(4, 10)
    urlaub = mon in (7, 8)
    km = random.randint(1700, 2300) if urlaub else random.randint(900, 1450)
    post("/fahrten", monat=m, km=str(km))
    post("/benzin", monat=m, preis=f"{random.uniform(1.68, 1.86):.3f}".replace(".", ","))
    verbrauch = (15.0 if sommer else 19.5) + random.uniform(-0.8, 0.8)
    kwh = km / 100 * verbrauch * 1.08
    oeffentlich = 0.0
    tage = (3, 11, 20, 27) if urlaub else random.sample((6, 13, 20, 27), random.choice((1, 2, 2)))
    for tag in sorted(tage):                         # Schnellladen mit dem EnBW-Abo
        menge = random.uniform(28, 46)
        oeffentlich += menge
        post("/laden", datum=f"{m}-{tag:02d}", kwh=f"{menge:.1f}".replace(".", ","),
             preis_kwh="52" if m >= "2026-02" else "49", blockier="", anbieter="EnBW",
             leistung="150", ladetyp="DC")
    if random.random() < 0.5:                        # ab und zu AC in der Stadt
        menge = random.uniform(9, 16)
        oeffentlich += menge
        post("/laden", datum=f"{m}-17", kwh=f"{menge:.1f}".replace(".", ","), preis_kwh="39",
             blockier="", anbieter="medl", leistung="22", ladetyp="AC")
    heim = max(kwh - oeffentlich, 20)
    pv_anteil = random.uniform(0.55, 0.7) if sommer else random.uniform(0.08, 0.2)
    rows.append({"monat": m, "pv": round(heim * pv_anteil, 1), "wallbox": round(heim * (1 - pv_anteil), 1)})
# laufender Monat: die ersten Tage im Oktober
post("/fahrten", monat="2026-10", km="430")
post("/benzin", monat="2026-10", preis="1,762")
rows.append({"monat": "2026-10", "pv": 22.0, "wallbox": 18.5})
post("/laden", datum="2026-10-04", kwh="36,8", preis_kwh="52", blockier="", anbieter="EnBW",
     leistung="150", ladetyp="DC")
r = c.post("/api/import/apply", json={"rows": rows})
assert r.status_code == 200, r.text[:300]

post("/steuer/kfz", betrag="180")
for d, b in (("2025-04-10", "85"), ("2026-04-10", "70,50")):
    post("/steuer/thg", datum=d, betrag=b, anbieter="ADAC")

for d, kat, text, werkstatt, km, betrag in (
        ("2025-11-08", "Reifen", "Winterreifen montiert", "Reifen Müller", "11.200", "45"),
        ("2026-01-20", "Inspektion / Wartung", "Inspektion 1 Jahr", "Kia Autohaus", "13.950", "189"),
        ("2026-03-28", "Reifen", "Sommerreifen montiert", "Reifen Müller", "16.400", "45"),
        ("2026-06-02", "Pflege", "Innenreinigung", "", "19.800", "59")):
    post("/instandhaltung", datum=d, kategorie=kat, beschreibung=text, werkstatt=werkstatt,
         km_stand=km, betrag=betrag)

post("/versicherung", fahrzeug="Kia EV3", gesellschaft="HUK-COBURG", tarif_name="Classic",
     gueltig_ab="2025-01-10", deckung="Vollkasko", sf_haftpflicht="SF 12", sf_kasko="SF 10",
     jahreslaufleistung="15.000", sb_teilkasko="150", sb_vollkasko="300", grundbeitrag="612",
     schutzbrief="12")

# Verbrauch laut Akkustand: Fahrtabschnitte je Monat
with sqlite3.connect(DB) as conn:
    km_stand = 12.0
    for m in monate:
        sommer = int(m[5:7]) in range(4, 10)
        for tag in (5, 12, 19, 26):
            km = random.uniform(120, 260)
            v = (14.6 if sommer else 18.8) + random.uniform(-1.0, 1.0)
            kwh = km * v / 100
            soc = kwh / 81.4 * 100
            conn.execute("INSERT INTO akku_abschnitt (start, ende, soc_start, soc_ende, km_start, "
                         "km_ende, kwh, km, laufend) VALUES (?,?,?,?,?,?,?,?,0)",
                         (f"{m}-{tag:02d}T07:00:00", f"{m}-{tag + 2:02d}T18:00:00", 90.0, 90.0 - soc,
                          km_stand, km_stand + km, round(kwh, 2), round(km, 1)))
            km_stand += km

# km je Tag fuer das Nutzungsprofil: werktags Pendeln, am Wochenende mal weiter, mal gar nicht
import calendar
from datetime import date
tage_km = {}
for m in monate:
    j, mon = int(m[:4]), int(m[5:7])
    for t in range(1, calendar.monthrange(j, mon)[1] + 1):
        wt = date(j, mon, t).weekday()
        if wt < 5:
            km = random.uniform(28, 48)
        else:
            km = random.choice((0.0, 0.0, random.uniform(40, 120), random.uniform(180, 320)))
        tage_km[f"{m}-{t:02d}"] = round(km, 1)
db.ersetze_fahrten_tag(None, tage_km)
post("/akku/soh", datum="2026-06-18", soh="97,5", km_stand="21.400", quelle="werkstatt",
     notiz="Inspektion")

# Energie je Tag wie aus der Fahrstatistik eines Kia: Klima im Winter deutlich hoeher
energie_tage = {}
for d, km in tage_km.items():
    mon = int(d[5:7])
    winter = mon in (11, 12, 1, 2, 3)
    antrieb = km * random.uniform(110, 130)
    klima = km * (random.uniform(22, 32) if winter else random.uniform(4, 9)) + (150 if winter else 0)
    elektronik = 60 + km * random.uniform(4, 6)
    energie_tage[d] = {"km": km, "antrieb_wh": round(antrieb), "klima_wh": round(klima),
                       "elektronik_wh": round(elektronik), "batterie_wh": 0.0,
                       "rekuperation_wh": round(antrieb * random.uniform(0.25, 0.4)),
                       "gesamt_wh": round(antrieb + klima + elektronik)}
db.upsert_energie_tage(energie_tage)

# Fahrtenbuch der letzten zwei Wochen: Arbeitsweg werktags, am Wochenende Ausfluege
fahrten, km_stand = [], 30000.0
for i in range(14):
    tag = date(2026, 9, 16 + i)
    wege = ([("07:35", "08:05", 21.4, "home", "Arbeit", "arbeitsweg"),
             ("16:50", "17:25", 21.6, "Arbeit", "home", "arbeitsweg")] if tag.weekday() < 5
            else [("10:10", "11:30", 74.2, "home", None, "privat"),
                  ("17:40", "19:05", 75.0, None, "home", "privat")] if tag.weekday() == 5 else [])
    for von, bis, km, start, ziel, kat in wege:
        fahrten.append({"start": f"{tag}T{von}", "ende": f"{tag}T{bis}", "km_start": km_stand,
                        "km_ende": km_stand + km, "km": km, "soc_start": 80.0,
                        "soc_ende": round(80 - km * 0.21, 1), "kwh": round(km * 0.17, 2),
                        "start_lat": 51.40, "start_lon": 6.85, "start_ort": start,
                        "ziel_lat": 51.45, "ziel_lon": 7.01, "ziel_ort": ziel, "kategorie": kat})
        km_stand += km
db.ersetze_fahrten("2026-09-01T00:00", fahrten)
post("/einstellungen/module", akku="1", profil="1", energie="1", fahrtenbuch="1")

import zeitraum
a = zeitraum.amortisation(zeitraum.laden())
k = zeitraum.kennzahlen(zeitraum.aufloesen("alles"), zeitraum.laden())
print("Ersparnis", round(k["ersparnis_gesamt"], 2), "Monate", k["steuer_monate"],
      "Amortisation", round(a["anteil"], 1), "% Prognose", a["prognose"])
