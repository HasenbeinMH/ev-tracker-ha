# -*- coding: utf-8 -*-
"""
Externe Datenquellen fuer Monatswerte und Stundenverlaeufe – Alternative zur HA-API.

Unterstuetzt (Einstellung "datasource"):
    "influxdb"    InfluxDB 1.x          (InfluxQL, Benutzer/Passwort)
    "influxdb2"   InfluxDB 2.x          (Flux, Organisation/Bucket/Token)
    "influxdb3"   InfluxDB 3.x          (SQL, Datenbank/Token)
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
    "influxdb3":  "InfluxDB 3.x",
    "postgres":   "PostgreSQL / TimescaleDB (LTSS)",
    "prometheus": "Prometheus / VictoriaMetrics",
}

# Zugangsdaten – nicht im Export ohne Zugangsdaten, leeres Feld behaelt den alten Wert
GEHEIM = {"influx_password", "influx2_token", "influx3_token", "pg_password", "prom_password"}

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

UTC = timezone.utc
TIMEOUT = 15
# Suche ueber die ganze Datenbank darf laenger dauern
TIMEOUT_SUCHE = 60
MAX_TREFFER = 40
# Plausibilitaet einer Monatsdifferenz (km bzw. kWh) – wie bisher bei InfluxDB 1.x
MAX_DELTA = 100000
# Stammt der letzte Zaehlerstand vor dem Monat aus einer laengeren Luecke, waere die
# Differenz die Strecke mehrerer Monate. Ab dieser Luecke wird sie nicht uebernommen.
# (Ein Auto, das so lange steht, meldet oft keinen neuen Stand – dann springt die
# HA-API ein, deren Langzeitstatistik auch ohne Aenderung stuendliche Werte hat.)
LUECKE_TAGE = 45


def namen_liste(wert: str) -> list:
    """Mehrere Namen je Sensor, getrennt mit "|" – etwa wenn ein Sensor umbenannt wurde
    ("Alter Name | Neuer Name"). Reihenfolge: aeltester zuerst, aktueller zuletzt."""
    return [n.strip() for n in (wert or "").split("|") if n.strip()]


def aus_einstellungen(cfg: dict):
    """Die eingestellte Datenquelle, oder None bei "ha" (nur HA-API)."""
    klasse = {"influxdb": InfluxDB1, "influxdb2": InfluxDB2, "influxdb3": InfluxDB3,
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


def _muster(begriff: str) -> str:
    """Suchbegriff als Regex-Teilstueck (Sonderzeichen maskiert)."""
    return re.escape((begriff or "").strip())


def _lokal(t: datetime) -> str:
    return t.astimezone().strftime("%Y-%m-%dT%H:%M")


def _http(url: str, daten: bytes | None = None, kopf: dict | None = None,
          user: str = "", passwort: str = "", timeout: int = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, data=daten, headers=kopf or {})
    if user or passwort:
        cred = base64.b64encode(f"{user}:{passwort}".encode()).decode()
        req.add_header("Authorization", f"Basic {cred}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        suche(begriff)                             -> [Treffer] (siehe unten)
        _letzter(schl, kennung, von, bis)          -> (zeit, wert) des letzten Werts in
                                                      (von, bis] oder None
        _werte(schl, kennung, von, bis)            -> [(datetime, float)] aufsteigend
        _stunden(schl, kennung, von, bis, aggregat) -> [(datetime Stundenbeginn, float)]
    """
    typ = ""
    nutzt_entity_ids = True     # False: InfluxDB mit Friendly Name/Tag

    def __init__(self, cfg: dict):
        self.cfg = cfg
        # Warum monatswert() fuer einen Schluessel nichts geliefert hat (kurzer Text)
        self.grund = {}
        self._warum = ""

    @property
    def name(self) -> str:
        return QUELLEN[self.typ]

    def kennungen(self, schluessel: str) -> list:
        """Alle Namen bzw. Entity-IDs des Sensors – je Feld auch mehrere mit "|"."""
        ent, namen, _, _ = SENSOREN[schluessel]
        felder = ent if self.nutzt_entity_ids else namen
        return [n for f in felder for n in namen_liste(self.cfg.get(f))]

    def hat(self, schluessel: str) -> bool:
        return bool(self.kennungen(schluessel))

    def beschreibung(self, schluessel: str) -> str:
        """Wonach gesucht wird – fuer Hinweise, warum nichts kam."""
        return " | ".join(self.kennungen(schluessel)) or "–"

    # ── Monatswerte ──────────────────────────────────────────────────────────

    def monatswert(self, schluessel: str, jahr: int, monat: int) -> float | None:
        """Monatswert fuer den Import. None = keine Daten; der Grund steht dann in
        self.grund[schluessel]. Fehler der Datenbank werden abgefangen."""
        self.grund.pop(schluessel, None)
        ids = self.kennungen(schluessel)
        if not ids:
            self.grund[schluessel] = "kein Sensor eingetragen"
            return None
        self._warum = "keine Werte im Monat"
        try:
            if schluessel == "benzin":
                wert = self.monat_mittel(schluessel, ids, jahr, monat)
            elif schluessel in ("pv", "wallbox"):
                wert = self.monat_summe(schluessel, ids, jahr, monat)
            else:
                wert = self.monat_delta(schluessel, ids, jahr, monat)
        except Exception as e:
            wert = None
            self._warum = "Fehler: " + self.fehlertext(e)
        if wert is None:
            self.grund[schluessel] = self._warum
        return wert

    def _letzter_von(self, schl, kennungen, von, bis):
        """Juengster Wert ueber alle Namen – nach einer Umbenennung der des neuen Namens."""
        treffer = [x for x in (self._letzter(schl, k, von, bis) for k in kennungen) if x]
        return max(treffer, key=lambda x: (x[0], x[1])) if treffer else None

    def monat_delta(self, schl, kennungen, jahr, monat) -> float | None:
        """Zaehlerstand am Monatsende minus letzter Stand vor dem Monat (bis 1 Jahr zurueck).
        Bei mehreren Namen zaehlt je Zeitpunkt der juengste Wert – so klappt auch der Monat
        einer Umbenennung (Stand unter dem neuen minus Stand unter dem alten Namen)."""
        start, ende = _monat(jahr, monat)
        jetzt = self._letzter_von(schl, kennungen, start, ende)
        if jetzt is None:
            self._warum = "keine Werte im Monat"
            return None
        vorher = self._letzter_von(schl, kennungen, start - timedelta(days=366), start)
        if vorher is None:
            self._warum = "kein Wert vor dem Monat (nötig für die Differenz)"
            return None
        delta = jetzt[1] - vorher[1]
        if delta < 0 or delta > MAX_DELTA:
            self._warum = f"Differenz unplausibel ({delta:.1f})"
            return None
        # Liegt der Stand davor lange zurueck, umfasst die Differenz auch die Monate der
        # Luecke – dann lieber nichts liefern (HA-API bzw. Nachtragen von Hand)
        grenze = start - timedelta(days=LUECKE_TAGE)
        if vorher[0] >= start:
            # Zeit des Werts unbekannt (Prometheus liefert nur den Auswertungszeitpunkt)
            luecke = self._letzter_von(schl, kennungen, grenze, start) is None
        else:
            luecke = vorher[0] < grenze
        if luecke:
            seit = (f"letzter Wert davor vom {vorher[0].astimezone():%d.%m.%Y}"
                    if vorher[0] < start else f"kein Wert in den {LUECKE_TAGE} Tagen davor")
            self._warum = (f"Lücke: {seit} – die Differenz ({delta:.0f}) "
                           f"würde mehrere Monate umfassen")
            return None
        return round(delta, 3)

    def monat_summe(self, schl, kennungen, jahr, monat) -> float | None:
        """Differenz wie beim Zaehler; bei taeglich zurueckgesetzten Sensoren (Differenz
        leer oder 0) die Summe der Tagesmaxima."""
        delta = self.monat_delta(schl, kennungen, jahr, monat)
        if delta:
            return delta
        start, ende = _monat(jahr, monat)
        tage = {}
        for k in kennungen:
            for t, v in self._werte(schl, k, start, ende):
                tag = t.astimezone().date()
                tage[tag] = max(tage.get(tag, v), v)
        summe = sum(v for v in tage.values() if v > 0)
        if summe > 0:
            return round(summe, 3)
        if tage:
            self._warum = "nur Nullwerte im Monat"
        return None

    def monat_mittel(self, schl, kennungen, jahr, monat) -> float | None:
        """Mittel aller Werte > 0 ueber alle Sensoren (Tankstelle nachts geschlossen = 0)."""
        start, ende = _monat(jahr, monat)
        alle, fehler = [], []
        for k in kennungen:
            try:
                alle += [v for _, v in self._werte(schl, k, start, ende) if v > 0]
            except Exception as e:
                fehler.append(self.fehlertext(e))
        if alle:
            return round(sum(alle) / len(alle), 4)
        self._warum = ("Fehler: " + fehler[0]) if len(fehler) == len(kennungen) \
            else "keine Werte über 0 im Monat"
        return None

    def stundenwerte(self, schluessel: str, start: datetime, ende: datetime,
                     aggregat: str = "mean") -> list:
        """[('YYYY-MM-DDTHH:MM' Ortszeit, wert)], aufsteigend. aggregat "mean" oder "last".
        Bei mehreren Namen werden die Verlaeufe zusammengefuegt (spaetere Namen gehen vor)."""
        werte = {}
        for k in self.kennungen(schluessel):
            for t, v in self._stunden(schluessel, k, _utc(start), _utc(ende), aggregat):
                werte[_lokal(t)] = float(v)
        return sorted(werte.items())

    # ── von den Unterklassen umzusetzen ──────────────────────────────────────

    def test(self) -> tuple:
        raise NotImplementedError

    def suche(self, begriff: str) -> list:
        """Sensoren, deren Name bzw. ID den Begriff enthaelt (Gross-/Kleinschreibung egal).
        [{"kennung", "name", "einheit", "von", "bis"}] – kennung ist der Wert fuer die
        Sensortabelle, von/bis (datetime oder None) der Zeitraum mit Daten."""
        raise NotImplementedError

    def fehlertext(self, e: Exception) -> str:
        return str(e)

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

    def beschreibung(self, schluessel: str) -> str:
        return f"{super().beschreibung(schluessel)} im Measurement {self.measurement(schluessel)}"


