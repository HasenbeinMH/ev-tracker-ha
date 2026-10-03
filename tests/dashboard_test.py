# -*- coding: utf-8 -*-
"""
Test des anpassbaren Dashboards (dashboard_layout.py, /api/dashboard/layout).

Prueft den Standard (sieht aus wie vor 3.4), das Bereinigen gespeicherter Anordnungen,
Speichern und Zuruecksetzen ueber die API sowie die Darstellung: Reihenfolge,
ausgeblendete Elemente, breite Diagramme, zusaetzliche Kacheln und den Abschnitt
Lade-Abo – in Deutsch und Englisch. Laeuft gegen eine eigene Test-DB.

Aufruf (aus dem Repo-Ordner):
    python tests/dashboard_test.py
"""
import os, re, sys, tempfile
from datetime import date

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
TESTDIR = tempfile.mkdtemp(prefix="ev_dashboard_")
os.environ["EV_TRACKER_DB"] = os.path.join(TESTDIR, "ev_tracker.db")
os.environ.pop("SUPERVISOR_TOKEN", None)
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "webapp"))

from fastapi.testclient import TestClient
import app as webapp
import database as db, dashboard_layout as dl

c = TestClient(webapp.app)
ERG = []


def check(test, ok, detail=""):
    ERG.append((test, bool(ok), detail))


def sichtbar(html, gruppe):
    """ids der eingeblendeten Elemente einer Gruppe in Seitenreihenfolge."""
    return [m.group(2) for m in re.finditer(
        r'class="[^"]*dash-el(?P<aus>[^"]*)"[^>]*data-gruppe="' + gruppe + r'"\s+data-id="([^"]+)"', html)
        if " aus" not in m.group(1)]


def alle(html, gruppe):
    return re.findall(r'data-gruppe="' + gruppe + r'"\s+data-id="([^"]+)"', html)


# ── Standard ─────────────────────────────────────────────────────────────────
std = dl.standard()
check("Standard: Kacheln wie bisher",
      [k["id"] for k in std["kacheln"] if k["an"]] ==
      ["strecke", "energie", "ersparnis_kraft", "steuer", "thg", "co2"])
check("Standard: zusaetzliche Kacheln aus", sum(1 for k in std["kacheln"] if not k["an"]) == 9)
check("Standard: Lade-Abo aus, Rest an",
      [b["id"] for b in std["bereiche"] if not b["an"]] == ["abo"])
check("Standard: alle Diagramme an und schmal",
      all(d["an"] and not d["breit"] for d in std["diagramme"]) and len(std["diagramme"]) == 9)
check("Ohne Eintrag gilt der Standard", dl.laden() == std)

# ── Bereinigen ───────────────────────────────────────────────────────────────
b = dl.bereinigen({"kacheln": [{"id": "co2", "an": False}, {"id": "unbekannt"}, {"id": "co2"},
                               "kaputt", {"id": "pv_anteil", "an": True}],
                   "diagramme": [{"id": "thg", "breit": True}]})
ids = [k["id"] for k in b["kacheln"]]
check("Bereinigen: Reihenfolge uebernommen, Rest hinten", ids[:2] == ["co2", "pv_anteil"]
      and len(ids) == len(dl.KACHELN) and len(set(ids)) == len(ids), str(ids))
check("Bereinigen: unbekannt und doppelt fallen weg", "unbekannt" not in ids and ids.count("co2") == 1)
check("Bereinigen: Werte uebernommen", not b["kacheln"][0]["an"] and b["kacheln"][1]["an"])
check("Bereinigen: fehlende mit Standard", next(k for k in b["kacheln"] if k["id"] == "strecke")["an"]
      and not next(k for k in b["kacheln"] if k["id"] == "stromkosten")["an"])
check("Bereinigen: breit", b["diagramme"][0] == {"id": "thg", "an": True, "breit": True})
check("Bereinigen: fehlende Gruppe = Standard", b["bereiche"] == std["bereiche"])
check("Bereinigen: Unsinn = Standard", dl.bereinigen("x") == std and dl.bereinigen(None) == std)
db.set_einstellung(dl.SCHLUESSEL, "{kein json")
check("Kaputter Eintrag = Standard", dl.laden() == std)

# ── Seite mit Standard ───────────────────────────────────────────────────────
db.set_einstellung(dl.SCHLUESSEL, "")
r = c.get("/")
check("Dashboard laedt", r.status_code == 200, f"HTTP {r.status_code}")
html = r.text
check("Seite: Kacheln wie bisher", sichtbar(html, "kacheln") ==
      ["strecke", "energie", "ersparnis_kraft", "steuer", "thg", "co2"], str(sichtbar(html, "kacheln")))
