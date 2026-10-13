from i18n import N_
import sqlite3
import os
from contextlib import closing, contextmanager
from contextvars import ContextVar
from datetime import datetime

# Pfad per Umgebungsvariable überschreibbar (für Docker: /data/ev_tracker.db)
DB_PATH = os.environ.get(
    "EV_TRACKER_DB",
    os.path.join(os.path.dirname(__file__), "ev_tracker.db"))


# Struktur-Stand der Datenbank. Steigt nur, wenn eine aeltere Version die Datenbank
# nicht mehr korrekt beschreiben koennte (z.B. geaenderte Eindeutigkeit einer Tabelle).
# Findet diese Version einen hoeheren Stand vor, oeffnet sie die DB nur lesend:
# sonst wuerde sie nach einem Downgrade still falsche Daten schreiben.
SCHEMA_VERSION = 3      # hoechster Stand, den dieser Code kennt
# Stand, den init_db() fuer alle setzt. 3 (Tabellen fuer mehrere Fahrzeuge umgebaut) entsteht
# erst beim Umschalten auf "Mehrere Fahrzeuge" (struktur_mehrere_fahrzeuge) – wer bei einem
# Fahrzeug bleibt, behaelt eine Datenbank, die auch 2.x noch korrekt beschreibt.
BASIS_SCHEMA = 2
SCHEMA_ZU_NEU = None    # gespeicherter Stand, wenn neuer als SCHEMA_VERSION, sonst None


def schema_pruefen() -> int | None:
    """Setzt SCHEMA_ZU_NEU anhand der Datenbank und gibt es zurueck."""
    global SCHEMA_ZU_NEU
    SCHEMA_ZU_NEU = None
    if not os.path.exists(DB_PATH):
        return None
    with closing(sqlite3.connect(DB_PATH)) as conn:
        try:
            row = conn.execute(
                "SELECT value FROM einstellungen WHERE key='schema_version'").fetchone()
        except sqlite3.OperationalError:      # neue oder leere Datenbank
            return None
    try:
        stand = int(row[0]) if row else 0
    except (TypeError, ValueError):
        stand = 0
    if stand > SCHEMA_VERSION:
        SCHEMA_ZU_NEU = stand
    return SCHEMA_ZU_NEU


