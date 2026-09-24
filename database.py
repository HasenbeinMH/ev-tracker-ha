import sqlite3
import os
from contextlib import closing
from datetime import datetime

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

        # Fahrtabschnitte zwischen zwei Ladungen, berechnet aus dem Akkustand
        # (siehe akkuverbrauch.py). start/ende als lokale ISO-Zeit "YYYY-MM-DDTHH:MM".
        c.execute("""
            CREATE TABLE IF NOT EXISTS akku_abschnitt (
                start TEXT PRIMARY KEY,
                ende TEXT NOT NULL,
                soc_start REAL NOT NULL,
                soc_ende REAL NOT NULL,
                km_start REAL NOT NULL,
                km_ende REAL NOT NULL,
                kwh REAL NOT NULL,
                km REAL NOT NULL,
                laufend INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Eigene Ladetarife (Abos) mit Preishistorie: eine Preisaenderung ist ein
        # neuer Eintrag mit neuem gueltig_ab. Zuordnung zu Ladungen ueber den Anbieter.
        c.execute("""
            CREATE TABLE IF NOT EXISTS ladetarif (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                anbieter TEXT NOT NULL,
                tarif_name TEXT,
                gueltig_ab TEXT NOT NULL,
                gueltig_bis TEXT,
                preis_ac REAL NOT NULL,
                preis_dc REAL,
                grundgebuehr REAL NOT NULL DEFAULT 0,
                blockier_ct_min REAL,
                blockier_ab_min REAL,
                blockier_max_eur REAL,
                fremd_ab_ct REAL,
                fremd_max_ct REAL,
                ladekarte_eur REAL,
                notiz TEXT
            )
        """)

        # Instandhaltung: Werkstatt, Reifen, Verschleiss usw. – ein Eintrag je Rechnung
        c.execute("""
            CREATE TABLE IF NOT EXISTS instandhaltung (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datum TEXT NOT NULL,
                kategorie TEXT NOT NULL,
                beschreibung TEXT,
                werkstatt TEXT,
                km_stand REAL,
                betrag REAL NOT NULL,
                notiz TEXT
            )
        """)

        # KFZ-Versicherung mit Historie: neues Versicherungsjahr oder Wechsel ist ein
        # neuer Eintrag mit neuem gueltig_ab. Betraege in €/Jahr; Zusatzbausteine leer
        # = nicht gebucht, Werkstattbindung ist meist ein Rabatt (negativer Betrag).
        c.execute("""
            CREATE TABLE IF NOT EXISTS versicherung (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fahrzeug TEXT NOT NULL,
                gesellschaft TEXT NOT NULL,
                tarif_name TEXT,
                gueltig_ab TEXT NOT NULL,
                gueltig_bis TEXT,
                deckung TEXT NOT NULL,
                sf_haftpflicht TEXT,
                sf_kasko TEXT,
                jahreslaufleistung REAL,
                sb_teilkasko REAL,
                sb_vollkasko REAL,
                grundbeitrag REAL NOT NULL,
                fahrerschutz REAL,
                werkstattbindung REAL,
                auslandsschutz REAL,
                schutzbrief REAL,
                sonstige_zusatz REAL,
                notiz TEXT
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

        # Migration: Blockiergebuehr je Ladevorgang (ist im gesamtpreis enthalten)
        try:
            c.execute("ALTER TABLE ladevorgang ADD COLUMN blockiergebuehr REAL")
        except sqlite3.OperationalError:
            pass

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
def add_ladevorgang(datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw, ladetyp,
                    notiz="", blockiergebuehr=None):
    """gesamtpreis enthaelt eine Blockiergebuehr bereits; das Feld schluesselt sie nur auf."""
    with closing(get_connection()) as conn:
        conn.execute("""
            INSERT INTO ladevorgang (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw,
                                     ladetyp, notiz, blockiergebuehr)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw, ladetyp, notiz,
              blockiergebuehr))
        conn.commit()


def get_ladevorgang(id):
    """Einzelnen Ladevorgang laden (fuer die Bearbeitung)."""
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM ladevorgang WHERE id=?", (id,)).fetchone()
    return dict(row) if row else None


def update_ladevorgang(id, datum, menge_kwh, preis_kwh, gesamtpreis, anbieter,
                       ladeleistung_kw, ladetyp, notiz="", blockiergebuehr=None):
    """Aendert einen bestehenden Ladevorgang."""
    with closing(get_connection()) as conn:
        conn.execute("""
            UPDATE ladevorgang
               SET datum=?, menge_kwh=?, preis_kwh=?, gesamtpreis=?, anbieter=?,
                   ladeleistung_kw=?, ladetyp=?, notiz=?, blockiergebuehr=?
             WHERE id=?
        """, (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter,
              ladeleistung_kw, ladetyp, notiz, blockiergebuehr, id))
        conn.commit()


def set_ladepreis(id, preis_kwh, gesamtpreis):
    """Nur den Preis eines Ladevorgangs aendern (Neubewertung nach Tarifaenderung)."""
    with closing(get_connection()) as conn:
        conn.execute("UPDATE ladevorgang SET preis_kwh=?, gesamtpreis=? WHERE id=?",
                     (preis_kwh, gesamtpreis, id))
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
            """SELECT id, menge_kwh, preis_kwh FROM ladevorgang
               WHERE datum=? AND anbieter=? AND notiz LIKE ?""",
            (datum, anbieter, AUTO_NOTIZ + "%")).fetchone()
        if row:
            if (abs((row["menge_kwh"] or 0) - menge_kwh) < 0.01
                    and abs((row["preis_kwh"] or 0) - (preis_kwh or 0)) < 0.001):
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


def ersetze_akku_abschnitte(ab: str | None, abschnitte: list):
    """Ersetzt alle Abschnitte ab Startzeit `ab` (None = alle) durch die neuen."""
    with closing(get_connection()) as conn:
        if ab is None:
            conn.execute("DELETE FROM akku_abschnitt")
        else:
            conn.execute("DELETE FROM akku_abschnitt WHERE start >= ?", (ab,))
        conn.executemany(
            """INSERT OR REPLACE INTO akku_abschnitt
               (start, ende, soc_start, soc_ende, km_start, km_ende, kwh, km, laufend)
               VALUES (:start, :ende, :soc_start, :soc_ende, :km_start, :km_ende,
                       :kwh, :km, :laufend)""",
            abschnitte)
        conn.commit()


def get_akku_abschnitte(limit: int | None = None):
    """Fahrtabschnitte aus dem Akkustand, neueste zuerst."""
    sql = "SELECT * FROM akku_abschnitt ORDER BY start DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with closing(get_connection()) as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


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


# --- Ladetarife (eigene Abos) ---
LADETARIF_FELDER = ["anbieter", "tarif_name", "gueltig_ab", "gueltig_bis", "preis_ac", "preis_dc",
                    "grundgebuehr", "blockier_ct_min", "blockier_ab_min", "blockier_max_eur",
                    "fremd_ab_ct", "fremd_max_ct", "ladekarte_eur", "notiz"]


def add_ladetarif(werte: dict):
    with closing(get_connection()) as conn:
        conn.execute(
            f"INSERT INTO ladetarif ({','.join(LADETARIF_FELDER)}) "
            f"VALUES ({','.join('?' * len(LADETARIF_FELDER))})",
            [werte.get(f) for f in LADETARIF_FELDER])
        conn.commit()


def update_ladetarif(id, werte: dict):
    with closing(get_connection()) as conn:
        conn.execute(
            f"UPDATE ladetarif SET {','.join(f + '=?' for f in LADETARIF_FELDER)} WHERE id=?",
            [werte.get(f) for f in LADETARIF_FELDER] + [id])
        conn.commit()


def get_ladetarife():
    """Alle Eintraege, aelteste zuerst je Anbieter/Tarif."""
    with closing(get_connection()) as conn:
        rows = conn.execute("""SELECT * FROM ladetarif
                               ORDER BY anbieter, tarif_name, gueltig_ab""").fetchall()
    return [dict(r) for r in rows]


def get_ladetarif_am(anbieter, datum):
    """Der am Datum gueltige Tarif des Anbieters (juengster gueltig_ab <= datum)."""
    with closing(get_connection()) as conn:
        row = conn.execute("""
            SELECT * FROM ladetarif
             WHERE anbieter=? AND gueltig_ab <= ?
               AND (gueltig_bis IS NULL OR gueltig_bis = '' OR gueltig_bis >= ?)
             ORDER BY gueltig_ab DESC LIMIT 1""", (anbieter, datum, datum)).fetchone()
    return dict(row) if row else None


def get_aktuelle_ladetarife() -> dict:
    """{anbieter: heute gueltiger Tarif} – fuer die Preisvorbelegung auf /laden."""
    heute = datetime.now().strftime("%Y-%m-%d")
    ergebnis = {}
    for name in {t["anbieter"] for t in get_ladetarife()}:
        t = get_ladetarif_am(name, heute)
        if t:
            ergebnis[name] = t
    return ergebnis


def delete_ladetarif(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM ladetarif WHERE id=?", (id,))
        conn.commit()


# --- Instandhaltung ---
INSTANDHALTUNG_FELDER = ["datum", "kategorie", "beschreibung", "werkstatt", "km_stand",
                         "betrag", "notiz"]


def add_instandhaltung(werte: dict):
    with closing(get_connection()) as conn:
        conn.execute(
            f"INSERT INTO instandhaltung ({','.join(INSTANDHALTUNG_FELDER)}) "
            f"VALUES ({','.join('?' * len(INSTANDHALTUNG_FELDER))})",
            [werte.get(f) for f in INSTANDHALTUNG_FELDER])
        conn.commit()


def update_instandhaltung(id, werte: dict):
    with closing(get_connection()) as conn:
        conn.execute(
            f"UPDATE instandhaltung SET {','.join(f + '=?' for f in INSTANDHALTUNG_FELDER)} "
            f"WHERE id=?",
            [werte.get(f) for f in INSTANDHALTUNG_FELDER] + [id])
        conn.commit()


def get_instandhaltung():
    with closing(get_connection()) as conn:
        rows = conn.execute("SELECT * FROM instandhaltung ORDER BY datum DESC, id DESC").fetchall()
    return [dict(r) for r in rows]


def delete_instandhaltung(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM instandhaltung WHERE id=?", (id,))
        conn.commit()


# --- Versicherung ---
VERSICHERUNG_FELDER = ["fahrzeug", "gesellschaft", "tarif_name", "gueltig_ab", "gueltig_bis",
                       "deckung", "sf_haftpflicht", "sf_kasko", "jahreslaufleistung", "sb_teilkasko", "sb_vollkasko",
                       "grundbeitrag", "fahrerschutz", "werkstattbindung", "auslandsschutz",
                       "schutzbrief", "sonstige_zusatz", "notiz"]


def add_versicherung(werte: dict):
    with closing(get_connection()) as conn:
        conn.execute(
            f"INSERT INTO versicherung ({','.join(VERSICHERUNG_FELDER)}) "
            f"VALUES ({','.join('?' * len(VERSICHERUNG_FELDER))})",
            [werte.get(f) for f in VERSICHERUNG_FELDER])
        conn.commit()


def update_versicherung(id, werte: dict):
    with closing(get_connection()) as conn:
        conn.execute(
            f"UPDATE versicherung SET {','.join(f + '=?' for f in VERSICHERUNG_FELDER)} "
            f"WHERE id=?",
            [werte.get(f) for f in VERSICHERUNG_FELDER] + [id])
        conn.commit()


def get_versicherungen():
    with closing(get_connection()) as conn:
        rows = conn.execute("""SELECT * FROM versicherung
                               ORDER BY fahrzeug, gueltig_ab""").fetchall()
    return [dict(r) for r in rows]


def delete_versicherung(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM versicherung WHERE id=?", (id,))
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


# --- Messdaten zuruecksetzen ---
# Was die Backup-Seite loeschen kann: Schluessel (Name im Formular) -> (Tabelle,
# Beschriftung). Einstellungen, Stromtarife und Lade-Anbieter stehen bewusst
# nicht drin – die gelten weiter, auch wenn ein anderes Auto erfasst wird.
MESSDATEN_BEREICHE = {
    "fahrten": ("fahrten_monat",  "Gefahrene Kilometer (monatlich)"),
    "laden":   ("ladevorgang",    "Ladevorgänge"),
    "benzin":  ("benzinpreis",    "Benzinpreise"),
    "akku":    ("akku_abschnitt", "Fahrtabschnitte aus dem Akkustand"),
    "thg":     ("thg_quote",      "THG-Einträge"),
}


def zaehle_messdaten() -> dict:
    """Datensaetze je loeschbarem Bereich: {schluessel: anzahl}."""
    with closing(get_connection()) as conn:
        return {s: conn.execute(f"SELECT COUNT(*) FROM {tabelle}").fetchone()[0]
                for s, (tabelle, _) in MESSDATEN_BEREICHE.items()}


def loesche_messdaten(bereiche: list) -> dict:
    """Leert die genannten Bereiche. Rueckgabe: {schluessel: geloeschte Anzahl}.
    Unbekannte Schluessel werden ignoriert – die Tabellennamen kommen nie aus
    der Anfrage, sondern immer aus MESSDATEN_BEREICHE."""
    gewaehlt = [b for b in bereiche if b in MESSDATEN_BEREICHE]
    if not gewaehlt:
        return {}
    vorher = zaehle_messdaten()
    with closing(get_connection()) as conn:
        for b in gewaehlt:
            conn.execute(f"DELETE FROM {MESSDATEN_BEREICHE[b][0]}")
        conn.commit()
        conn.isolation_level = None   # VACUUM laeuft nicht in einer Transaktion
        conn.execute("VACUUM")
    return {b: vorher[b] for b in gewaehlt}


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
    "fn_ev_battery":             "",
    # InfluxDB Verbindung
    "influx_url":                "http://localhost",
    "influx_port":               "8086",
    "influx_database":           "home_assistant",
    "influx_user":               "",
    "influx_password":           "",
    "influx_measurement_km":     "km",
    "influx_measurement_kwh":    "kWh",
    "influx_measurement_eur_l":  "EUR/L",
    "influx_measurement_prozent": "%",
    # Tag, ueber den InfluxDB 1.x/2.x den Sensor findet (friendly_name oder entity_id)
    "influx_tag":                "friendly_name",
    # InfluxDB 2.x
    "influx2_url":               "http://localhost:8086",
    "influx2_org":               "",
    "influx2_bucket":            "home_assistant",
    "influx2_token":             "",
    # PostgreSQL / TimescaleDB (HA-Integration LTSS)
    "pg_host":                   "localhost",
    "pg_port":                   "5432",
    "pg_database":               "homeassistant",
    "pg_user":                   "",
    "pg_password":               "",
    "pg_tabelle":                "ltss",
    # Prometheus / VictoriaMetrics (leerer Selektor = Standard aus datenquellen.py)
    "prom_url":                  "http://localhost:9090",
    "prom_user":                 "",
    "prom_password":             "",
    "prom_selektor":             "",
    # Datenquelle: "ha", "influxdb", "influxdb2", "postgres" oder "prometheus"
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
