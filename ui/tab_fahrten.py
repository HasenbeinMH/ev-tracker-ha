from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QGroupBox, QHeaderView,
                             QMessageBox)
from PyQt6.QtGui import QColor
from datetime import datetime
import database as db
import berechnung
from ui.common import (BaseTableTab, configure_table, parse_de_float, fmt_de,
                       monat_combo, jahr_combo)


class TabFahrten(BaseTableTab):

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        lbl = QLabel("🚗 Gefahrene Kilometer (monatlich)")
        lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #00d4ff;")
        layout.addWidget(lbl)

        hint = QLabel("Trage die im Monat mit dem E-Auto gefahrenen Gesamtkilometer ein.")
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        group = QGroupBox("Monat erfassen")
        row = QHBoxLayout(group)
        row.setSpacing(12)

        now = datetime.now()
        self.combo_monat = monat_combo(now.month)
        self.combo_monat.setMinimumWidth(130)
        self.combo_jahr = jahr_combo(now.year, start=2024)

        self.inp_km = QLineEdit()
        self.inp_km.setPlaceholderText("Kilometer (z.B. 1250)")
        self.inp_km.setMinimumWidth(160)
        self.inp_km.textChanged.connect(self._update_equiv)

        btn_add = QPushButton("💾 Speichern")
        btn_add.clicked.connect(self._add)

        row.addWidget(QLabel("Monat:"))
        row.addWidget(self.combo_monat)
        row.addWidget(QLabel("Jahr:"))
        row.addWidget(self.combo_jahr)
        row.addWidget(QLabel("km:"))
        row.addWidget(self.inp_km)
        row.addWidget(btn_add)
        row.addStretch()

        layout.addWidget(group)

        self.lbl_equiv = QLabel("")
        self.lbl_equiv.setStyleSheet("color: #888; font-size: 12px; padding-left: 4px;")
        layout.addWidget(self.lbl_equiv)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Monat", "km", "Benzin-Äquivalent", "CO2-Ersparnis"])
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 160)
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

    def _update_equiv(self, text):
        try:
            km = parse_de_float(text)
        except ValueError:
            km = None
        if km is None:
            self.lbl_equiv.setText("")
            return
        cfg = db.get_config()
        liter = berechnung.benzin_liter(km, cfg["benziner_verbrauch"])
        co2_benzin = berechnung.co2_kg(liter, cfg["co2_faktor_benzin"])
        self.lbl_equiv.setText(
            f"≈ {liter:.1f} L Benzin-Äquivalent  ·  "
            f"CO2-Ersparnis (vs. Grünstrom): {co2_benzin:.1f} kg")

    def _add(self):
        try:
            km = parse_de_float(self.inp_km.text())
        except ValueError:
            km = None
        if km is None:
            QMessageBox.warning(self, "Fehler", "Bitte gültige km-Zahl eingeben.")
            return
        monat_idx = self.combo_monat.currentIndex() + 1
        jahr = int(self.combo_jahr.currentText())
        monat_key = f"{jahr}-{monat_idx:02d}"
        db.set_fahrt_monat(monat_key, km)
        self.inp_km.clear()
        self.lbl_equiv.setText("")
        self._notify_change()

    def _load_table(self):
        daten = db.get_fahrten_monate()
        cfg = db.get_config()
        benziner_l = cfg["benziner_verbrauch"]
        co2_faktor = cfg["co2_faktor_benzin"]
        self.table.setRowCount(len(daten))
        total_km = 0
        for row, d in enumerate(daten):
            total_km += d["km"]
            liter = berechnung.benzin_liter(d["km"], benziner_l)
            co2 = berechnung.co2_kg(liter, co2_faktor)
            self.table.setItem(row, 0, QTableWidgetItem(d["monat"]))
            self.table.setItem(row, 1, QTableWidgetItem(f"{fmt_de(d['km'])} km"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{liter:.1f} L"))
            item = QTableWidgetItem(f"{co2:.1f} kg")
            item.setForeground(QColor("#00ff9d"))
            self.table.setItem(row, 3, item)

        gesamt_liter = berechnung.benzin_liter(total_km, benziner_l)
        gesamt_co2 = berechnung.co2_kg(gesamt_liter, co2_faktor)
        self.lbl_total.setText(
            f"Gesamt: {fmt_de(total_km)} km  ·  {fmt_de(gesamt_liter, 1)} L Äquivalent"
            f"  ·  {fmt_de(gesamt_co2, 1)} kg CO2 gespart")

    def _delete_rows(self, rows):
        for row in rows:
            monat_item = self.table.item(row, 0)
            if monat_item:
                db.delete_fahrt_monat(monat_item.text())
