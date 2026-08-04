from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QDateEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QGroupBox, QHeaderView,
                             QComboBox, QMessageBox, QFrame)
from PyQt6.QtCore import QDate
from PyQt6.QtGui import QColor
import database as db
from ui.common import BaseTableTab, configure_table, parse_de_float

THG_ANBIETER = [
    "ADAC", "Deutsche Emissionshandelsgesellschaft (DEHSt)",
    "Volkswagen Financial Services", "finn.auto", "zinq", "Sonstige"
]


class TabSteuerThg(BaseTableTab):

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        lbl = QLabel("💶 KFZ-Steuer & THG-Quote")
        lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #00d4ff;")
        layout.addWidget(lbl)

        # KFZ-Steuer Block
        kfz_group = QGroupBox("KFZ-Steuer Benziner (einmalig festlegen)")
        kfz_row = QHBoxLayout(kfz_group)
        kfz_row.setSpacing(12)

        self.inp_kfz = QLineEdit()
        self.inp_kfz.setPlaceholderText("€/Jahr (z.B. 168,00)")

        btn_kfz = QPushButton("💾 Speichern")
        btn_kfz.clicked.connect(self._save_kfz)

        self.lbl_kfz_info = QLabel("")
        self.lbl_kfz_info.setStyleSheet("color: #ffd700; font-size: 13px;")

        kfz_row.addWidget(QLabel("Benziner KFZ-Steuer €/Jahr:"))
        kfz_row.addWidget(self.inp_kfz)
        kfz_row.addWidget(btn_kfz)
        kfz_row.addWidget(self.lbl_kfz_info)
        kfz_row.addStretch()

        layout.addWidget(kfz_group)

        # KFZ-Steuer Ersparnis Anzeige
        self.lbl_ersparnis = QLabel("")
        self.lbl_ersparnis.setStyleSheet(
            "color: #00ff9d; font-size: 16px; font-weight: 700; padding: 10px 4px;")
        layout.addWidget(self.lbl_ersparnis)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #2a2d3e;")
        layout.addWidget(sep)

        # THG-Quote
        thg_lbl = QLabel("🌿 THG-Quote Einträge")
        thg_lbl.setStyleSheet("font-size: 15px; font-weight: 700; color: #00d4ff;")
        layout.addWidget(thg_lbl)

        thg_group = QGroupBox("Neuer THG-Eintrag")
        thg_row = QHBoxLayout(thg_group)
        thg_row.setSpacing(12)

        self.inp_thg_datum = QDateEdit(QDate.currentDate())
        self.inp_thg_datum.setCalendarPopup(True)
        self.inp_thg_datum.setDisplayFormat("yyyy-MM-dd")

        self.inp_thg_betrag = QLineEdit()
        self.inp_thg_betrag.setPlaceholderText("Betrag € (z.B. 75,00)")

        self.combo_thg_anbieter = QComboBox()
        self.combo_thg_anbieter.addItems(THG_ANBIETER)
        self.combo_thg_anbieter.setEditable(True)

        self.inp_thg_notiz = QLineEdit()
        self.inp_thg_notiz.setPlaceholderText("Notiz (optional)")

        btn_thg_add = QPushButton("➕ Hinzufügen")
        btn_thg_add.clicked.connect(self._add_thg)

        thg_row.addWidget(QLabel("Datum:"))
        thg_row.addWidget(self.inp_thg_datum)
        thg_row.addWidget(QLabel("Betrag €:"))
        thg_row.addWidget(self.inp_thg_betrag)
        thg_row.addWidget(QLabel("Anbieter:"))
        thg_row.addWidget(self.combo_thg_anbieter)
        thg_row.addWidget(self.inp_thg_notiz, 1)
        thg_row.addWidget(btn_thg_add)

        layout.addWidget(thg_group)

        self.thg_table = QTableWidget()
        self.thg_table.setColumnCount(4)
        self.thg_table.setHorizontalHeaderLabels(["Datum", "Betrag €", "Anbieter", "Notiz"])
        configure_table(self.thg_table)
        self.thg_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.thg_table.setColumnWidth(0, 120)
        self.thg_table.setColumnWidth(1, 100)
        layout.addWidget(self.thg_table, 1)

        bottom = QHBoxLayout()
        btn_del = QPushButton("🗑 THG löschen")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self._delete_selected)
        self.lbl_thg_total = QLabel("")
        self.lbl_thg_total.setStyleSheet("color: #00ff9d; font-size: 13px; font-weight: 700;")
        bottom.addWidget(btn_del)
        bottom.addStretch()
        bottom.addWidget(self.lbl_thg_total)
        layout.addLayout(bottom)

    def _save_kfz(self):
        try:
            val = parse_de_float(self.inp_kfz.text())
        except ValueError:
            val = None
        if val is None:
            QMessageBox.warning(self, "Fehler", "Bitte gültigen Betrag eingeben.")
            return
        db.set_einstellung("kfz_steuer_benziner", val)
        self._update_ersparnis(val)
        self.lbl_kfz_info.setText(f"✓ {val:.2f} €/Jahr gespeichert")
        if self.on_change:
            self.on_change()

    def _update_ersparnis(self, val):
        self.lbl_ersparnis.setText(
            f"KFZ-Steuer Ersparnis: {val:.2f} €/Jahr  "
            f"(Benziner: {val:.2f} € − E-Auto: 0,00 € = {val:.2f} € gespart)")

    def _add_thg(self):
        try:
            betrag = parse_de_float(self.inp_thg_betrag.text())
        except ValueError:
            betrag = None
        if betrag is None:
            QMessageBox.warning(self, "Fehler", "Bitte gültigen Betrag eingeben.")
            return
        datum = self.inp_thg_datum.date().toString("yyyy-MM-dd")
        anbieter = self.combo_thg_anbieter.currentText()
        db.add_thg(datum, betrag, anbieter, self.inp_thg_notiz.text())
        self.inp_thg_betrag.clear()
        self.inp_thg_notiz.clear()
        self._notify_change()

    def _load_table(self):
        kfz = db.get_einstellung("kfz_steuer_benziner") or 0.0
        if kfz > 0:
            self.inp_kfz.setText(f"{kfz:.2f}")
            self.lbl_kfz_info.setText(f"✓ {kfz:.2f} €/Jahr gespeichert")
            self._update_ersparnis(kfz)
        self._load_thg_table()

    def _load_thg_table(self):
        daten = db.get_thg_eintraege()
        self.thg_table.setRowCount(len(daten))
        self._thg_ids = [d["id"] for d in daten]
        total = 0
        for row, d in enumerate(daten):
            total += d["betrag"]
            self.thg_table.setItem(row, 0, QTableWidgetItem(d["datum"]))
            item = QTableWidgetItem(f"{d['betrag']:.2f} €")
            item.setForeground(QColor("#00ff9d"))
            self.thg_table.setItem(row, 1, item)
            self.thg_table.setItem(row, 2, QTableWidgetItem(d["anbieter"]))
            self.thg_table.setItem(row, 3, QTableWidgetItem(d["notiz"] or ""))

        self.lbl_thg_total.setText(f"THG Gesamt: {total:.2f} €")

    def _delete_table(self):
        return self.thg_table

    def _delete_rows(self, rows):
        for row in rows:
            if row < len(self._thg_ids):
                db.delete_thg(self._thg_ids[row])
