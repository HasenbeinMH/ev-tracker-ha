# -*- coding: utf-8 -*-
"""
Externe Datenquellen fuer Monatswerte und Stundenverlaeufe – Alternative zur HA-API.

Unterstuetzt (Einstellung "datasource"):
    "influxdb"    InfluxDB 1.x          (InfluxQL, Benutzer/Passwort)
    "influxdb2"   InfluxDB 2.x          (Flux, Organisation/Bucket/Token)
    "postgres"    PostgreSQL/TimescaleDB mit der HA-Integration LTSS
    "prometheus"  Prometheus oder VictoriaMetrics (HA-Integration prometheus)

Jede Quelle beantwortet dieselben Fragen ueber einen Sensor-Schluessel:
    "km"       Kilometerstand            -> Monatsdifferenz
    "pv"       PV ins Auto (kWh)         -> Monatsdifferenz, sonst Summe der Tagesmaxima
    "wallbox"  Netz ins Auto (kWh)       -> wie "pv"
    "benzin"   1–2 Preissensoren (€/L)   -> Monatsmittel ohne Nullwerte
    "soc"      Akkustand (%)             -> Stundenwerte (Akkuverbrauch, Ladeerkennung)

Welcher Sensor dahintersteht, kommt aus den Einstellungen: InfluxDB sucht ueber
einen Tag-Wert (Standard friendly_name, Spalte "Friendly Name") im Measurement der
Einheit, PostgreSQL und Prometheus ueber die Entity-ID (Spalte "Entity-ID (HA)").

Liefert eine Quelle nichts (None bzw. []), faellt der Aufrufer auf die HA-API zurueck.
Jede Quelle muss nur vier Grundfunktionen umsetzen (siehe Datenquelle); Monatsdifferenz,
Tagessummen und Mittelwerte rechnet die Basisklasse daraus.
"""
import base64
import calendar
import csv
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

QUELLEN = {
    "influxdb":   "InfluxDB 1.x",
    "influxdb2":  "InfluxDB 2.x",
    "postgres":   "PostgreSQL / TimescaleDB (LTSS)",
    "prometheus": "Prometheus / VictoriaMetrics",
}

# Zugangsdaten – nicht im Export ohne Zugangsdaten, leeres Feld behaelt den alten Wert
GEHEIM = {"influx_password", "influx2_token", "pg_password", "prom_password"}

# schluessel: (Entity-ID-Felder, Friendly-Name-Felder, Measurement-Feld, Measurement-Standard)
SENSOREN = {
    "km":      (["ha_odometer"], ["fn_odometer"], "influx_measurement_km", "km"),
    "pv":      (["ha_pv_production"], ["fn_pv_production"], "influx_measurement_kwh", "kWh"),
    "wallbox": (["ha_wallbox_energy"], ["fn_wallbox_energy"], "influx_measurement_kwh", "kWh"),
    "benzin":  (["ha_tankerkoenig", "ha_tankerkoenig_2"], ["fn_tankerkoenig", "fn_tankerkoenig_2"],
                "influx_measurement_eur_l", "EUR/L"),
    "soc":     (["ha_ev_battery"], ["fn_ev_battery"], "influx_measurement_prozent", "%"),
}

PROM_SELEKTOR_STANDARD = ('{__name__=~"homeassistant_sensor_.+",'
                          '__name__!~"homeassistant_sensor_(attr_.+|unit_info)",'
                          'entity="{entity}"}')

TIMEOUT = 15
# Plausibilitaet einer Monatsdifferenz (km bzw. kWh) – wie bisher bei InfluxDB 1.x
MAX_DELTA = 100000


def aus_einstellungen(cfg: dict):
    """Die eingestellte Datenquelle, oder None bei "ha" (nur HA-API)."""
    klasse = {"influxdb": InfluxDB1, "influxdb2": InfluxDB2,
              "postgres": PostgresLTSS, "prometheus": Prometheus}.get(cfg.get("datasource"))
    return klasse(cfg) if klasse else None


