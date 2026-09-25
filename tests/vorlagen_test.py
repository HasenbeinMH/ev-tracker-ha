# -*- coding: utf-8 -*-
"""
Test der Vorlagen fuer den PV-Anteil beim Laden (vorlagen/).

Node-RED: tests/vorlagen_nodered_pruefstand.js fuehrt die Funktionsknoten des fertigen
Flows (ev_pv_anteil_flow.json) in Node.js aus und spielt Home Assistant nach.
Home Assistant: die Templates der YAML-Pakete werden mit Jinja2 gerendert
(states(), state_attr(), is_number, this, trigger nachgebaut).
Nicht geprueft: der Import in ein echtes Node-RED bzw. Home Assistant.

Aufruf (aus dem Repo-Ordner):  python tests/vorlagen_test.py      (braucht Node.js)
"""
import json, os, subprocess, sys, tempfile
import jinja2
import yaml

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
FLOW = os.path.join(REPO, "vorlagen", "node-red", "ev_pv_anteil_flow.json")
PAKET = os.path.join(REPO, "vorlagen", "homeassistant", "ev_pv_anteil.yaml")
PAKET_Z = os.path.join(REPO, "vorlagen", "homeassistant", "ev_pv_anteil_mit_zaehler.yaml")
ERG = []


def check(bereich, test, ok, detail=""):
    ERG.append((bereich, test, bool(ok), detail))


def nah(a, b, tol=0.01):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


# ═══ Node-RED ═══════════════════════════════════════════════════════════════
BASIS = {"netz": "sensor.netz", "wallbox": "sensor.wb", "ha_url": "", "ha_token": ""}
ENV = {"SUPERVISOR_TOKEN": "abc"}


def z(wert, einheit="W"):
    return {"state": str(wert), "attributes": {"unit_of_measurement": einheit}}


def lauf(schritte, einstellungen=None, env=ENV, dateispeicher=False):
    sz = {"einstellungen": {**BASIS, **(einstellungen or {})}, "env": env,
          "dateispeicher": dateispeicher, "schritte": schritte}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(sz, f)
    try:
        r = subprocess.run(["node", os.path.join(HIER, "vorlagen_nodered_pruefstand.js"), FLOW, f.name],
                           capture_output=True, text=True, encoding="utf-8")
    finally:
        os.remove(f.name)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-800:])
    return json.loads(r.stdout)


def ha_wert(schritt, entity):
    s = schritt["ha"].get(entity)
    return float(s["state"]) if s else None


def leistung(netz, wb, einheit="W", einstellungen=None, extra=None):
    zust = {"sensor.netz": z(netz, einheit), "sensor.wb": z(wb, einheit), **(extra or {})}
    e = lauf([{"t": 0, "zustaende": zust}, {"t": 10, "zustaende": zust}], einstellungen)[-1]
    return ha_wert(e, "sensor.ev_ladeleistung_pv"), ha_wert(e, "sensor.ev_ladeleistung_netz"), e


FAELLE = [  # (Name, Netz, Wallbox, Einheit, Einstellungen, extra, soll PV, soll Netz)
    ("Sonne: Einspeisung, Auto lädt komplett mit PV", -3000, 7000, "W", None, None, 7000, 0),
    ("Teilweise: 2 kW Bezug bei 7 kW Laden", 2000, 7000, "W", None, None, 5000, 2000),
    ("Nachts: Bezug größer als Ladeleistung", 7400, 7000, "W", None, None, 0, 7000),
    ("Standby-Leistung zählt als 0", 500, 30, "W", None, None, 0, 0),
    ("Einheit kW wird erkannt", 2.0, 7.0, "kW", None, None, 5000, 2000),
    ("Vorzeichen: Bezug negativ (SolarEdge)", -2000, 7000, "W",
     {"netz_bezug_positiv": False}, None, 5000, 2000),
    ("Hausakku entlädt 5 kW ins Auto → zählt als PV", 6000, 11000, "W", None, None, 5000, 6000),
    ("Hausakku als Netz (Option)", 6000, 11000, "W",
     {"akku_als": "netz", "akku": "sensor.akku"}, {"sensor.akku": z(5000)}, 0, 11000),
]
for name, netz, wb, einheit, einst, extra, s_pv, s_netz in FAELLE:
    pv, nz, e = leistung(netz, wb, einheit, einst, extra)
    check("Node-RED", name, nah(pv, s_pv, 1) and nah(nz, s_netz, 1), f"PV {pv} / Netz {nz} – {e['status2']}")

