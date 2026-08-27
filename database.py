import sqlite3
import os
from contextlib import closing

# Pfad per Umgebungsvariable überschreibbar (für Docker: /data/ev_tracker.db)
DB_PATH = os.environ.get(
    "EV_TRACKER_DB",
    os.path.join(os.path.dirname(__file__), "ev_tracker.db"))


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with closing(get_connection()) as conn:
        c = conn.cursor()

        c.execute("""
            CREATE TABLE IF NOT EXISTS fahrten_monat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monat TEXT NOT NULL UNIQUE,
                km REAL NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS ladevorgang (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datum TEXT NOT NULL,
                menge_kwh REAL NOT NULL,
                preis_kwh REAL,
                gesamtpreis REAL NOT NULL,
                anbieter TEXT NOT NULL,
                ladeleistung_kw REAL,
                ladetyp TEXT NOT NULL,
                notiz TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS stromtarif (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                gueltig_ab TEXT NOT NULL,
                preis_kwh REAL NOT NULL,
                tarif_name TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS benzinpreis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                monat TEXT NOT NULL UNIQUE,
                preis_liter REAL NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS einstellungen (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS thg_quote (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datum TEXT NOT NULL,
                betrag REAL NOT NULL,
                anbieter TEXT NOT NULL,
                notiz TEXT
            )
        """)

        c.execute("""
            CREATE TABLE IF NOT EXISTS lade_anbieter (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                ist_system INTEGER NOT NULL DEFAULT 0,
                gruenstrom INTEGER NOT NULL DEFAULT 0
            )
        """)

        c.execute("""CREATE INDEX IF NOT EXISTS idx_ladevorgang_datum
                     ON ladevorgang(datum)""")

        # Defaults
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('benziner_verbrauch', '7.0')")
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('kfz_steuer_benziner', '0.0')")
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('ev_verbrauch_default', '15.0')")
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('co2_strommix', '401')")
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('pv_preis_ct', '13.0')")
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('co2_faktor_benzin', '2.37')")
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('ha_aktiv', '0')")

        # Migration: gruenstrom Spalte hinzufuegen falls nicht vorhanden
        try:
            c.execute("ALTER TABLE lade_anbieter ADD COLUMN gruenstrom INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits

        # Migration: alten mEDL-Eintrag korrigieren
        c.execute("UPDATE lade_anbieter SET name='medl', gruenstrom=1 WHERE name='mEDL'")

        # System-Anbieter
        system_anbieter = [
            ("Privat – Netzbezug", 1),
            ("Privat – PV",        1),
            ("medl",               1),
            ("EnBW",               0),
            ("Ionity",             0),
            ("ARAL Pulse",         0),
        ]
        for name, gruenstrom in system_anbieter:
            c.execute("""INSERT OR IGNORE INTO lade_anbieter (name, ist_system, gruenstrom)
                         VALUES (?,1,?)""", (name, gruenstrom))

        conn.commit()


# --- Einstellungen ---
def get_einstellung(key):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT value FROM einstellungen WHERE key=?", (key,)).fetchone()
    if row is None:
        return None
    try:
        return float(row["value"])
    except ValueError:
        return None


def get_einstellung_str(key):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT value FROM einstellungen WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_einstellung(key, value):
    with closing(get_connection()) as conn:
        conn.execute("INSERT OR REPLACE INTO einstellungen VALUES (?,?)", (key, str(value)))
        conn.commit()


def get_config() -> dict:
    """Gibt alle häufig genutzten Konfigurationswerte als dict zurück (eine DB-Abfrage)."""
    keys = ["benziner_verbrauch", "ev_verbrauch_default", "pv_preis_ct",
            "co2_faktor_benzin", "co2_strommix", "ha_aktiv"]
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT key, value FROM einstellungen WHERE key IN ({','.join('?'*len(keys))})", keys
        ).fetchall()
    m = {r["key"]: r["value"] for r in rows}
    return {
        "benziner_verbrauch": float(m.get("benziner_verbrauch") or 7.0),
        "ev_verbrauch":       float(m.get("ev_verbrauch_default") or 15.0),
        "pv_preis_ct":        float(m.get("pv_preis_ct") or 13.0),
        "co2_faktor_benzin":  float(m.get("co2_faktor_benzin") or 2.37),
        "co2_strommix":       float(m.get("co2_strommix") or 401.0),
        "ha_aktiv":           m.get("ha_aktiv") == "1",
    }