def _monat(jahr: int, monat: int) -> tuple:
    """Monatsbeginn und Beginn des Folgemonats, Ortszeit (zeitzonenbewusst)."""
    start = datetime(jahr, monat, 1).astimezone()
    j, m = (jahr + 1, 1) if monat == 12 else (jahr, monat + 1)
    return start, datetime(j, m, 1).astimezone()


def _utc(t: datetime) -> datetime:
    return (t if t.tzinfo else t.astimezone()).astimezone(timezone.utc)


def _iso(t: datetime) -> str:
    return _utc(t).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_zeit(wert) -> datetime:
    if isinstance(wert, datetime):
        return wert if wert.tzinfo else wert.replace(tzinfo=timezone.utc)
    if isinstance(wert, (int, float)):
        return datetime.fromtimestamp(wert, tz=timezone.utc)
    s = str(wert).strip().replace("Z", "+00:00")
    # Nanosekunden (InfluxDB) auf Mikrosekunden kuerzen
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _lokal(t: datetime) -> str:
    return t.astimezone().strftime("%Y-%m-%dT%H:%M")


def _http(url: str, daten: bytes | None = None, kopf: dict | None = None,
          user: str = "", passwort: str = "") -> bytes:
    req = urllib.request.Request(url, data=daten, headers=kopf or {})
    if user or passwort:
        cred = base64.b64encode(f"{user}:{passwort}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace")[:200]
        raise ConnectionError(f"HTTP {e.code}: {text or e.reason}")
    except urllib.error.URLError as e:
        raise ConnectionError(f"nicht erreichbar ({e.reason})")


def _url(roh: str, port: str | int | None = None) -> str:
    u = (roh or "").strip().rstrip("/")
    if u and not u.startswith(("http://", "https://")):
        u = "http://" + u
    if port and not re.search(r":\d+$", u):
        u = f"{u}:{port}"
    return u


# ═══════════════════════════════════════════════════════════════════════════════
#  Basisklasse
# ═══════════════════════════════════════════════════════════════════════════════