def get_connection():
    if SCHEMA_ZU_NEU:
        # nur lesend – jeder Schreibversuch scheitert, statt Daten zu verfaelschen
        from pathlib import Path
        conn = sqlite3.connect(Path(DB_PATH).resolve().as_uri() + "?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    if schema_pruefen():
        print(f"[DB] Datenbank hat Struktur-Stand {SCHEMA_ZU_NEU}, diese Version kennt "
              f"{SCHEMA_VERSION}: nur lesend geoeffnet. Neue Version installieren oder "
              f"ein Backup wiederherstellen.", flush=True)
        return
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
                notiz TEXT,
                nur_vergleich INTEGER NOT NULL DEFAULT 0
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
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('kfz_steuer_eauto', '0.0')")
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

        # Migration: Kennung von Ladungen, die Home Assistant schickt (Push) – macht
        # das Senden wiederholbar, ohne doppelte Eintraege
        try:
            c.execute("ALTER TABLE ladevorgang ADD COLUMN extern_id TEXT")
        except sqlite3.OperationalError:
            pass
        c.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_ladevorgang_extern
                     ON ladevorgang(extern_id) WHERE extern_id IS NOT NULL""")

        # Struktur-Stand merken (nie herabsetzen)
        c.execute("INSERT OR IGNORE INTO einstellungen VALUES ('schema_version', ?)",
                  (str(BASIS_SCHEMA),))
        c.execute("""UPDATE einstellungen SET value=? WHERE key='schema_version'
                     AND CAST(value AS INTEGER) < ?""", (str(BASIS_SCHEMA), BASIS_SCHEMA))

        # Mehrere Fahrzeuge (3.0): Fahrzeugliste und Spalte fahrzeug_id. Nur Spalten
        # ergaenzen – bestehende Zeilen gehoeren damit Fahrzeug 1, die Eindeutigkeit
        # bleibt wie bisher (Umbau erst beim Umschalten, siehe struktur_mehrere_fahrzeuge).
        c.execute("""
            CREATE TABLE IF NOT EXISTS fahrzeug (
                id INTEGER PRIMARY KEY,
                aktiv INTEGER NOT NULL DEFAULT 1,
                sortierung INTEGER NOT NULL DEFAULT 0
            )
        """)
        c.execute("INSERT OR IGNORE INTO fahrzeug (id, aktiv, sortierung) VALUES (1, 1, 1)")
        for tabelle in FAHRZEUG_TABELLEN:
            try:
                c.execute(f"ALTER TABLE {tabelle} ADD COLUMN fahrzeug_id INTEGER NOT NULL DEFAULT 1")
            except sqlite3.OperationalError:
                pass
        # Versicherung: Freitext "fahrzeug" bisher; Vertraege des aktuellen Autos -> 1,
        # andere (fruehere Autos) bleiben ohne Zuordnung (NULL) und sind weiter sichtbar
        try:
            c.execute("ALTER TABLE versicherung ADD COLUMN fahrzeug_id INTEGER")
            name = c.execute("SELECT value FROM einstellungen WHERE key='fahrzeug_name'").fetchone()
            namen = {r[0] for r in c.execute("SELECT DISTINCT fahrzeug FROM versicherung")}
            if name and name[0] in namen:
                c.execute("UPDATE versicherung SET fahrzeug_id=1 WHERE fahrzeug=?", (name[0],))
            elif len(namen) == 1:
                c.execute("UPDATE versicherung SET fahrzeug_id=1")
        except sqlite3.OperationalError:
            pass
        # Ladetarif: NULL = gemeinsam (Grundgebuehr nach km auf die Fahrzeuge verteilt)
        try:
            c.execute("ALTER TABLE ladetarif ADD COLUMN fahrzeug_id INTEGER")
        except sqlite3.OperationalError:
            pass
        # Ladetarif nur zum Vergleich (Ad-hoc-Preis oder anderes Abo, nicht abgeschlossen)
        try:
            c.execute("ALTER TABLE ladetarif ADD COLUMN nur_vergleich INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        c.execute("""CREATE INDEX IF NOT EXISTS idx_ladevorgang_fahrzeug
                     ON ladevorgang(fahrzeug_id, datum)""")

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


# --- Fahrzeuge ---
# Tabellen mit Zeilen je Fahrzeug (Spalte fahrzeug_id, Standard 1)
FAHRZEUG_TABELLEN = ("fahrten_monat", "ladevorgang", "akku_abschnitt", "thg_quote",
                     "instandhaltung")

# Einstellungen, die jedes Fahrzeug fuer sich hat. Fahrzeug 1 nutzt die bisherigen
# Schluessel unveraendert, weitere Fahrzeuge "<schluessel>@<id>" – so aendert sich fuer
# alle, die bei einem Fahrzeug bleiben, an den gespeicherten Einstellungen nichts.
FAHRZEUG_SCHLUESSEL = {
    "fahrzeug_name", "auto_bild_datei", "auto_bild_galerie",
    "kraftstoff", "benziner_verbrauch", "ev_verbrauch_default", "co2_faktor_benzin",
    "kfz_steuer_benziner", "kfz_steuer_eauto", "kfz_steuer_eauto_ab",
    "anschaffung_eauto", "anschaffung_verbrenner", "anschaffung_foerderung",
    "erstzulassung", "zulassung_eigen", "km_bei_kauf",
    "akku_kapazitaet_kwh", "lade_min_anstieg", "heimladung",
    "ha_odometer", "ha_ev_battery", "ha_ev_range", "fn_odometer", "fn_ev_battery",
}
# Eigene Ladezaehler eines Fahrzeugs (Heimladung "eigen"): immer "<schluessel>@<id>",
# ohne @ sind es die Zaehler der gemeinsamen Wallbox
WALLBOX_SCHLUESSEL = ("ha_pv_production", "ha_wallbox_energy", "ha_wallbox_cost",
                      "fn_pv_production", "fn_wallbox_energy", "fn_wallbox_cost")
# Heimladung je Fahrzeug: gemeinsame Wallbox (Rest nach km verteilt; "push" = zusaetzlich
# Einzelladungen aus HA mit Fahrzeug-Kennung; "akku" = Wallbox-Stunden dem Auto zuordnen, dessen
# Akkustand gleichzeitig stieg, siehe heimladung.akku_anteile) oder eigene Zaehler
HEIMLADUNG_MODI = {"km": N_("Gemeinsame Wallbox – Aufteilung nach km"),
                   "push": N_("Gemeinsame Wallbox – Einzelladungen per Push, Rest nach km"),
                   "akku": N_("Gemeinsame Wallbox – Zuordnung über den Akkustand, Rest nach km"),
                   "eigen": N_("Eigene Zähler")}

ALLE = "alle"
_fahrzeug = ContextVar("fahrzeug", default=None)   # id, ALLE oder None (= Hauptfahrzeug)


def _roh(key):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT value FROM einstellungen WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


# Fahrzeugstatus (Modus, Hauptfahrzeug, Liste, Struktur-Stand) wird bei fast jeder Abfrage
# gebraucht – gepuffert. Geleert bei jeder eigenen Schreiboperation (_geaendert) und sobald
# sich die Datei aendert (z.B. Wiederherstellen eines Backups: neue Datei, neuer Inode).
_puffer: dict = {}


def _geaendert():
    _puffer.clear()


def _status() -> dict:
    try:
        st = os.stat(DB_PATH)
        schluessel_datei = (DB_PATH, st.st_ino, st.st_mtime_ns, st.st_size)
    except OSError:
        schluessel_datei = None
    if schluessel_datei is not None and _puffer.get("datei") == schluessel_datei:
        return _puffer["status"]
    with closing(get_connection()) as conn:
        werte = {r["key"]: r["value"] for r in conn.execute(
            "SELECT key, value FROM einstellungen WHERE key IN "
            "('mehrere_fahrzeuge', 'hauptfahrzeug', 'schema_version', 'sprache') "
            "OR key='fahrzeug_name' OR key LIKE 'fahrzeug_name@%'").fetchall()}
        try:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM fahrzeug ORDER BY sortierung, id").fetchall()]
        except sqlite3.OperationalError:          # vor init_db
            rows = [{"id": 1, "aktiv": 1, "sortierung": 1}]
    try:
        stand = int(werte.get("schema_version") or 0)
    except ValueError:
        stand = 0
    try:
        haupt = int(werte.get("hauptfahrzeug") or 1)
    except ValueError:
        haupt = 1
    for f in rows:
        f["name"] = (werte.get("fahrzeug_name" if f["id"] == 1 else f"fahrzeug_name@{f['id']}")
                     or f"Fahrzeug {f['id']}")
        f["aktiv"] = bool(f["aktiv"])
    status = {"stand": stand, "haupt": haupt, "fahrzeuge": rows,
              "sprache": "en" if werte.get("sprache") == "en" else "de",
              # Mehrere nur mit umgebauten Tabellen (Stand 3) – sonst waeren Monate verschiedener
              # Fahrzeuge nicht unterscheidbar (z.B. nach dem Import fremder Einstellungen)
              "mehrere": werte.get("mehrere_fahrzeuge") == "1" and stand >= 3}
    if schluessel_datei is not None:
        _puffer.update(datei=schluessel_datei, status=status)
    return status


def sprache() -> str:
    """Sprache der Oberflaeche und Berichte: "de" (Standard) oder "en" (siehe i18n.py)."""
    return _status()["sprache"]


def mehrere_fahrzeuge() -> bool:
    """Schalter in den Einstellungen; aus = Oberflaeche und Rechnung wie bei einem Auto."""
    return _status()["mehrere"]


def hauptfahrzeug() -> int:
    return _status()["haupt"]


def fahrzeuge(alle: bool = False) -> list:
    """Fahrzeuge mit Name, sortiert. alle=False: nur die sichtbaren – bei einem
    Fahrzeug das Hauptfahrzeug, sonst die aktiven (eingeblendeten)."""
    rows = [dict(f) for f in _status()["fahrzeuge"]]
    if alle:
        return rows
    if not mehrere_fahrzeuge():
        haupt = hauptfahrzeug()
        return [f for f in rows if f["id"] == haupt] or rows[:1]
    return [f for f in rows if f["aktiv"]]


def sichtbare_ids() -> list:
    return [f["id"] for f in fahrzeuge()]


def aktuelles_fahrzeug() -> int | None:
    """Gewaehltes Fahrzeug der Anfrage bzw. des Laufs; None = alle sichtbaren (Gesamtsicht).
    Bei einem Fahrzeug immer das Hauptfahrzeug.

    Ein im Programm ausdruecklich gesetztes Fahrzeug (fahrzeug_kontext mit id) gilt immer –
    auch ausgeblendet –, sonst landeten Daten beim falschen Fahrzeug. Nur die Auswahl der
    Nutzerin/des Nutzers (Cookie) faellt bei einem ausgeblendeten Fahrzeug zurueck."""
    wert = _fahrzeug.get()
    if isinstance(wert, tuple):          # ("fest", id) aus fahrzeug_kontext
        return wert[1]
    if not mehrere_fahrzeuge():
        return hauptfahrzeug()
    ids = sichtbare_ids()
    if wert == ALLE:
        return None if len(ids) > 1 else (ids[0] if ids else hauptfahrzeug())
    if isinstance(wert, int) and wert in ids:
        return wert
    haupt = hauptfahrzeug()
    return haupt if haupt in ids else (ids[0] if ids else haupt)


def setze_fahrzeug(wert):
    """Fahrzeug fuer den laufenden Kontext setzen (id, ALLE oder None)."""
    return _fahrzeug.set(wert)


@contextmanager
def fahrzeug_kontext(wert):
    """Fahrzeug fuer einen Programmabschnitt: id (gilt fest, auch ausgeblendet) oder ALLE."""
    token = _fahrzeug.set(("fest", int(wert)) if isinstance(wert, int) or str(wert).isdigit()
                          else wert)
    try:
        yield
    finally:
        _fahrzeug.reset(token)


def _ids() -> list:
    """Fahrzeug-ids, auf die sich Abfragen gerade beziehen."""
    fid = aktuelles_fahrzeug()
    return [fid] if fid is not None else sichtbare_ids()


def _filter(spalte="fahrzeug_id") -> tuple:
    ids = _ids()
    return f"{spalte} IN ({','.join('?' * len(ids))})", ids


def schreib_fahrzeug(fid=None) -> int:
    """Fahrzeug fuer neue Zeilen: angegeben, sonst das aktuelle bzw. Hauptfahrzeug."""
    if fid:
        return int(fid)
    return aktuelles_fahrzeug() or hauptfahrzeug()


def schluessel(key: str, fid: int | None = None) -> str:
    """Gespeicherter Schluessel einer Einstellung fuer ein Fahrzeug."""
    if key not in FAHRZEUG_SCHLUESSEL:
        return key
    fid = fid or aktuelles_fahrzeug() or hauptfahrzeug()
    return key if fid == 1 else f"{key}@{fid}"


def heimladung_modus(fid: int | None = None) -> str:
    m = _roh(schluessel("heimladung", fid))
    return m if m in HEIMLADUNG_MODI else "km"


def fahrzeug_anlegen(name: str, vorlage: int | None = None) -> int:
    """Neues Fahrzeug; Vergleichswerte (Verbrenner, CO2, Verbrauch) vom Vorlage-Fahrzeug,
    Sensoren, Steuer und Bild leer – nie die eines anderen Autos."""
    vorlage = vorlage or hauptfahrzeug()
    with closing(get_connection()) as conn:
        neu = (conn.execute("SELECT MAX(id) FROM fahrzeug").fetchone()[0] or 0) + 1
        sort = (conn.execute("SELECT MAX(sortierung) FROM fahrzeug").fetchone()[0] or 0) + 1
        conn.execute("INSERT INTO fahrzeug (id, aktiv, sortierung) VALUES (?,1,?)", (neu, sort))
        werte = {"fahrzeug_name": name.strip() or f"Fahrzeug {neu}", "heimladung": "km",
                 "kfz_steuer_benziner": "0.0", "kfz_steuer_eauto": "0.0"}
        for key in ("kraftstoff", "benziner_verbrauch", "ev_verbrauch_default",
                    "co2_faktor_benzin", "akku_kapazitaet_kwh", "lade_min_anstieg"):
            row = conn.execute("SELECT value FROM einstellungen WHERE key=?",
                               (schluessel(key, vorlage),)).fetchone()
            if row:
                werte[key] = row[0]
        for key in FAHRZEUG_SCHLUESSEL - set(werte):
            werte[key] = ""
        for key, val in werte.items():
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES (?,?)",
                         (schluessel(key, neu), str(val)))
        conn.commit()
    return neu


def fahrzeug_aktiv(fid: int, aktiv: bool):
    with closing(get_connection()) as conn:
        conn.execute("UPDATE fahrzeug SET aktiv=? WHERE id=?", (1 if aktiv else 0, fid))
        conn.commit()


def fahrzeug_zeilen(fid: int) -> dict:
    """Datensaetze eines Fahrzeugs je Tabelle (fuer die Rueckfrage beim Loeschen)."""
    with closing(get_connection()) as conn:
        erg = {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE fahrzeug_id=?", (fid,)).fetchone()[0]
               for t in FAHRZEUG_TABELLEN}
        erg["versicherung"] = conn.execute(
            "SELECT COUNT(*) FROM versicherung WHERE fahrzeug_id=?", (fid,)).fetchone()[0]
    return erg


def fahrzeug_loeschen(fid: int) -> dict:
    """Loescht ein Fahrzeug mit allen Daten – nur als ausdrueckliche Aktion (die
    Web-Oberflaeche legt vorher eine Sicherung an). Das Hauptfahrzeug und das letzte
    Fahrzeug lassen sich nicht loeschen."""
    if fid == hauptfahrzeug():
        raise ValueError("Das Hauptfahrzeug lässt sich nicht löschen.")
    if len(fahrzeuge(alle=True)) <= 1:
        raise ValueError("Das letzte Fahrzeug lässt sich nicht löschen.")
    vorher = fahrzeug_zeilen(fid)
    with closing(get_connection()) as conn:
        for t in FAHRZEUG_TABELLEN:
            conn.execute(f"DELETE FROM {t} WHERE fahrzeug_id=?", (fid,))
        conn.execute("DELETE FROM versicherung WHERE fahrzeug_id=?", (fid,))
        conn.execute("UPDATE ladetarif SET fahrzeug_id=NULL WHERE fahrzeug_id=?", (fid,))
        conn.execute("DELETE FROM einstellungen WHERE key LIKE ?", (f"%@{fid}",))
        conn.execute("DELETE FROM fahrzeug WHERE id=?", (fid,))
        conn.commit()
    return vorher


def schema_stand() -> int:
    return _status()["stand"]


def _summen(conn) -> dict:
    """Zeilen und Summen der umzubauenden Tabellen – Pruefung vor/nach dem Umbau."""
    return {
        "fahrten": tuple(conn.execute(
            "SELECT COUNT(*), TOTAL(km), TOTAL(fahrzeug_id) FROM fahrten_monat").fetchone()),
        "akku": tuple(conn.execute(
            "SELECT COUNT(*), TOTAL(km), TOTAL(kwh), TOTAL(fahrzeug_id) FROM akku_abschnitt").fetchone()),
    }


def struktur_mehrere_fahrzeuge(_fehler_nach: str | None = None) -> bool:
    """Baut fahrten_monat (eindeutig je Fahrzeug und Monat) und akku_abschnitt
    (Schluessel Fahrzeug + Startzeit) um und setzt den Struktur-Stand auf 3.

    Alles in einer Transaktion; danach werden Zeilenzahl und Summen verglichen –
    bei einer Abweichung oder einem Fehler wird alles zurueckgerollt (Ausnahme).
    Rueckgabe: True, wenn umgebaut wurde, False, wenn schon geschehen.
    _fehler_nach: nur fuer Tests – Fehler nach diesem Schritt erzwingen."""
    if schema_stand() >= 3:
        return False
    conn = get_connection()
    conn.isolation_level = None          # Transaktion selbst steuern (DDL eingeschlossen)
    try:
        conn.execute("BEGIN IMMEDIATE")
        vorher = _summen(conn)
        conn.execute("""CREATE TABLE fahrten_monat_neu (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            monat TEXT NOT NULL,
                            km REAL NOT NULL,
                            fahrzeug_id INTEGER NOT NULL DEFAULT 1,
                            UNIQUE (fahrzeug_id, monat))""")
        conn.execute("""INSERT INTO fahrten_monat_neu (id, monat, km, fahrzeug_id)
                        SELECT id, monat, km, fahrzeug_id FROM fahrten_monat""")
        conn.execute("DROP TABLE fahrten_monat")
        conn.execute("ALTER TABLE fahrten_monat_neu RENAME TO fahrten_monat")
        if _fehler_nach == "fahrten":
            raise RuntimeError("Testfehler nach dem Umbau von fahrten_monat")
        conn.execute("""CREATE TABLE akku_abschnitt_neu (
                            start TEXT NOT NULL,
                            ende TEXT NOT NULL,
                            soc_start REAL NOT NULL,
                            soc_ende REAL NOT NULL,
                            km_start REAL NOT NULL,
                            km_ende REAL NOT NULL,
                            kwh REAL NOT NULL,
                            km REAL NOT NULL,
                            laufend INTEGER NOT NULL DEFAULT 0,
                            fahrzeug_id INTEGER NOT NULL DEFAULT 1,
                            PRIMARY KEY (fahrzeug_id, start))""")
        conn.execute("""INSERT INTO akku_abschnitt_neu
                        SELECT start, ende, soc_start, soc_ende, km_start, km_ende, kwh, km,
                               laufend, fahrzeug_id FROM akku_abschnitt""")
        conn.execute("DROP TABLE akku_abschnitt")
        conn.execute("ALTER TABLE akku_abschnitt_neu RENAME TO akku_abschnitt")
        nachher = _summen(conn)
        if nachher != vorher:
            raise RuntimeError(f"Prüfsummen weichen ab: {vorher} → {nachher}")
        conn.execute("UPDATE einstellungen SET value='3' WHERE key='schema_version'")
        conn.execute("COMMIT")
        return True
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


# --- Einstellungen ---
# Schluessel aus FAHRZEUG_SCHLUESSEL beziehen sich auf das aktuelle Fahrzeug (siehe oben).
def get_einstellung(key):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT value FROM einstellungen WHERE key=?",
                           (schluessel(key),)).fetchone()
    if row is None:
        return None
    try:
        return float(row["value"])
    except ValueError:
        return None


def get_einstellung_str(key):
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT value FROM einstellungen WHERE key=?",
                           (schluessel(key),)).fetchone()
    return row["value"] if row else None


def set_einstellung(key, value):
    with closing(get_connection()) as conn:
        conn.execute("INSERT OR REPLACE INTO einstellungen VALUES (?,?)",
                     (schluessel(key), str(value)))
        conn.commit()


def _werte(keys: list) -> dict:
    """{schluessel_ohne_fahrzeug: wert} fuer das aktuelle Fahrzeug, eine Abfrage."""
    echt = {schluessel(k): k for k in keys}
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT key, value FROM einstellungen WHERE key IN ({','.join('?' * len(echt))})",
            list(echt)).fetchall()
    return {echt[r["key"]]: r["value"] for r in rows}


def get_config() -> dict:
    """Gibt alle häufig genutzten Konfigurationswerte als dict zurück (eine DB-Abfrage)."""
    keys = ["benziner_verbrauch", "ev_verbrauch_default", "pv_preis_ct",
            "co2_faktor_benzin", "co2_strommix", "ha_aktiv", "kraftstoff",
            "simulation", "sim_anteil_pv", "sim_anteil_netz", "sim_anteil_oeffentlich",
            "sim_preis_oeffentlich", "sim_ladeverlust"]
    m = _werte(keys)
    return {
        "benziner_verbrauch": float(m.get("benziner_verbrauch") or 7.0),
        "ev_verbrauch":       float(m.get("ev_verbrauch_default") or 15.0),
        "pv_preis_ct":        float(m.get("pv_preis_ct") or 13.0),
        "co2_faktor_benzin":  float(m.get("co2_faktor_benzin") or 2.37),
        "co2_strommix":       float(m.get("co2_strommix") or 401.0),
        "ha_aktiv":           m.get("ha_aktiv") == "1",
        # Vergleichsfahrzeug: "benzin", "diesel" oder "autogas" (nur Beschriftung und
        # CO2-Standard; die Liste steht in berechnung.KRAFTSTOFFE)
        "kraftstoff":         m.get("kraftstoff") or "benzin",
        # Simulationsmodus: noch kein E-Auto – Ladungen werden aus den km gerechnet
        # (berechnung.simulierte_ladungen), nichts davon wird gespeichert
        "simulation":             m.get("simulation") == "1",
        "sim_anteil_pv":          _zahl(m.get("sim_anteil_pv"), 30.0),
        "sim_anteil_netz":        _zahl(m.get("sim_anteil_netz"), 60.0),
        "sim_anteil_oeffentlich": _zahl(m.get("sim_anteil_oeffentlich"), 10.0),
        "sim_preis_oeffentlich":  _zahl(m.get("sim_preis_oeffentlich"), 55.0),
        "sim_ladeverlust":        _zahl(m.get("sim_ladeverlust"), 10.0),
    }


def _zahl(wert, standard: float) -> float:
    """Gespeicherte Zahl oder Standard – 0 ist ein gueltiger Wert (z.B. 0 % PV)."""
    try:
        return float(wert)
    except (TypeError, ValueError):
        return standard


# Nie aus einer Einstellungsdatei uebernehmen: beschreibt die Datenbank, nicht die Wahl
NICHT_IMPORTIEREN = {"schema_version"}


def get_fahrzeug_liste_roh() -> list:
    """Fahrzeugtabelle fuer den Einstellungs-Export."""
    with closing(get_connection()) as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM fahrzeug ORDER BY id")]


def set_fahrzeug_liste_roh(liste: list) -> int:
    """Fahrzeuge aus einem Einstellungs-Export ergaenzen (vorhandene bleiben). Anzahl neu."""
    neu = 0
    with closing(get_connection()) as conn:
        for f in liste or []:
            try:
                fid = int(f.get("id"))
            except (TypeError, ValueError):
                continue
            cur = conn.execute("INSERT OR IGNORE INTO fahrzeug (id, aktiv, sortierung) VALUES (?,?,?)",
                               (fid, 1 if f.get("aktiv", 1) else 0, int(f.get("sortierung") or fid)))
            neu += cur.rowcount
        conn.commit()
    return neu


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
def set_fahrt_monat(monat, km, fahrzeug_id=None):
    fid = schreib_fahrzeug(fahrzeug_id)
    with closing(get_connection()) as conn:
        # vor dem Umbau ist monat allein eindeutig – dann gibt es nur Fahrzeug 1
        conn.execute("DELETE FROM fahrten_monat WHERE monat=? AND fahrzeug_id=?", (monat, fid))
        conn.execute("INSERT OR REPLACE INTO fahrten_monat (monat, km, fahrzeug_id) VALUES (?,?,?)",
                     (monat, km, fid))
        conn.commit()


def get_fahrten_monate():
    """km je Monat; in der Gesamtsicht ueber die Fahrzeuge summiert."""
    f, p = _filter()
    with closing(get_connection()) as conn:
        rows = conn.execute(f"""SELECT MIN(id) AS id, monat, SUM(km) AS km FROM fahrten_monat
                                WHERE {f} GROUP BY monat ORDER BY monat DESC""", p).fetchall()
    return [dict(r) for r in rows]


def get_fahrten_je_fahrzeug() -> dict:
    """{fahrzeug_id: {monat: km}} aller Fahrzeuge – fuer die Aufteilung nach km."""
    erg = {}
    with closing(get_connection()) as conn:
        for r in conn.execute("SELECT fahrzeug_id, monat, km FROM fahrten_monat"):
            erg.setdefault(r["fahrzeug_id"], {})[r["monat"]] = r["km"]
    return erg


def delete_fahrt_monat(monat, fahrzeug_id=None):
    fid = schreib_fahrzeug(fahrzeug_id)
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM fahrten_monat WHERE monat=? AND fahrzeug_id=?", (monat, fid))
        conn.commit()


def get_fahrten_gesamt_km():
    f, p = _filter()
    with closing(get_connection()) as conn:
        row = conn.execute(f"SELECT SUM(km) as total FROM fahrten_monat WHERE {f}", p).fetchone()
    return row["total"] or 0.0


def get_fahrten_alle_als_liste():
    """Kompatibilität für Charts: gibt Liste mit datum+km zurück"""
    f, p = _filter()
    with closing(get_connection()) as conn:
        rows = conn.execute(f"""SELECT monat as datum, SUM(km) AS km FROM fahrten_monat
                                WHERE {f} GROUP BY monat ORDER BY monat""", p).fetchall()
    return [dict(r) for r in rows]


# --- Laden ---
def add_ladevorgang(datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw, ladetyp,
                    notiz="", blockiergebuehr=None, fahrzeug_id=None):
    """gesamtpreis enthaelt eine Blockiergebuehr bereits; das Feld schluesselt sie nur auf."""
    with closing(get_connection()) as conn:
        conn.execute("""
            INSERT INTO ladevorgang (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw,
                                     ladetyp, notiz, blockiergebuehr, fahrzeug_id)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw, ladetyp, notiz,
              blockiergebuehr, schreib_fahrzeug(fahrzeug_id)))
        conn.commit()