# Eine Stunde 2 kW Bezug bei 7 kW Laden, Leistung aufsummiert
konst = {"sensor.netz": z(2000), "sensor.wb": z(7000)}
e = lauf([{"t": i * 10, "zustaende": konst} for i in range(361)])[-1]
check("Node-RED", "1 h integriert: 5,0 kWh PV / 2,0 kWh Netz",
      nah(ha_wert(e, "sensor.ev_ladung_pv"), 5.0) and nah(ha_wert(e, "sensor.ev_ladung_netz"), 2.0),
      f'{ha_wert(e, "sensor.ev_ladung_pv")} / {ha_wert(e, "sensor.ev_ladung_netz")}')
check("Node-RED", "Sensor-Attribute fürs Energie-Dashboard",
      e["ha"]["sensor.ev_ladung_pv"]["attributes"]["state_class"] == "total_increasing"
      and e["ha"]["sensor.ev_ladung_pv"]["attributes"]["unit_of_measurement"] == "kWh")

# Wallbox-Zaehler: 7 kWh pro Stunde, alle 10 s abgefragt, in kWh und in Wh
for einheit, faktor in (("kWh", 1), ("Wh", 1000)):
    schritte = [{"t": i * 10, "zustaende": {**konst, "sensor.zaehler": z(round((100 + i * 7 / 360) * faktor, 4), einheit)}}
                for i in range(361)]
    e = lauf(schritte, {"wallbox_zaehler": "sensor.zaehler"})[-1]
    check("Node-RED", f"Zähler ({einheit}) aufgeteilt: 5,0 kWh PV / 2,0 kWh Netz",
          nah(ha_wert(e, "sensor.ev_ladung_pv"), 5.0) and nah(ha_wert(e, "sensor.ev_ladung_netz"), 2.0),
          f'{ha_wert(e, "sensor.ev_ladung_pv")} / {ha_wert(e, "sensor.ev_ladung_netz")}')

# Zaehler faellt auf 0 (Wallbox getauscht/zurueckgesetzt): kein Minus, danach weiter
schritte = [{"t": 0, "zustaende": {**konst, "sensor.zaehler": z(100, "kWh")}},
            {"t": 10, "zustaende": {**konst, "sensor.zaehler": z(107, "kWh")}},
            {"t": 20, "zustaende": {**konst, "sensor.zaehler": z(0, "kWh")}},
            {"t": 30, "zustaende": {**konst, "sensor.zaehler": z(7, "kWh")}}]
e = lauf(schritte, {"wallbox_zaehler": "sensor.zaehler"})
summen = [round(ha_wert(x, "sensor.ev_ladung_pv") + ha_wert(x, "sensor.ev_ladung_netz"), 3) for x in e]
check("Node-RED", "Zähler zurückgesetzt: kein Minus, danach weiter", summen == [0, 7, 7, 14], str(summen))

# Neustarts
schritte = [{"t": i * 10, "zustaende": konst} for i in range(181)]
schritte.append({"t": 1810, "zustaende": konst, "nodered_neustart": True})
e = lauf(schritte)
check("Node-RED", "Node-RED-Neustart ohne Dateispeicher: Stand aus HA übernommen",
      ha_wert(e[-1], "sensor.ev_ladung_pv") >= ha_wert(e[-2], "sensor.ev_ladung_pv") > 2.4,
      f'{ha_wert(e[-2], "sensor.ev_ladung_pv")} → {ha_wert(e[-1], "sensor.ev_ladung_pv")}')
