# -*- coding: utf-8 -*-
"""
Baut den importierbaren Node-RED-Flow ../ev_pv_anteil_flow.json aus
einstellungen.js und berechnen.js (die Quelltexte bleiben so lesbar und testbar).
Die .js-Dateien sind nur Quellen – importiert wird die JSON-Datei.

    python vorlagen/node-red/quellen/flow_bauen.py

Der Flow nutzt nur Standard-Knoten (inject, function, http request, join, comment,
debug) – keine Zusatzpalette noetig.
"""
import json
import os

HIER = os.path.dirname(os.path.abspath(__file__))


def lesen(name):
    with open(os.path.join(HIER, name), encoding="utf-8") as f:
        return f.read()


TAB = "evpv0000tab00001"
knoten = [
    {"id": TAB, "type": "tab", "label": "EV Tracker – PV-Anteil beim Laden", "disabled": False,
     "info": "Teilt die Ladeleistung der Wallbox in PV und Netz auf und legt in Home Assistant "
             "die Sensoren sensor.ev_ladung_pv und sensor.ev_ladung_netz (kWh) an – fuer den "
             "EV Tracker (PV ins Auto / Netz ins Auto) und das Energie-Dashboard.\n\n"
             "Einrichtung: nur den Knoten \"⚙ Einstellungen\" oeffnen, Sensoren eintragen, "
             "Übernehmen (Deploy)."},
    {"id": "evpv0000cmt00001", "type": "comment", "z": TAB,
     "name": "① Knoten \"⚙ Einstellungen\" öffnen und Sensoren eintragen · ② Übernehmen",
     "info": "Regel: Haus zuerst, das Auto bekommt den Überschuss.\n"
             "Netz ins Auto = min(Netzbezug, Wallbox-Leistung), PV ins Auto = Rest.\n"
             "Ein Hausakku, der ins Auto entlädt, zählt als PV (einstellbar).",
     "x": 330, "y": 40, "wires": []},
    {"id": "evpv0000inj00001", "type": "inject", "z": TAB, "name": "alle 10 s",
     "props": [{"p": "payload"}], "repeat": "10", "crontab": "", "once": True,
     "onceDelay": "5", "topic": "", "payload": "", "payloadType": "date",
     "x": 120, "y": 100, "wires": [["evpv0000fn000001"]]},
    {"id": "evpv0000fn000001", "type": "function", "z": TAB,
     "name": "⚙ Einstellungen – hier Sensoren eintragen", "func": lesen("einstellungen.js"),
     "outputs": 1, "timeout": 0, "noerr": 0, "initialize": "", "finalize": "", "libs": [],
     "x": 360, "y": 100, "wires": [["evpv0000http0001"]]},
    {"id": "evpv0000http0001", "type": "http request", "z": TAB, "name": "Zustände lesen",
     "method": "use", "ret": "obj", "paytoqs": "ignore", "url": "", "tls": "",
     "persist": False, "proxy": "", "insecureHTTPParser": False, "authType": "",
     "senderr": False, "headers": [], "x": 610, "y": 100, "wires": [["evpv0000join0001"]]},
    {"id": "evpv0000join0001", "type": "join", "z": TAB, "name": "sammeln", "mode": "auto",
     "build": "object", "property": "payload", "propertyType": "msg", "key": "topic",
     "joiner": "\\n", "joinerType": "str", "accumulate": False, "timeout": "", "count": "",
     "reduceRight": False, "reduceExp": "", "reduceInit": "", "reduceInitType": "",
     "reduceFixup": "", "x": 790, "y": 100, "wires": [["evpv0000fn000002"]]},
    {"id": "evpv0000fn000002", "type": "function", "z": TAB, "name": "PV / Netz berechnen",
     "func": lesen("berechnen.js"), "outputs": 1, "timeout": 0, "noerr": 0,
     "initialize": "", "finalize": "", "libs": [],
     "x": 380, "y": 180, "wires": [["evpv0000http0002"]]},
    {"id": "evpv0000http0002", "type": "http request", "z": TAB, "name": "Sensoren nach HA schreiben",
     "method": "use", "ret": "obj", "paytoqs": "ignore", "url": "", "tls": "",
     "persist": False, "proxy": "", "insecureHTTPParser": False, "authType": "",
     "senderr": False, "headers": [], "x": 640, "y": 180, "wires": [["evpv0000dbg00001"]]},
    {"id": "evpv0000dbg00001", "type": "debug", "z": TAB, "name": "Antwort (bei Bedarf einschalten)",
     "active": False, "tosidebar": True, "console": False, "tostatus": False,
     "complete": "true", "targetType": "full", "statusVal": "", "statusType": "auto",
     "x": 900, "y": 180, "wires": []},
]

ziel = os.path.join(os.path.dirname(HIER), "ev_pv_anteil_flow.json")
with open(ziel, "w", encoding="utf-8", newline="\n") as f:
    json.dump(knoten, f, ensure_ascii=False, indent=2)
    f.write("\n")
print(f"geschrieben: {ziel} ({len(knoten)} Knoten)")