class InfluxDB1(_Influx):
    typ = "influxdb"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = _url(cfg.get("influx_url") or "http://localhost", cfg.get("influx_port") or 8086)
        self.db = cfg.get("influx_database") or "home_assistant"

    def _query(self, q: str, timeout: int = TIMEOUT) -> dict:
        url = f"{self.base}/query?{urllib.parse.urlencode({'db': self.db, 'q': q, 'epoch': 's'})}"
        return json.loads(_http(url, user=self.cfg.get("influx_user") or "",
                                passwort=self.cfg.get("influx_password") or "", timeout=timeout))

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

    def suche(self, begriff):
        tag = _esc_ident(self.tag)
        q = f'SHOW TAG VALUES WITH KEY = "{tag}"'
        muster = _muster(begriff).replace("/", "\\/")
        if muster:
            q += f' WHERE "{tag}" =~ /(?i){muster}/'
        paare = set()
        for res in self._query(q, TIMEOUT_SUCHE).get("results", []):
            if res.get("error"):
                raise ConnectionError(res["error"])
            for serie in res.get("series", []):
                paare |= {(serie["name"], z[1]) for z in serie.get("values", [])}
        treffer = []
        for meas, wert in sorted(paare, key=lambda p: (p[1].lower(), p[0])):
            wo = f'FROM "{_esc_ident(meas)}" WHERE "{tag}" = \'{_esc_str(wert)}\''
            zeiten = [t for t, _ in self._zeilen(self._query(
                f'SELECT first("value") {wo}; SELECT last("value") {wo}', TIMEOUT_SUCHE))]
            if zeiten:          # ohne Zahlenwerte (Textzustaende) nicht brauchbar
                treffer.append({"kennung": wert, "name": wert, "einheit": meas,
                                "von": min(zeiten), "bis": max(zeiten)})
            if len(treffer) >= MAX_TREFFER:
                break
        return treffer

    def _letzter(self, schl, kennung, von, bis):
        w = self._zeilen(self._query(f'SELECT last("value") {self._wo(schl, kennung, von, bis)}'))
        return w[-1] if w else None

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

    def _roh(self, flux: str, timeout: int = TIMEOUT) -> list:
        """Zeilen der CSV-Antwort als dicts (Spaltenname -> Text)."""
        url = f"{self.base}/api/v2/query?{urllib.parse.urlencode({'org': self.org})}"
        try:
            roh = _http(url, daten=flux.encode(), timeout=timeout, kopf={
                "Authorization": f"Token {self.token}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv"}).decode("utf-8", errors="replace")
        except ConnectionError as e:
            raise ConnectionError(self._fehlertext(str(e))) from None
        return self._csv_zeilen(roh)

    def _query(self, flux: str) -> list:
        return self._csv(self._roh(flux))

    @staticmethod
    def _csv_zeilen(roh: str) -> list:
        """CSV-Antwort (mehrere Tabellen, je mit Kopfzeile, ggf. Annotationen) -> [dict]."""
        zeilen, kopf = [], None
        for zeile in csv.reader(io.StringIO(roh)):
            if not any(zeile):                  # Leerzeile trennt Tabellen
                kopf = None
                continue
            if zeile[0].startswith("#"):        # Annotationen
                continue
            if kopf is None:
                kopf = zeile
                continue
            eintrag = dict(zip(kopf, zeile))
            if "error" in eintrag and "_value" not in eintrag:
                raise ConnectionError(eintrag["error"])
            zeilen.append(eintrag)
        return zeilen

    @staticmethod
    def _csv(zeilen: list) -> list:
        """[(datetime, float)] aus den CSV-Zeilen."""
        werte = []
        for z in zeilen:
            try:
                werte.append((_parse_zeit(z["_time"]), float(z["_value"])))
            except (KeyError, ValueError):
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

    def _fehlertext(self, text: str) -> str:
        """Haeufige Antworten von InfluxDB 2 in Klartext – die Rohmeldung bleibt dahinter stehen."""
        if "HTTP 401" in text:
            # Die letzten Zeichen reichen zum Abgleich mit der InfluxDB-Oberflaeche
            ende = self.token[-4:] if len(self.token) > 12 else "…"
            return (f"Token wird nicht angenommen (gespeichertes Token endet auf …{ende}). "
                    f"Gehört es zu genau dieser InfluxDB unter {self.base}? Bei mehreren "
                    f"Instanzen hat jede eigene Tokens. Neues Token dort unter Load Data → "
                    f"API Tokens anlegen, mit Lesezugriff auf den Bucket '{self.bucket}'. — {text}")
        if "HTTP 404" in text and "organization" in text.lower():
            return (f"Organisation '{self.org}' gibt es in dieser InfluxDB nicht – den Namen "
                    f"unter Profil → About bzw. im Menü oben links prüfen. — {text}")
        if "HTTP 404" in text and "bucket" in text.lower():
            return f"Bucket '{self.bucket}' nicht gefunden oder das Token darf ihn nicht lesen. — {text}"
        return text

    def suche(self, begriff):
        tag = _flux_str(self.tag)
        bedingung = f'r._field == "value" and exists r[{tag}]'
        muster = _muster(begriff).replace("/", "\\/")
        if muster:
            bedingung += f" and r[{tag}] =~ /(?i){muster}/"
        flux = (f"daten = from(bucket: {_flux_str(self.bucket)})\n"
                f"  |> range(start: 0)\n"
                f"  |> filter(fn: (r) => {bedingung})\n"
                f'  |> group(columns: ["_measurement", {tag}])\n'
                f'daten |> first() |> yield(name: "erster")\n'
                f'daten |> last() |> yield(name: "letzter")\n')
        gefunden = {}
        for z in self._roh(flux, TIMEOUT_SUCHE):
            schluessel = (z.get("_measurement"), z.get(self.tag))
            if not all(schluessel) or not z.get("_time"):
                continue
            eintrag = gefunden.setdefault(schluessel, {
                "kennung": schluessel[1], "name": schluessel[1], "einheit": schluessel[0],
                "von": None, "bis": None})
            eintrag["von" if z.get("result") == "erster" else "bis"] = _parse_zeit(z["_time"])
        return sorted(gefunden.values(),
                      key=lambda e: (e["kennung"].lower(), e["einheit"]))[:MAX_TREFFER]

    def _letzter(self, schl, kennung, von, bis):
        # range() schliesst stop aus – eine Sekunde dazu, damit bis enthalten ist
        w = self._query(self._basis(schl, kennung, von + timedelta(seconds=1),
                                    bis + timedelta(seconds=1)) + "  |> last()")
        return w[-1] if w else None

    def _werte(self, schl, kennung, von, bis):
        return self._query(self._basis(schl, kennung, von, bis))

    def _stunden(self, schl, kennung, von, bis, aggregat):
        fn = "last" if aggregat == "last" else "mean"
        return self._query(self._basis(schl, kennung, von, bis)
                           + f"  |> aggregateWindow(every: 1h, fn: {fn}, createEmpty: false,"
                             f" timeSrc: \"_start\")")