schritte[-1] = {"t": 1810, "zustaende": konst, "ha_neustart": True}
e = lauf(schritte)
check("Node-RED", "HA-Neustart: Zähler laufen aus dem Node-RED-Speicher weiter",
      ha_wert(e[-1], "sensor.ev_ladung_pv") >= ha_wert(e[-2], "sensor.ev_ladung_pv") > 2.4)
schritte[-1] = {"t": 1810, "zustaende": konst, "nodered_neustart": True, "ha_neustart": True}
e = lauf(schritte, dateispeicher=True)
check("Node-RED", "Beide neu gestartet, Dateispeicher eingerichtet: Stand bleibt",
      ha_wert(e[-1], "sensor.ev_ladung_pv") >= 2.4, str(ha_wert(e[-1], "sensor.ev_ladung_pv")))

# Sensor fehlt kurz: gelber Status, danach keine Nachholung der Pause
schritte = [{"t": 0, "zustaende": konst}, {"t": 10, "zustaende": konst},
            {"t": 20, "zustaende": {"sensor.netz": z(2000), "sensor.wb": z("unavailable")}},
            {"t": 1000, "zustaende": konst}, {"t": 1010, "zustaende": konst}]
e = lauf(schritte)
check("Node-RED", "Sensor nicht verfügbar → gelber Status mit Hinweis",
      e[2]["status2"]["fill"] == "yellow" and "sensor.wb" in e[2]["status2"]["text"], str(e[2]["status2"]))
check("Node-RED", "Nach Pause keine Riesen-Nachzahlung (lange Lücke nicht integriert)",
      nah(ha_wert(e[-1], "sensor.ev_ladung_pv"), 5000 * 20 / 3.6e6, 0.002),
      str(ha_wert(e[-1], "sensor.ev_ladung_pv")))
e = lauf([{"t": 0, "zustaende": {"sensor.wb": z(7000)}}])
check("Node-RED", "Unbekannte Entity → Meldung von HA im Status",
      "Entity not found" in (e[0]["status2"] or {}).get("text", ""), str(e[0]["status2"]))

# Einrichtung
e = lauf([{"t": 0, "zustaende": konst}], env={})
check("Node-RED", "Ohne Add-on und ohne Token → roter Hinweis",
      e[0]["status1"]["fill"] == "red" and "ha_token" in e[0]["status1"]["text"], str(e[0]["status1"]))
e = lauf([{"t": 0, "zustaende": konst}], {"netz": "sensor.DEIN_NETZ"})
check("Node-RED", "Platzhalter nicht ersetzt → roter Hinweis",
      e[0]["status1"]["fill"] == "red" and "netz" in e[0]["status1"]["text"], str(e[0]["status1"]))

# Nicht bei jedem Durchlauf senden: gleiche Werte erst nach 5 Minuten wieder
null = {"sensor.netz": z(500), "sensor.wb": z(0)}
e = lauf([{"t": t, "zustaende": null} for t in (0, 10, 20, 310)])
check("Node-RED", "Unveränderte Werte nicht dauernd senden, nach 5 min erneut",
      [len(x["gesendet"]) for x in e] == [4, 0, 0, 4], str([len(x["gesendet"]) for x in e]))

# Flow selbst: nur Standardknoten, Verkettung
knoten = json.load(open(FLOW, encoding="utf-8"))
typen = {k["type"] for k in knoten}
check("Node-RED", "Flow nutzt nur Standardknoten",
      typen <= {"tab", "comment", "inject", "function", "http request", "join", "debug"}, str(typen))
