# -*- coding: utf-8 -*-
"""
Einstellungen der Desktop-App als JSON-Datei sichern oder laden.

  python settings_tool.py export [datei.json] [--ohne-secrets]
  python settings_tool.py import datei.json

Die Datei ist identisch zum Export/Import der Web-Version – damit lassen sich
Einstellungen zwischen Desktop-App und Docker-Webapp übertragen.
"""
import json
import sys
from datetime import datetime

import database as db

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

GEHEIM_KEYS = {"ha_token", "influx_password", "influx2_token", "influx3_token", "pg_password", "prom_password"}


def exportieren(pfad, mit_secrets=True):
    db.init_db()
    werte = db.get_alle_einstellungen()
    if not mit_secrets:
        werte = {k: v for k, v in werte.items() if k not in GEHEIM_KEYS}
    daten = {
        "typ": "ev-tracker-einstellungen",
        "version": 1,
        "exportiert": datetime.now().isoformat(timespec="seconds"),
        "enthaelt_zugangsdaten": mit_secrets,
        "einstellungen": werte,
        "lade_anbieter": [
            {"name": a["name"], "gruenstrom": a["gruenstrom"],
             "ist_system": a["ist_system"]}
            for a in db.get_lade_anbieter()
        ],
    }
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=2, ensure_ascii=False)
    print(f"{len(werte)} Einstellungen + {len(daten['lade_anbieter'])} Anbieter "
          f"geschrieben nach: {pfad}")
    if mit_secrets:
        print("ACHTUNG: Datei enthaelt Token/Passwort im Klartext.")


def importieren(pfad):
    db.init_db()
    with open(pfad, encoding="utf-8") as f:
        daten = json.load(f)
    if daten.get("typ") != "ev-tracker-einstellungen":
        print("FEHLER: Keine EV-Tracker-Einstellungsdatei.")
        return 1

    werte = daten.get("einstellungen") or {}
    vorhanden = db.get_alle_einstellungen()
    werte = {k: v for k, v in werte.items()
             if not (k in GEHEIM_KEYS and not str(v).strip() and vorhanden.get(k))}
    db.set_einstellungen(werte)

    bekannt = {a["name"] for a in db.get_lade_anbieter()}
    neu = 0
    for a in daten.get("lade_anbieter") or []:
        name = (a.get("name") or "").strip()
        if name and name not in bekannt:
            db.add_lade_anbieter(name, 1 if a.get("gruenstrom") else 0)
            neu += 1
    print(f"{len(werte)} Einstellungen uebernommen, {neu} neue Anbieter "
          f"(Export vom {daten.get('exportiert', '?')})")
    return 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    ohne = "--ohne-secrets" in sys.argv
    if not args or args[0] not in ("export", "import"):
        print(__doc__)
        return 1
    if args[0] == "export":
        pfad = args[1] if len(args) > 1 else \
            f"ev_tracker_einstellungen_{datetime.now():%Y-%m-%d}.json"
        exportieren(pfad, mit_secrets=not ohne)
        return 0
    if len(args) < 2:
        print("Bitte Dateiname angeben.")
        return 1
    return importieren(args[1])


if __name__ == "__main__":
    sys.exit(main())