class Datenquelle:
    """Gemeinsame Logik. Unterklassen setzen um:
        test()                                     -> (ok, text)
        _letzter(schl, kennung, von, bis)          -> letzter Wert in (von, bis] oder None
        _werte(schl, kennung, von, bis)            -> [(datetime, float)] aufsteigend
        _stunden(schl, kennung, von, bis, aggregat) -> [(datetime Stundenbeginn, float)]
    """
    typ = ""
    nutzt_entity_ids = True     # False: InfluxDB mit Friendly Name/Tag

    def __init__(self, cfg: dict):
        self.cfg = cfg

    @property
    def name(self) -> str:
        return QUELLEN[self.typ]

    def kennungen(self, schluessel: str) -> list:
        ent, namen, _, _ = SENSOREN[schluessel]
        felder = ent if self.nutzt_entity_ids else namen
        return [v for v in ((self.cfg.get(f) or "").strip() for f in felder) if v]

    def hat(self, schluessel: str) -> bool:
        return bool(self.kennungen(schluessel))

    # ── Monatswerte ──────────────────────────────────────────────────────────

    def monatswert(self, schluessel: str, jahr: int, monat: int) -> float | None:
        """Monatswert fuer den Import (None = keine Daten, Fehler werden geschluckt)."""
        ids = self.kennungen(schluessel)
        if not ids:
            return None
        try:
            if schluessel == "benzin":
                return self.monat_mittel(schluessel, ids, jahr, monat)
            if schluessel in ("pv", "wallbox"):
                return self.monat_summe(schluessel, ids[0], jahr, monat)
            return self.monat_delta(schluessel, ids[0], jahr, monat)
        except Exception:
            return None

    def monat_delta(self, schl, kennung, jahr, monat) -> float | None:
        """Zaehlerstand am Monatsende minus letzter Stand vor dem Monat (bis 1 Jahr zurueck)."""
        start, ende = _monat(jahr, monat)
        jetzt = self._letzter(schl, kennung, start, ende)
        if jetzt is None:
            return None
        vorher = self._letzter(schl, kennung, start - timedelta(days=366), start)
        if vorher is None:
            return None
        delta = jetzt - vorher
        if delta < 0 or delta > MAX_DELTA:
            return None
        return round(delta, 3)

    def monat_summe(self, schl, kennung, jahr, monat) -> float | None:
        """Differenz wie beim Zaehler; bei taeglich zurueckgesetzten Sensoren (Differenz
        leer oder 0) die Summe der Tagesmaxima."""
        delta = self.monat_delta(schl, kennung, jahr, monat)
        if delta:
            return delta
        start, ende = _monat(jahr, monat)
        tage = {}
        for t, v in self._werte(schl, kennung, start, ende):
            tag = t.astimezone().date()
            tage[tag] = max(tage.get(tag, v), v)
        summe = sum(v for v in tage.values() if v > 0)
        return round(summe, 3) if summe > 0 else None

    def monat_mittel(self, schl, kennungen, jahr, monat) -> float | None:
        """Mittel aller Werte > 0 ueber alle Sensoren (Tankstelle nachts geschlossen = 0)."""
        start, ende = _monat(jahr, monat)
        alle = []
        for k in kennungen:
            try:
                alle += [v for _, v in self._werte(schl, k, start, ende) if v > 0]
            except Exception:
                continue
        return round(sum(alle) / len(alle), 4) if alle else None

    def stundenwerte(self, schluessel: str, start: datetime, ende: datetime,
                     aggregat: str = "mean") -> list:
        """[('YYYY-MM-DDTHH:MM' Ortszeit, wert)], aufsteigend. aggregat "mean" oder "last"."""
        ids = self.kennungen(schluessel)
        if not ids:
            return []
        werte = [(_lokal(t), float(v))
                 for t, v in self._stunden(schluessel, ids[0], _utc(start), _utc(ende), aggregat)]
        return sorted(werte, key=lambda x: x[0])

    # ── von den Unterklassen umzusetzen ──────────────────────────────────────

    def test(self) -> tuple:
        raise NotImplementedError

    def _letzter(self, schl, kennung, von, bis):
        raise NotImplementedError

    def _werte(self, schl, kennung, von, bis):
        raise NotImplementedError

    def _stunden(self, schl, kennung, von, bis, aggregat):
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════════════════
#  InfluxDB 1.x – InfluxQL ueber GET /query
#  HA schreibt: Measurement = Einheit ("km", "kWh", "EUR/L", "%"), Feld "value",
#  Tags u.a. entity_id (ohne "sensor.") und – je nach Konfiguration – friendly_name
# ═══════════════════════════════════════════════════════════════════════════════