quellen = {"⚙": "einstellungen.js", "PV / Netz berechnen": "berechnen.js"}
for anfang, datei in quellen.items():
    fn = next(k for k in knoten if k["type"] == "function" and k["name"].startswith(anfang))
    quelltext = open(os.path.join(REPO, "vorlagen", "node-red", "quellen", datei), encoding="utf-8").read()
    check("Node-RED", f"Flow-JSON ist aktuell ({datei}) – sonst quellen/flow_bauen.py ausführen",
          fn["func"] == quelltext)
ids = {k["id"] for k in knoten}
check("Node-RED", "Alle Verbindungen zeigen auf vorhandene Knoten",
      all(z_ in ids for k in knoten for w in k.get("wires", []) for z_ in w))


# ═══ Home Assistant (Jinja2-Nachbau) ════════════════════════════════════════
class Zustand:
    def __init__(self, state, attributes=None):
        self.state, self.attributes = str(state), attributes or {}


def ist_zahl(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def renderer(zustaende):
    env = jinja2.Environment()
    env.globals["states"] = lambda e: zustaende[e].state if e in zustaende else "unknown"
    env.globals["state_attr"] = lambda e, a: zustaende[e].attributes.get(a) if e in zustaende else None
    env.filters["is_number"] = ist_zahl
    return env


def templates(pfad, ersetzen=None):
    text = open(pfad, encoding="utf-8").read()
    for alt, neu in (ersetzen or {}).items():
        text = text.replace(alt, neu)
    d = yaml.safe_load(text)
    alle = {}
    for block in d["template"]:
        for s in block["sensor"]:
            alle[s["unique_id"]] = s
    return alle


ERSETZEN = {"sensor.DEIN_NETZ": "sensor.netz", "sensor.DEINE_WALLBOX": "sensor.wb",
            "sensor.DEIN_AKKU": "sensor.akku", "sensor.DEIN_WALLBOX_ZAEHLER": "sensor.zaehler"}


def leistung_ha(netz, wb, einheit="W", ersetzen=None, akku=None):
    t = templates(PAKET, {**ERSETZEN, **(ersetzen or {})})
    zust = {"sensor.netz": Zustand(netz, {"unit_of_measurement": einheit}),
            "sensor.wb": Zustand(wb, {"unit_of_measurement": einheit})}
    if akku is not None:
        zust["sensor.akku"] = Zustand(akku, {"unit_of_measurement": "W"})
    env = renderer(zust)
    # Reihenfolge wie in HA: Wallbox → Netz → PV (jeweils aus dem Ergebnis davor)
    for uid, entity in (("ev_tracker_ladeleistung_wallbox", "sensor.ev_ladeleistung_wallbox"),
                        ("ev_tracker_ladeleistung_netz", "sensor.ev_ladeleistung_netz"),
                        ("ev_tracker_ladeleistung_pv", "sensor.ev_ladeleistung_pv")):
        verf = env.from_string(t[uid]["availability"]).render().strip()
        wert = env.from_string(t[uid]["state"]).render().strip() if verf == "True" else "unavailable"
        zust[entity] = Zustand(wert)
    return zust["sensor.ev_ladeleistung_pv"].state, zust["sensor.ev_ladeleistung_netz"].state, zust


for name, netz, wb, einheit, einst, extra, s_pv, s_netz in FAELLE:
    ersetzen = {}
    if einst and einst.get("netz_bezug_positiv") is False:
        ersetzen["{% set netz_bezug_positiv = true %}"] = "{% set netz_bezug_positiv = false %}"
    if einst and einst.get("akku_als") == "netz":
        ersetzen["{% set akku_als_netz = false %}"] = "{% set akku_als_netz = true %}"
    pv, nz, _ = leistung_ha(netz, wb, einheit, ersetzen, akku=5000 if extra else None)
    check("HA-Paket", name, nah(pv, s_pv, 1) and nah(nz, s_netz, 1), f"PV {pv} / Netz {nz}")

pv, nz, zust = leistung_ha("unavailable", 7000)
check("HA-Paket", "Netzsensor nicht verfügbar → Netz/PV nicht verfügbar statt falscher Werte",
      nz == "unavailable" and pv == "unavailable", f"{pv} / {nz}")
for pfad in (PAKET, PAKET_Z):
    rest = [p for p in ("sensor.DEIN_NETZ", "sensor.DEINE_WALLBOX") if p not in open(pfad, encoding="utf-8").read()]
    check("HA-Paket", f"Platzhalter vorhanden ({os.path.basename(pfad)})", not rest, str(rest))

# Integral-Sensoren (Leistung → kWh)
d = yaml.safe_load(open(PAKET, encoding="utf-8"))
integ = {s["name"]: s for s in d["sensor"]}
check("HA-Paket", "Integral-Sensoren: PV/Netz, Methode links, kWh",
      integ["EV Ladung PV"]["source"] == "sensor.ev_ladeleistung_pv"
      and integ["EV Ladung Netz"]["source"] == "sensor.ev_ladeleistung_netz"
      and all(s["method"] == "left" and s["unit_prefix"] == "k" for s in integ.values()))

# Zaehler-Variante: eine Stunde, Zaehler steigt alle 10 s, Leistung 2 kW Netz / 5 kW PV
for einheit, faktor in (("kWh", 1), ("Wh", 1000)):
    t = templates(PAKET_Z, ERSETZEN)
    zust = {"sensor.ev_ladeleistung_wallbox": Zustand(7000), "sensor.ev_ladeleistung_pv": Zustand(5000)}
    env = renderer(zust)
    stand = {"ev_tracker_ladung_pv": "unknown", "ev_tracker_ladung_netz": "unknown"}
    for i in range(360):
        alt, neu = (100 + i * 7 / 360) * faktor, (100 + (i + 1) * 7 / 360) * faktor
        trig = {"to_state": Zustand(neu, {"unit_of_measurement": einheit}),
                "from_state": Zustand(alt, {"unit_of_measurement": einheit})}
        for uid in stand:
            stand[uid] = env.from_string(t[uid]["state"]).render(
                trigger=trig, this=Zustand(stand[uid])).strip()
    check("HA-Paket", f"Zähler ({einheit}): 1 h → 5,0 kWh PV / 2,0 kWh Netz",
          nah(stand["ev_tracker_ladung_pv"], 5.0) and nah(stand["ev_tracker_ladung_netz"], 2.0), str(stand))
t = templates(PAKET_Z, ERSETZEN)
env = renderer({"sensor.ev_ladeleistung_wallbox": Zustand(7000), "sensor.ev_ladeleistung_pv": Zustand(5000)})
trig = {"to_state": Zustand(0, {"unit_of_measurement": "kWh"}), "from_state": Zustand(107, {"unit_of_measurement": "kWh"})}
wert = env.from_string(t["ev_tracker_ladung_pv"]["state"]).render(trigger=trig, this=Zustand("12.5")).strip()
check("HA-Paket", "Zähler zurückgesetzt: Stand bleibt, kein Minus", nah(wert, 12.5), wert)
env = renderer({"sensor.ev_ladeleistung_wallbox": Zustand(0), "sensor.ev_ladeleistung_pv": Zustand(0)})
trig = {"to_state": Zustand(100.05, {"unit_of_measurement": "kWh"}), "from_state": Zustand(100, {"unit_of_measurement": "kWh"})}
netz = env.from_string(t["ev_tracker_ladung_netz"]["state"]).render(trigger=trig, this=Zustand("3")).strip()
check("HA-Paket", "Zähler steigt ohne gemessene Leistung → zählt als Netz (vorsichtig)", nah(netz, 3.05), netz)

# ── Ausgabe ──────────────────────────────────────────────────────────────────
ok_n = sum(1 for e in ERG if e[2])
print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
for b, t_, ok, d_ in ERG:
    if not ok:
        print(f"FEHLER  [{b}] {t_}\n        {d_}")
sys.exit(0 if ok_n == len(ERG) else 1)