def get_ladevorgang(id):
    """Einzelnen Ladevorgang laden (fuer die Bearbeitung)."""
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM ladevorgang WHERE id=?", (id,)).fetchone()
    return dict(row) if row else None


def update_ladevorgang(id, datum, menge_kwh, preis_kwh, gesamtpreis, anbieter,
                       ladeleistung_kw, ladetyp, notiz="", blockiergebuehr=None, fahrzeug_id=None):
    """Aendert einen bestehenden Ladevorgang (Fahrzeug nur, wenn angegeben)."""
    with closing(get_connection()) as conn:
        conn.execute("""
            UPDATE ladevorgang
               SET datum=?, menge_kwh=?, preis_kwh=?, gesamtpreis=?, anbieter=?,
                   ladeleistung_kw=?, ladetyp=?, notiz=?, blockiergebuehr=?,
                   fahrzeug_id=COALESCE(?, fahrzeug_id)
             WHERE id=?
        """, (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter,
              ladeleistung_kw, ladetyp, notiz, blockiergebuehr,
              int(fahrzeug_id) if fahrzeug_id else None, id))
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
    f, p = _filter()
    with closing(get_connection()) as conn:
        row = conn.execute(f"""
            SELECT 1 FROM ladevorgang
            WHERE datum=? AND anbieter=? AND ABS(menge_kwh - ?) < 0.001 AND {f}
            LIMIT 1
        """, (datum, anbieter, menge_kwh, *p)).fetchone()
    return row is not None


