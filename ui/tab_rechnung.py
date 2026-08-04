"""
Tab: Rechnungsimport
Laedt PDF-Laderechnungen (EWE go, EnBW, medl), zeigt editierbare Vorschau,
schreibt nach Bestätigung in die Datenbank.
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QGroupBox, QHeaderView,
    QFileDialog, QMessageBox, QTextEdit, QTabWidget,
    QFrame, QComboBox, QProgressBar, QSizePolicy
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
import os
import database as db

# Spalten der Vorschautabelle
COLS = ["Datum", "kWh", "ct/kWh", "Gesamt €", "Anbieter", "kW", "AC/DC", "Typ", "Notiz"]
COL_IDX = {name: i for i, name in enumerate(COLS)}


class ParseWorker(QThread):
    result_ready = pyqtSignal(str, list)   # anbieter, [Ladevorgang]
    error        = pyqtSignal(str)

    def __init__(self, path: str, is_text: bool = False, raw_text: str = ""):
        super().__init__()
        self.path     = path
        self.is_text  = is_text
        self.raw_text = raw_text

    def run(self):
        try:
            from pdf_parser import parse_rechnung_pdf, parse_rechnung_text
            if self.is_text:
                anbieter, vorgaenge = parse_rechnung_text(self.raw_text)
            else:
                anbieter, vorgaenge = parse_rechnung_pdf(self.path)
            self.result_ready.emit(anbieter, vorgaenge)
        except ImportError as e:
            self.error.emit(str(e))
        except IOError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"Unerwarteter Fehler: {e}")


class TabRechnung(QWidget):
    def __init__(self, on_change=None):
        super().__init__()
        self.on_change  = on_change
        self._vorgaenge = []   # aktuell in Tabelle angezeigte Roh-Daten
        self._build_ui()

    # ─────────────────────────────────────────
    #  UI AUFBAU
    # ─────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Titel
        lbl = QLabel("📄 Rechnungsimport")
        lbl.setStyleSheet("font-size: 18px; font-weight: 800; color: #00d4ff;")
        layout.addWidget(lbl)

        hint = QLabel(
            "Lade eine PDF-Rechnung (EWE go, EnBW, medl) oder füge den Rechnungstext ein. "
            "Die erkannten Ladevorgänge werden in der Vorschau angezeigt und können vor "
            "der Übernahme editiert werden."
        )
        hint.setStyleSheet("color: #6b7280; font-size: 12px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Eingabe: PDF oder Text
        input_tabs = QTabWidget()
        input_tabs.setMaximumHeight(160)

        # ---- PDF-Tab ----
        pdf_widget = QWidget()
        pdf_lay = QVBoxLayout(pdf_widget)
        pdf_lay.setContentsMargins(10, 10, 10, 10)

        pdf_row = QHBoxLayout()
        self.lbl_datei = QLabel("Keine Datei ausgewählt")
        self.lbl_datei.setStyleSheet("color: #6b7280; font-size: 12px;")
        self.lbl_datei.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        btn_browse = QPushButton("📂 PDF öffnen")
        btn_browse.setMinimumWidth(130)
        btn_browse.clicked.connect(self._browse_pdf)

        self.btn_parse_pdf = QPushButton("🔍 Auslesen")
        self.btn_parse_pdf.setMinimumWidth(110)
        self.btn_parse_pdf.setEnabled(False)
        self.btn_parse_pdf.clicked.connect(self._parse_pdf)

        pdf_row.addWidget(self.lbl_datei, 1)
        pdf_row.addWidget(btn_browse)
        pdf_row.addWidget(self.btn_parse_pdf)
        pdf_lay.addLayout(pdf_row)

        self.lbl_anbieter_erkannt = QLabel("")
        self.lbl_anbieter_erkannt.setStyleSheet("color: #5aaa78; font-size: 12px; font-weight: 600;")
        pdf_lay.addWidget(self.lbl_anbieter_erkannt)

        input_tabs.addTab(pdf_widget, "📄 PDF")

        # ---- Text-Tab ----
        text_widget = QWidget()
        text_lay = QVBoxLayout(text_widget)
        text_lay.setContentsMargins(10, 8, 10, 8)

        self.txt_roh = QTextEdit()
        self.txt_roh.setPlaceholderText(
            "Rechnungstext hier einfügen (z.B. aus E-Mail kopiert) …")
        self.txt_roh.setStyleSheet(
            "background:#1c1f28; color:#c8ccd4; border:1px solid #2e3340; border-radius:4px; font-size:11px;")
        self.txt_roh.setMaximumHeight(90)

        self.btn_parse_text = QPushButton("🔍 Text auslesen")
        self.btn_parse_text.setMinimumWidth(130)
        self.btn_parse_text.clicked.connect(self._parse_text)

        text_row = QHBoxLayout()
        text_row.addWidget(self.txt_roh, 1)
        text_row.addWidget(self.btn_parse_text)
        text_lay.addLayout(text_row)

        input_tabs.addTab(text_widget, "✉️ Text / Mail")

        layout.addWidget(input_tabs)

        # Fortschrittsbalken
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setMaximumHeight(4)
        self.progress.setStyleSheet(
            "QProgressBar{border:none;background:#1c1f28;}"
            "QProgressBar::chunk{background:#2d6a9f;}")
        layout.addWidget(self.progress)

        # Vorschau-Tabelle
        preview_group = QGroupBox("Vorschau – erkannte Ladevorgänge")
        prev_layout = QVBoxLayout(preview_group)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet(
            "QTableWidget{alternate-background-color:#1a1d24;}"
            "QTableWidget::item:selected{background:#2d3a50;}"
        )
        # Spaltenbreiten
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(COL_IDX["Datum"],     QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_IDX["Anbieter"],  QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_IDX["Notiz"],     QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(COL_IDX["Datum"],    110)
        self.table.setColumnWidth(COL_IDX["kWh"],       80)
        self.table.setColumnWidth(COL_IDX["ct/kWh"],    80)
        self.table.setColumnWidth(COL_IDX["Gesamt €"],  90)
        self.table.setColumnWidth(COL_IDX["kW"],        65)
        self.table.setColumnWidth(COL_IDX["AC/DC"],     65)
        self.table.setColumnWidth(COL_IDX["Typ"],       120)
        prev_layout.addWidget(self.table)

        # Zeile löschen + Typ-Hinweis
        tbl_btns = QHBoxLayout()
        btn_del_row = QPushButton("🗑 Zeile löschen")
        btn_del_row.setObjectName("danger")
        btn_del_row.clicked.connect(self._delete_selected_rows)

        btn_add_row = QPushButton("➕ Zeile hinzufügen")
        btn_add_row.setObjectName("secondary")
        btn_add_row.clicked.connect(self._add_empty_row)

        self.lbl_table_info = QLabel("")
        self.lbl_table_info.setStyleSheet("color: #6b7280; font-size: 11px;")

        tbl_btns.addWidget(btn_del_row)
        tbl_btns.addWidget(btn_add_row)
        tbl_btns.addStretch()
        tbl_btns.addWidget(self.lbl_table_info)
        prev_layout.addLayout(tbl_btns)

        layout.addWidget(preview_group, 1)

        # Hinweis + Übernahme
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #252830;")
        layout.addWidget(sep)

        action_row = QHBoxLayout()

        self.lbl_status = QLabel("")
        self.lbl_status.setStyleSheet("font-size: 12px; color: #6b7280;")
        self.lbl_status.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.btn_uebernehmen = QPushButton("✓ Alle Zeilen in DB übernehmen")
        self.btn_uebernehmen.setEnabled(False)
        self.btn_uebernehmen.setMinimumWidth(240)
        self.btn_uebernehmen.clicked.connect(self._uebernehmen)
        self.btn_uebernehmen.setStyleSheet(
            "QPushButton{background:#3a7a3a;color:#e8eaf0;border:none;border-radius:5px;"
            "padding:7px 16px;font-size:12px;font-weight:700;min-height:30px;}"
            "QPushButton:hover{background:#4a8a4a;}"
            "QPushButton:disabled{background:#252830;color:#555;}"
        )

        action_row.addWidget(self.lbl_status, 1)
        action_row.addWidget(self.btn_uebernehmen)
        layout.addLayout(action_row)

        # Ergebnis-Log
        self.lbl_log = QLabel("")
        self.lbl_log.setStyleSheet(
            "color:#5aaa78;font-size:12px;padding:6px;"
            "background:#1a2a1a;border-radius:4px;border:1px solid #2a4a2a;")
        self.lbl_log.setWordWrap(True)
        self.lbl_log.setVisible(False)
        layout.addWidget(self.lbl_log)

    # ─────────────────────────────────────────
    #  DATEI-DIALOG
    # ─────────────────────────────────────────

    def _browse_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "PDF-Rechnung öffnen", "",
            "PDF-Dateien (*.pdf);;Alle Dateien (*)"
        )
        if path:
            self._pdf_path = path
            self.lbl_datei.setText(os.path.basename(path))
            self.lbl_datei.setStyleSheet("color:#c8ccd4;font-size:12px;")
            self.btn_parse_pdf.setEnabled(True)
            self.lbl_anbieter_erkannt.setText("")
            self.lbl_log.setVisible(False)

    # ─────────────────────────────────────────
    #  PARSE-AUFRUFE
    # ─────────────────────────────────────────

    def _parse_pdf(self):
        if not hasattr(self, "_pdf_path"):
            return
        self._start_parse(ParseWorker(self._pdf_path))

    def _parse_text(self):
        raw = self.txt_roh.toPlainText().strip()
        if not raw:
            QMessageBox.warning(self, "Kein Text", "Bitte Rechnungstext einfügen.")
            return
        self._start_parse(ParseWorker("", is_text=True, raw_text=raw))

    def _start_parse(self, worker: ParseWorker):
        if getattr(self, "_worker", None) is not None and self._worker.isRunning():
            return
        self.progress.setVisible(True)
        self.btn_uebernehmen.setEnabled(False)
        self.btn_parse_pdf.setEnabled(False)
        self.btn_parse_text.setEnabled(False)
        self.lbl_status.setText("Wird ausgelesen …")
        self.lbl_log.setVisible(False)
        self.table.setRowCount(0)

        self._worker = worker
        self._worker.result_ready.connect(self._on_result)
        self._worker.error.connect(self._on_error)
        self._worker.finished.connect(self._on_parse_finished)
        self._worker.start()

    def _on_parse_finished(self):
        self.progress.setVisible(False)
        self.btn_parse_pdf.setEnabled(hasattr(self, "_pdf_path"))
        self.btn_parse_text.setEnabled(True)

    def wait_workers(self):
        """Beim Schließen der App laufende Parse-Threads sauber beenden."""
        worker = getattr(self, "_worker", None)
        if worker is not None and worker.isRunning():
            worker.wait(5000)

    # ─────────────────────────────────────────
    #  ERGEBNIS VERARBEITEN
    # ─────────────────────────────────────────

    def _on_result(self, anbieter: str, vorgaenge: list):
        self._vorgaenge = vorgaenge

        if anbieter != "Unbekannt":
            self.lbl_anbieter_erkannt.setText(f"✓ Anbieter erkannt: {anbieter}")
        else:
            self.lbl_anbieter_erkannt.setText("⚠ Anbieter nicht eindeutig erkannt")

        if not vorgaenge:
            self.lbl_status.setText("⚠ Keine Ladevorgänge erkannt. Bitte manuell prüfen.")
            self._add_empty_row()
            return

        self._fill_table(vorgaenge)
        n = len(vorgaenge)
        self.lbl_status.setText(
            f"{n} {'Vorgang' if n == 1 else 'Vorgänge'} erkannt – bitte prüfen und ggf. korrigieren.")
        self.btn_uebernehmen.setEnabled(True)

    def _on_error(self, msg: str):
        self.lbl_status.setText(f"Fehler: {msg}")
        QMessageBox.warning(self, "Fehler beim Auslesen", msg)

    def _fill_table(self, vorgaenge: list):
        self.table.setRowCount(0)
        for v in vorgaenge:
            self._append_row(
                datum=v.datum,
                kwh=str(round(v.menge_kwh, 3)),
                ct=str(round(v.preis_kwh, 2)),
                gesamt=str(round(v.gesamtpreis, 2)),
                anbieter=v.anbieter,
                kw=str(v.ladeleistung_kw) if v.ladeleistung_kw else "",
                ladetyp=v.ladetyp,
                quelle=v.quelle,
                notiz=v.notiz,
            )
        self.lbl_table_info.setText(
            "Alle Felder editierbar · Typ: Einzelvorgang / Monatsübersicht")

    def _append_row(self, datum="", kwh="", ct="", gesamt="",
                    anbieter="", kw="", ladetyp="AC", quelle="Einzelvorgang", notiz=""):
        row = self.table.rowCount()
        self.table.insertRow(row)

        def item(text, center=False, color=None):
            it = QTableWidgetItem(str(text))
            if center:
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if color:
                it.setForeground(QColor(color))
            return it

        self.table.setItem(row, COL_IDX["Datum"],    item(datum))
        self.table.setItem(row, COL_IDX["kWh"],      item(kwh, center=True))
        self.table.setItem(row, COL_IDX["ct/kWh"],   item(ct, center=True))
        self.table.setItem(row, COL_IDX["Gesamt €"], item(gesamt, center=True, color="#5aaa78"))
        self.table.setItem(row, COL_IDX["Anbieter"], item(anbieter))

        # kW – Combobox wäre aufwändig, plain text reicht
        self.table.setItem(row, COL_IDX["kW"],       item(kw, center=True))

        # AC/DC als Combo
        combo_typ = QComboBox()
        combo_typ.addItems(["AC", "DC"])
        combo_typ.setCurrentText(ladetyp)
        combo_typ.setStyleSheet(
            "QComboBox{background:#1c1f28;color:#c8ccd4;border:1px solid #2e3340;"
            "border-radius:3px;padding:1px 4px;font-size:11px;}"
            "QComboBox::drop-down{border:none;}"
        )
        self.table.setCellWidget(row, COL_IDX["AC/DC"], combo_typ)

        # Typ (Einzelvorgang / Monatsübersicht)
        combo_quelle = QComboBox()
        combo_quelle.addItems(["Einzelvorgang", "Monatsübersicht"])
        combo_quelle.setCurrentText(quelle)
        combo_quelle.setStyleSheet(combo_typ.styleSheet())
        self.table.setCellWidget(row, COL_IDX["Typ"], combo_quelle)

        self.table.setItem(row, COL_IDX["Notiz"], item(notiz))

    def _add_empty_row(self):
        """Leere Zeile für manuelle Eingabe."""
        self._append_row(anbieter="")
        self.btn_uebernehmen.setEnabled(True)
        self.table.scrollToBottom()

    def _delete_selected_rows(self):
        rows = sorted(set(i.row() for i in self.table.selectedItems()), reverse=True)
        for row in rows:
            self.table.removeRow(row)
        if self.table.rowCount() == 0:
            self.btn_uebernehmen.setEnabled(False)

    # ─────────────────────────────────────────
    #  ÜBERNAHME IN DB
    # ─────────────────────────────────────────

    def _uebernehmen(self):
        if self.table.rowCount() == 0:
            return

        errors = []
        imported = []
        uebersprungen = []

        for row in range(self.table.rowCount()):
            def cell(col_name):
                item = self.table.item(row, COL_IDX[col_name])
                return item.text().strip() if item else ""

            def combo_val(col_name):
                w = self.table.cellWidget(row, COL_IDX[col_name])
                return w.currentText() if w else ""

            datum    = cell("Datum")
            kwh_raw  = cell("kWh")
            ct_raw   = cell("ct/kWh")
            eur_raw  = cell("Gesamt €")
            anbieter = cell("Anbieter")
            kw_raw   = cell("kW")
            ladetyp  = combo_val("AC/DC")
            notiz    = cell("Notiz")

            # Validierung
            try:
                kwh = float(kwh_raw.replace(",", "."))
            except ValueError:
                errors.append(f"Zeile {row+1}: kWh ungültig ('{kwh_raw}')")
                continue

            try:
                gesamt = float(eur_raw.replace(",", "."))
            except ValueError:
                errors.append(f"Zeile {row+1}: Gesamtpreis ungültig ('{eur_raw}')")
                continue

            try:
                ct = float(ct_raw.replace(",", ".")) if ct_raw else round(gesamt / kwh * 100, 2)
            except (ValueError, ZeroDivisionError):
                ct = 0.0

            try:
                leistung = float(kw_raw.replace(",", ".")) if kw_raw else None
            except ValueError:
                leistung = None

            if not datum:
                errors.append(f"Zeile {row+1}: Datum fehlt")
                continue
            if not anbieter:
                errors.append(f"Zeile {row+1}: Anbieter fehlt")
                continue
            if kwh <= 0:
                errors.append(f"Zeile {row+1}: kWh muss > 0 sein")
                continue

            # Anbieter auf DB-Namen mappen
            anbieter_db = _map_anbieter(anbieter)

            # Duplikat-Schutz: dieselbe Rechnung nicht doppelt importieren
            if db.ladevorgang_exists(datum, round(kwh, 3), anbieter_db):
                uebersprungen.append(
                    f"{datum}: {kwh:.2f} kWh ({anbieter_db}) bereits vorhanden")
                continue

            db.add_ladevorgang(
                datum=datum,
                menge_kwh=round(kwh, 3),
                preis_kwh=round(ct, 2),
                gesamtpreis=round(gesamt, 2),
                anbieter=anbieter_db,
                ladeleistung_kw=leistung,
                ladetyp=ladetyp,
                notiz=notiz or "Rechnungsimport"
            )
            imported.append(f"{datum}: {kwh:.2f} kWh · {gesamt:.2f} € ({anbieter_db})")

        # Feedback
        log_parts = []
        if imported:
            log_parts.append(f"✓ {len(imported)} Vorgang/Vorgänge übernommen:")
            log_parts += [f"  · {s}" for s in imported]
        if uebersprungen:
            log_parts.append(f"≡ {len(uebersprungen)} Duplikat(e) übersprungen:")
            log_parts += [f"  · {s}" for s in uebersprungen]
        if errors:
            log_parts.append(f"⚠ {len(errors)} Fehler:")
            log_parts += [f"  · {e}" for e in errors]

        self.lbl_log.setText("\n".join(log_parts))
        self.lbl_log.setVisible(True)

        if imported or uebersprungen:
            self.table.setRowCount(0)
            self.btn_uebernehmen.setEnabled(False)
            self.lbl_status.setText(
                f"✓ {len(imported)} Einträge in Datenbank übernommen"
                + (f", {len(uebersprungen)} Duplikate übersprungen." if uebersprungen else "."))
            if imported and self.on_change:
                self.on_change()

        if errors:
            QMessageBox.warning(self, "Validierungsfehler",
                "Einige Zeilen konnten nicht übernommen werden:\n\n" +
                "\n".join(errors))


# ─────────────────────────────────────────
#  ANBIETER-MAPPING
# ─────────────────────────────────────────

_ANBIETER_MAP = {
    "ewe go":   "EWE go",
    "ewego":    "EWE go",
    "ewe-go":   "EWE go",
    "enbw":     "EnBW",
    "medl":     "medl",
    "privat – netzbezug": "Privat – Netzbezug",
    "privat – pv":        "Privat – PV",
    "privat pv":          "Privat – PV",
    "aral pulse":         "ARAL Pulse",
    "ionity":             "Ionity",
}

def _map_anbieter(name: str) -> str:
    """Normalisiert Anbieternamen auf DB-Werte."""
    key = name.strip().lower()
    if key in _ANBIETER_MAP:
        return _ANBIETER_MAP[key]
    # Teilübereinstimmung
    for k, v in _ANBIETER_MAP.items():
        if k in key:
            return v
    return name  # Unverändert übernehmen