def get_alle_einstellungen() -> dict:
    """Alle Schlüssel/Werte der Einstellungen-Tabelle (für Export)."""
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT key, value FROM einstellungen").fetchall()
    return {r["key"]: r["value"] for r in rows}


def set_einstellungen(werte: dict):
    """Mehrere Einstellungen auf einmal schreiben (für Import)."""
    with closing(get_connection()) as conn:
        for key, val in werte.items():
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES (?,?)",
                         (key, str(val)))
        conn.commit()


# --- Fahrten (Monats-km) ---
def set_fahrt_monat(monat, km):
    with closing(get_connection()) as conn:
        conn.execute("INSERT OR REPLACE INTO fahrten_monat (monat, km) VALUES (?,?)", (monat, km))
        conn.commit()


def get_fahrten_monate():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM fahrten_monat ORDER BY monat DESC").fetchall()
    return [dict(r) for r in rows]


def delete_fahrt_monat(monat):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM fahrten_monat WHERE monat=?", (monat,))
        conn.commit()


def get_fahrten_gesamt_km():
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT SUM(km) as total FROM fahrten_monat").fetchone()
    return row["total"] or 0.0


def get_fahrten_alle_als_liste():
    """Kompatibilität für Charts: gibt Liste mit datum+km zurück"""
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT monat as datum, km FROM fahrten_monat ORDER BY monat").fetchall()
    return [dict(r) for r in rows]


# --- Laden ---
def add_ladevorgang(datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw, ladetyp, notiz=""):
    with closing(get_connection()) as conn:
        conn.execute("""
            INSERT INTO ladevorgang (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw, ladetyp, notiz)
            VALUES (?,?,?,?,?,?,?,?)
        """, (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw, ladetyp, notiz))
        conn.commit()


def ladevorgang_exists(datum, menge_kwh, anbieter):
    """Duplikat-Schutz beim Import: existiert bereits ein Vorgang mit
    gleichem Datum, Anbieter und (nahezu) gleicher kWh-Menge?"""
    with closing(get_connection()) as conn:
        row = conn.execute("""
            SELECT 1 FROM ladevorgang
            WHERE datum=? AND anbieter=? AND ABS(menge_kwh - ?) < 0.001
            LIMIT 1
        """, (datum, anbieter, menge_kwh)).fetchone()
    return row is not None


