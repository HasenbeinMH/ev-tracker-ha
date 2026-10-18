# -*- coding: utf-8 -*-
"""
Diagnose-Paket: alles, was zum Nachstellen eines Importproblems noetig ist, in einer ZIP.

Inhalt:
  ev_tracker.db      Kopie der Datenbank, Zugangsdaten und Mail-Adressen geleert
  import.log         Importprotokoll
  info.json          Version, Struktur-Stand, Datenquelle, eingetragene Sensoren
  ha_rohdaten.json   je eingetragenem HA-Sensor: aktueller Zustand, Stundenwerte der
                     Langzeitstatistik (state/sum/mean) der letzten Monate und die History
                     um jeden Monatswechsel (dort passieren Resets und Aussetzer)

Die Datenbank allein zeigt nur das Ergebnis des Imports – erst die Rohdaten aus Home
Assistant zeigen, wie es zustande kam.
"""
import io
import json
import os
import platform
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timedelta

import database as db
import datenquellen
import heimladung

# Empfaenger fuer "Per Mail schicken" auf der Backup-Seite; leer = Knopf ausgeblendet
SUPPORT_MAIL = "ev-tracker@email.de"

# Zugangsdaten – fehlen im Einstellungs-Export "ohne Token/Passwort" und im Diagnose-Paket
GEHEIM = {"ha_token", heimladung.TOKEN_KEY, "mail_passwort"} | datenquellen.GEHEIM
# Zusaetzlich im Diagnose-Paket geleert: persoenlich, fuer die Fehlersuche ohne Nutzen
PERSOENLICH = {"mail_benutzer", "mail_absender", "mail_empfaenger"}

# Einstellungen mit HA-Entity-IDs (Fahrzeug-Schluessel auch als "<key>@<id>")
SENSOR_KEYS = ("ha_odometer", "ha_ev_battery", "ha_ev_range", "ha_pv_production",
               "ha_grid_consumption", "ha_grid_export", "ha_wallbox_energy",
               "ha_wallbox_cost", "ha_tankerkoenig", "ha_tankerkoenig_2")


def _basis(key: str) -> str:
    """'ha_token@2' -> 'ha_token'."""
    return key.split("@", 1)[0]


def sensoren(einstellungen: dict) -> dict:
    """{entity_id: [einstellungs-schluessel, ...]} aller eingetragenen HA-Sensoren."""
    erg = {}
    for key, wert in einstellungen.items():
        if _basis(key) not in SENSOR_KEYS:
            continue
        for eid in datenquellen.namen_liste(wert):
            if "." in eid:
                erg.setdefault(eid, []).append(key)
    return erg


def db_bereinigt(ziel: str) -> list:
    """Konsistente Kopie der Datenbank nach `ziel`, Zugangsdaten geleert.
    Rueckgabe: geleerte Schluessel. VACUUM, damit die alten Werte auch nicht mehr in
    freien Seiten der Datei stehen."""
    quelle = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    kopie = sqlite3.connect(ziel)
    try:
        with kopie:
            quelle.backup(kopie)
        geleert = []
        for (key, wert) in kopie.execute("SELECT key, value FROM einstellungen").fetchall():
            if _basis(key) in GEHEIM | PERSOENLICH and wert:
                kopie.execute("UPDATE einstellungen SET value='' WHERE key=?", (key,))
                geleert.append(key)
        kopie.commit()
        kopie.execute("VACUUM")
    finally:
        kopie.close()
        quelle.close()
    return sorted(geleert)


def _monatsanfaenge(jetzt: datetime, monate: int) -> list:
    """Erster Tag der letzten `monate` Monate inkl. dem laufenden, aelteste zuerst."""
    j, m = jetzt.year, jetzt.month
    erg = []
    for _i in range(monate):
        erg.append(datetime(j, m, 1))
        m -= 1
        if m < 1:
            m, j = 12, j - 1
    return erg[::-1]


