# -*- coding: utf-8 -*-
"""
Test der Rentabilitaet von Lade-Abos (Vergleichstarife, Break-even, Monatsverlauf) und
der Schnellerfassung auf /laden (Datum, Anbieter, Typ und kW bleiben stehen).

Rechnung mit festem "heute" gegen handgerechnete Werte, dazu die Formular-Endpunkte
in Deutsch und Englisch. Laeuft gegen eine eigene Test-DB in einem temporaeren Ordner.

Aufruf (aus dem Repo-Ordner):
    python tests/ladetarife_test.py
"""
import os, sys, tempfile
from datetime import date

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_ladetarife_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, ladetarife, berechnung

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def nah(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


def tarif(name, ab, ac, dc, grund, vergleich=0):
    return {"anbieter": "EnBW", "tarif_name": name, "gueltig_ab": ab, "gueltig_bis": None,
            "preis_ac": ac, "preis_dc": dc, "grundgebuehr": grund, "nur_vergleich": vergleich}


def ladung(datum, kwh, typ, gesamt, blockier=None, anbieter="EnBW"):
    return {"datum": datum, "menge_kwh": kwh, "ladetyp": typ, "gesamtpreis": gesamt,
            "anbieter": anbieter, "blockiergebuehr": blockier}


# ── Rechnung mit festem Datum ────────────────────────────────────────────────
# Eigenes Abo EnBW M: 49/59 ct, 5,99 €. Vergleich: Ad-hoc 59/69 ct ohne Grundgebuehr
# (erst ab September eingetragen – gilt fuer die Vormonate mit), Abo L 39/49 ct, 17,99 €.
HEUTE = date(2026, 9, 10)
EIGEN = [tarif("M", "2026-01-01", 49.0, 59.0, 5.99)]
VERGL = [tarif("Ad-hoc", "2026-09-01", 59.0, 69.0, 0, 1),
         tarif("L", "2026-01-01", 39.0, 49.0, 17.99, 1)]
LADUNGEN = [ladung("2026-08-05", 30, "AC", 14.70),
            ladung("2026-08-20", 20, "DC", 12.80, 1.00),
            ladung("2026-09-03", 10, "AC", 4.90),
            ladung("2026-08-07", 40, "AC", 20.00, anbieter="Ionity")]

r = ladetarife.rentabilitaet(EIGEN, VERGL, LADUNGEN, HEUTE)
check("Ein Anbieter mit Vergleich", len(r) == 1 and r[0]["anbieter"] == "EnBW", str(len(r)))
r = r[0]
namen = [v["name"] for v in r["vergleiche"]]
check("Vergleiche sortiert", namen == ["Ad-hoc", "L"], str(namen))
check("Monate Januar bis September", len(r["monate"]) == 9 and r["monate"][0]["monat"] == "2026-09",
      str([m["monat"] for m in r["monate"]]))
aug = next(m for m in r["monate"] if m["monat"] == "2026-08")
check("August: AC/DC getrennt", aug["kwh_ac"] == 30 and aug["kwh_dc"] == 20)
check("August: mit Abo inkl. Grundgebuehr", nah(aug["gesamt"], 14.70 + 12.80 + 5.99), str(aug["gesamt"]))
check("August Ad-hoc: 30×59 + 20×69 ct + 1 € Blockier",
      nah(aug["alt"][0]["kosten"], 17.70 + 13.80 + 1.00), str(aug["alt"][0]))
check("August Ad-hoc: Abo war 0,99 € teurer", nah(aug["alt"][0]["diff"], -0.99), str(aug["alt"][0]))
check("August L: inkl. 17,99 € Grundgebuehr",
      nah(aug["alt"][1]["kosten"], 11.70 + 9.80 + 1.00 + 17.99), str(aug["alt"][1]))
leer = next(m for m in r["monate"] if m["monat"] == "2026-03")
check("Monat ohne Ladung: nur Grundgebuehren",
      nah(leer["gesamt"], 5.99) and leer["alt"][0]["kosten"] == 0 and nah(leer["alt"][1]["kosten"], 17.99))
check("Summe mit Abo", nah(r["summe_ist"], 9 * 5.99 + 14.70 + 12.80 + 4.90), str(r["summe_ist"]))
check("Summe Ersparnis Ad-hoc = Summe der Monate",
      nah(r["vergleiche"][0]["diff"], sum(m["alt"][0]["diff"] for m in r["monate"])))
check("Anderer Anbieter bleibt draussen", all(m["anbieter"] == "EnBW" for m in r["monate"]))

# Break-even: DC-Anteil 20 von 60 kWh -> Abo 52,33 ct, Ad-hoc 62,33 ct, L 42,33 ct
be = r["vergleiche"][0]["break_even"]
check("Break-even Ad-hoc: ab 59,9 kWh (5,99 € / 10 ct)", be["art"] == "ab" and nah(be["kwh"], 59.9, 0.05),
      str(be))
be = r["vergleiche"][1]["break_even"]
check("Break-even L: bis 120 kWh ist M guenstiger", be["art"] == "bis" and nah(be["kwh"], 120, 0.05),
      str(be))
check("kWh im laufenden Monat", r["kwh_jetzt"] == 10, str(r["kwh_jetzt"]))
ist = {"preis_ac": 40.0, "preis_dc": None, "grundgebuehr": 5.0}
check("Break-even: guenstiger und ohne Mehr-Grundgebuehr -> immer",
      ladetarife.break_even(ist, {"preis_ac": 50.0, "preis_dc": None, "grundgebuehr": 5.0})["art"] == "immer")
check("Break-even: teurer und Grundgebuehr -> nie",
      ladetarife.break_even(ist, {"preis_ac": 30.0, "preis_dc": None, "grundgebuehr": 0})["art"] == "nie")
check("Break-even: gleicher Preis, Grundgebuehr entscheidet",
      ladetarife.break_even(ist, {"preis_ac": 40.0, "preis_dc": None, "grundgebuehr": 0})["art"] == "nie")

v = r["verlauf"]
check("Verlauf: ganzer September, Werte bis heute",
      v["tage"] == list(range(1, 31)) and v["ist"][9] is not None and v["ist"][10] is None
      and v["alt"][0]["werte"][10] is None, str(v["ist"]))
check("Verlauf: Abo startet bei der Grundgebuehr, Ad-hoc bei 0, L bei 17,99",
      nah(v["ist"][0], 5.99) and v["alt"][0]["werte"][0] == 0 and nah(v["alt"][1]["werte"][0], 17.99))
check("Verlauf: Ladung am 3. eingerechnet",
      nah(v["ist"][2], 10.89) and nah(v["alt"][0]["werte"][2], 5.90) and nah(v["alt"][1]["werte"][2], 21.89),
      f'{v["ist"][2]} {v["alt"][0]["werte"][2]} {v["alt"][1]["werte"][2]}')
check("Ohne Vergleichstarif keine Auswertung", ladetarife.rentabilitaet(EIGEN, [], LADUNGEN, HEUTE) == [])

# ── Ueber die Oberflaeche ────────────────────────────────────────────────────
heute = date.today()
start = f"{heute.year - 1}-01-01"
c.post("/ladetarife", data={"anbieter": "EnBW", "tarif_name": "M", "gueltig_ab": start,
                            "preis_ac": "49", "preis_dc": "59", "grundgebuehr": "5,99"})
c.post("/ladetarife", data={"anbieter": "EnBW", "tarif_name": "Ad-hoc", "gueltig_ab": start,
                            "preis_ac": "59", "preis_dc": "69", "nur_vergleich": "1"})
alle = db.get_ladetarife(vergleich=None)
check("Vergleichstarif gespeichert", [t["nur_vergleich"] for t in alle] == [1, 0],
      str([(t["tarif_name"], t["nur_vergleich"]) for t in alle]))
check("Eigene Tarife ohne Vergleich", [t["tarif_name"] for t in db.get_ladetarife()] == ["M"])
check("Vorbelegung auf /laden nur aus dem eigenen Abo",
      db.get_aktuelle_ladetarife()["EnBW"]["tarif_name"] == "M")
gebuehren = [l for l in berechnung.ladevorgaenge() if l.get("grundgebuehr")]
check("Vergleichstarif kostet keine Grundgebuehr",
      all("Ad-hoc" not in l["notiz"] for l in gebuehren) and gebuehren, str(len(gebuehren)))

r = c.post("/laden", data={"datum": f"{heute.year - 1}-03-14", "kwh": "30", "preis_kwh": "49",
                           "anbieter": "EnBW", "ladetyp": "DC", "leistung": "150"},
           follow_redirects=False)
ziel = r.headers.get("location", "")
check("Nach dem Hinzufuegen: Eingaben im Redirect",
      r.status_code == 303 and f"datum={heute.year - 1}-03-14" in ziel and "anbieter=EnBW" in ziel
      and "typ=DC" in ziel and "kw=150" in ziel and "ok=1" in ziel, ziel)
html = c.get("/" + ziel).text
check("/laden: Datum bleibt stehen", f'value="{heute.year - 1}-03-14"' in html)
check("/laden: Anbieter bleibt stehen", "<option selected>EnBW</option>" in html)
check("/laden: Typ DC bleibt stehen", "<option selected>DC</option>" in html)
check("/laden: kW bleibt stehen", 'value="150"' in html)
check("/laden: Hinweis gespeichert", "✓ Gespeichert" in html)
r = c.post("/laden", data={"datum": "2025-03-14", "kwh": "abc", "anbieter": "EnBW"},
           follow_redirects=False)
check("Ungueltige Eingabe: kein Hinweis gespeichert", "ok=1" not in r.headers.get("location", ""))
check("/laden ohne Parameter: heute vorbelegt",
      f'value="{heute.isoformat()}"' in c.get("/laden").text)

html = c.get("/ladetarife").text
check("/ladetarife: Abschnitt Rentabilitaet", "Lohnt sich das Abo? EnBW M" in html)
check("/ladetarife: Break-even-Satz", "Ab 60 kWh im Monat ist dein Abo günstiger als EnBW Ad-hoc" in html
      or "kWh im Monat ist dein Abo günstiger als EnBW Ad-hoc" in html)
check("/ladetarife: Diagramm", 'data-echart="opt-rentabilitaet-1"' in html)
check("/ladetarife: Markierung Vergleich", "(Vergleich)" in html)
c.post("/einstellungen/sprache", data={"sprache": "en"}, follow_redirects=False)
html = c.get("/ladetarife").text
check("Englisch: Rentabilitaet", "Does the subscription pay off? EnBW M" in html)
c.post("/einstellungen/sprache", data={"sprache": "de"}, follow_redirects=False)

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
