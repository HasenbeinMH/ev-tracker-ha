"""
Gemeinsame UI-Bausteine: Konstanten, Zahlen-Parsing/-Formatierung,
Monat/Jahr-Comboboxen, Hintergrund-Worker und Tab-Basisklasse.
"""
from datetime import datetime

from PyQt6.QtWidgets import QWidget, QTableWidget, QComboBox, QMessageBox
from PyQt6.QtCore import QThread, pyqtSignal

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]


def parse_de_float(text: str | None) -> float | None:
    """Parst eine Zahl mit Komma oder Punkt als Dezimaltrenner.
    Gibt None bei leerem Text zurück, wirft ValueError bei ungültiger Eingabe."""
    t = (text or "").strip().replace(",", ".")
    if not t:
        return None
    return float(t)


def fmt_de(value: float, decimals: int = 0) -> str:
    """Deutsche Zahlformatierung: 12345.67 → '12.345,67'."""
    s = f"{value:,.{decimals}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def monat_combo(default_month: int | None = None) -> QComboBox:
    """Combobox mit den 12 Monatsnamen; default_month ist 1-basiert."""
    c = QComboBox()
    c.setMinimumWidth(120)
    for m in MONATE:
        c.addItem(m)
    month = default_month if default_month else datetime.now().month
    c.setCurrentIndex(max(0, min(month - 1, 11)))
    return c


def jahr_combo(default_year: int | None = None, start: int = 2023) -> QComboBox:
    """Combobox mit Jahren von start bis übernächstes Jahr."""
    now = datetime.now()
    c = QComboBox()
    c.setMinimumWidth(90)
    for y in range(start, now.year + 2):
        c.addItem(str(y))
    c.setCurrentText(str(default_year or now.year))
    return c


def configure_table(table: QTableWidget):
    """Standard-Konfiguration für Daten-Tabellen."""
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)


class FuncWorker(QThread):
    """Führt eine beliebige Funktion in einem Hintergrund-Thread aus,
    damit HTTP-Aufrufe die GUI nicht einfrieren."""
    result_ready = pyqtSignal(object)
    error        = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn     = fn
        self._args   = args
        self._kwargs = kwargs

    def run(self):
        try:
            self.result_ready.emit(self._fn(*self._args, **self._kwargs))
        except Exception as e:
            self.error.emit(str(e))


class BaseTableTab(QWidget):
    """Gemeinsames Grundgerüst der Daten-Tabs: on_change-Callback,
    Neuladen nach Änderungen und Löschen mit Bestätigung."""

    def __init__(self, on_change=None):
        super().__init__()
        self.on_change = on_change
        self._build_ui()
        self._load_table()

    def _build_ui(self):
        raise NotImplementedError

    def _load_table(self):
        raise NotImplementedError

    def _notify_change(self):
        self._load_table()
        if self.on_change:
            self.on_change()

    def _delete_table(self) -> QTableWidget:
        """Tabelle, auf die sich _delete_selected bezieht (überschreibbar)."""
        return self.table

    def _delete_rows(self, rows: list[int]):
        """Löscht die Datensätze der übergebenen Tabellenzeilen."""
        raise NotImplementedError

    def _delete_selected(self):
        table = self._delete_table()
        rows = sorted(set(i.row() for i in table.selectedItems()))
        if not rows:
            return
        antwort = QMessageBox.question(
            self, "Löschen bestätigen",
            f"{len(rows)} Eintrag löschen?" if len(rows) == 1
            else f"{len(rows)} Einträge löschen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if antwort != QMessageBox.StandardButton.Yes:
            return
        self._delete_rows(rows)
        self._notify_change()