def ha_rohdaten(client, entities: dict, monate: int = 3, jetzt: datetime | None = None) -> dict:
    """Zustand, Stundenstatistik und History um die Monatswechsel je Sensor.
    Fehler landen im Ergebnis statt abzubrechen – ein Paket gibt es immer."""
    jetzt = jetzt or datetime.now()
    anfaenge = _monatsanfaenge(jetzt, monate)
    # Ab dem Vorabend des aeltesten Monats: wie beim Import (Basiswert vor dem Monat)
    von = anfaenge[0] - timedelta(hours=4)
    erg = {"zeitraum": [von.isoformat(timespec="minutes"), jetzt.isoformat(timespec="minutes")],
           "sensoren": {}}
    try:
        statistik = client._get_statistics(list(entities), von, jetzt, period="hour")
        erg["statistik_api"] = "ok" if statistik else "keine Daten (oder websocket-client fehlt)"
    except Exception as e:
        statistik = {}
        erg["statistik_api"] = f"Fehler: {e}"

    for eid, keys in entities.items():
        s = {"einstellung": keys}
        try:
            st = client._get(f"/api/states/{eid}")
            s["zustand"] = {"state": st.get("state"), "last_changed": st.get("last_changed"),
                            "attribute": st.get("attributes", {})}
        except Exception as e:
            s["zustand"] = {"fehler": str(e)}
        s["statistik_stunden"] = [
            {k: r.get(k) for k in ("start", "state", "sum", "mean") if k in r}
            for r in statistik.get(eid, [])]
        # Monatswechsel: vom Vorabend bis zum Abend des 1. – Resets und Aussetzer
        s["history_monatswechsel"] = {}
        for anfang in anfaenge:
            try:
                h = client.get_history_period(eid, anfang - timedelta(hours=4),
                                              anfang + timedelta(hours=20))
                s["history_monatswechsel"][anfang.strftime("%Y-%m")] = [
                    [e.get("last_changed") or e.get("last_updated"), e.get("state")] for e in h]
            except Exception as e:
                s["history_monatswechsel"][anfang.strftime("%Y-%m")] = f"Fehler: {e}"
        erg["sensoren"][eid] = s
    return erg


def paket_bauen(version: str, log_dateien: dict, client=None, ist_addon: bool = False,
                monate: int = 3) -> bytes:
    """ZIP als Bytes. log_dateien: {Name im Paket: Pfad}, fehlende werden uebersprungen."""
    einstellungen = db.get_alle_einstellungen()
    entities = sensoren(einstellungen)
    puffer = io.BytesIO()
    tmp = tempfile.mkdtemp(prefix="ev_diagnose_")
    try:
        kopie = os.path.join(tmp, "ev_tracker.db")
        geleert = db_bereinigt(kopie)
        with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(kopie, "ev_tracker.db")
            for name, pfad in log_dateien.items():
                if pfad and os.path.exists(pfad):
                    z.write(pfad, name)

            info = {
                "typ": "ev-tracker-diagnose",
                "erstellt": datetime.now().isoformat(timespec="seconds"),
                "version": version,
                "schema_db": einstellungen.get("schema_version"),
                "schema_code": db.SCHEMA_VERSION,
                "add_on": ist_addon,
                "python": sys.version.split()[0],
                "system": platform.platform(),
                "datenquelle": einstellungen.get("datasource", "ha"),
                "sprache": einstellungen.get("sprache", "de"),
                "sensoren": entities,
                "geleert": geleert,
            }
            z.writestr("info.json", json.dumps(info, indent=2, ensure_ascii=False))

            if client is None:
                roh = {"hinweis": "Home Assistant nicht konfiguriert – keine Rohdaten"}
            elif not entities:
                roh = {"hinweis": "Keine HA-Sensoren eingetragen"}
            else:
                roh = ha_rohdaten(client, entities, monate)
            z.writestr("ha_rohdaten.json", json.dumps(roh, indent=1, ensure_ascii=False))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return puffer.getvalue()
