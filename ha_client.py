"""
Home Assistant REST API Client
Primär: Long-Term Statistics API (/api/statistics_during_period)
Fallback: History API (/api/history/period)

Statistics-API Vorteile:
- Stündliche Auflösung, lückenlos gespeichert
- sum  = kumulativer Endwert (für Zähler: Odometer, kWh-Zähler)
- mean = Durchschnitt (für Preissensoren)
- Monatswert = sum[letzter Stundenwert] - sum[erster Stundenwert]
"""
import urllib.request
import urllib.error
import urllib.parse
import base64
import calendar
import json
from datetime import datetime
from collections import defaultdict


def _esc_str(s: str) -> str:
    """Escapt einen Wert für ein einfach-quotiertes InfluxQL-String-Literal."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


def _esc_ident(s: str) -> str:
    """Escapt einen Namen für einen doppelt-quotierten InfluxQL-Identifier."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


class HAClient:
    def __init__(self, url: str, token: str):
        self.url   = url.rstrip("/")
        self.token = token

    # ─────────────────────────────────────────
    #  HTTP-Basis
    # ─────────────────────────────────────────

    def _get(self, path: str) -> dict | list | None:
        req = urllib.request.Request(
            f"{self.url}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type":  "application/json",
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            raise ConnectionError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise ConnectionError(f"Verbindungsfehler: {e.reason}")

    # ─────────────────────────────────────────
    #  Verbindungstest
    # ─────────────────────────────────────────

    def test_connection(self) -> bool:
        try:
            data = self._get("/api/")
            return isinstance(data, dict) and "message" in data
        except Exception:
            return False

    # ─────────────────────────────────────────
    #  Aktueller Sensorwert
    # ─────────────────────────────────────────

    def get_current_state(self, entity_id: str) -> float | None:
        try:
            data = self._get(f"/api/states/{entity_id}")
            return float(data.get("state", ""))
        except (ValueError, TypeError, ConnectionError):
            return None

    # ─────────────────────────────────────────
    #  Statistics API  (primär)
    # ─────────────────────────────────────────

    def _get_statistics(self, entity_ids: list[str],
                        start: datetime, end: datetime,
                        period: str = "hour") -> dict:
        """
        Ruft Long-Term Statistics ab.
        Wichtig: Diese API existiert nur über den WebSocket-Endpunkt
        (recorder/statistics_during_period) – es gibt keinen REST-Endpunkt.
        Rückgabe: {entity_id: [{"start": "...", "sum": ..., "mean": ..., ...}]}
        """
        try:
            import websocket
        except ImportError:
            # websocket-client fehlt → Aufrufer fällt auf die History-API zurück
            return {}

        ws_url = (self.url
                  .replace("https://", "wss://", 1)
                  .replace("http://",  "ws://",  1)) + "/api/websocket"
        try:
            ws = websocket.create_connection(ws_url, timeout=15)
        except Exception as e:
            raise ConnectionError(f"WebSocket-Verbindungsfehler: {e}")

        try:
            json.loads(ws.recv())  # "auth_required"
            ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            msg = json.loads(ws.recv())
            if msg.get("type") != "auth_ok":
                raise ConnectionError("WebSocket-Authentifizierung fehlgeschlagen (Token?)")

            ws.send(json.dumps({
                "id":            1,
                "type":          "recorder/statistics_during_period",
                "start_time":    start.astimezone().isoformat(),
                "end_time":      end.astimezone().isoformat(),
                "statistic_ids": entity_ids,
                "period":        period,
                "types":         ["sum", "mean", "state"],
            }))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") == 1:
                    break
            if not msg.get("success"):
                return {}
            result = msg.get("result") or {}
        finally:
            ws.close()

        # "start" kommt als Epoch-Millisekunden → in lokale ISO-Strings wandeln,
        # damit die Monats-Zuordnung (String-Prefix "YYYY-MM") funktioniert
        out = {}
        for eid, rows in result.items():
            conv = []
            for r in rows:
                ts = r.get("start")
                if isinstance(ts, (int, float)):
                    r = dict(r)
                    r["start"] = datetime.fromtimestamp(ts / 1000).isoformat()
                conv.append(r)
            out[eid] = conv
        return out

    def get_month_value_stats(self, entity_id: str,
                              year: int, month: int,
                              mode: str = "delta") -> float | None:
        """
        Holt den Monatswert über die Statistics-API.
        Gibt None zurück wenn keine Statistics → Fallback auf History.
        """
        last_day  = calendar.monthrange(year, month)[1]

        # Etwas vor Monatsbeginn für den Basis-sum-Wert
        if month == 1:
            pre_start = datetime(year - 1, 12, 31, 20, 0, 0)
        else:
            prev_last = calendar.monthrange(year, month - 1)[1]
            pre_start = datetime(year, month - 1, prev_last, 20, 0, 0)

        end = datetime(year, month, last_day, 23, 59, 59)

        try:
            stats = self._get_statistics([entity_id], pre_start, end, period="hour")
        except Exception:
            return None

        rows = stats.get(entity_id, [])
        if not rows:
            return None

        # Zeitzone-robuste Monatserkennung: prüfe Jahr+Monat im ISO-String
        year_str  = str(year)
        month_str = f"{month:02d}"

        def in_month(row):
            ts = row.get("start", "")
            # ISO: "2026-04-01T00:00:00+02:00" oder "2026-04-01T00:00:00Z"
            # Nur die ersten 7 Zeichen prüfen: "2026-04"
            return ts[:7] == f"{year_str}-{month_str}"

        def before_month(row):
            ts = row.get("start", "")
            return ts[:7] < f"{year_str}-{month_str}"

        month_rows = [r for r in rows if in_month(r)]
        pre_rows   = [r for r in rows if before_month(r)]

        if not month_rows:
            return None

        if mode == "delta":
            curr_sum_rows = [r for r in month_rows if r.get("sum") is not None]
            if not curr_sum_rows:
                return None
            end_sum      = curr_sum_rows[-1]["sum"]
            pre_sum_rows = [r for r in pre_rows if r.get("sum") is not None]
            base_sum     = pre_sum_rows[-1]["sum"] if pre_sum_rows else curr_sum_rows[0].get("sum", end_sum)
            delta = end_sum - base_sum
            return round(delta, 3) if delta >= 0 else None

        elif mode == "mean":
            # Nur Werte > 0 (Tankstelle nachts = 0)
            means = [r["mean"] for r in month_rows
                     if r.get("mean") is not None and r["mean"] > 0]
            if not means:
                states = [r["state"] for r in month_rows
                          if r.get("state") is not None and r["state"] > 0]
                if not states:
                    return None
                return round(sum(states) / len(states), 4)
            return round(sum(means) / len(means), 4)

        elif mode == "sum":
            state_rows = [r for r in month_rows if r.get("state") is not None]
            if not state_rows:
                return self.get_month_value_stats(entity_id, year, month, mode="delta")
            states = [r["state"] for r in state_rows if r["state"] >= 0]
            if not states:
                return None
            resets = sum(1 for i in range(1, len(states))
                         if states[i] < states[i-1] * 0.3 and states[i-1] > 0.1)
            if resets > 2:
                daily_max: dict = defaultdict(float)
                for r in state_rows:
                    ts  = r.get("start", "")[:10]
                    val = r.get("state", 0)
                    if val >= 0:
                        daily_max[ts] = max(daily_max[ts], val)
                total = sum(daily_max.values())
                return round(total, 3) if total > 0 else None
            else:
                return self.get_month_value_stats(entity_id, year, month, mode="delta")

        return None

    def diagnose_entity(self, entity_id: str, year: int, month: int) -> dict:
        """
        Diagnosefunktion: testet Statistics- und History-API für eine Entity.
        Berechnet auch direkt den Delta-Wert über History.
        """
        result = {"entity_id": entity_id, "stats_rows": 0, "history_rows": 0,
                  "stats_sample": None, "history_sample": None,
                  "history_delta": None, "history_avg": None, "error": None}
        try:
            last_day  = calendar.monthrange(year, month)[1]
            pre_start = datetime(year, month, 1, 0, 0, 0)
            end       = datetime(year, month, last_day, 23, 59, 59)

            # Statistics
            stats = self._get_statistics([entity_id], pre_start, end, period="hour")
            rows  = stats.get(entity_id, [])
            result["stats_rows"]   = len(rows)
            result["stats_sample"] = rows[:2] if rows else None

            # History
            history = self.get_history_period(entity_id, pre_start, end)
            result["history_rows"]   = len(history)
            result["history_sample"] = history[:1] if history else None

            # Delta und Avg berechnen
            result["history_delta"] = self._history_delta(entity_id, year, month)
            result["history_avg"]   = self._history_avg([entity_id], year, month)

        except Exception as e:
            result["error"] = str(e)
        return result

    # ─────────────────────────────────────────
    #  History API  (Fallback)
    # ─────────────────────────────────────────

    def get_history_period(self, entity_id: str,
                           start: datetime, end: datetime) -> list[dict]:
        start_str = start.strftime("%Y-%m-%dT%H:%M:%S")
        end_str   = end.strftime("%Y-%m-%dT%H:%M:%S")
        path = (f"/api/history/period/{start_str}"
                f"?filter_entity_id={entity_id}"
                f"&end_time={end_str}"
                f"&minimal_response=true&no_attributes=true")
        try:
            data = self._get(path)
            if data and isinstance(data, list) and len(data) > 0:
                return data[0]
            return []
        except Exception:
            return []

    def _history_delta(self, entity_id: str, year: int, month: int) -> float | None:
        """History-Fallback: Delta mit letztem bekannten Wert vor Monatsbeginn als Basis.
        Sucht bis zu 12 Monate zurück – nötig für Sensoren die selten aktualisieren."""
        # Letzten Wert VOR Monatsbeginn suchen – bis 12 Monate zurück
        start_val  = None
        start_ts   = None
        search_end = datetime(year, month, 1, 0, 0, 0)

        for back in range(1, 13):
            m, y = month - back, year
            while m <= 0:
                m += 12
                y -= 1
            h = self.get_history_period(
                entity_id,
                datetime(y, m, 1),
                search_end)
            if h:
                for entry in reversed(h):
                    try:
                        v = float(entry.get("state", ""))
                        if v > 0:
                            start_val = v
                            start_ts  = entry.get("last_changed", "")
                            break
                    except (ValueError, TypeError):
                        continue
            if start_val is not None:
                break

        # Letzten Wert IM aktuellen Monat holen
        last_day = calendar.monthrange(year, month)[1]
        h_curr = self.get_history_period(
            entity_id,
            datetime(year, month, 1),
            datetime(year, month, last_day, 23, 59, 59))

        # Falls kein Wert im Monat: letzten bekannten Wert nach Monatsbeginn suchen
        # (Sensor hat im Monat evtl. nur einen Eintrag ganz am Ende)
        if not h_curr:
            # Suche auch im Folgemonat nach dem letzten Wert des gesuchten Monats
            if month == 12:
                next_y, next_m = year + 1, 1
            else:
                next_y, next_m = year, month + 1
            h_curr = self.get_history_period(
                entity_id,
                datetime(year, month, 1),
                datetime(next_y, next_m, 1))

        if not h_curr:
            return None

        last_val  = None
        first_val = None
        for entry in h_curr:
            # Nur Werte die noch im gesuchten Monat liegen
            ts = entry.get("last_changed", entry.get("last_updated", ""))
            if ts and ts[:7] > f"{year}-{month:02d}":
                break
            try:
                v = float(entry.get("state", ""))
                if v > 0:
                    if first_val is None:
                        first_val = v
                    last_val = v
            except (ValueError, TypeError):
                continue

        # Fallback: letzter Wert aus gesamter Abfrage
        if last_val is None:
            for entry in reversed(h_curr):
                try:
                    v = float(entry.get("state", ""))
                    if v > 0:
                        last_val = v
                        break
                except (ValueError, TypeError):
                    continue

        if last_val is None:
            return None

        base = start_val if start_val is not None else first_val
        if base is None:
            return None

        delta = last_val - base
        # Plausibilitätsprüfung: 0 bis 10.000 km/Monat
        if delta < 0 or delta > 10000:
            return None
        return round(delta, 1)

    def _history_avg(self, entity_ids: list[str], year: int, month: int) -> float | None:
        """History-Fallback: Durchschnitt, Nullwerte ignorieren."""
        start    = datetime(year, month, 1)
        last_day = calendar.monthrange(year, month)[1]
        end      = datetime(year, month, last_day, 23, 59, 59)

        all_values = []
        for eid in entity_ids:
            for entry in self.get_history_period(eid, start, end):
                try:
                    v = float(entry.get("state", ""))
                    if v > 0:
                        all_values.append(v)
                except (ValueError, TypeError):
                    continue

        if not all_values:
            return None
        return round(sum(all_values) / len(all_values), 4)

    # ─────────────────────────────────────────
    #  Öffentliche Monatswert-Methoden
    #  Statistics → Fallback History
    # ─────────────────────────────────────────

    def get_month_delta(self, entity_id: str, year: int, month: int) -> float | None:
        """Monatliches Delta eines kumulativen Zählers (kWh, km)."""
        val = self.get_month_value_stats(entity_id, year, month, mode="delta")
        if val is None:
            val = self._history_delta(entity_id, year, month)
        return val

    def get_month_delta_with_prev(self, entity_id: str, year: int, month: int) -> float | None:
        """Alias – nutzt Statistics als primäre Quelle."""
        return self.get_month_delta(entity_id, year, month)

    def get_month_sum_from_daily(self, entity_id: str, year: int, month: int) -> float | None:
        """Monatssumme für Sensoren mit täglichem Reset (z.B. PV yield_today)."""
        val = self.get_month_value_stats(entity_id, year, month, mode="sum")
        if val is None:
            val = self._history_delta(entity_id, year, month)
        return val

    def get_month_avg(self, entity_id: str, year: int, month: int) -> float | None:
        """Monatsdurchschnitt (z.B. Tankerkönig)."""
        val = self.get_month_value_stats(entity_id, year, month, mode="mean")
        if val is None:
            val = self._history_avg([entity_id], year, month)
        return val

    def get_month_avg_multi(self, entity_ids: list[str],
                            year: int, month: int) -> float | None:
        """Monatsdurchschnitt über mehrere Sensoren (z.B. 2x Tankerkönig)."""
        valid_ids = [e for e in entity_ids if e and e.strip()]
        if not valid_ids:
            return None

        values = []
        for eid in valid_ids:
            v = self.get_month_value_stats(eid, year, month, mode="mean")
            if v is not None:
                values.append(v)

        if not values:
            return self._history_avg(valid_ids, year, month)

        return round(sum(values) / len(values), 4)

    # ─────────────────────────────────────────
    #  Ersparnis → HA zurückschreiben
    # ─────────────────────────────────────────

    def push_state(self, entity_id: str, state: float,
                   unit: str = "€", friendly_name: str = "") -> bool:
        payload = json.dumps({
            "state": str(round(state, 2)),
            "attributes": {
                "unit_of_measurement": unit,
                "friendly_name":       friendly_name or entity_id,
                "icon":                "mdi:cash-multiple",
            }
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/api/states/{entity_id}",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type":  "application/json",
            },
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201)
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════════
#  InfluxDB 1.x Client
#  Nutzt HTTP Query API: GET /query?db=...&q=...
#  Authentifizierung optional (user/password als URL-Parameter)
# ═══════════════════════════════════════════════════════════════════════════════

class InfluxClient:
    """
    InfluxDB 1.x Client für Monatswert-Abfragen.

    Struktur HA → InfluxDB:
      Measurement = Einheit (z.B. "km", "kWh", "EUR/L")
      Tag         = friendly_name
      Field       = value
    """

    def __init__(self, url: str, port: int, database: str,
                 user: str = "", password: str = "",
                 meas_km:    str = "km",
                 meas_kwh:   str = "kWh",
                 meas_eur_l: str = "EUR/L"):
        self.base     = f"{url.rstrip('/')}:{port}"
        self.database = database
        self.user     = user
        self.password = password
        self.meas_km    = meas_km
        self.meas_kwh   = meas_kwh
        self.meas_eur_l = meas_eur_l

    def _query(self, q: str) -> dict | None:
        """Führt einen InfluxQL-Query aus und gibt das JSON-Ergebnis zurück."""
        params = {"db": self.database, "q": q}
        url = f"{self.base}/query?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url)
        if self.user or self.password:
            cred = base64.b64encode(
                f"{self.user}:{self.password}".encode()).decode()
            req.add_header("Authorization", f"Basic {cred}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            raise ConnectionError(f"InfluxDB Verbindungsfehler: {e.reason}")
        except Exception as e:
            raise ConnectionError(f"InfluxDB Fehler: {e}")

    def _extract_values(self, result: dict) -> list[tuple]:
        """Extrahiert [(timestamp, value), ...] aus einem InfluxDB-Ergebnis.
        Die Wertspalte heißt je nach Query "value" oder wie das Aggregat
        ("last", "first", "max", ...) – daher: erste Nicht-Zeit-Spalte."""
        try:
            series = result["results"][0]["series"][0]
            cols   = series["columns"]
            rows   = series["values"]
            t_idx  = cols.index("time")
            v_idx  = next(i for i in range(len(cols)) if i != t_idx)
            return [(r[t_idx], r[v_idx]) for r in rows
                    if r[v_idx] is not None]
        except (KeyError, IndexError, ValueError, StopIteration):
            return []

    def test_connection(self) -> bool:
        """Testet die Verbindung zur InfluxDB."""
        try:
            result = self._query("SHOW DATABASES")
            dbs = [v[0] for v in
                   result["results"][0]["series"][0]["values"]]
            return self.database in dbs
        except Exception:
            return False

    def get_friendly_names(self, measurement: str) -> list[str]:
        """Gibt alle friendly_names eines Measurements zurück."""
        try:
            result = self._query(
                f'SHOW TAG VALUES FROM "{_esc_ident(measurement)}" '
                f'WITH KEY = "friendly_name"')
            return [v[1] for v in
                    result["results"][0]["series"][0]["values"]]
        except Exception:
            return []

    def _get_month_range_query(self, year: int, month: int) -> tuple[str, str]:
        """Gibt ISO-Zeitstrings für Monatsbeginn und -ende zurück."""
        last_day = calendar.monthrange(year, month)[1]
        start = f"{year}-{month:02d}-01T00:00:00Z"
        end   = f"{year}-{month:02d}-{last_day:02d}T23:59:59Z"
        return start, end

    def get_month_delta(self, friendly_name: str, measurement: str,
                        year: int, month: int) -> float | None:
        """
        Monatliches Delta eines kumulativen Zählers (km, kWh).
        Strategie: last(value) im Monat  minus  last(value) im Vormonat.
        Robust auch wenn der Sensor selten schreibt.
        """
        # Letzter Wert im aktuellen Monat
        start, end = self._get_month_range_query(year, month)
        q_curr = (f'SELECT last("value") FROM "{_esc_ident(measurement)}" '
                  f'WHERE "friendly_name" = \'{_esc_str(friendly_name)}\' '
                  f"AND time >= '{start}' AND time <= '{end}'")
        try:
            r_curr = self._query(q_curr)
            vals_curr = self._extract_values(r_curr)
            if not vals_curr:
                return None
            last_val = vals_curr[-1][1]
        except Exception:
            return None

        # Letzter Wert VOR dem Monat – bis 12 Monate zurücksuchen
        base_val = None
        for back in range(1, 13):
            m, y = month - back, year
            while m <= 0:
                m += 12
                y -= 1
            prev_last = calendar.monthrange(y, m)[1]
            q_prev = (f'SELECT last("value") FROM "{_esc_ident(measurement)}" '
                      f'WHERE "friendly_name" = \'{_esc_str(friendly_name)}\' '
                      f"AND time >= '{y}-{m:02d}-01T00:00:00Z' "
                      f"AND time <= '{y}-{m:02d}-{prev_last:02d}T23:59:59Z'")
            try:
                r_prev = self._query(q_prev)
                vals_prev = self._extract_values(r_prev)
                if vals_prev:
                    base_val = vals_prev[-1][1]
                    break
            except Exception:
                continue

        if base_val is None:
            return None

        delta = last_val - base_val
        if delta < 0 or delta > 100000:  # Plausibilitätsprüfung
            return None
        return round(delta, 3)

    def get_month_sum(self, friendly_name: str, measurement: str,
                      year: int, month: int) -> float | None:
        """
        Monatssumme über integral/sum – für kumulative kWh-Zähler.
        Nutzt first/last-Delta, fällt auf Tagessumme zurück wenn Sensor täglich resettet.
        """
        # Erst Delta versuchen
        delta = self.get_month_delta(friendly_name, measurement, year, month)
        if delta is not None and delta > 0:
            return delta

        # Fallback: Tagesmaximum summieren (für täglich-reset Sensoren)
        start, end = self._get_month_range_query(year, month)
        q = (f'SELECT max("value") FROM "{_esc_ident(measurement)}" '
             f'WHERE "friendly_name" = \'{_esc_str(friendly_name)}\' '
             f"AND time >= '{start}' AND time <= '{end}' "
             f"GROUP BY time(1d) fill(none)")
        try:
            result = self._query(q)
            series = result["results"][0]["series"][0]
            vals   = [r[1] for r in series["values"] if r[1] is not None and r[1] > 0]
            if vals:
                return round(sum(vals), 3)
        except Exception:
            pass
        return None

    def get_month_avg(self, friendly_names: list[str], measurement: str,
                      year: int, month: int) -> float | None:
        """
        Monatsdurchschnitt über mehrere friendly_names (z.B. 2x Tankerkönig).
        Nullwerte (Tankstelle nachts geschlossen) werden ignoriert.
        """
        start, end = self._get_month_range_query(year, month)
        all_values = []

        for fn in friendly_names:
            if not fn or not fn.strip():
                continue
            # Alle Werte > 0 im Monat holen und mitteln
            q = (f'SELECT "value" FROM "{_esc_ident(measurement)}" '
                 f'WHERE "friendly_name" = \'{_esc_str(fn)}\' '
                 f"AND time >= '{start}' AND time <= '{end}' "
                 f'AND "value" > 0')
            try:
                result = self._query(q)
                vals   = self._extract_values(result)
                all_values.extend(v for _, v in vals if v > 0)
            except Exception:
                continue

        if not all_values:
            return None
        return round(sum(all_values) / len(all_values), 4)

    def diagnose(self, friendly_name: str, measurement: str,
                 year: int, month: int) -> dict:
        """Diagnosefunktion – zeigt Anzahl Einträge und Beispielwert."""
        start, end = self._get_month_range_query(year, month)
        result = {"friendly_name": friendly_name, "measurement": measurement,
                  "rows": 0, "first": None, "last": None, "error": None}
        try:
            q = (f'SELECT "value" FROM "{_esc_ident(measurement)}" '
                 f'WHERE "friendly_name" = \'{_esc_str(friendly_name)}\' '
                 f"AND time >= '{start}' AND time <= '{end}' "
                 f"ORDER BY time ASC LIMIT 100")
            r     = self._query(q)
            vals  = self._extract_values(r)
            result["rows"]  = len(vals)
            result["first"] = vals[0]  if vals else None
            result["last"]  = vals[-1] if vals else None
        except Exception as e:
            result["error"] = str(e)
        return result
