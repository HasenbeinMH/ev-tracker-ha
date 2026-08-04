from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QDateEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QGroupBox, QHeaderView,
                             QComboBox, QMessageBox, QRadioButton, QButtonGroup)
from PyQt6.QtCore import QDate
import database as db
from ui.common import BaseTableTab, configure_table, parse_de_float, fmt_de


def _get_pv_preis() -> float:
    return db.get_einstellung("pv_preis_ct") or 13.0


class TabLaden(BaseTableTab):

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        lbl = QLabel("🔌 Ladevorgänge erfassen")
        lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #00d4ff;")
        layout.addWidget(lbl)

        group = QGroupBox("Neuer Ladevorgang")
        form_layout = QVBoxLayout(group)
        form_layout.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(12)

        self.inp_datum = QDateEdit(QDate.currentDate())
        self.inp_datum.setCalendarPopup(True)
        self.inp_datum.setDisplayFormat("yyyy-MM-dd")

        self.inp_menge = QLineEdit()
        self.inp_menge.setPlaceholderText("kWh (z.B. 32,5)")
        self.inp_menge.textChanged.connect(self._calc_gesamt)

        self.inp_preis_kwh = QLineEdit()
        self.inp_preis_kwh.setPlaceholderText("ct/kWh")
        self.inp_preis_kwh.textChanged.connect(self._calc_gesamt)

        self.inp_gesamt = QLineEdit()
        self.inp_gesamt.setPlaceholderText("Gesamtpreis € (wird berechnet)")

        row1.addWidget(QLabel("Datum:"))
        row1.addWidget(self.inp_datum)
        row1.addWidget(QLabel("kWh:"))
        row1.addWidget(self.inp_menge)
        row1.addWidget(QLabel("ct/kWh:"))
        row1.addWidget(self.inp_preis_kwh)
        row1.addWidget(QLabel("Gesamt €:"))
        row1.addWidget(self.inp_gesamt)

        row2 = QHBoxLayout()
        row2.setSpacing(12)

        self.combo_anbieter = QComboBox()
        self.combo_anbieter.setMinimumWidth(200)
        self.combo_anbieter.currentTextChanged.connect(self._anbieter_changed)

        self.inp_leistung = QLineEdit()
        self.inp_leistung.setPlaceholderText("Ladeleistung kW (z.B. 11)")

        self.btn_ac = QRadioButton("AC")
        self.btn_dc = QRadioButton("DC")
        self.btn_ac.setChecked(True)
        self.btn_ac.setStyleSheet("color: #e0e0e0;")
        self.btn_dc.setStyleSheet("color: #e0e0e0;")
        ladetyp_grp = QButtonGroup(self)
        ladetyp_grp.addButton(self.btn_ac)
        ladetyp_grp.addButton(self.btn_dc)

        self.inp_notiz = QLineEdit()
        self.inp_notiz.setPlaceholderText("Notiz (optional)")

        btn_add = QPushButton("➕ Hinzufügen")
        btn_add.clicked.connect(self._add)

        row2.addWidget(QLabel("Anbieter:"))
        row2.addWidget(self.combo_anbieter)
        row2.addWidget(QLabel("kW:"))
        row2.addWidget(self.inp_leistung)
        row2.addWidget(self.btn_ac)
        row2.addWidget(self.btn_dc)
        row2.addWidget(self.inp_notiz, 1)
        row2.addWidget(btn_add)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setStyleSheet("color: #ffd700; font-size: 11px;")
        self.lbl_hint.setVisible(False)
        self._reload_anbieter_combo()

        form_layout.addLayout(row1)
        form_layout.addLayout(row2)
        form_layout.addWidget(self.lbl_hint)
        layout.addWidget(group)

        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Datum", "kWh", "ct/kWh", "Gesamt €", "Anbieter", "kW", "AC/DC"])
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 40)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        btn_del = QPushButton("🗑 Löschen")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self._delete_selected)
        self.lbl_total = QLabel("")
        self.lbl_total.setStyleSheet("color: #00ff9d; font-size: 13px; font-weight: 700;")
        bottom.addWidget(btn_del)
        bottom.addStretch()
        bottom.addWidget(self.lbl_total)
        layout.addLayout(bottom)

    def _reload_anbieter_combo(self):
        current = self.combo_anbieter.currentText() if self.combo_anbieter.count() > 0 else ""
        self.combo_anbieter.blockSignals(True)
        self.combo_anbieter.clear()
        for a in db.get_lade_anbieter():
            self.combo_anbieter.addItem(a["name"])
        idx = self.combo_anbieter.findText(current)
        if idx >= 0:
            self.combo_anbieter.setCurrentIndex(idx)
        self.combo_anbieter.blockSignals(False)
        self._anbieter_changed(self.combo_anbieter.currentText())

    def _anbieter_changed(self, text):
        self.lbl_hint.setStyleSheet("color: #ffd700; font-size: 11px;")
        if text == "Privat – Netzbezug":
            aktuell = db.get_aktueller_stromtarif()
            if aktuell:
                self.inp_preis_kwh.setText(str(aktuell["preis_kwh"]))
                self.inp_preis_kwh.setReadOnly(False)
                self.lbl_hint.setText(
                    f"💡 Netzbezug: Stromtarif {aktuell['preis_kwh']:.2f} ct/kWh übernommen "
                    f"({aktuell['tarif_name'] or 'kein Name'})")
            else:
                self.lbl_hint.setText("⚠️ Kein Stromtarif hinterlegt – bitte im Tab ⚡ Stromtarif eintragen.")
            self.lbl_hint.setVisible(True)
        elif text == "Privat – PV":
            pv_ct = _get_pv_preis()
            self.inp_preis_kwh.setText(str(pv_ct))
            self.inp_preis_kwh.setReadOnly(True)
            self.lbl_hint.setStyleSheet("color: #00ff9d; font-size: 11px;")
            self.lbl_hint.setText(f"☀️ PV-Eigenverbrauch: {pv_ct:.1f} ct/kWh (aus Einstellungen)")
            self.lbl_hint.setVisible(True)
        else:
            self.inp_preis_kwh.setReadOnly(False)
            self.inp_preis_kwh.clear()
            self.lbl_hint.setVisible(False)

    def _calc_gesamt(self):
        try:
            kwh = parse_de_float(self.inp_menge.text())
            ct = parse_de_float(self.inp_preis_kwh.text())
            if kwh is not None and ct is not None:
                self.inp_gesamt.setText(f"{kwh * ct / 100:.2f}")
        except ValueError:
            pass

    def _add(self):
        try:
            kwh = parse_de_float(self.inp_menge.text())
            gesamt = parse_de_float(self.inp_gesamt.text())
        except ValueError:
            kwh = gesamt = None
        if kwh is None or gesamt is None:
            QMessageBox.warning(self, "Fehler", "kWh und Gesamtpreis müssen Zahlen sein.")
            return

        try:
            preis_kwh = parse_de_float(self.inp_preis_kwh.text())
            leistung = parse_de_float(self.inp_leistung.text())
        except ValueError:
            QMessageBox.warning(self, "Fehler", "ct/kWh und kW müssen Zahlen sein (oder leer bleiben).")
            return

        if kwh <= 0:
            QMessageBox.warning(self, "Fehler", "kWh muss größer als 0 sein.")
            return

        ladetyp = "AC" if self.btn_ac.isChecked() else "DC"
        datum = self.inp_datum.date().toString("yyyy-MM-dd")
        anbieter = self.combo_anbieter.currentText()

        db.add_ladevorgang(datum, kwh, preis_kwh, gesamt, anbieter, leistung, ladetyp,
                           self.inp_notiz.text())

        self.inp_menge.clear()
        self.inp_preis_kwh.clear()
        self.inp_preis_kwh.setReadOnly(False)
        self.inp_gesamt.clear()
        self.inp_leistung.clear()
        self.inp_notiz.clear()
        self._notify_change()

    def _load_table(self):
        daten = db.get_ladevorgaenge(limit=500)
        self.table.setRowCount(len(daten))
        total_kwh = total_kosten = 0
        for row, d in enumerate(daten):
            total_kwh += d["menge_kwh"]
            total_kosten += d["gesamtpreis"]
            self.table.setItem(row, 0, QTableWidgetItem(str(d["id"])))
            self.table.setItem(row, 1, QTableWidgetItem(d["datum"]))
            self.table.setItem(row, 2, QTableWidgetItem(f"{d['menge_kwh']:.2f}"))
            self.table.setItem(row, 3, QTableWidgetItem(
                f"{d['preis_kwh']:.2f}" if d["preis_kwh"] else "—"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{d['gesamtpreis']:.2f} €"))
            self.table.setItem(row, 5, QTableWidgetItem(d["anbieter"]))
            self.table.setItem(row, 6, QTableWidgetItem(
                f"{d['ladeleistung_kw']:.0f} kW" if d["ladeleistung_kw"] else "—"))
            self.table.setItem(row, 7, QTableWidgetItem(d["ladetyp"]))
        self.lbl_total.setText(
            f"Gesamt: {fmt_de(total_kwh, 2)} kWh · {fmt_de(total_kosten, 2)} €")

    def _delete_rows(self, rows):
        for row in rows:
            id_item = self.table.item(row, 0)
            if id_item:
                db.delete_ladevorgang(int(id_item.text()))

    def refresh_anbieter(self):
        """Wird vom Einstellungen-Tab nach Änderungen aufgerufen."""
        self._reload_anbieter_combo()
