from PyQt6.QtWidgets import QMainWindow, QTabWidget, QStatusBar
import database as db
from ui.tab_dashboard import TabDashboard
from ui.tab_fahrten import TabFahrten
from ui.tab_laden import TabLaden
from ui.tab_benzin import TabBenzin
from ui.tab_strom_tarif import TabStromTarif
from ui.tab_steuer_thg import TabSteuerThg
from ui.tab_einstellungen import TabEinstellungen
from ui.tab_ha_import import TabHAImport
from ui.tab_rechnung import TabRechnung

STYLE = """
QMainWindow, QWidget {
    background-color: #12141a;
    color: #c8ccd4;
    font-family: 'Segoe UI', sans-serif;
}
QTabWidget::pane {
    border: 1px solid #252830;
    background-color: #12141a;
}
QTabBar::tab {
    background-color: #1c1f28;
    color: #8b9ab0;
    padding: 9px 18px;
    margin-right: 2px;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    font-size: 12px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #2d6a9f;
    color: #e8eaf0;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background-color: #252830;
    color: #c8ccd4;
}
QGroupBox {
    border: 1px solid #252830;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 6px;
    font-size: 12px;
    font-weight: 600;
    color: #7a9ec4;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QLineEdit, QDateEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background-color: #1c1f28;
    border: 1px solid #2e3340;
    border-radius: 5px;
    padding: 5px 9px;
    color: #c8ccd4;
    font-size: 12px;
    min-height: 26px;
}
QLineEdit:focus, QDateEdit:focus, QComboBox:focus {
    border: 1px solid #2d6a9f;
}
QLineEdit:read-only {
    background-color: #161920;
    color: #6aaa7a;
    border-color: #2a4a32;
}
QDateEdit {
    min-width: 120px;
}
QComboBox::drop-down { border: none; padding-right: 8px; }
QComboBox QAbstractItemView {
    background-color: #1c1f28;
    border: 1px solid #2e3340;
    color: #c8ccd4;
    selection-background-color: #2d6a9f;
    selection-color: #e8eaf0;
}
QPushButton {
    background-color: #2d6a9f;
    color: #e8eaf0;
    border: none;
    border-radius: 5px;
    padding: 7px 16px;
    font-size: 12px;
    font-weight: 600;
    min-height: 30px;
}
QPushButton:hover { background-color: #3578b0; }
QPushButton:pressed { background-color: #1f5580; }
QPushButton#danger {
    background-color: #8b3333;
    color: #e8eaf0;
}
QPushButton#danger:hover { background-color: #a03a3a; }
QPushButton#secondary {
    background-color: #252830;
    color: #c8ccd4;
    border: 1px solid #2e3340;
}
QPushButton#secondary:hover { background-color: #2e3340; }
QPushButton#expand {
    background-color: #1c2535;
    color: #7a9ec4;
    border: 1px solid #2e3a4e;
    padding: 3px 10px;
    min-height: 22px;
    font-size: 11px;
}
QPushButton#expand:hover { background-color: #253045; color: #a0bcd4; }
QTableWidget {
    background-color: #1c1f28;
    border: 1px solid #252830;
    border-radius: 5px;
    gridline-color: #252830;
    color: #c8ccd4;
    font-size: 12px;
}
QTableWidget::item:selected {
    background-color: #2d3a50;
    color: #e8eaf0;
}
QHeaderView::section {
    background-color: #12141a;
    color: #7a9ec4;
    padding: 7px;
    border: none;
    border-bottom: 1px solid #252830;
    font-weight: 600;
    font-size: 11px;
}
QScrollBar:vertical {
    background-color: #1c1f28;
    width: 7px;
    border-radius: 3px;
}
QScrollBar::handle:vertical {
    background-color: #2e3340;
    border-radius: 3px;
}
QStatusBar {
    background-color: #1c1f28;
    color: #8b9ab0;
    font-size: 11px;
    padding: 2px 8px;
}
QStatusBar::item {
    border: none;
}
QRadioButton { color: #c8ccd4; font-size: 12px; }
QRadioButton::indicator {
    border: 2px solid #2e3340;
    border-radius: 6px;
    width: 12px;
    height: 12px;
}
QRadioButton::indicator:checked {
    background-color: #2d6a9f;
    border-color: #2d6a9f;
}
QCheckBox { color: #c8ccd4; font-size: 12px; }
QCheckBox::indicator {
    border: 2px solid #2e3340;
    border-radius: 3px;
    width: 13px;
    height: 13px;
}
QCheckBox::indicator:checked {
    background-color: #2d6a9f;
    border-color: #2d6a9f;
}
QDialog {
    background-color: #12141a;
    color: #c8ccd4;
}
QDialogButtonBox QPushButton {
    min-width: 80px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EV Tracker – Kia EV3")
        self.setMinimumSize(1280, 800)
        self.setStyleSheet(STYLE)

        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        self.tab_dashboard   = TabDashboard()
        self.tab_fahrten     = TabFahrten(on_change=self._refresh_dashboard)
        self.tab_laden       = TabLaden(on_change=self._refresh_dashboard)
        self.tab_benzin      = TabBenzin(on_change=self._refresh_dashboard)
        self.tab_strom       = TabStromTarif(on_change=self._refresh_dashboard)
        self.tab_steuer      = TabSteuerThg(on_change=self._refresh_dashboard)
        self.tab_ha_import   = TabHAImport(on_change=self._refresh_dashboard)
        self.tab_rechnung    = TabRechnung(on_change=self._refresh_dashboard)
        self.tab_einstellungen = TabEinstellungen(
            on_anbieter_change=self._on_anbieter_change,
            on_settings_change=self._refresh_dashboard)

        tabs.addTab(self.tab_dashboard,      "Dashboard")
        tabs.addTab(self.tab_fahrten,        "Fahrten")
        tabs.addTab(self.tab_laden,          "Laden")
        tabs.addTab(self.tab_benzin,         "Benzinpreise")
        tabs.addTab(self.tab_strom,          "Stromtarif")
        tabs.addTab(self.tab_steuer,         "Steuer & THG")
        tabs.addTab(self.tab_ha_import,      "HA Import")
        tabs.addTab(self.tab_rechnung,       "📄 Rechnungen")
        tabs.addTab(self.tab_einstellungen,  "Einstellungen")

        self.setCentralWidget(tabs)

        self._status_bar = QStatusBar()
        self.setStatusBar(self._status_bar)
        self._update_statusbar()

    def _refresh_dashboard(self):
        self.tab_dashboard.refresh()
        self._update_statusbar()

    def _update_statusbar(self):
        cfg = db.get_config()
        ha  = "HA aktiv" if db.get_einstellung_str("ha_aktiv") == "1" else "kein HA"
        self._status_bar.showMessage(
            f"EV Tracker  ·  {cfg['benziner_verbrauch']:.1f} L/100km Äquivalent  ·  "
            f"PV: {cfg['pv_preis_ct']:.1f} ct/kWh  ·  "
            f"CO₂: {cfg['co2_faktor_benzin']:.2f} kg/L  ·  "
            f"{ha}  ·  Daten lokal (SQLite)"
        )

    def _on_anbieter_change(self):
        self.tab_laden.refresh_anbieter()

    def closeEvent(self, event):
        # Laufende Hintergrund-Threads beenden, sonst crasht Qt beim Schließen
        for tab in (self.tab_ha_import, self.tab_rechnung, self.tab_einstellungen):
            tab.wait_workers()
        super().closeEvent(event)
