"""
HA Import Tab – Zeitbereich-Import
Zieht alle Monate zwischen Von/Bis auf einmal aus der HA Statistics-API.
Vorschautabelle: eine Zeile pro Monat, alle Felder editierbar.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFrame,
    QProgressBar, QLineEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from datetime import datetime
import database as db
import berechnung
from ha_client import HAClient, InfluxClient
from ui.common import MONATE, FuncWorker, monat_combo, jahr_combo

# (key, kurzname, entity_setting_key, einheit, fetch_mode)
IMPORT_FELDER = [
    ("km",          "km",     "ha_odometer",        "km",   "delta"),
    ("pv",          "PV kWh", "ha_pv_production",   "kWh",  "sum"),
    ("netz",        "Netz kWh","ha_grid_consumption","kWh",  "delta"),
    ("wallbox",     "WB kWh", "ha_wallbox_energy",  "kWh",  "delta"),
    ("benzin",      "€/L",    "ha_tankerkoenig",    "€/L",  "mean"),
]

# Spalten der Vorschautabelle
# Monat | km | PV kWh | Netz kWh | WB kWh | €/L | Status
COL_MONAT   = 0
COL_KM      = 1
COL_PV      = 2
COL_NETZ    = 3
COL_WALLBOX = 4
COL_BENZIN  = 5
COL_STATUS  = 6
COL_HEADERS = ["Monat", "km", "PV kWh", "Netz kWh", "WB kWh", "€/L", "Status"]
KEY_TO_COL  = {"km": COL_KM, "pv": COL_PV, "netz": COL_NETZ,
               "wallbox": COL_WALLBOX, "benzin": COL_BENZIN}


def _ha_konfiguriert() -> bool:
    cfg = db.get_ha_settings()
    return bool(cfg.get("ha_url", "").strip() and cfg.get("ha_token", "").strip())


def _monat_liste(von_y, von_m, bis_y, bis_m) -> list[tuple[int,int]]:
    """Erzeugt Liste [(year, month), ...] für den Zeitraum."""
    result = []
    y, m = von_y, von_m
    while (y, m) <= (bis_y, bis_m):
        result.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return result


# ── Worker ────────────────────────────────────────────────────────────────────

class RangeWorker(QThread):
    """Holt alle Monate im Zeitraum sequenziell aus HA oder InfluxDB."""
    monat_fertig = pyqtSignal(int, int, dict)
    fortschritt  = pyqtSignal(int, int)
    fehler       = pyqtSignal(str)

    def __init__(self, client, monate: list, entities: dict, cfg: dict,
                 influx_client=None):
        super().__init__()
        self.client        = client         # HAClient oder None
        self.influx_client = influx_client  # InfluxClient oder None
        self.monate        = monate
        self.entities      = entities
        self.cfg           = cfg

    def _fetch_influx(self, key: str, year: int, month: int) -> float | None:
        """Holt Wert für einen Key aus InfluxDB."""
        ic   = self.influx_client
        cfg  = self.cfg
        meas_km    = cfg.get("influx_measurement_km",    "km")
        meas_kwh   = cfg.get("influx_measurement_kwh",   "kWh")
        meas_eur_l = cfg.get("influx_measurement_eur_l", "EUR/L")

        if key == "km":
            fn = cfg.get("fn_odometer", "").strip()
            if not fn:
                return None
            return ic.get_month_delta(fn, meas_km, year, month)

        elif key == "pv":
            fn = cfg.get("fn_pv_production", "").strip()
            if not fn:
                return None
            return ic.get_month_sum(fn, meas_kwh, year, month)

        elif key == "netz":
            fn = cfg.get("fn_grid_consumption", "").strip()
            if not fn:
                return None
            return ic.get_month_sum(fn, meas_kwh, year, month)

        elif key == "wallbox":
            fn = cfg.get("fn_wallbox_energy", "").strip()
            if not fn:
                return None
            return ic.get_month_sum(fn, meas_kwh, year, month)

        elif key == "benzin":
            fn1 = cfg.get("fn_tankerkoenig",   "").strip()
            fn2 = cfg.get("fn_tankerkoenig_2", "").strip()
            fns = [f for f in [fn1, fn2] if f]
            if not fns:
                return None
            return ic.get_month_avg(fns, meas_eur_l, year, month)

        return None

    def run(self):
        gesamt      = len(self.monate)
        use_influx  = (self.influx_client is not None and
                       self.cfg.get("datasource", "ha") == "influxdb")

        for i, (year, month) in enumerate(self.monate):
            self.fortschritt.emit(i + 1, gesamt)
            results = {}

            for key, entity_id in self.entities.items():
                try:
                    if use_influx:
                        val = self._fetch_influx(key, year, month)
                        if val is None and self.client and entity_id:
                            val = self._fetch_ha(key, entity_id, year, month)
                    elif self.client and entity_id:
                        val = self._fetch_ha(key, entity_id, year, month)
                    else:
                        val = None
                    results[key] = val
                except Exception as e:
                    results[key] = None
                    self.fehler.emit(f"{year}-{month:02d} {key} ({entity_id}): {e}")

            self.monat_fertig.emit(year, month, results)

    def _fetch_ha(self, key: str, entity_id: str, year: int, month: int) -> float | None:
        """Holt Wert für einen Key aus HA API."""
        if key == "benzin":
            eid2 = self.cfg.get("ha_tankerkoenig_2", "").strip()
            ids  = [entity_id]
            if eid2 and eid2 != entity_id:
                ids.append(eid2)
            return self.client.get_month_avg_multi(ids, year, month)
        elif key == "km":
            return self.client.get_month_delta(entity_id, year, month)
        elif key == "pv":
            val = self.client.get_month_sum_from_daily(entity_id, year, month)
            return val if val is not None else self.client.get_month_delta(entity_id, year, month)
        else:
            return self.client.get_month_delta(entity_id, year, month)


# ── Haupt-Tab ─────────────────────────────────────────────────────────────────

class TabHAImport(QWidget):
    def __init__(self, on_change=None):
        super().__init__()
        self.on_change     = on_change
        self._monat_daten  = {}   # {(year,month): {key: val}}
        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(14)

        lbl = QLabel("📥 Datenimport – Home Assistant oder manuell")
        lbl.setStyleSheet("font-size:18px;font-weight:700;color:#7a9ec4;")
        outer.addWidget(lbl)

        # ── HA-Banner ─────────────────────────────────────────────────────
        self.banner_no_ha = QFrame()
        self.banner_no_ha.setStyleSheet(
            "QFrame{background:#1c2535;border:1px solid #2e3a4e;border-radius:6px;padding:4px;}")
        bl = QHBoxLayout(self.banner_no_ha)
        bl_lbl = QLabel(
            "ℹ️  Home Assistant nicht konfiguriert – manuelle Eingabe nutzen "
            "oder HA-URL/Token in <b>Einstellungen → Home Assistant</b> hinterlegen.")
        bl_lbl.setStyleSheet("color:#7a9ec4;font-size:12px;border:none;")
        bl_lbl.setWordWrap(True)
        bl.addWidget(bl_lbl)
        outer.addWidget(self.banner_no_ha)

        # ── HA-Sektion ────────────────────────────────────────────────────
        self.ha_group = QGroupBox("🏠 Automatisch aus Home Assistant abrufen")
        ha_lay = QVBoxLayout(self.ha_group)
        ha_lay.setSpacing(10)

        # Zeitraum Von / Bis
        range_row = QHBoxLayout()
        range_row.setSpacing(10)

        now = datetime.now()
        lbl_von = QLabel("Von:")
        lbl_von.setStyleSheet("color:#c8ccd4;font-size:12px;")

        self.combo_von_monat = monat_combo(now.month - 2 if now.month > 2 else 1)
        self.combo_von_jahr  = jahr_combo(now.year if now.month > 2 else now.year - 1)

        lbl_bis = QLabel("Bis:")
        lbl_bis.setStyleSheet("color:#c8ccd4;font-size:12px;")
        self.combo_bis_monat = monat_combo(now.month - 1 if now.month > 1 else 12)
        self.combo_bis_jahr  = jahr_combo(now.year)

        self.btn_fetch = QPushButton("⬇ Daten abrufen")
        self.btn_fetch.setMinimumWidth(160)
        self.btn_fetch.clicked.connect(self._fetch)

        self.btn_diagnose = QPushButton("🔬 Diagnose")
        self.btn_diagnose.setObjectName("secondary")
        self.btn_diagnose.setMinimumWidth(100)
        self.btn_diagnose.setToolTip(
            "Testet Statistics- und History-API für den Von-Monat")
        self.btn_diagnose.clicked.connect(self._diagnose)

        self.lbl_ha_status = QLabel("")
        self.lbl_ha_status.setStyleSheet("color:#8b9ab0;font-size:11px;")

        range_row.addWidget(lbl_von)
        range_row.addWidget(self.combo_von_monat)
        range_row.addWidget(self.combo_von_jahr)
        range_row.addSpacing(16)
        range_row.addWidget(lbl_bis)
        range_row.addWidget(self.combo_bis_monat)
        range_row.addWidget(self.combo_bis_jahr)
        range_row.addSpacing(16)
        range_row.addWidget(self.btn_fetch)
        range_row.addWidget(self.btn_diagnose)
        range_row.addWidget(self.lbl_ha_status)
        range_row.addStretch()
        ha_lay.addLayout(range_row)

        # Fortschrittsbalken
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            "QProgressBar{border:none;background:#252830;border-radius:3px;}"
            "QProgressBar::chunk{background:#2d6a9f;border-radius:3px;}")
        ha_lay.addWidget(self.progress)

        # Vorschau-Tabelle
        self.table = QTableWidget()
        self.table.setColumnCount(len(COL_HEADERS))
        self.table.setHorizontalHeaderLabels(COL_HEADERS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget{alternate-background-color:#1a1d24;}"
            "QTableWidget::item:selected{background:#2d3a50;}")
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(COL_MONAT,   QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_STATUS,  QHeaderView.ResizeMode.Fixed)
        for col in [COL_KM, COL_PV, COL_NETZ, COL_WALLBOX, COL_BENZIN]:
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_MONAT,  90)
        self.table.setColumnWidth(COL_STATUS, 75)
        ha_lay.addWidget(self.table, 1)

        tbl_hint = QLabel(
            "Alle Werte editierbar · Leeres Feld = nicht übernehmen · "
            "Zeile markieren + Entf zum Löschen")
        tbl_hint.setStyleSheet("color:#7a8899;font-size:11px;")
        ha_lay.addWidget(tbl_hint)

        # Aktions-Buttons
        action_row = QHBoxLayout()
        self.btn_uebernehmen = QPushButton("✓ Alle Werte in DB übernehmen")
        self.btn_uebernehmen.setMinimumWidth(230)
        self.btn_uebernehmen.setEnabled(False)
        self.btn_uebernehmen.clicked.connect(self._uebernehmen_ha)
        self.btn_uebernehmen.setStyleSheet(
            "QPushButton{background:#3a7a3a;color:#e8eaf0;border:none;border-radius:5px;"
            "padding:7px 16px;font-size:12px;font-weight:700;min-height:30px;}"
            "QPushButton:hover{background:#4a8a4a;}"
            "QPushButton:disabled{background:#252830;color:#8b9ab0;}")

        sep_v = QFrame()
        sep_v.setFrameShape(QFrame.Shape.VLine)
        sep_v.setStyleSheet("color:#252830;")

        self.btn_push_ha = QPushButton("📤 Ersparnis → HA senden")
        self.btn_push_ha.setObjectName("secondary")
        self.btn_push_ha.setMinimumWidth(200)
        self.btn_push_ha.clicked.connect(self._push_ersparnis)

        self.lbl_push_status = QLabel("")
        self.lbl_push_status.setStyleSheet("font-size:11px;color:#8b9ab0;")

        action_row.addWidget(self.btn_uebernehmen)
        action_row.addWidget(sep_v)
        action_row.addWidget(self.btn_push_ha)
        action_row.addWidget(self.lbl_push_status)
        action_row.addStretch()
        ha_lay.addLayout(action_row)

        outer.addWidget(self.ha_group, 1)

        # ── Separator ─────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#252830;")
        outer.addWidget(sep)

        # ── Manuelle Eingabe ──────────────────────────────────────────────
        manual_group = QGroupBox("✏️ Manuelle Eingabe  (ohne Home Assistant)")
        man_lay = QVBoxLayout(manual_group)

        man_hint = QLabel(
            "Monat wählen und Werte direkt eintragen. Nur ausgefüllte Felder werden übernommen.")
        man_hint.setStyleSheet("color:#8b9ab0;font-size:12px;")
        man_hint.setWordWrap(True)
        man_lay.addWidget(man_hint)

        man_ctrl = QHBoxLayout()
        man_ctrl.setSpacing(10)
        self.combo_man_monat = monat_combo(now.month - 1 if now.month > 1 else 12)
        self.combo_man_jahr  = jahr_combo(now.year)
        man_ctrl.addWidget(QLabel("Monat:"))
        man_ctrl.addWidget(self.combo_man_monat)
        man_ctrl.addWidget(QLabel("Jahr:"))
        man_ctrl.addWidget(self.combo_man_jahr)
        man_ctrl.addStretch()
        man_lay.addLayout(man_ctrl)

        man_fields = QHBoxLayout()
        man_fields.setSpacing(12)

        def man_inp(label, attr, placeholder):
            col = QVBoxLayout()
            lbl_w = QLabel(label)
            lbl_w.setStyleSheet("color:#7a9ec4;font-size:11px;")
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setFixedWidth(130)
            setattr(self, attr, inp)
            col.addWidget(lbl_w)
            col.addWidget(inp)
            man_fields.addLayout(col)

        man_inp("Gefahrene km:",         "m_km",     "z.B. 1250")
        man_inp("PV geladen (kWh):",     "m_pv",     "z.B. 45.2")
        man_inp("Netz/Wallbox (kWh):",   "m_wallbox","z.B. 120.5")
        man_inp("Benzinpreis (€/L):",    "m_benzin", "z.B. 1.849")
        man_fields.addStretch()
        man_lay.addLayout(man_fields)

        btn_man = QPushButton("✓ Manuelle Werte übernehmen")
        btn_man.setMinimumWidth(220)
        btn_man.clicked.connect(self._uebernehmen_manuell)
        man_lay.addWidget(btn_man)

        outer.addWidget(manual_group)

        # ── Log ───────────────────────────────────────────────────────────
        self.lbl_log = QLabel("")
        self.lbl_log.setStyleSheet(
            "color:#5aaa78;font-size:12px;padding:6px;"
            "background:#1a2a1a;border-radius:4px;border:1px solid #2a4a2a;")
        self.lbl_log.setWordWrap(True)
        self.lbl_log.setVisible(False)
        outer.addWidget(self.lbl_log)

        self._update_ha_visibility()

    # ── Hilfsmethoden UI ──────────────────────────────────────────────────────

    def _update_ha_visibility(self):
        ha_ok = _ha_konfiguriert()
        self.banner_no_ha.setVisible(not ha_ok)
        self.ha_group.setEnabled(ha_ok)

    def showEvent(self, event):
        super().showEvent(event)
        self._update_ha_visibility()

    # ── HA Fetch ──────────────────────────────────────────────────────────────

    @staticmethod
    def _make_influx_client(cfg: dict) -> InfluxClient:
        return InfluxClient(
            url      = cfg.get("influx_url",      "http://localhost"),
            port     = int(cfg.get("influx_port", "8086")),
            database = cfg.get("influx_database", "home_assistant"),
            user     = cfg.get("influx_user",     ""),
            password = cfg.get("influx_password", ""),
            meas_km    = cfg.get("influx_measurement_km",    "km"),
            meas_kwh   = cfg.get("influx_measurement_kwh",   "kWh"),
            meas_eur_l = cfg.get("influx_measurement_eur_l", "EUR/L"),
        )

    def _diagnose(self):
        """Testet die konfigurierte Datenquelle für den Von-Monat (im Hintergrund)."""
        if getattr(self, "_diag_worker", None) is not None and self._diag_worker.isRunning():
            return
        cfg        = db.get_ha_settings()
        datasource = cfg.get("datasource", "ha")
        year       = int(self.combo_von_jahr.currentText())
        month      = self.combo_von_monat.currentIndex() + 1

        if datasource == "influxdb":
            try:
                ic = self._make_influx_client(cfg)
            except Exception as e:
                QMessageBox.warning(self, "Diagnose Fehler", str(e))
                return
            fn   = cfg.get("fn_odometer", "").strip()
            meas = cfg.get("influx_measurement_km", "km")
            if not fn:
                QMessageBox.warning(self, "Diagnose",
                    "Kein Friendly Name für Odometer konfiguriert.\n"
                    "Bitte in Einstellungen → Friendly Name eintragen.")
                return

            def influx_diag():
                diag = ic.diagnose(fn, meas, year, month)
                delta = None
                if diag["rows"] > 1:
                    delta = ic.get_month_delta(fn, meas, year, month)
                return diag, delta

            self._start_diagnose(
                influx_diag,
                lambda result: self._show_influx_diag(result, year, month))
        else:
            url   = cfg.get("ha_url", "")
            token = cfg.get("ha_token", "")
            if not url or not token:
                QMessageBox.warning(self, "Diagnose",
                    "HA-URL und Token in Einstellungen hinterlegen.")
                return
            client = HAClient(url, token)
            sensor = ""
            for key, _, ek, _, _ in IMPORT_FELDER:
                sensor = cfg.get(ek, "")
                if sensor:
                    break
            if not sensor:
                QMessageBox.warning(self, "Diagnose",
                    "Keine Entity-IDs konfiguriert.")
                return
            self._start_diagnose(
                lambda: client.diagnose_entity(sensor, year, month),
                lambda diag: self._show_ha_diag(diag, year, month))

    def _start_diagnose(self, fn, on_result):
        self.btn_diagnose.setEnabled(False)
        self.lbl_ha_status.setText("Diagnose läuft …")
        self._diag_worker = FuncWorker(fn)
        self._diag_worker.result_ready.connect(on_result)
        self._diag_worker.error.connect(
            lambda msg: QMessageBox.warning(self, "Diagnose Fehler", msg))
        self._diag_worker.finished.connect(
            lambda: self.btn_diagnose.setEnabled(True))
        self._diag_worker.start()

    def _show_influx_diag(self, result, year, month):
        diag, delta = result
        lines = [
            "Quelle: InfluxDB",
            f"Friendly Name: {diag['friendly_name']}",
            f"Measurement:   {diag['measurement']}",
            f"Monat: {MONATE[month-1]} {year}",
            "",
            f"Einträge im Monat: {diag['rows']}",
        ]
        if diag["first"]:
            lines.append(f"Erster Wert: {diag['first'][1]} @ {diag['first'][0][:10]}")
        if diag["last"]:
            lines.append(f"Letzter Wert: {diag['last'][1]} @ {diag['last'][0][:10]}")
            if delta is not None:
                lines.append(f"→ Delta (gefahrene km): {delta}")
        if diag["error"]:
            lines.append(f"Fehler: {diag['error']}")
        if diag["rows"] == 0:
            lines += ["", "⚠ Keine Daten – mögliche Ursachen:",
                      "  • Friendly Name falsch geschrieben",
                      "  • Measurement-Name falsch",
                      "  • Zeitraum außerhalb der gespeicherten Daten"]
        QMessageBox.information(self, "Diagnose InfluxDB", "\n".join(lines))
        self.lbl_ha_status.setText(
            f"Diagnose: {diag['rows']} Einträge in InfluxDB")

    def _show_ha_diag(self, diag, year, month):
        lines = [
            "Quelle: HA API",
            f"Sensor: {diag['entity_id']}",
            f"Monat: {MONATE[month-1]} {year}",
            "",
            f"Statistics-API: {diag['stats_rows']} Einträge",
            f"History-API:    {diag['history_rows']} Einträge",
        ]
        if diag["history_delta"] is not None:
            lines.append(f"→ Berechneter Delta-Wert: {diag['history_delta']:.1f}")
        if diag["history_avg"] is not None:
            lines.append(f"→ Berechneter Ø-Wert:     {diag['history_avg']:.4f}")
        if diag["error"]:
            lines.append(f"Fehler: {diag['error']}")
        if diag["stats_sample"]:
            lines.append(f"\nStats-Beispiel:\n{diag['stats_sample'][0]}")
        if diag["history_sample"]:
            lines.append(f"\nHistory-Beispiel:\n{diag['history_sample'][0]}")
        if diag["stats_rows"] == 0 and diag["history_rows"] == 0:
            lines += ["", "⚠ Kein Datenzugriff",
                      "  • Entity-ID falsch?", "  • Token ungültig?"]
        elif diag["stats_rows"] == 0 and diag["history_rows"] > 0:
            lines += ["", "ℹ Keine Statistics → History-API wird verwendet (OK)"]
        QMessageBox.information(self, "Diagnose HA API", "\n".join(lines))
        self.lbl_ha_status.setText(
            f"Diagnose: Stats={diag['stats_rows']} History={diag['history_rows']}")

    def _get_client(self):
        cfg   = db.get_ha_settings()
        url   = cfg.get("ha_url", "")
        token = cfg.get("ha_token", "")
        if not url or not token:
            QMessageBox.warning(self, "Keine HA-Verbindung",
                "Bitte HA-URL und Token in den Einstellungen hinterlegen.")
            return None, None
        return HAClient(url, token), cfg

    def _fetch(self):
        cfg = db.get_ha_settings()
        datasource = cfg.get("datasource", "ha")

        # HA Client – auch bei InfluxDB-Quelle als Fallback nutzen
        client = None
        url   = cfg.get("ha_url", "")
        token = cfg.get("ha_token", "")
        if url and token:
            client = HAClient(url, token)

        # InfluxDB Client
        influx_client = None
        if datasource == "influxdb":
            try:
                influx_client = self._make_influx_client(cfg)
            except Exception as e:
                QMessageBox.warning(self, "InfluxDB Fehler",
                    f"InfluxDB konnte nicht initialisiert werden:\n{e}")
                return

        if not client and not influx_client:
            QMessageBox.warning(self, "Keine Verbindung",
                "Weder HA noch InfluxDB konfiguriert.\n"
                "Bitte Verbindungsdaten in Einstellungen hinterlegen.")
            return

        von_m = self.combo_von_monat.currentIndex() + 1
        von_y = int(self.combo_von_jahr.currentText())
        bis_m = self.combo_bis_monat.currentIndex() + 1
        bis_y = int(self.combo_bis_jahr.currentText())

        if (von_y, von_m) > (bis_y, bis_m):
            QMessageBox.warning(self, "Ungültiger Zeitraum",
                "Von-Datum muss vor Bis-Datum liegen.")
            return

        monate   = _monat_liste(von_y, von_m, bis_y, bis_m)
        n        = len(monate)
        entities = {key: cfg.get(ek, "")
                    for key, _, ek, _, _ in IMPORT_FELDER}

        # Quellenindikator in Statuszeile
        src_label = "InfluxDB" if datasource == "influxdb" else "HA API"
        self.lbl_ha_status.setText(f"Quelle: {src_label} · 0 / {n} Monate …")

        # Tabelle vorbereiten
        self.table.setRowCount(n)
        self._monat_daten = {}
        for row, (y, m) in enumerate(monate):
            self.table.setItem(row, COL_MONAT,
                QTableWidgetItem(f"{MONATE[m-1][:3]} {y}"))
            for col in range(1, len(COL_HEADERS)):
                self.table.setItem(row, col, QTableWidgetItem("…"))

        self.btn_fetch.setEnabled(False)
        self.btn_uebernehmen.setEnabled(False)
        self.lbl_log.setVisible(False)
        self.progress.setRange(0, n)
        self.progress.setValue(0)
        self.progress.setVisible(True)

        self._aktive_monate = monate  # für _on_monat_fertig

        self._worker = RangeWorker(client, monate, entities, cfg, influx_client)
        self._worker.monat_fertig.connect(self._on_monat_fertig)
        self._worker.fortschritt.connect(self._on_fortschritt)
        self._worker.fehler.connect(self._on_error)
        self._worker.finished.connect(self._on_fetch_done)
        self._worker.start()

    def _on_fortschritt(self, aktuell, gesamt):
        self.progress.setValue(aktuell)
        self.lbl_ha_status.setText(f"{aktuell} / {gesamt} Monate abgerufen …")

    def _on_monat_fertig(self, year, month, results):
        """Trägt einen Monat in die Tabelle ein."""
        if year == 0:
            return

        monate = getattr(self, "_aktive_monate", [])
        row = next((i for i, (y, m) in enumerate(monate)
                    if y == year and m == month), None)
        if row is None:
            return

        monat_key = f"{year}-{month:02d}"
        self._monat_daten[monat_key] = results

        gefunden = 0
        for key, col in KEY_TO_COL.items():
            val = results.get(key)
            if val is not None:
                item = QTableWidgetItem(f"{val:.2f}")
                item.setForeground(QColor("#c8ccd4"))
                gefunden += 1
            else:
                # Immer die "…" Platzhalter ersetzen – auch mit leerem Wert
                item = QTableWidgetItem("")
                item.setForeground(QColor("#4b5263"))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, col, item)

        # Status-Spalte
        if gefunden == 0:
            si = QTableWidgetItem("—")
            si.setForeground(QColor("#aa5a5a"))
        elif gefunden == len(KEY_TO_COL):
            si = QTableWidgetItem("✓ voll")
            si.setForeground(QColor("#5aaa78"))
        else:
            si = QTableWidgetItem(f"✓ {gefunden}/{len(KEY_TO_COL)}")
            si.setForeground(QColor("#c4963a"))
        si.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, COL_STATUS, si)

    def _on_fetch_done(self):
        self.btn_fetch.setEnabled(True)
        self.progress.setVisible(False)
        n = self.table.rowCount()
        # Zähle Zeilen mit mindestens einem Wert (nicht "…" und nicht leer)
        gefunden = 0
        for row in range(n):
            for col in [COL_KM, COL_PV, COL_NETZ, COL_WALLBOX, COL_BENZIN]:
                item = self.table.item(row, col)
                if item and item.text().strip() not in ("", "…", "—"):
                    gefunden += 1
                    break
        self.lbl_ha_status.setText(
            f"Fertig: {n} Monate abgerufen, {gefunden} mit Daten")
        self.btn_uebernehmen.setEnabled(gefunden > 0)

    def _on_error(self, msg):
        # Fehler kurz in Statuszeile anzeigen ohne Fortschritt zu überschreiben
        current = self.lbl_ha_status.text()
        if "⚠" not in current:
            self.lbl_ha_status.setText(f"{current}  ⚠ {msg[:80]}")

    # ── Übernahme HA ──────────────────────────────────────────────────────────

    def _uebernehmen_ha(self):
        """Liest aktuelle Tabellenwerte aus und schreibt in DB."""
        # Wichtig: die beim Abruf gespeicherte Monatsliste verwenden –
        # die Von/Bis-Comboboxen können danach verändert worden sein.
        monate = getattr(self, "_aktive_monate", [])
        if not monate:
            return

        gesamt_log = []
        fehler     = []

        for row, (year, month) in enumerate(monate):
            monat_key = f"{year}-{month:02d}"

            def zelle(col):
                item = self.table.item(row, col)
                return item.text().strip() if item else ""

            def parse(col):
                t = zelle(col).replace(",", ".")
                try:
                    v = float(t)
                    return v if v > 0 else None
                except ValueError:
                    return None

            data = {
                "km":      parse(COL_KM),
                "pv":      parse(COL_PV),
                "wallbox": parse(COL_WALLBOX),
                "benzin":  parse(COL_BENZIN),
            }

            if all(v is None for v in data.values()):
                continue

            log = self._schreibe_monatsdaten(monat_key, data)
            if log:
                gesamt_log.append(f"{MONATE[month-1][:3]} {year}: " +
                                  ", ".join(log))

        if gesamt_log:
            self.lbl_log.setText("\n".join(gesamt_log))
            self.lbl_log.setVisible(True)
            self.btn_uebernehmen.setEnabled(False)
            if self.on_change:
                self.on_change()
        else:
            self.lbl_log.setText("Keine Werte zum Übernehmen.")
            self.lbl_log.setVisible(True)

    # ── Manuelle Übernahme ────────────────────────────────────────────────────

    def _uebernehmen_manuell(self):
        m   = self.combo_man_monat.currentIndex() + 1
        y   = int(self.combo_man_jahr.currentText())
        key = f"{y}-{m:02d}"

        def parse(inp):
            t = inp.text().strip().replace(",", ".")
            try:
                v = float(t)
                return v if v > 0 else None
            except ValueError:
                return None

        data = {
            "km":      parse(self.m_km),
            "pv":      parse(self.m_pv),
            "wallbox": parse(self.m_wallbox),
            "benzin":  parse(self.m_benzin),
        }

        if all(v is None for v in data.values()):
            QMessageBox.warning(self, "Keine Werte",
                "Bitte mindestens einen Wert eingeben.")
            return

        log = self._schreibe_monatsdaten(key, data)
        self.lbl_log.setText(
            f"{MONATE[m-1]} {y}: " + ("  ·  ".join(log) if log else "Nichts gespeichert"))
        self.lbl_log.setVisible(True)

        for inp in [self.m_km, self.m_pv, self.m_wallbox, self.m_benzin]:
            inp.clear()

        if self.on_change:
            self.on_change()

    # ── Gemeinsame Schreib-Logik ──────────────────────────────────────────────

    def _schreibe_monatsdaten(self, monat_key: str, data: dict) -> list[str]:
        monat_idx  = int(monat_key.split("-")[1])
        monat_name = MONATE[monat_idx - 1]
        jahr       = int(monat_key.split("-")[0])
        log        = []

        pv_ct   = db.get_einstellung("pv_preis_ct") or 13.0
        aktuell = db.get_aktueller_stromtarif()
        netz_ct = aktuell["preis_kwh"] if aktuell else 30.0

        if data.get("km") is not None:
            db.set_fahrt_monat(monat_key, round(data["km"], 1))
            log.append(f"✓ {data['km']:.0f} km")

        if data.get("benzin") is not None:
            db.set_benzinpreis(monat_key, round(data["benzin"], 3))
            log.append(f"✓ {data['benzin']:.3f} €/L")

        if data.get("pv") is not None:
            kwh = data["pv"]
            if db.ladevorgang_exists(f"{monat_key}-01", kwh, "Privat – PV"):
                log.append(f"≡ PV {kwh:.1f} kWh bereits vorhanden")
            else:
                gesamt = round(kwh * pv_ct / 100, 2)
                db.add_ladevorgang(
                    f"{monat_key}-01", kwh, pv_ct, gesamt,
                    "Privat – PV", 11, "AC",
                    f"HA Import {monat_name} {jahr}")
                log.append(f"✓ PV {kwh:.1f} kWh")

        if data.get("wallbox") is not None:
            kwh = data["wallbox"]
            if db.ladevorgang_exists(f"{monat_key}-01", kwh, "Privat – Netzbezug"):
                log.append(f"≡ WB {kwh:.1f} kWh bereits vorhanden")
            else:
                gesamt = round(kwh * netz_ct / 100, 2)
                db.add_ladevorgang(
                    f"{monat_key}-01", kwh, netz_ct, gesamt,
                    "Privat – Netzbezug", 11, "AC",
                    f"HA Import {monat_name} {jahr}")
                log.append(f"✓ WB {kwh:.1f} kWh")

        return log

    # ── Ersparnis → HA ────────────────────────────────────────────────────────

    def _push_ersparnis(self):
        if getattr(self, "_push_worker", None) is not None and self._push_worker.isRunning():
            return
        client, _ = self._get_client()
        if not client:
            return

        ersparnis = round(berechnung.ersparnis_uebersicht()["ersparnis_gesamt"], 2)

        self.btn_push_ha.setEnabled(False)
        self.lbl_push_status.setText("Sende …")
        self.lbl_push_status.setStyleSheet("font-size:11px;color:#8b9ab0;")

        self._push_worker = FuncWorker(
            client.push_state,
            "sensor.ev_tracker_ersparnis_gesamt", ersparnis,
            unit="€", friendly_name="EV Tracker – Gesamtersparnis")
        self._push_worker.result_ready.connect(
            lambda ok: self._on_push_done(bool(ok), ersparnis))
        self._push_worker.error.connect(
            lambda msg: self._on_push_done(False, ersparnis))
        self._push_worker.finished.connect(
            lambda: self.btn_push_ha.setEnabled(True))
        self._push_worker.start()

    def _on_push_done(self, ok: bool, ersparnis: float):
        if ok:
            self.lbl_push_status.setText(f"✓ {ersparnis:.2f} € gesendet")
            self.lbl_push_status.setStyleSheet("font-size:11px;color:#5aaa78;")
        else:
            self.lbl_push_status.setText("Fehler beim Senden")
            self.lbl_push_status.setStyleSheet("font-size:11px;color:#aa5a5a;")

    def wait_workers(self):
        """Beim Schließen der App laufende Threads sauber beenden."""
        for attr in ("_worker", "_diag_worker", "_push_worker"):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.wait(5000)
