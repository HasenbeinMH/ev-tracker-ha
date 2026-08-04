from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QTableWidget, QTableWidgetItem,
                             QGroupBox, QHeaderView, QMessageBox)
from PyQt6.QtGui import QColor
from datetime import datetime
import database as db
from ui.common import BaseTableTab, configure_table, parse_de_float, monat_combo, jahr_combo


class TabBenzin(BaseTableTab):

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        lbl = QLabel("⛽ Benzinpreise (Monatsdurchschnitt)")
        lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #00d4ff;")
        layout.addWidget(lbl)

        group = QGroupBox("Monatspreis eingeben")
        row = QHBoxLayout(group)
        row.setSpacing(12)

        now = datetime.now()
        self.combo_monat = monat_combo(now.month)
        self.combo_jahr = jahr_combo(now.year)

        self.inp_preis = QLineEdit()
        self.inp_preis.setPlaceholderText("Preis €/L (z.B. 1,849)")

        btn_add = QPushButton("💾 Speichern")
        btn_add.clicked.connect(self._add)

        row.addWidget(QLabel("Monat:"))
        row.addWidget(self.combo_monat)
        row.addWidget(QLabel("Jahr:"))
        row.addWidget(self.combo_jahr)
        row.addWidget(QLabel("€/Liter:"))
        row.addWidget(self.inp_preis)
        row.addWidget(btn_add)
        row.addStretch()

        layout.addWidget(group)

        self.lbl_akt = QLabel("")
        self.lbl_akt.setStyleSheet("color: #888; font-size: 12px; padding-left: 4px;")
        layout.addWidget(self.lbl_akt)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Monat", "€/Liter", "Tendenz"])
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        bottom = QHBoxLayout()
        btn_del = QPushButton("🗑 Löschen")
        btn_del.setObjectName("danger")
        btn_del.clicked.connect(self._delete_selected)
        bottom.addWidget(btn_del)
        bottom.addStretch()
        layout.addLayout(bottom)

    def _add(self):
        try:
            preis = parse_de_float(self.inp_preis.text())
        except ValueError:
            preis = None
        if preis is None:
            QMessageBox.warning(self, "Fehler", "Bitte gültigen Preis eingeben.")
            return
        monat_idx = self.combo_monat.currentIndex() + 1
        jahr = int(self.combo_jahr.currentText())
        monat_key = f"{jahr}-{monat_idx:02d}"
        db.set_benzinpreis(monat_key, preis)
        self.inp_preis.clear()
        self._notify_change()

    def _load_table(self):
        daten = db.get_benzinpreise()
        self.table.setRowCount(len(daten))

        if daten:
            avg = sum(d["preis_liter"] for d in daten) / len(daten)
            self.lbl_akt.setText(
                f"Ø Durchschnitt: {avg:.3f} €/L · {len(daten)} Monate erfasst")
        else:
            self.lbl_akt.setText("")

        for row, d in enumerate(daten):
            self.table.setItem(row, 0, QTableWidgetItem(d["monat"]))
            self.table.setItem(row, 1, QTableWidgetItem(f"{d['preis_liter']:.3f} €"))

            # Tendenz
            if row > 0:
                prev = daten[row - 1]["preis_liter"]
                diff = d["preis_liter"] - prev
                if diff > 0.005:
                    tendenz = f"▲ +{diff:.3f}"
                    color = "#ff6b35"
                elif diff < -0.005:
                    tendenz = f"▼ {diff:.3f}"
                    color = "#00ff9d"
                else:
                    tendenz = "→ stabil"
                    color = "#888"
                item = QTableWidgetItem(tendenz)
                item.setForeground(QColor(color))
                self.table.setItem(row, 2, item)
            else:
                self.table.setItem(row, 2, QTableWidgetItem("—"))

    def _delete_rows(self, rows):
        for row in rows:
            monat_item = self.table.item(row, 0)
            if monat_item:
                db.delete_benzinpreis(monat_item.text())