check("Seite: alle Kacheln im DOM (fuer den Bearbeiten-Modus)", len(alle(html, "kacheln")) == len(dl.KACHELN))
check("Seite: Diagramme in Standard-Reihenfolge",
      sichtbar(html, "diagramme") == [i for i, _a in dl.DIAGRAMME])
check("Seite: Knopf Anpassen", 'id="dash-anpassen"' in html)
check("Seite: Platzhalter ohne Kaufpreis und ohne Vergleichstarif",
      "dash-platzhalter" in html and "Lade-Abo: erscheint" in html)

# ── Speichern ueber die API ──────────────────────────────────────────────────
layout = dl.standard()
layout["kacheln"] = sorted(layout["kacheln"], key=lambda k: k["id"] != "pv_anteil")
for k in layout["kacheln"]:
    if k["id"] in ("pv_anteil", "verbrauch"):
        k["an"] = True
    if k["id"] == "co2":
        k["an"] = False
for d in layout["diagramme"]:
    d["breit"] = d["id"] == "monatlich"
    d["an"] = d["id"] != "thg"
layout["bereiche"] = [b for b in layout["bereiche"] if b["id"] == "diagramme"] + \
                     [b for b in layout["bereiche"] if b["id"] != "diagramme"]
r = c.post("/api/dashboard/layout", json=layout)
check("API: gespeichert", r.status_code == 200 and r.json()["ok"], r.text[:200])
check("API: als Einstellung abgelegt (global)", '"pv_anteil"' in (db.get_einstellung_str(dl.SCHLUESSEL) or ""))
html = c.get("/").text
check("Seite: PV-Anteil vorne, CO2 aus, Verbrauch an",
      sichtbar(html, "kacheln") == ["pv_anteil", "strecke", "energie", "ersparnis_kraft", "steuer", "thg",
                                     "verbrauch"], str(sichtbar(html, "kacheln")))
check("Seite: Diagramme zuerst", alle(html, "bereiche")[0] == "diagramme", str(alle(html, "bereiche")))
check("Seite: breites Diagramm", re.search(r'class="chart dash-el breit"[^>]*data-id="monatlich"', html))
check("Seite: THG-Diagramm ausgeblendet", re.search(r'class="chart dash-el aus"[^>]*data-id="thg"', html))
check("Seite: Kachel PV-Anteil in %", re.search(r'PV-Anteil', html))
r = c.post("/api/dashboard/layout", json={"kacheln": "kaputt"})
check("API: ungueltige Daten -> Standard statt Fehler", r.status_code == 200
      and r.json()["layout"] == std)

# ── Lade-Abo-Abschnitt ───────────────────────────────────────────────────────
heute = date.today()
start = f"{heute.year - 1}-01-01"
c.post("/ladetarife", data={"anbieter": "EnBW", "tarif_name": "M", "gueltig_ab": start,
                            "preis_ac": "49", "preis_dc": "59", "grundgebuehr": "5,99"})
c.post("/ladetarife", data={"anbieter": "EnBW", "tarif_name": "Ad-hoc", "gueltig_ab": start,
                            "preis_ac": "59", "preis_dc": "69", "nur_vergleich": "1"})
layout = dl.standard()
for b in layout["bereiche"]:
    b["an"] = True
c.post("/api/dashboard/layout", json=layout)
html = c.get("/").text
check("Lade-Abo: Abschnitt mit Break-even",
      "Lohnt sich das Abo?" in html and "kWh im Monat ist dein Abo günstiger als EnBW Ad-hoc" in html)
check("Lade-Abo: Link zur Seite Ladetarife", 'href="ladetarife#rentabilitaet-1"' in html)

# ── Englisch ─────────────────────────────────────────────────────────────────
c.post("/einstellungen/sprache", data={"sprache": "en"}, follow_redirects=False)
html = c.get("/").text
check("Englisch: Knopf und Abschnitt", "✏ Customise" in html and "Does the subscription pay off?" in html)
check("Englisch: Leiste", "Drag or ◀ ▶ to sort" in html)
c.post("/einstellungen/sprache", data={"sprache": "de"}, follow_redirects=False)

# ── Zuruecksetzen ────────────────────────────────────────────────────────────
r = c.post("/api/dashboard/layout/standard")
check("Standard wiederhergestellt", r.status_code == 200 and dl.laden() == std)
check("Nach Zuruecksetzen: Kacheln wie bisher", sichtbar(c.get("/").text, "kacheln") ==
      ["strecke", "energie", "ersparnis_kraft", "steuer", "thg", "co2"])

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[1])
for test, ok, detail in ERG:
    if not ok:
        print(f"  FEHLER  {test}  {detail}")
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
sys.exit(0 if ok_n == len(ERG) else 1)
