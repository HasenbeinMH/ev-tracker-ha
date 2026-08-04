from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QGroupBox, QHeaderView,
                             QMessageBox, QFrame, QCheckBox, QDialog,
                             QDialogButtonBox, QFormLayout, QDoubleSpinBox,
                             QScrollArea, QComboBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
import database as db
from ui.common import FuncWorker


class AnbieterDialog(QDialog):
    def __init__(self, parent=None, name="", gruenstrom=False):
        super().__init__(parent)
        self.setWindowTitle("Anbieter bearbeiten")
        self.setMinimumWidth(380)
        self.setStyleSheet(parent.styleSheet() if parent else "")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.inp_name = QLineEdit(name)
        self.inp_name.setMinimumWidth(220)
        self.chk_gruenstrom = QCheckBox("Grünstrom (CO2 = 0 g/kWh)")
        self.chk_gruenstrom.setChecked(gruenstrom)
        self.chk_gruenstrom.setStyleSheet("color:#e0e0e0;")
        form.addRow("Name:", self.inp_name)
        form.addRow("", self.chk_gruenstrom)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_values(self):
        return self.inp_name.text().strip(), self.chk_gruenstrom.isChecked()


def _spin(val, min_val, max_val, decimals, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(min_val, max_val)
    s.setDecimals(decimals)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    s.setFixedWidth(130)
    return s


class TabEinstellungen(QWidget):
    def __init__(self, on_anbieter_change=None, on_settings_change=None):
        super().__init__()
        self.on_anbieter_change = on_anbieter_change
        self.on_settings_change = on_settings_change
        self._build_ui()
        self._load_table()
        self._load_settings()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        inner = QWidget()
        inner.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        lbl = QLabel("⚙️ Einstellungen & Anbieterverwaltung")
        lbl.setStyleSheet("font-size:18px;font-weight:800;color:#00d4ff;")
        layout.addWidget(lbl)

        # ── Berechnungsparameter ─────────────────────────────────────────
        calc_group = QGroupBox("Berechnungsparameter")
        calc_layout = QVBoxLayout(calc_group)
        calc_layout.setSpacing(10)

        hint_calc = QLabel(
            "Passe diese Werte an dein Fahrzeug an. "
            "Änderungen wirken sich auf Dashboard, Charts und alle Berechnungen aus."
        )
        hint_calc.setStyleSheet("color:#888;font-size:12px;")
        hint_calc.setWordWrap(True)
        calc_layout.addWidget(hint_calc)

        def param_row(parent_layout, label, tooltip, widget, unit=""):
            row = QHBoxLayout()
            lbl_w = QLabel(label)
            lbl_w.setFixedWidth(260)
            lbl_w.setStyleSheet("color:#c8ccd4;font-size:12px;")
            lbl_w.setToolTip(tooltip)
            row.addWidget(lbl_w)
            row.addWidget(widget)
            if unit:
                u = QLabel(unit)
                u.setStyleSheet("color:#6b7280;font-size:11px;margin-left:4px;")
                row.addWidget(u)
            row.addStretch()
            parent_layout.addLayout(row)

        self.sp_benzin_verbrauch = _spin(7.0, 1.0, 30.0, 1)
        param_row(calc_layout, "Benziner Verbrauch:",
                  "Verbrauch deines hypothetischen Benziners für Kostenvgl.",
                  self.sp_benzin_verbrauch, "L / 100 km")

        self.sp_ev_verbrauch = _spin(15.0, 5.0, 50.0, 1)
        param_row(calc_layout, "EV Verbrauch (Referenzlinie):",
                  "Referenzwert für die Referenzlinie im kWh/100km-Chart",
                  self.sp_ev_verbrauch, "kWh / 100 km")

        self.sp_pv_preis = _spin(13.0, 0.0, 100.0, 1)
        param_row(calc_layout, "PV-Eigenverbrauch Preis:",
                  "Verrechnungspreis für selbst erzeugten Solarstrom beim Laden",
                  self.sp_pv_preis, "ct / kWh")

        self.sp_co2_benzin = _spin(2.37, 1.0, 5.0, 3)
        param_row(calc_layout, "CO2-Faktor Benzin:",
                  "kg CO2 pro Liter Benzin (Verbrennung inkl. Vorkette ~2.37)",
                  self.sp_co2_benzin, "kg CO2 / L")

        self.sp_kfz_steuer = _spin(0.0, 0.0, 5000.0, 2)
        param_row(calc_layout, "KFZ-Steuer Benziner:",
                  "Jährliche KFZ-Steuer des hypothetischen Benziners",
                  self.sp_kfz_steuer, "€ / Jahr")

        save_row = QHBoxLayout()
        btn_save_calc = QPushButton("💾 Parameter speichern")
        btn_save_calc.setFixedWidth(200)
        btn_save_calc.clicked.connect(self._save_settings)
        self.lbl_save_calc = QLabel("")
        self.lbl_save_calc.setStyleSheet("color:#5aaa78;font-size:11px;")
        save_row.addWidget(btn_save_calc)
        save_row.addWidget(self.lbl_save_calc)
        save_row.addStretch()
        calc_layout.addLayout(save_row)
        layout.addWidget(calc_group)

        # ── Lade-Anbieter ────────────────────────────────────────────────
        sep0 = QFrame()
        sep0.setFrameShape(QFrame.Shape.HLine)
        sep0.setStyleSheet("color:#252830;")
        layout.addWidget(sep0)

        group = QGroupBox("Lade-Anbieter verwalten")
        grp_layout = QVBoxLayout(group)
        grp_layout.setSpacing(12)

        hint = QLabel(
            "Alle Anbieter können bearbeitet werden. "
            "Benutzerdefinierte Anbieter können zusätzlich gelöscht werden."
        )
        hint.setStyleSheet("color:#888;font-size:12px;")
        hint.setWordWrap(True)
        grp_layout.addWidget(hint)

        add_row = QHBoxLayout()
        add_row.setSpacing(10)
        self.inp_neuer_anbieter = QLineEdit()
        self.inp_neuer_anbieter.setPlaceholderText("Neuen Anbieter (z.B. Tesla Supercharger)")
        self.inp_neuer_anbieter.returnPressed.connect(self._add_anbieter)
        self.chk_neu_gruenstrom = QCheckBox("Grünstrom")
        self.chk_neu_gruenstrom.setStyleSheet("color:#e0e0e0;")
        btn_add = QPushButton("➕ Hinzufügen")
        btn_add.clicked.connect(self._add_anbieter)
        add_row.addWidget(self.inp_neuer_anbieter, 1)
        add_row.addWidget(self.chk_neu_gruenstrom)
        add_row.addWidget(btn_add)
        grp_layout.addLayout(add_row)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Anbieter", "Grünstrom", "Typ"])
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 160)
        self.table.setMaximumHeight(260)
        self.table.doubleClicked.connect(self._edit_anbieter)
        grp_layout.addWidget(self.table)

        btn_row2 = QHBoxLayout()
        btn_edit = QPushButton("✏️ Bearbeiten")
        btn_edit.setObjectName("secondary")
        btn_edit.clicked.connect(self._edit_anbieter)
        btn_del = QPushButton("🗑 Löschen")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self._delete_selected)
        btn_row2.addWidget(btn_edit)
        btn_row2.addWidget(btn_del)
        btn_row2.addStretch()
        grp_layout.addLayout(btn_row2)
        layout.addWidget(group)

        # ── Home Assistant (optional) ─────────────────────────────────────
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#252830;")
        layout.addWidget(sep2)

        ha_header = QHBoxLayout()
        ha_lbl = QLabel("🏠 Home Assistant Verbindung")
        ha_lbl.setStyleSheet("font-size:14px;font-weight:700;color:#7a9ec4;")
        ha_optional = QLabel("optional")
        ha_optional.setStyleSheet(
            "color:#6b7280;font-size:11px;background:#1c1f28;"
            "border:1px solid #2e3340;border-radius:3px;padding:1px 6px;")
        ha_header.addWidget(ha_lbl)
        ha_header.addWidget(ha_optional)
        ha_header.addStretch()
        layout.addLayout(ha_header)

        ha_hint = QLabel(
            "Ohne Home Assistant können alle Daten manuell erfasst werden. "
            "Mit HA werden km, kWh und Benzinpreise automatisch importiert."
        )
        ha_hint.setStyleSheet("color:#6b7280;font-size:12px;")
        ha_hint.setWordWrap(True)
        layout.addWidget(ha_hint)

        self.ha_widget = HASettingsWidget()
        layout.addWidget(self.ha_widget)
        layout.addStretch()

    # ── Berechnungsparameter ──────────────────────────────────────────────

    def _load_settings(self):
        def g(key, default):
            v = db.get_einstellung(key)
            return v if v is not None else default

        self.sp_benzin_verbrauch.setValue(g("benziner_verbrauch",  7.0))
        self.sp_ev_verbrauch.setValue(    g("ev_verbrauch_default", 15.0))
        self.sp_pv_preis.setValue(        g("pv_preis_ct",          13.0))
        self.sp_co2_benzin.setValue(      g("co2_faktor_benzin",   2.37))
        self.sp_kfz_steuer.setValue(      g("kfz_steuer_benziner",  0.0))

    def _save_settings(self):
        db.set_einstellung("benziner_verbrauch",  self.sp_benzin_verbrauch.value())
        db.set_einstellung("ev_verbrauch_default", self.sp_ev_verbrauch.value())
        db.set_einstellung("pv_preis_ct",          self.sp_pv_preis.value())
        db.set_einstellung("co2_faktor_benzin",    self.sp_co2_benzin.value())
        db.set_einstellung("kfz_steuer_benziner",  self.sp_kfz_steuer.value())
        self.lbl_save_calc.setText("✓ Gespeichert")
        QTimer.singleShot(3000, lambda: self.lbl_save_calc.setText(""))
        if self.on_settings_change:
            self.on_settings_change()

    # ── Anbieter ──────────────────────────────────────────────────────────

    def _add_anbieter(self):
        name = self.inp_neuer_anbieter.text().strip()
        if not name:
            return
        gruenstrom = 1 if self.chk_neu_gruenstrom.isChecked() else 0
        db.add_lade_anbieter(name, gruenstrom)
        self.inp_neuer_anbieter.clear()
        self.chk_neu_gruenstrom.setChecked(False)
        self._load_table()
        if self.on_anbieter_change:
            self.on_anbieter_change()

    def _edit_anbieter(self):
        rows = list(set(i.row() for i in self.table.selectedItems()))
        if not rows:
            return
        row = rows[0]
        daten = db.get_lade_anbieter()
        if row >= len(daten):
            return
        d = daten[row]
        dialog = AnbieterDialog(self, d["name"], bool(d["gruenstrom"]))
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name, gruenstrom = dialog.get_values()
            if name:
                db.update_lade_anbieter(d["id"], name, 1 if gruenstrom else 0)
                self._load_table()
                if self.on_anbieter_change:
                    self.on_anbieter_change()

    def _load_table(self):
        daten = db.get_lade_anbieter()
        self.table.setRowCount(len(daten))
        self._row_ids = [d["id"] for d in daten]
        for row, d in enumerate(daten):
            ist_system = d["ist_system"] == 1
            ist_gruen  = d["gruenstrom"] == 1
            name_item  = QTableWidgetItem(d["name"])
            if ist_system:
                name_item.setForeground(QColor("#aaa"))
            self.table.setItem(row, 0, name_item)
            gruen_item = QTableWidgetItem("🌿 Ja" if ist_gruen else "—")
            gruen_item.setForeground(QColor("#00ff9d") if ist_gruen else QColor("#555"))
            gruen_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, gruen_item)
            typ_item = QTableWidgetItem("System" if ist_system else "Eigener")
            typ_item.setForeground(QColor("#888" if ist_system else "#00d4ff"))
            self.table.setItem(row, 2, typ_item)

    def _delete_selected(self):
        rows = set(i.row() for i in self.table.selectedItems())
        if not rows:
            return
        daten = db.get_lade_anbieter()
        system = [daten[r]["name"] for r in rows if r < len(daten) and daten[r]["ist_system"]]
        if system:
            QMessageBox.warning(self, "Nicht möglich",
                "System-Anbieter können nicht gelöscht werden:\n" +
                "\n".join(f"• {n}" for n in system))
            return
        antwort = QMessageBox.question(
            self, "Löschen bestätigen",
            f"{len(rows)} Anbieter löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if antwort != QMessageBox.StandardButton.Yes:
            return
        for row in rows:
            if row < len(self._row_ids):
                db.delete_lade_anbieter(self._row_ids[row])
        self._load_table()
        if self.on_anbieter_change:
            self.on_anbieter_change()

    def wait_workers(self):
        """Beim Schließen der App laufende Threads sauber beenden."""
        self.ha_widget.wait_workers()


# ── HA Settings Widget ────────────────────────────────────────────────────

class HASettingsWidget(QWidget):
    def __init__(self):
        super().__init__()
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        conn_group = QGroupBox("Verbindung")
        conn_layout = QVBoxLayout(conn_group)

        row1 = QHBoxLayout()
        self.inp_url = QLineEdit()
        self.inp_url.setPlaceholderText("http://192.168.1.x:8123")
        self.inp_url.setMinimumWidth(280)
        row1.addWidget(QLabel("URL:"))
        row1.addWidget(self.inp_url, 1)

        row2 = QHBoxLayout()
        self.inp_token = QLineEdit()
        self.inp_token.setPlaceholderText("eyJ0eXAiOiJKV1Q…  (Long-Lived Access Token)")
        self.inp_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.inp_token.setMinimumWidth(280)
        btn_test = QPushButton("Verbindung testen")
        btn_test.setObjectName("secondary")
        btn_test.clicked.connect(self._test_connection)
        self.lbl_conn = QLabel("")
        self.lbl_conn.setStyleSheet("font-size:11px;")
        row2.addWidget(QLabel("Token:"))
        row2.addWidget(self.inp_token, 1)
        row2.addWidget(btn_test)
        row2.addWidget(self.lbl_conn)

        conn_layout.addLayout(row1)
        conn_layout.addLayout(row2)
        layout.addWidget(conn_group)

        entity_group = QGroupBox("Sensor-Konfiguration  (Entity-ID für HA  ·  Friendly Name für InfluxDB)")
        entity_layout = QVBoxLayout(entity_group)

        # Spalten-Header
        hdr_row = QHBoxLayout()
        hdr_lbl   = QLabel("Sensor")
        hdr_eid   = QLabel("Entity-ID  (HA)")
        hdr_fn    = QLabel("Friendly Name  (InfluxDB)")
        for w in [hdr_lbl, hdr_eid, hdr_fn]:
            w.setStyleSheet("color:#4b5263;font-size:10px;font-weight:600;")
        hdr_lbl.setFixedWidth(185)
        hdr_row.addWidget(hdr_lbl)
        hdr_row.addWidget(hdr_eid, 1)
        hdr_row.addWidget(hdr_fn,  1)
        entity_layout.addLayout(hdr_row)

        sep_e = QFrame()
        sep_e.setFrameShape(QFrame.Shape.HLine)
        sep_e.setStyleSheet("color:#252830;")
        entity_layout.addWidget(sep_e)

        from database import HA_ENTITY_DEFAULTS
        self._entity_inputs = {}
        self._fn_inputs     = {}

        # (ha_key, fn_key, label)
        sensor_rows = [
            ("ha_odometer",         "fn_odometer",         "Odometer (km):"),
            ("ha_ev_battery",       None,                  "EV Batterie (%):"),
            ("ha_ev_range",         None,                  "Reichweite (km):"),
            ("ha_pv_production",    "fn_pv_production",    "PV Erzeugung (kWh):"),
            ("ha_grid_consumption", "fn_grid_consumption", "Netzbezug (kWh):"),
            ("ha_grid_export",      "fn_grid_export",      "Netzeinspeisung (kWh):"),
            ("ha_wallbox_energy",   "fn_wallbox_energy",   "Wallbox geladen (kWh):"),
            ("ha_tankerkoenig",     "fn_tankerkoenig",     "Tankerkönig E10 Sensor 1:"),
            ("ha_tankerkoenig_2",   "fn_tankerkoenig_2",   "Tankerkönig E10 Sensor 2:"),
        ]

        for ha_key, fn_key, label in sensor_rows:
            row = QHBoxLayout()
            lbl = QLabel(label)
            lbl.setFixedWidth(185)
            lbl.setStyleSheet("color:#7a9ec4;font-size:11px;")

            inp_eid = QLineEdit()
            inp_eid.setPlaceholderText(HA_ENTITY_DEFAULTS.get(ha_key, "") or "optional")
            self._entity_inputs[ha_key] = inp_eid

            row.addWidget(lbl)
            row.addWidget(inp_eid, 1)

            if fn_key:
                inp_fn = QLineEdit()
                inp_fn.setPlaceholderText(HA_ENTITY_DEFAULTS.get(fn_key, "") or "optional")
                self._fn_inputs[fn_key] = inp_fn
                row.addWidget(inp_fn, 1)
            else:
                row.addWidget(QLabel(""), 1)  # Platzhalter

            entity_layout.addLayout(row)

        layout.addWidget(entity_group)

        # ── InfluxDB Verbindung ───────────────────────────────────────────
        influx_group = QGroupBox("InfluxDB 1.x Verbindung  (optional)")
        influx_lay   = QVBoxLayout(influx_group)

        # Datenquelle wählen
        src_row = QHBoxLayout()
        src_lbl = QLabel("Datenquelle:")
        src_lbl.setFixedWidth(185)
        src_lbl.setStyleSheet("color:#7a9ec4;font-size:11px;")
        self.combo_datasource = QComboBox()
        self.combo_datasource.addItem("Home Assistant API", "ha")
        self.combo_datasource.addItem("InfluxDB",           "influxdb")
        self.combo_datasource.setFixedWidth(200)
        src_row.addWidget(src_lbl)
        src_row.addWidget(self.combo_datasource)
        src_row.addStretch()
        influx_lay.addLayout(src_row)

        # Verbindungsfelder
        def influx_row(label, attr, placeholder, width=280, pw=False):
            r = QHBoxLayout()
            l = QLabel(label)
            l.setFixedWidth(185)
            l.setStyleSheet("color:#7a9ec4;font-size:11px;")
            i = QLineEdit()
            i.setPlaceholderText(placeholder)
            i.setFixedWidth(width)
            if pw:
                i.setEchoMode(QLineEdit.EchoMode.Password)
            setattr(self, attr, i)
            r.addWidget(l)
            r.addWidget(i)
            r.addStretch()
            influx_lay.addLayout(r)

        influx_row("URL:",            "inp_influx_url",      "http://localhost",  220)
        influx_row("Port:",           "inp_influx_port",     "8086",              80)
        influx_row("Datenbank:",      "inp_influx_db",       "home_assistant",    180)
        influx_row("Benutzer:",       "inp_influx_user",     "optional",          180)
        influx_row("Passwort:",       "inp_influx_pw",       "optional",          180, pw=True)

        # Measurement-Namen
        sep_m = QFrame()
        sep_m.setFrameShape(QFrame.Shape.HLine)
        sep_m.setStyleSheet("color:#252830;")
        influx_lay.addWidget(sep_m)

        meas_hint = QLabel("Measurement-Namen (wie in InfluxDB konfiguriert):")
        meas_hint.setStyleSheet("color:#6b7280;font-size:11px;")
        influx_lay.addWidget(meas_hint)

        influx_row("Measurement km:",    "inp_influx_meas_km",    "km",    120)
        influx_row("Measurement kWh:",   "inp_influx_meas_kwh",   "kWh",   120)
        influx_row("Measurement EUR/L:", "inp_influx_meas_eur_l", "EUR/L", 120)

        # Test + Speichern
        influx_btn_row = QHBoxLayout()
        btn_influx_test = QPushButton("Verbindung testen")
        btn_influx_test.setObjectName("secondary")
        btn_influx_test.clicked.connect(self._test_influx)
        self.lbl_influx_conn = QLabel("")
        self.lbl_influx_conn.setStyleSheet("font-size:11px;")
        influx_btn_row.addWidget(btn_influx_test)
        influx_btn_row.addWidget(self.lbl_influx_conn)
        influx_btn_row.addStretch()
        influx_lay.addLayout(influx_btn_row)

        layout.addWidget(influx_group)

        btn_save = QPushButton("💾 Alle Einstellungen speichern")
        btn_save.clicked.connect(self._save)
        layout.addWidget(btn_save, alignment=Qt.AlignmentFlag.AlignLeft)

        self.lbl_save = QLabel("")
        self.lbl_save.setStyleSheet("color:#5aaa78;font-size:11px;")
        layout.addWidget(self.lbl_save)

    def _load(self):
        cfg = db.get_ha_settings()
        self.inp_url.setText(cfg.get("ha_url", ""))
        self.inp_token.setText(cfg.get("ha_token", ""))
        for key, inp in self._entity_inputs.items():
            inp.setText(cfg.get(key, ""))
        for key, inp in self._fn_inputs.items():
            inp.setText(cfg.get(key, ""))
        # Datenquelle
        ds = cfg.get("datasource", "ha")
        idx = self.combo_datasource.findData(ds)
        if idx >= 0:
            self.combo_datasource.setCurrentIndex(idx)
        # InfluxDB
        self.inp_influx_url.setText(cfg.get("influx_url", "http://localhost"))
        self.inp_influx_port.setText(cfg.get("influx_port", "8086"))
        self.inp_influx_db.setText(cfg.get("influx_database", "home_assistant"))
        self.inp_influx_user.setText(cfg.get("influx_user", ""))
        self.inp_influx_pw.setText(cfg.get("influx_password", ""))
        self.inp_influx_meas_km.setText(cfg.get("influx_measurement_km", "km"))
        self.inp_influx_meas_kwh.setText(cfg.get("influx_measurement_kwh", "kWh"))
        self.inp_influx_meas_eur_l.setText(cfg.get("influx_measurement_eur_l", "EUR/L"))

    def _save(self):
        settings = {
            "ha_url":   self.inp_url.text().strip(),
            "ha_token": self.inp_token.text().strip(),
            "datasource": self.combo_datasource.currentData(),
            "influx_url":              self.inp_influx_url.text().strip(),
            "influx_port":             self.inp_influx_port.text().strip(),
            "influx_database":         self.inp_influx_db.text().strip(),
            "influx_user":             self.inp_influx_user.text().strip(),
            "influx_password":         self.inp_influx_pw.text().strip(),
            "influx_measurement_km":   self.inp_influx_meas_km.text().strip() or "km",
            "influx_measurement_kwh":  self.inp_influx_meas_kwh.text().strip() or "kWh",
            "influx_measurement_eur_l":self.inp_influx_meas_eur_l.text().strip() or "EUR/L",
        }
        for key, inp in self._entity_inputs.items():
            settings[key] = inp.text().strip()
        for key, inp in self._fn_inputs.items():
            settings[key] = inp.text().strip()
        db.save_ha_settings(settings)
        self.lbl_save.setText("✓ Gespeichert")
        QTimer.singleShot(3000, lambda: self.lbl_save.setText(""))

    def _test_connection(self):
        from ha_client import HAClient
        if getattr(self, "_ha_test_worker", None) is not None and self._ha_test_worker.isRunning():
            return
        url   = self.inp_url.text().strip()
        token = self.inp_token.text().strip()
        if not url or not token:
            self.lbl_conn.setText("URL und Token eingeben")
            self.lbl_conn.setStyleSheet("color:#c4963a;font-size:11px;")
            return
        client = HAClient(url, token)
        self.lbl_conn.setText("Teste …")
        self.lbl_conn.setStyleSheet("color:#8b9ab0;font-size:11px;")
        self._ha_test_worker = FuncWorker(client.test_connection)
        self._ha_test_worker.result_ready.connect(self._on_ha_test_done)
        self._ha_test_worker.error.connect(lambda _msg: self._on_ha_test_done(False))
        self._ha_test_worker.start()

    def _on_ha_test_done(self, ok):
        if ok:
            self.lbl_conn.setText("✓ Verbunden")
            self.lbl_conn.setStyleSheet("color:#5aaa78;font-size:11px;")
        else:
            self.lbl_conn.setText("✗ Keine Verbindung")
            self.lbl_conn.setStyleSheet("color:#aa5a5a;font-size:11px;")

    def _test_influx(self):
        from ha_client import InfluxClient
        if getattr(self, "_influx_test_worker", None) is not None and self._influx_test_worker.isRunning():
            return
        url = self.inp_influx_url.text().strip() or "http://localhost"
        try:
            port = int(self.inp_influx_port.text().strip() or "8086")
        except ValueError:
            self.lbl_influx_conn.setText("✗ Port muss eine Zahl sein")
            self.lbl_influx_conn.setStyleSheet("color:#aa5a5a;font-size:11px;")
            return
        db_  = self.inp_influx_db.text().strip() or "home_assistant"
        user = self.inp_influx_user.text().strip()
        pw   = self.inp_influx_pw.text().strip()
        client = InfluxClient(url, port, db_, user, pw)
        self.lbl_influx_conn.setText("Teste …")
        self.lbl_influx_conn.setStyleSheet("color:#8b9ab0;font-size:11px;")
        self._influx_test_worker = FuncWorker(client.test_connection)
        self._influx_test_worker.result_ready.connect(
            lambda ok: self._on_influx_test_done(bool(ok), db_))
        self._influx_test_worker.error.connect(
            lambda _msg: self._on_influx_test_done(False, db_))
        self._influx_test_worker.start()

    def _on_influx_test_done(self, ok, db_name):
        if ok:
            self.lbl_influx_conn.setText(f"✓ Verbunden · Datenbank '{db_name}' gefunden")
            self.lbl_influx_conn.setStyleSheet("color:#5aaa78;font-size:11px;")
        else:
            self.lbl_influx_conn.setText("✗ Keine Verbindung oder Datenbank nicht gefunden")
            self.lbl_influx_conn.setStyleSheet("color:#aa5a5a;font-size:11px;")

    def wait_workers(self):
        """Beim Schließen der App laufende Test-Threads sauber beenden."""
        for attr in ("_ha_test_worker", "_influx_test_worker"):
            worker = getattr(self, attr, None)
            if worker is not None and worker.isRunning():
                worker.wait(5000)