# ═══════════════════════════════════════════════════════════════════════════════
#  InfluxDB 3.x (Core/Enterprise) – SQL ueber POST /api/v3/query_sql, Antwort als JSON
#  HA schreibt ueber die v2-Schnittstelle wie bei InfluxDB 2: Measurement = Tabelle
#  (Einheit), Feld "value" und die Tags werden zu Spalten, der Bucket ist die Datenbank.
#  Flux gibt es in InfluxDB 3 nicht mehr.
# ═══════════════════════════════════════════════════════════════════════════════

def _sql_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _sql_ident(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


class InfluxDB3(_Influx):
    typ = "influxdb3"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.base = _url(cfg.get("influx3_url") or "http://localhost:8181")
        self.db = (cfg.get("influx3_database") or "home_assistant").strip()
        self.token = (cfg.get("influx3_token") or "").strip()

    def _sql(self, q: str, timeout: int = TIMEOUT) -> list:
        """Zeilen als dicts (Spaltenname -> Wert)."""
        daten = json.dumps({"db": self.db, "q": q, "format": "json"}).encode()
        try:
            roh = _http(f"{self.base}/api/v3/query_sql", daten=daten, timeout=timeout, kopf={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json"})
        except ConnectionError as e:
            raise ConnectionError(self._fehlertext(str(e))) from None
        text = roh.decode("utf-8", errors="replace").strip()
        return json.loads(text) if text else []

    def _fehlertext(self, text: str) -> str:
        if "HTTP 401" in text or "HTTP 403" in text:
            ende = self.token[-4:] if len(self.token) > 12 else "…"
            return (f"Token wird nicht angenommen (gespeichertes Token endet auf …{ende}). "
                    f"Gehört es zu genau dieser InfluxDB unter {self.base}? Ein Token legt man "
                    f"mit „influxdb3 create token --admin“ an bzw. in InfluxDB 3 Explorer. — {text}")
        if "HTTP 404" in text and "database" in text.lower():
            return (f"Datenbank '{self.db}' nicht gefunden – das ist der Name, den Home Assistant "
                    f"in der InfluxDB-Konfiguration als bucket einträgt. — {text}")
        return text

    @staticmethod
    def _paare(zeilen: list) -> list:
        """[(datetime, float)] aus Zeilen mit den Spalten time und value."""
        werte = []
        for z in zeilen:
            try:
                werte.append((_parse_zeit(z["time"]), float(z["value"])))
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(werte, key=lambda x: x[0])

    def _wo(self, schl, kennung, von, bis, ab_inkl=False) -> str:
        return (f"FROM {_sql_ident(self.measurement(schl))} "
                f"WHERE {_sql_ident(self.tag)} = {_sql_str(kennung)} AND \"value\" IS NOT NULL "
                f"AND time {'>=' if ab_inkl else '>'} {_sql_str(_iso(von))} "
                f"AND time <= {_sql_str(_iso(bis))}")

    def test(self):
        if not self.token:
            return False, "Token fehlt"
        try:
            tabellen = self._sql("SELECT table_name FROM information_schema.tables "
                                 "WHERE table_schema = 'iox'")
        except Exception as e:
            return False, str(e)
        return True, f"Verbunden · Datenbank '{self.db}' mit {len(tabellen)} Measurements"

    def suche(self, begriff):
        tag = self.tag
        # Nur Tabellen (Measurements), die sowohl den Tag als auch das Feld "value" haben
        spalten = self._sql("SELECT table_name, column_name FROM information_schema.columns "
                            f"WHERE table_schema = 'iox' AND column_name IN ({_sql_str(tag)}, 'value')",
                            TIMEOUT_SUCHE)
        je_tabelle = {}
        for z in spalten:
            je_tabelle.setdefault(z["table_name"], set()).add(z["column_name"])
        tabellen = sorted(t for t, s in je_tabelle.items() if s == {tag, "value"})
        begriff = (begriff or "").strip().lower()
        treffer = []
        for tabelle in tabellen:
            q = (f"SELECT {_sql_ident(tag)} AS kennung, min(time) AS von, max(time) AS bis "
                 f"FROM {_sql_ident(tabelle)} WHERE \"value\" IS NOT NULL")
            if begriff:
                q += f" AND strpos(lower({_sql_ident(tag)}), {_sql_str(begriff)}) > 0"
            for z in self._sql(q + " GROUP BY 1", TIMEOUT_SUCHE):
                if z.get("kennung") and z.get("von"):
                    treffer.append({"kennung": z["kennung"], "name": z["kennung"], "einheit": tabelle,
                                    "von": _parse_zeit(z["von"]), "bis": _parse_zeit(z["bis"])})
        return sorted(treffer, key=lambda e: (e["kennung"].lower(), e["einheit"]))[:MAX_TREFFER]

    def _letzter(self, schl, kennung, von, bis):
        w = self._paare(self._sql(f"SELECT time, \"value\" {self._wo(schl, kennung, von, bis)} "
                                  "ORDER BY time DESC LIMIT 1"))
        return w[-1] if w else None

    def _werte(self, schl, kennung, von, bis):
        return self._paare(self._sql(f"SELECT time, \"value\" {self._wo(schl, kennung, von, bis)} "
                                     "ORDER BY time"))

    def _stunden(self, schl, kennung, von, bis, aggregat):
        wert = ('last_value("value" ORDER BY time)' if aggregat == "last" else 'avg("value")')
        return self._paare(self._sql(
            f"SELECT date_bin(INTERVAL '1 hour', time) AS time, {wert} AS \"value\" "
            f"{self._wo(schl, kennung, von, bis, ab_inkl=True)} GROUP BY 1 ORDER BY 1"))


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

    def _sql(self, sql: str, timeout: int = TIMEOUT, **param) -> list:
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
            timeout=timeout)
        try:
            con.run("SET TIME ZONE 'UTC'")
            return con.run(sql, **param)
        finally:
            con.close()

    # Haeufige PostgreSQL-Fehlercodes -> verstaendlicher Hinweis
    FEHLERCODES = {"28P01": "Benutzer oder Passwort falsch",
                   "28000": "Benutzer hat keinen Zugriff",
                   "3D000": "Datenbank nicht gefunden",
                   "42P01": "Tabelle nicht gefunden – ist LTSS eingerichtet?",
                   "42501": "Benutzer darf die Tabelle nicht lesen"}

    def fehlertext(self, e: Exception) -> str:
        """pg8000 liefert Serverfehler als dict {'C': Code, 'M': Meldung, ...}."""
        info = e.args[0] if e.args and isinstance(e.args[0], dict) else None
        if not info:
            return str(e)
        hinweis = self.FEHLERCODES.get(info.get("C"))
        return f"{hinweis} ({info.get('M')})" if hinweis else str(info.get("M") or e)

    def _wo(self, ab_inkl=False) -> str:
        return (f"FROM {self.tabelle} WHERE entity_id = :e "
                f"AND time {'>=' if ab_inkl else '>'} :von AND time <= :bis "
                f"AND state ~ '{_ZAHL}'")

    def test(self):
        try:
            self._sql(f"SELECT 1 FROM {self.tabelle} LIMIT 1")
        except Exception as e:
            return False, self.fehlertext(e)
        return True, f"Verbunden · Tabelle '{self.tabelle}' gefunden"

    def suche(self, begriff):
        # ILIKE-Muster: \, % und _ im Suchbegriff maskieren
        roh = (begriff or "").strip()
        roh = roh.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        zeilen = self._sql(
            f"SELECT entity_id, min(time), max(time), "
            f"max(attributes->>'unit_of_measurement'), max(attributes->>'friendly_name') "
            f"FROM {self.tabelle} WHERE entity_id ILIKE :m AND state ~ '{_ZAHL}' "
            f"GROUP BY entity_id ORDER BY entity_id LIMIT {MAX_TREFFER}",
            timeout=TIMEOUT_SUCHE, m=f"%{roh}%")
        return [{"kennung": e, "name": name or "", "einheit": einheit or "",
                 "von": _parse_zeit(von) if von else None,
                 "bis": _parse_zeit(bis) if bis else None}
                for e, von, bis, einheit, name in zeilen]

    def _letzter(self, schl, kennung, von, bis):
        z = self._sql(f"SELECT time, state::float {self._wo()} ORDER BY time DESC LIMIT 1",
                      e=kennung, von=_utc(von), bis=_utc(bis))
        return (_parse_zeit(z[0][0]), float(z[0][1])) if z else None

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

    def _api(self, pfad: str, param: dict, timeout: int = TIMEOUT):
        url = f"{self.base}/api/v1/{pfad}?{urllib.parse.urlencode(param)}"
        d = json.loads(_http(url, user=self.cfg.get("prom_user") or "",
                             passwort=self.cfg.get("prom_password") or "", timeout=timeout))
        if d.get("status") != "success":
            raise ConnectionError(d.get("error") or "Abfrage fehlgeschlagen")
        # query/query_range: {"result": [...]}; series: direkt eine Liste
        return d["data"]["result"] if isinstance(d["data"], dict) else d["data"]

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

    def suche(self, begriff):
        """Ueber die Serien-API: Labels entity/friendly_name, Einheit aus dem Metriknamen.
        Den Zeitraum mit Daten liefert diese API nicht (von/bis bleiben leer)."""
        wert = f"(?i).*{_muster(begriff)}.*" if _muster(begriff) else ".+"
        literal = wert.replace("\\", "\\\\").replace('"', '\\"')
        vorlage = self.vorlage if 'entity="{entity}"' in self.vorlage else PROM_SELEKTOR_STANDARD
        selektor = vorlage.replace('entity="{entity}"', f'entity=~"{literal}"')
        jetzt = datetime.now(UTC)
        serien = self._api("series", {"match[]": selektor,
                                      "start": (jetzt - timedelta(days=3650)).timestamp(),
                                      "end": jetzt.timestamp()}, TIMEOUT_SUCHE)
        gefunden = {}
        for s in serien:
            ent = s.get("entity")
            if ent and ent not in gefunden:
                gefunden[ent] = {"kennung": ent, "name": s.get("friendly_name", ""),
                                 "einheit": s.get("__name__", "").replace("homeassistant_sensor_", ""),
                                 "von": None, "bis": None}
        return sorted(gefunden.values(), key=lambda e: e["kennung"])[:MAX_TREFFER]

    def _letzter(self, schl, kennung, von, bis):
        sekunden = max(int((_utc(bis) - _utc(von)).total_seconds()), 60)
        serien = self._api("query", {"query": f"last_over_time({self.selektor(kennung)}[{sekunden}s])",
                                     "time": _utc(bis).timestamp()})
        # Die Zeit des Werts liefert last_over_time nicht – der Auswertungszeitpunkt
        # genuegt, um mehrere Namen zu vergleichen (bei Gleichstand gewinnt der hoehere)
        return (_utc(bis), float(serien[0]["value"][1])) if serien else None

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
