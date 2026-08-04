from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel,
                             QLineEdit, QDateEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QGroupBox, QHeaderView, QMessageBox)
from PyQt6.QtCore import Qt, QDate
import database as db
from ui.common import BaseTableTab, configure_table, parse_de_float


class TabStromTarif(BaseTableTab):

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        lbl = QLabel("⚡ Stromtarif-Verlauf")
        lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #00d4ff;")
        layout.addWidget(lbl)

        hint = QLabel(
            "Trage hier deinen Haushaltsstrompreis ein – bei Tarifwechsel neuen Eintrag hinzufügen. "
            "Der neueste Preis wird beim Privat-Laden als Vorschlag übernommen."
        )
        hint.setStyleSheet("color: #888; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        group = QGroupBox("Neuer Tarif")
        row = QHBoxLayout(group)
        row.setSpacing(12)

        self.inp_datum = QDateEdit(QDate.currentDate())
        self.inp_datum.setCalendarPopup(True)
        self.inp_datum.setDisplayFormat("yyyy-MM-dd")

        self.inp_preis = QLineEdit()
        self.inp_preis.setPlaceholderText("ct/kWh (z.B. 31,5)")

        self.inp_name = QLineEdit()
        self.inp_name.setPlaceholderText("Tarifname (z.B. E.ON Strom 24)")

        btn_add = QPushButton("💾 Speichern")
        btn_add.clicked.connect(self._add)

        row.addWidget(QLabel("Gültig ab:"))
        row.addWidget(self.inp_datum)
        row.addWidget(QLabel("ct/kWh:"))
        row.addWidget(self.inp_preis)
        row.addWidget(QLabel("Tarif:"))
        row.addWidget(self.inp_name, 1)
        row.addWidget(btn_add)

        layout.addWidget(group)

        self.lbl_aktuell = QLabel("")
        self.lbl_aktuell.setStyleSheet(
            "color: #00ff9d; font-size: 14px; font-weight: 700; padding: 8px;")
        layout.addWidget(self.lbl_aktuell)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Gültig ab", "ct/kWh", "Tarifname"])
        configure_table(self.table)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 100)
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
            QMessageBox.warning(self, "Fehler", "Bitte gültigen ct/kWh Wert eingeben.")
            return
        datum = self.inp_datum.date().toString("yyyy-MM-dd")
        name = self.inp_name.text()
        db.add_stromtarif(datum, preis, name)
        self.inp_preis.clear()
        self.inp_name.clear()
        self._notify_change()

    def _load_table(self):
        daten = db.get_stromtarife()
        self.table.setRowCount(len(daten))

        aktuell = db.get_aktueller_stromtarif()
        if aktuell:
            self.lbl_aktuell.setText(
                f"Aktueller Tarif: {aktuell['preis_kwh']:.2f} ct/kWh "
                f"({aktuell['tarif_name'] or 'kein Name'}) · ab {aktuell['gueltig_ab']}")
        else:
            self.lbl_aktuell.setText("Noch kein Tarif hinterlegt.")

        for row, d in enumerate(daten):
            datum_item = QTableWidgetItem(d["gueltig_ab"])
            datum_item.setData(Qt.ItemDataRole.UserRole, d["id"])
            self.table.setItem(row, 0, datum_item)
            self.table.setItem(row, 1, QTableWidgetItem(f"{d['preis_kwh']:.2f} ct"))
            self.table.setItem(row, 2, QTableWidgetItem(d["tarif_name"] or ""))

    def _delete_rows(self, rows):
        for row in rows:
            id_item = self.table.item(row, 0)
            if id_item is not None:
                tarif_id = id_item.data(Qt.ItemDataRole.UserRole)
                if tarif_id is not None:
                    db.delete_stromtarif(tarif_id)