def get_ladevorgaenge(limit=500):
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM ladevorgang ORDER BY datum DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def delete_ladevorgang(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM ladevorgang WHERE id=?", (id,))
        conn.commit()


def get_lade_gesamt():
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT SUM(menge_kwh) as kwh, SUM(gesamtpreis) as kosten FROM ladevorgang").fetchone()
    return row["kwh"] or 0.0, row["kosten"] or 0.0


AUTO_NOTIZ = "Auto-Import HA"


def upsert_auto_ladevorgang(datum, menge_kwh, preis_kwh, gesamtpreis, anbieter):
    """Legt einen automatisch importierten Ladevorgang an oder aktualisiert ihn.

    Erkennungsmerkmal ist Datum + Anbieter + die Notiz `AUTO_NOTIZ`; manuell
    erfasste Vorgaenge bleiben davon unberuehrt.
    Rueckgabe: "neu", "aktualisiert" oder "unveraendert".
    """
    with closing(get_connection()) as conn:
        row = conn.execute(
            """SELECT id, menge_kwh FROM ladevorgang
               WHERE datum=? AND anbieter=? AND notiz LIKE ?""",
            (datum, anbieter, AUTO_NOTIZ + "%")).fetchone()
        if row:
            if abs((row["menge_kwh"] or 0) - menge_kwh) < 0.01:
                return "unveraendert"
            conn.execute(
                """UPDATE ladevorgang
                   SET menge_kwh=?, preis_kwh=?, gesamtpreis=? WHERE id=?""",
                (menge_kwh, preis_kwh, gesamtpreis, row["id"]))
            conn.commit()
            return "aktualisiert"
        conn.execute(
            """INSERT INTO ladevorgang (datum, menge_kwh, preis_kwh, gesamtpreis,
                                        anbieter, ladeleistung_kw, ladetyp, notiz)
               VALUES (?,?,?,?,?,?,?,?)""",
            (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, 11, "AC", AUTO_NOTIZ))
        conn.commit()
        return "neu"


def get_ladevorgaenge_zeitraum(von: str, bis: str):
    """Ladevorgaenge zwischen zwei Datumsangaben (YYYY-MM-DD, inklusive)."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM ladevorgang WHERE datum >= ? AND datum <= ? ORDER BY datum",
            (von, bis)).fetchall()
    return [dict(r) for r in rows]


def get_thg_zeitraum(von: str, bis: str):
    """THG-Eintraege zwischen zwei Datumsangaben (inklusive)."""
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT * FROM thg_quote WHERE datum >= ? AND datum <= ? ORDER BY datum",
            (von, bis)).fetchall()
    return [dict(r) for r in rows]


# --- Stromtarif ---
def add_stromtarif(gueltig_ab, preis_kwh, tarif_name=""):
    with closing(get_connection()) as conn:
        conn.execute("INSERT INTO stromtarif (gueltig_ab, preis_kwh, tarif_name) VALUES (?,?,?)",
                     (gueltig_ab, preis_kwh, tarif_name))
        conn.commit()


def get_stromtarife():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM stromtarif ORDER BY gueltig_ab DESC").fetchall()
    return [dict(r) for r in rows]


def get_aktueller_stromtarif():
    """Gibt den zuletzt gültigen Stromtarif zurück (oder None)."""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT * FROM stromtarif ORDER BY gueltig_ab DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def delete_stromtarif(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM stromtarif WHERE id=?", (id,))
        conn.commit()


# --- Benzinpreise ---
def set_benzinpreis(monat, preis):
    with closing(get_connection()) as conn:
        conn.execute("INSERT OR REPLACE INTO benzinpreis (monat, preis_liter) VALUES (?,?)", (monat, preis))
        conn.commit()


def get_benzinpreise():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM benzinpreis ORDER BY monat").fetchall()
    return [dict(r) for r in rows]


def delete_benzinpreis(monat):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM benzinpreis WHERE monat=?", (monat,))
        conn.commit()


# --- THG-Quote ---
def add_thg(datum, betrag, anbieter, notiz=""):
    with closing(get_connection()) as conn:
        conn.execute("INSERT INTO thg_quote (datum, betrag, anbieter, notiz) VALUES (?,?,?,?)",
                     (datum, betrag, anbieter, notiz))
        conn.commit()


def get_thg_eintraege():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM thg_quote ORDER BY datum DESC").fetchall()
    return [dict(r) for r in rows]


def delete_thg(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM thg_quote WHERE id=?", (id,))
        conn.commit()


def get_thg_gesamt():
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT SUM(betrag) as total FROM thg_quote").fetchone()
    return row["total"] or 0.0


# --- Lade-Anbieter ---
def get_lade_anbieter():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM lade_anbieter ORDER BY ist_system DESC, name").fetchall()
    return [dict(r) for r in rows]


def add_lade_anbieter(name, gruenstrom=0):
    with closing(get_connection()) as conn:
        conn.execute("INSERT OR IGNORE INTO lade_anbieter (name, ist_system, gruenstrom) VALUES (?,0,?)",
                     (name, gruenstrom))
        conn.commit()


def update_lade_anbieter(id, name, gruenstrom):
    with closing(get_connection()) as conn:
        conn.execute("UPDATE lade_anbieter SET name=?, gruenstrom=? WHERE id=?",
                     (name, gruenstrom, id))
        conn.commit()


def delete_lade_anbieter(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM lade_anbieter WHERE id=? AND ist_system=0", (id,))
        conn.commit()


# --- HA Konfiguration ---
HA_ENTITY_DEFAULTS = {
    "ha_url":                    "http://homeassistant.local:8123",
    "ha_token":                  "",
    "ha_odometer":               "sensor.kia_ev3_odometer",
    "ha_ev_battery":             "sensor.kia_ev3_ev_battery_level",
    "ha_ev_range":               "sensor.kia_ev3_ev_range",
    "ha_pv_production":          "sensor.solaredge_energy_production",
    "ha_grid_consumption":       "sensor.solaredge_energy_consumption",
    "ha_grid_export":            "sensor.solaredge_energy_export",
    "ha_wallbox_energy":         "sensor.wallbox_energy_charged",
    "ha_tankerkoenig":           "sensor.tankerkoenig_e10_preis",
    "ha_tankerkoenig_2":         "",
    # Friendly Names für InfluxDB-Abfragen
    "fn_odometer":               "Ceed Kilometerstand",
    "fn_pv_production":          "",
    "fn_grid_consumption":       "",
    "fn_grid_export":            "",
    "fn_wallbox_energy":         "",
    "fn_tankerkoenig":           "",
    "fn_tankerkoenig_2":         "",
    # InfluxDB Verbindung
    "influx_url":                "http://localhost",
    "influx_port":               "8086",
    "influx_database":           "home_assistant",
    "influx_user":               "",
    "influx_password":           "",
    "influx_measurement_km":     "km",
    "influx_measurement_kwh":    "kWh",
    "influx_measurement_eur_l":  "EUR/L",
    # Datenquelle: "ha" oder "influxdb"
    "datasource":                "ha",
}


MAIL_DEFAULTS = {
    "mail_aktiv":        "0",
    "mail_smtp_server":  "smtp.web.de",
    "mail_smtp_port":    "587",
    "mail_benutzer":     "",
    "mail_passwort":     "",
    "mail_absender":     "",
    "mail_empfaenger":   "",
    "mail_uhrzeit":      "00:00",
    "mail_monat_aktiv":  "1",
    "mail_jahr_aktiv":   "1",
    # Merker, wann zuletzt versendet wurde (Format YYYY-MM bzw. YYYY)
    "mail_letzter_monat": "",
    "mail_letztes_jahr":  "",
    # Auf vollstaendige Daten warten, bevor der Monatsbericht rausgeht
    "bericht_warten":       "1",
    "bericht_max_wartetage": "10",
    # Naechtlicher Datenabruf aus Home Assistant
    "auto_import":         "1",
    "auto_import_letzter": "",
    # Ladeerkennung ueber den Batteriestand
    "akku_kapazitaet_kwh":  "58.3",
    "lade_min_anstieg":     "5",
}


def init_mail_settings():
    with closing(get_connection()) as conn:
        for key, val in MAIL_DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO einstellungen VALUES (?,?)", (key, val))
        conn.commit()


def get_mail_settings() -> dict:
    keys = list(MAIL_DEFAULTS.keys())
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT key, value FROM einstellungen WHERE key IN ({','.join('?'*len(keys))})", keys
        ).fetchall()
    gefunden = {r["key"]: r["value"] for r in rows}
    return {k: gefunden.get(k, MAIL_DEFAULTS[k]) for k in keys}


def init_ha_settings():
    with closing(get_connection()) as conn:
        for key, val in HA_ENTITY_DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO einstellungen VALUES (?,?)", (key, val))
        conn.commit()


def get_ha_settings():
    keys = list(HA_ENTITY_DEFAULTS.keys())
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT key, value FROM einstellungen WHERE key IN ({','.join('?'*len(keys))})", keys
        ).fetchall()
    found = {r["key"]: r["value"] for r in rows}
    return {key: found.get(key, HA_ENTITY_DEFAULTS.get(key, "")) for key in keys}


def save_ha_settings(settings: dict):
    with closing(get_connection()) as conn:
        for key, val in settings.items():
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES (?,?)", (key, val))
        conn.commit()