def get_ladevorgaenge(limit=500):
    f, p = _filter()
    with closing(get_connection()) as conn:
        rows = conn.execute(f"SELECT * FROM ladevorgang WHERE {f} ORDER BY datum DESC LIMIT ?",
                            (*p, limit)).fetchall()
    return [dict(r) for r in rows]


def delete_ladevorgang(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM ladevorgang WHERE id=?", (id,))
        conn.commit()


def get_lade_gesamt():
    f, p = _filter()
    with closing(get_connection()) as conn:
        row = conn.execute(f"SELECT SUM(menge_kwh) as kwh, SUM(gesamtpreis) as kosten "
                           f"FROM ladevorgang WHERE {f}", p).fetchone()
    return row["kwh"] or 0.0, row["kosten"] or 0.0


AUTO_NOTIZ = "Auto-Import HA"


def upsert_auto_ladevorgang(datum, menge_kwh, preis_kwh, gesamtpreis, anbieter,
                            notiz=AUTO_NOTIZ, fahrzeug_id=None):
    """Legt einen automatisch importierten Ladevorgang an oder aktualisiert ihn.

    Erkennungsmerkmal ist Datum + Anbieter + die Notiz `AUTO_NOTIZ` (die `notiz`
    beginnt immer damit, z.B. mit Zusatz fuer den dynamischen Tarif); manuell
    erfasste Vorgaenge bleiben davon unberuehrt.
    Rueckgabe: "neu", "aktualisiert" oder "unveraendert".
    """
    fid = schreib_fahrzeug(fahrzeug_id)
    with closing(get_connection()) as conn:
        row = conn.execute(
            """SELECT id, menge_kwh, preis_kwh, notiz FROM ladevorgang
               WHERE datum=? AND anbieter=? AND notiz LIKE ? AND fahrzeug_id=?""",
            (datum, anbieter, AUTO_NOTIZ + "%", fid)).fetchone()
        if row:
            if (abs((row["menge_kwh"] or 0) - menge_kwh) < 0.01
                    and abs((row["preis_kwh"] or 0) - (preis_kwh or 0)) < 0.001
                    and row["notiz"] == notiz):
                return "unveraendert"
            conn.execute(
                """UPDATE ladevorgang
                   SET menge_kwh=?, preis_kwh=?, gesamtpreis=?, notiz=? WHERE id=?""",
                (menge_kwh, preis_kwh, gesamtpreis, notiz, row["id"]))
            conn.commit()
            return "aktualisiert"
        conn.execute(
            """INSERT INTO ladevorgang (datum, menge_kwh, preis_kwh, gesamtpreis,
                                        anbieter, ladeleistung_kw, ladetyp, notiz, fahrzeug_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, 11, "AC", notiz, fid))
        conn.commit()
        return "neu"


def delete_auto_ladevorgang(datum, anbieter, fahrzeug_id=None) -> bool:
    """Entfernt die automatisch importierte Monatssumme (Notiz beginnt mit AUTO_NOTIZ) –
    wenn Einzelladungen aus HA den Monat schon ganz abdecken. True, wenn es eine gab."""
    with closing(get_connection()) as conn:
        n = conn.execute("DELETE FROM ladevorgang WHERE datum=? AND anbieter=? AND notiz LIKE ? "
                         "AND fahrzeug_id=?",
                         (datum, anbieter, AUTO_NOTIZ + "%", schreib_fahrzeug(fahrzeug_id))).rowcount
        conn.commit()
    return n > 0


def upsert_extern_ladevorgang(extern_id, datum, menge_kwh, preis_kwh, gesamtpreis, anbieter,
                              ladeleistung_kw, notiz, fahrzeug_id=None):
    """Ladung, die Home Assistant geschickt hat: anlegen oder – beim erneuten Senden
    derselben Ladung (gleiche extern_id) – aktualisieren.
    Rueckgabe: ("neu" | "aktualisiert" | "unveraendert", id)."""
    werte = (datum, menge_kwh, preis_kwh, gesamtpreis, anbieter, ladeleistung_kw, notiz)
    with closing(get_connection()) as conn:
        row = conn.execute("""SELECT id, datum, menge_kwh, preis_kwh, gesamtpreis, anbieter,
                                     ladeleistung_kw, notiz
                              FROM ladevorgang WHERE extern_id=?""", (extern_id,)).fetchone()
        if row:
            if tuple(row)[1:] == werte:
                return "unveraendert", row["id"]
            conn.execute("""UPDATE ladevorgang SET datum=?, menge_kwh=?, preis_kwh=?, gesamtpreis=?,
                                   anbieter=?, ladeleistung_kw=?, notiz=? WHERE id=?""",
                         (*werte, row["id"]))
            conn.commit()
            return "aktualisiert", row["id"]
        cur = conn.execute("""INSERT INTO ladevorgang (datum, menge_kwh, preis_kwh, gesamtpreis,
                                  anbieter, ladeleistung_kw, notiz, ladetyp, extern_id, fahrzeug_id)
                              VALUES (?,?,?,?,?,?,?,?,?,?)""",
                           (*werte, "AC", extern_id, schreib_fahrzeug(fahrzeug_id)))
        conn.commit()
        return "neu", cur.lastrowid


def summe_extern(monat: str, anbieter: str, fahrzeug_ids: list | None = None) -> tuple:
    """(kWh, €) der von HA geschickten Ladungen eines Monats 'YYYY-MM' und Anbieters
    (fahrzeug_ids: diese Fahrzeuge, sonst die des aktuellen Kontexts)."""
    ids = list(fahrzeug_ids) if fahrzeug_ids is not None else _ids()
    with closing(get_connection()) as conn:
        row = conn.execute(f"""SELECT COALESCE(SUM(menge_kwh), 0) AS kwh,
                                     COALESCE(SUM(gesamtpreis), 0) AS kosten
                              FROM ladevorgang WHERE extern_id IS NOT NULL
                                AND anbieter=? AND substr(datum, 1, 7)=?
                                AND fahrzeug_id IN ({','.join('?' * len(ids))})""",
                           (anbieter, monat, *ids)).fetchone()
    return row["kwh"], row["kosten"]


def get_ladevorgaenge_zeitraum(von: str, bis: str):
    """Ladevorgaenge zwischen zwei Datumsangaben (YYYY-MM-DD, inklusive)."""
    f, p = _filter()
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT * FROM ladevorgang WHERE datum >= ? AND datum <= ? AND {f} ORDER BY datum",
            (von, bis, *p)).fetchall()
    return [dict(r) for r in rows]


def ersetze_akku_abschnitte(ab: str | None, abschnitte: list, fahrzeug_id=None):
    """Ersetzt alle Abschnitte des Fahrzeugs ab Startzeit `ab` (None = alle) durch die neuen."""
    fid = schreib_fahrzeug(fahrzeug_id)
    with closing(get_connection()) as conn:
        if ab is None:
            conn.execute("DELETE FROM akku_abschnitt WHERE fahrzeug_id=?", (fid,))
        else:
            conn.execute("DELETE FROM akku_abschnitt WHERE start >= ? AND fahrzeug_id=?", (ab, fid))
        conn.executemany(
            """INSERT OR REPLACE INTO akku_abschnitt
               (start, ende, soc_start, soc_ende, km_start, km_ende, kwh, km, laufend, fahrzeug_id)
               VALUES (:start, :ende, :soc_start, :soc_ende, :km_start, :km_ende,
                       :kwh, :km, :laufend, :fahrzeug_id)""",
            [{**a, "fahrzeug_id": fid} for a in abschnitte])
        conn.commit()


def get_akku_abschnitte(limit: int | None = None):
    """Fahrtabschnitte aus dem Akkustand, neueste zuerst."""
    f, p = _filter()
    sql = f"SELECT * FROM akku_abschnitt WHERE {f} ORDER BY start DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    with closing(get_connection()) as conn:
        return [dict(r) for r in conn.execute(sql, p).fetchall()]


def get_thg_zeitraum(von: str, bis: str):
    """THG-Eintraege zwischen zwei Datumsangaben (inklusive)."""
    f, p = _filter()
    with closing(get_connection()) as conn:
        rows = conn.execute(
            f"SELECT * FROM thg_quote WHERE datum >= ? AND datum <= ? AND {f} ORDER BY datum",
            (von, bis, *p)).fetchall()
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
                    "fremd_ab_ct", "fremd_max_ct", "ladekarte_eur", "notiz", "fahrzeug_id",
                    "nur_vergleich"]


def add_ladetarif(werte: dict):
    with closing(get_connection()) as conn:
        conn.execute(
            f"INSERT INTO ladetarif ({','.join(LADETARIF_FELDER)}) "
            f"VALUES ({','.join('?' * len(LADETARIF_FELDER))})",
            [werte.get(f) for f in LADETARIF_FELDER])
        conn.commit()


def _aenderbar(felder: list, werte: dict) -> list:
    """Felder fuer ein UPDATE – fahrzeug_id nur, wenn sie ausdruecklich angegeben ist
    (sonst bliebe ein Formular ohne Fahrzeugauswahl nicht ohne Folgen)."""
    return [f for f in felder if f != "fahrzeug_id" or "fahrzeug_id" in werte]


def update_ladetarif(id, werte: dict):
    felder = _aenderbar(LADETARIF_FELDER, werte)
    with closing(get_connection()) as conn:
        conn.execute(
            f"UPDATE ladetarif SET {','.join(f + '=?' for f in felder)} WHERE id=?",
            [werte.get(f) for f in felder] + [id])
        conn.commit()


def get_ladetarife(vergleich: bool | None = False):
    """Eintraege, aelteste zuerst je Anbieter/Tarif. vergleich=False: nur die eigenen
    Abos (Standard – nur sie kosten Grundgebuehr und belegen Preise vor), True: nur die
    Vergleichstarife, None: alle."""
    bedingung = "" if vergleich is None else         f"WHERE COALESCE(nur_vergleich, 0) = {1 if vergleich else 0}"
    with closing(get_connection()) as conn:
        rows = conn.execute(f"""SELECT * FROM ladetarif {bedingung}
                                ORDER BY anbieter, tarif_name, gueltig_ab""").fetchall()
    return [dict(r) for r in rows]


def get_ladetarif_am(anbieter, datum):
    """Der am Datum gueltige Tarif des Anbieters (juengster gueltig_ab <= datum)."""
    with closing(get_connection()) as conn:
        row = conn.execute("""
            SELECT * FROM ladetarif
             WHERE anbieter=? AND gueltig_ab <= ? AND COALESCE(nur_vergleich, 0) = 0
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
    felder = INSTANDHALTUNG_FELDER + ["fahrzeug_id"]
    werte = {**werte, "fahrzeug_id": schreib_fahrzeug(werte.get("fahrzeug_id"))}
    with closing(get_connection()) as conn:
        conn.execute(
            f"INSERT INTO instandhaltung ({','.join(felder)}) "
            f"VALUES ({','.join('?' * len(felder))})",
            [werte.get(f) for f in felder])
        conn.commit()


def update_instandhaltung(id, werte: dict):
    with closing(get_connection()) as conn:
        conn.execute(
            f"UPDATE instandhaltung SET {','.join(f + '=?' for f in INSTANDHALTUNG_FELDER)}, "
            f"fahrzeug_id=COALESCE(?, fahrzeug_id) WHERE id=?",
            [werte.get(f) for f in INSTANDHALTUNG_FELDER]
            + [int(werte["fahrzeug_id"]) if werte.get("fahrzeug_id") else None, id])
        conn.commit()


def get_instandhaltung():
    f, p = _filter()
    with closing(get_connection()) as conn:
        rows = conn.execute(f"SELECT * FROM instandhaltung WHERE {f} ORDER BY datum DESC, id DESC",
                            p).fetchall()
    return [dict(r) for r in rows]


def delete_instandhaltung(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM instandhaltung WHERE id=?", (id,))
        conn.commit()


# --- Versicherung ---
VERSICHERUNG_FELDER = ["fahrzeug", "gesellschaft", "tarif_name", "gueltig_ab", "gueltig_bis",
                       "deckung", "sf_haftpflicht", "sf_kasko", "jahreslaufleistung", "sb_teilkasko", "sb_vollkasko",
                       "grundbeitrag", "fahrerschutz", "werkstattbindung", "auslandsschutz",
                       "schutzbrief", "sonstige_zusatz", "notiz", "fahrzeug_id"]


def add_versicherung(werte: dict):
    werte = {**werte, "fahrzeug_id": schreib_fahrzeug(werte.get("fahrzeug_id"))}
    with closing(get_connection()) as conn:
        conn.execute(
            f"INSERT INTO versicherung ({','.join(VERSICHERUNG_FELDER)}) "
            f"VALUES ({','.join('?' * len(VERSICHERUNG_FELDER))})",
            [werte.get(f) for f in VERSICHERUNG_FELDER])
        conn.commit()


def update_versicherung(id, werte: dict):
    felder = _aenderbar(VERSICHERUNG_FELDER, werte)
    with closing(get_connection()) as conn:
        conn.execute(
            f"UPDATE versicherung SET {','.join(f + '=?' for f in felder)} "
            f"WHERE id=?",
            [werte.get(f) for f in felder] + [id])
        conn.commit()


def get_versicherungen():
    """Vertraege des aktuellen Fahrzeugs. Bei einem Fahrzeug und in der Gesamtsicht alle –
    auch die frueherer Autos ohne Zuordnung (fahrzeug_id NULL), wie vor 3.0."""
    if not mehrere_fahrzeuge() or aktuelles_fahrzeug() is None:
        where, p = "1", []
    else:
        where, p = "fahrzeug_id=?", [aktuelles_fahrzeug()]
    with closing(get_connection()) as conn:
        rows = conn.execute(f"""SELECT * FROM versicherung WHERE {where}
                               ORDER BY fahrzeug, gueltig_ab""", p).fetchall()
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
def add_thg(datum, betrag, anbieter, notiz="", fahrzeug_id=None):
    with closing(get_connection()) as conn:
        conn.execute("INSERT INTO thg_quote (datum, betrag, anbieter, notiz, fahrzeug_id) "
                     "VALUES (?,?,?,?,?)",
                     (datum, betrag, anbieter, notiz, schreib_fahrzeug(fahrzeug_id)))
        conn.commit()


def get_thg_eintraege():
    f, p = _filter()
    with closing(get_connection()) as conn:
        rows = conn.execute(f"SELECT * FROM thg_quote WHERE {f} ORDER BY datum DESC", p).fetchall()
    return [dict(r) for r in rows]


def delete_thg(id):
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM thg_quote WHERE id=?", (id,))
        conn.commit()


def get_thg_gesamt():
    f, p = _filter()
    with closing(get_connection()) as conn:
        row = conn.execute(f"SELECT SUM(betrag) as total FROM thg_quote WHERE {f}", p).fetchone()
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
    "fahrten": ("fahrten_monat",  N_("Gefahrene Kilometer (monatlich)")),
    "laden":   ("ladevorgang",    N_("Ladevorgänge")),
    "benzin":  ("benzinpreis",    N_("Benzinpreise")),
    "akku":    ("akku_abschnitt", N_("Fahrtabschnitte aus dem Akkustand")),
    "thg":     ("thg_quote",      N_("THG-Einträge")),
}


def zaehle_messdaten() -> dict:
    """Datensaetze je loeschbarem Bereich: {schluessel: anzahl} – je Fahrzeug-Tabelle nur
    die des aktuellen Fahrzeugs (bzw. aller sichtbaren), ausgeblendete bleiben unberuehrt."""
    f, p = _filter()
    with closing(get_connection()) as conn:
        return {s: conn.execute(f"SELECT COUNT(*) FROM {tabelle}"
                                + (f" WHERE {f}" if tabelle in FAHRZEUG_TABELLEN else ""),
                                p if tabelle in FAHRZEUG_TABELLEN else []).fetchone()[0]
                for s, (tabelle, _) in MESSDATEN_BEREICHE.items()}


def loesche_messdaten(bereiche: list) -> dict:
    """Leert die genannten Bereiche. Rueckgabe: {schluessel: geloeschte Anzahl}.
    Unbekannte Schluessel werden ignoriert – die Tabellennamen kommen nie aus
    der Anfrage, sondern immer aus MESSDATEN_BEREICHE."""
    gewaehlt = [b for b in bereiche if b in MESSDATEN_BEREICHE]
    if not gewaehlt:
        return {}
    vorher = zaehle_messdaten()
    f, p = _filter()
    with closing(get_connection()) as conn:
        for b in gewaehlt:
            tabelle = MESSDATEN_BEREICHE[b][0]
            if tabelle in FAHRZEUG_TABELLEN:
                conn.execute(f"DELETE FROM {tabelle} WHERE {f}", p)
            else:
                conn.execute(f"DELETE FROM {tabelle}")
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
    # Optional: fortlaufender Kostenzaehler (EUR) fuer "Netz ins Auto" – dynamischer Tarif
    "ha_wallbox_cost":           "",
    "ha_tankerkoenig":           "sensor.tankerkoenig_e10_preis",
    "ha_tankerkoenig_2":         "",
    # Friendly Names für InfluxDB-Abfragen
    "fn_odometer":               "Ceed Kilometerstand",
    "fn_pv_production":          "",
    "fn_grid_consumption":       "",
    "fn_grid_export":            "",
    "fn_wallbox_energy":         "",
    "fn_wallbox_cost":           "",
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
    "influx_measurement_eur":    "EUR",
    "influx_measurement_prozent": "%",
    # Tag, ueber den InfluxDB 1.x/2.x den Sensor findet (friendly_name oder entity_id)
    "influx_tag":                "friendly_name",
    # InfluxDB 2.x
    "influx2_url":               "http://localhost:8086",
    "influx2_org":               "",
    "influx2_bucket":            "home_assistant",
    "influx2_token":             "",
    # InfluxDB 3.x (Core/Enterprise): Datenbank = der Bucket aus der HA-Konfiguration
    "influx3_url":               "http://localhost:8181",
    "influx3_database":          "home_assistant",
    "influx3_token":             "",
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
    # Datenquelle: "ha", "influxdb", "influxdb2", "influxdb3", "postgres" oder "prometheus"
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
    if SCHEMA_ZU_NEU:
        return
    with closing(get_connection()) as conn:
        for key, val in MAIL_DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO einstellungen VALUES (?,?)", (key, val))
        conn.commit()


def get_mail_settings() -> dict:
    gefunden = _werte(list(MAIL_DEFAULTS.keys()))
    return {k: gefunden.get(k, MAIL_DEFAULTS[k]) for k in MAIL_DEFAULTS}


def init_ha_settings():
    if SCHEMA_ZU_NEU:
        return
    with closing(get_connection()) as conn:
        for key, val in HA_ENTITY_DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO einstellungen VALUES (?,?)", (key, val))
        conn.commit()


def get_ha_settings(fahrzeug_id=None, eigene_zaehler: bool = False):
    """HA-/Datenbank-Einstellungen; Kilometer- und Akku-Sensoren die des Fahrzeugs
    (Standard: aktuelles). eigene_zaehler=True: statt der gemeinsamen Wallbox die
    eigenen Ladezaehler des Fahrzeugs."""
    keys = list(HA_ENTITY_DEFAULTS.keys())
    kauf = ["erstzulassung", "zulassung_eigen", "km_bei_kauf"]
    if fahrzeug_id is not None:
        with fahrzeug_kontext(int(fahrzeug_id)):
            found = _werte(keys + kauf)
    else:
        found = _werte(keys + kauf)
    erg = {key: found.get(key, HA_ENTITY_DEFAULTS.get(key, "")) for key in keys}
    # Kaufmonat und km-Stand bei Kauf: km im Kaufmonat = Stand am Monatsende − km bei Kauf
    erg["kauf_monat"] = (found.get("zulassung_eigen") or found.get("erstzulassung") or "")[:7]
    try:
        erg["km_bei_kauf"] = float(found.get("km_bei_kauf") or 0)
    except ValueError:
        erg["km_bei_kauf"] = 0.0
    if eigene_zaehler:
        fid = schreib_fahrzeug(fahrzeug_id)
        with closing(get_connection()) as conn:
            for key in WALLBOX_SCHLUESSEL:
                row = conn.execute("SELECT value FROM einstellungen WHERE key=?",
                                   (f"{key}@{fid}",)).fetchone()
                erg[key] = row[0] if row else ""
    return erg


def save_ha_settings(settings: dict):
    """Speichert Einstellungen; Fahrzeug-Schluessel fuer das aktuelle Fahrzeug."""
    with closing(get_connection()) as conn:
        for key, val in settings.items():
            conn.execute("INSERT OR REPLACE INTO einstellungen VALUES (?,?)",
                         (schluessel(key), val))
        conn.commit()


# Nach jeder Aenderung an Einstellungen oder Fahrzeugen den Status-Puffer leeren
def _mit_puffer_leeren(func):
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            _geaendert()
    return wrapper


for _name in ("init_db", "set_einstellung", "set_einstellungen", "save_ha_settings",
              "fahrzeug_anlegen", "fahrzeug_aktiv", "fahrzeug_loeschen",
              "struktur_mehrere_fahrzeuge", "set_fahrzeug_liste_roh", "init_ha_settings",
              "init_mail_settings", "schema_pruefen"):
    globals()[_name] = _mit_puffer_leeren(globals()[_name])