def _esc_str(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _esc_ident(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


class _Influx(Datenquelle):
    nutzt_entity_ids = False

    def measurement(self, schl: str) -> str:
        _, _, feld, standard = SENSOREN[schl]
        return (self.cfg.get(feld) or standard).strip()

    @property
    def tag(self) -> str:
        return (self.cfg.get("influx_tag") or "friendly_name").strip()


class InfluxDB1(_Influx):
    typ = "influxdb"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = _url(cfg.get("influx_url") or "http://localhost", cfg.get("influx_port") or 8086)
        self.db = cfg.get("influx_database") or "home_assistant"

    def _query(self, q: str) -> dict:
        url = f"{self.base}/query?{urllib.parse.urlencode({'db': self.db, 'q': q, 'epoch': 's'})}"
        return json.loads(_http(url, user=self.cfg.get("influx_user") or "",
                                passwort=self.cfg.get("influx_password") or ""))

    @staticmethod
    def _zeilen(ergebnis: dict) -> list:
        """[(datetime, float)] aus allen Serien; Wertspalte = erste Nicht-Zeit-Spalte."""
        werte = []
        for res in ergebnis.get("results", []):
            if res.get("error"):
                raise ConnectionError(res["error"])
            for serie in res.get("series", []):
                spalten = serie["columns"]
                t = spalten.index("time")
                v = next(i for i in range(len(spalten)) if i != t)
                for zeile in serie.get("values", []):
                    if zeile[v] is not None:
                        werte.append((_parse_zeit(zeile[t]), float(zeile[v])))
        return sorted(werte, key=lambda x: x[0])

    def _wo(self, schl, kennung, von, bis, ab_inkl=False) -> str:
        return (f'FROM "{_esc_ident(self.measurement(schl))}" '
                f'WHERE "{_esc_ident(self.tag)}" = \'{_esc_str(kennung)}\' '
                f"AND time {'>=' if ab_inkl else '>'} '{_iso(von)}' AND time <= '{_iso(bis)}'")

    def test(self):
        try:
            erg = self._query("SHOW DATABASES")
            dbs = [z[0] for s in erg["results"][0].get("series", []) for z in s["values"]]
        except Exception as e:
            return False, str(e)
        if self.db not in dbs:
            return False, f"Verbunden, aber Datenbank '{self.db}' nicht gefunden"
        return True, f"Verbunden · '{self.db}' gefunden"

    def _letzter(self, schl, kennung, von, bis):
        w = self._zeilen(self._query(f'SELECT last("value") {self._wo(schl, kennung, von, bis)}'))
        return w[-1][1] if w else None

    def _werte(self, schl, kennung, von, bis):
        return self._zeilen(self._query(f'SELECT "value" {self._wo(schl, kennung, von, bis)}'))

    def _stunden(self, schl, kennung, von, bis, aggregat):
        agg = "last" if aggregat == "last" else "mean"
        return self._zeilen(self._query(
            f'SELECT {agg}("value") {self._wo(schl, kennung, von, bis, ab_inkl=True)} '
            f"GROUP BY time(1h) fill(none)"))


# ═══════════════════════════════════════════════════════════════════════════════
#  InfluxDB 2.x – Flux ueber POST /api/v2/query, Antwort als CSV
# ═══════════════════════════════════════════════════════════════════════════════

def _flux_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class InfluxDB2(_Influx):
    typ = "influxdb2"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = _url(cfg.get("influx2_url") or "http://localhost:8086")
        self.org = (cfg.get("influx2_org") or "").strip()
        self.bucket = (cfg.get("influx2_bucket") or "home_assistant").strip()
        self.token = (cfg.get("influx2_token") or "").strip()

    def _query(self, flux: str) -> list:
        url = f"{self.base}/api/v2/query?{urllib.parse.urlencode({'org': self.org})}"
        roh = _http(url, daten=flux.encode(), kopf={
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/vnd.flux",
            "Accept": "application/csv"}).decode("utf-8", errors="replace")
        return self._csv(roh)

    @staticmethod
    def _csv(roh: str) -> list:
        """[(datetime, float)] aus der CSV-Antwort (mehrere Tabellen, je mit Kopfzeile)."""
        werte, kopf = [], None
        for zeile in csv.reader(io.StringIO(roh)):
            if not any(zeile):                  # Leerzeile trennt Tabellen
                kopf = None
                continue
            if zeile[0].startswith("#"):        # Annotationen
                continue
            if kopf is None:
                kopf = {name: i for i, name in enumerate(zeile)}
                continue
            if "error" in kopf and "_value" not in kopf:
                raise ConnectionError(zeile[kopf["error"]])
            if "_value" not in kopf or "_time" not in kopf:
                continue
            try:
                werte.append((_parse_zeit(zeile[kopf["_time"]]), float(zeile[kopf["_value"]])))
            except (ValueError, IndexError):
                continue
        return sorted(werte, key=lambda x: x[0])

    def _basis(self, schl, kennung, von, bis) -> str:
        return (f"from(bucket: {_flux_str(self.bucket)})\n"
                f"  |> range(start: {_iso(von)}, stop: {_iso(bis)})\n"
                f"  |> filter(fn: (r) => r._measurement == {_flux_str(self.measurement(schl))}"
                f" and r._field == \"value\""
                f" and r[{_flux_str(self.tag)}] == {_flux_str(kennung)})\n")

    def test(self):
        if not self.token:
            return False, "Token fehlt"
        try:
            self._query(f"from(bucket: {_flux_str(self.bucket)}) |> range(start: -1m) |> limit(n: 1)")
        except Exception as e:
            return False, str(e)
        return True, f"Verbunden · Bucket '{self.bucket}' gefunden"

    def _letzter(self, schl, kennung, von, bis):
        # range() schliesst stop aus – eine Sekunde dazu, damit bis enthalten ist
        w = self._query(self._basis(schl, kennung, von + timedelta(seconds=1),
                                    bis + timedelta(seconds=1)) + "  |> last()")
        return w[-1][1] if w else None

    def _werte(self, schl, kennung, von, bis):
        return self._query(self._basis(schl, kennung, von, bis))

    def _stunden(self, schl, kennung, von, bis, aggregat):
        fn = "last" if aggregat == "last" else "mean"
        return self._query(self._basis(schl, kennung, von, bis)
                           + f"  |> aggregateWindow(every: 1h, fn: {fn}, createEmpty: false,"
                             f" timeSrc: \"_start\")")


# ═══════════════════════════════════════════════════════════════════════════════
#  PostgreSQL / TimescaleDB – Tabelle der HA-Integration LTSS
#  Spalten: time (timestamptz), entity_id ("sensor.xyz"), state (Text), attributes
# ═══════════════════════════════════════════════════════════════════════════════

_ZAHL = r"^-?[0-9]+(\.[0-9]+)?$"


class PostgresLTSS(Datenquelle):
    typ = "postgres"

    def __init__(self, cfg):
        super().__init__(cfg)
        tabelle = (cfg.get("pg_tabelle") or "ltss").strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?", tabelle):
            raise ValueError(f"Ungültiger Tabellenname: {tabelle}")
        self.tabelle = tabelle

    def _sql(self, sql: str, **param) -> list:
        try:
            import pg8000.native
        except ImportError:
            raise ConnectionError("PostgreSQL-Treiber pg8000 ist nicht installiert")
        con = pg8000.native.Connection(
            user=self.cfg.get("pg_user") or "postgres",
            password=self.cfg.get("pg_password") or None,
            host=(self.cfg.get("pg_host") or "localhost").strip(),
            port=int(self.cfg.get("pg_port") or 5432),
            database=(self.cfg.get("pg_database") or "homeassistant").strip(),
            timeout=TIMEOUT)
        try:
            con.run("SET TIME ZONE 'UTC'")
            return con.run(sql, **param)
        finally:
            con.close()

    def _wo(self, ab_inkl=False) -> str:
        return (f"FROM {self.tabelle} WHERE entity_id = :e "
                f"AND time {'>=' if ab_inkl else '>'} :von AND time <= :bis "
                f"AND state ~ '{_ZAHL}'")

    def test(self):
        try:
            self._sql(f"SELECT 1 FROM {self.tabelle} LIMIT 1")
        except Exception as e:
            return False, str(e)
        return True, f"Verbunden · Tabelle '{self.tabelle}' gefunden"

    def _letzter(self, schl, kennung, von, bis):
        z = self._sql(f"SELECT state::float {self._wo()} ORDER BY time DESC LIMIT 1",
                      e=kennung, von=_utc(von), bis=_utc(bis))
        return float(z[0][0]) if z else None

    def _werte(self, schl, kennung, von, bis):
        z = self._sql(f"SELECT time, state::float {self._wo()} ORDER BY time",
                      e=kennung, von=_utc(von), bis=_utc(bis))
        return [(_parse_zeit(t), float(v)) for t, v in z]

    def _stunden(self, schl, kennung, von, bis, aggregat):
        if aggregat == "last":
            sql = (f"SELECT DISTINCT ON (date_trunc('hour', time)) date_trunc('hour', time), "
                   f"state::float {self._wo(ab_inkl=True)} "
                   f"ORDER BY date_trunc('hour', time), time DESC")
        else:
            sql = (f"SELECT date_trunc('hour', time) AS h, avg(state::float) "
                   f"{self._wo(ab_inkl=True)} GROUP BY h ORDER BY h")
        z = self._sql(sql, e=kennung, von=_utc(von), bis=_utc(bis))
        return [(_parse_zeit(t), float(v)) for t, v in z]


# ═══════════════════════════════════════════════════════════════════════════════
#  Prometheus / VictoriaMetrics – HTTP-API /api/v1/query(_range)
#  Die HA-Integration prometheus exportiert je Sensor eine Metrik
#  homeassistant_sensor_<einheit> mit dem Label entity="sensor.xyz".
# ═══════════════════════════════════════════════════════════════════════════════

class Prometheus(Datenquelle):
    typ = "prometheus"
    # Prometheus liefert je Abfrage hoechstens 11.000 Punkte pro Serie
    MAX_PUNKTE = 10000

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = _url(cfg.get("prom_url") or "http://localhost:9090")
        self.vorlage = (cfg.get("prom_selektor") or "").strip() or PROM_SELEKTOR_STANDARD

    def selektor(self, kennung: str) -> str:
        wert = kennung.replace("\\", "\\\\").replace('"', '\\"')
        return self.vorlage.replace("{entity}", wert)

    def _api(self, pfad: str, param: dict) -> list:
        url = f"{self.base}/api/v1/{pfad}?{urllib.parse.urlencode(param)}"
        d = json.loads(_http(url, user=self.cfg.get("prom_user") or "",
                             passwort=self.cfg.get("prom_password") or ""))
        if d.get("status") != "success":
            raise ConnectionError(d.get("error") or "Abfrage fehlgeschlagen")
        return d["data"]["result"]

    def _bereich(self, ausdruck: str, von: datetime, bis: datetime, schritt: int) -> list:
        """query_range in Stuecken; [(datetime Auswertungszeit, float)] der ersten Serie."""
        werte = []
        stueck = timedelta(seconds=schritt * self.MAX_PUNKTE)
        a = _utc(von)
        while a < _utc(bis):
            b = min(a + stueck, _utc(bis))
            serien = self._api("query_range", {"query": ausdruck, "start": a.timestamp(),
                                               "end": b.timestamp(), "step": schritt})
            if serien:
                werte += [(_parse_zeit(float(t)), float(v)) for t, v in serien[0]["values"]]
            a = b + timedelta(seconds=schritt)
        return sorted(werte, key=lambda x: x[0])

    def test(self):
        try:
            self._api("query", {"query": "vector(1)"})
        except Exception as e:
            return False, str(e)
        return True, "Verbunden"

    def _letzter(self, schl, kennung, von, bis):
        sekunden = max(int((_utc(bis) - _utc(von)).total_seconds()), 60)
        serien = self._api("query", {"query": f"last_over_time({self.selektor(kennung)}[{sekunden}s])",
                                     "time": _utc(bis).timestamp()})
        return float(serien[0]["value"][1]) if serien else None

    def _werte(self, schl, kennung, von, bis):
        # Keine Rohwerte ueber die API – Stichproben alle 5 Minuten
        return self._bereich(f"last_over_time({self.selektor(kennung)}[5m])", von, bis, 300)

    def _stunden(self, schl, kennung, von, bis, aggregat):
        fn = "last_over_time" if aggregat == "last" else "avg_over_time"
        # Das Fenster [1h] endet am Auswertungszeitpunkt und schliesst ihn ein. Ausgewertet
        # wird deshalb eine Sekunde vor dem Stundenende – so deckt es [h, h+1h) ab wie bei
        # InfluxDB – und das Ergebnis auf den Stundenbeginn h gelegt.
        vorlauf = timedelta(hours=1) - timedelta(seconds=1)
        werte = self._bereich(f"{fn}({self.selektor(kennung)}[1h])",
                              von + vorlauf, bis + vorlauf, 3600)
        return [(t - vorlauf, v) for t, v in werte]
