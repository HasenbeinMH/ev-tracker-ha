import os

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QScrollArea, QFrame, QPushButton, QDialog,
                             QVBoxLayout as QVBox, QSizePolicy, QGridLayout)
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineWidgets import QWebEngineView
import database as db
import berechnung
import charts
from ui.common import fmt_de

BG = "#12141a"
CARD = "#1c1f28"
BORDER = "#252830"

# Plotly-JS lokal ausliefern, damit die Charts auch ohne Internet funktionieren.
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PLOTLY_JS_PATH = os.path.join(_ROOT_DIR, "plotly.min.js")
_BASE_URL = QUrl.fromLocalFile(_ROOT_DIR + os.sep)
PLOTLY_JS = '<script src="plotly.min.js"></script>'


def _ensure_plotly_js():
    """Schreibt plotly.min.js einmalig aus dem plotly-Paket neben die App."""
    if not os.path.exists(_PLOTLY_JS_PATH):
        import plotly.offline
        with open(_PLOTLY_JS_PATH, "w", encoding="utf-8") as f:
            f.write(plotly.offline.get_plotlyjs())


def _html_page(body, bg=BG):
    return f"""<!DOCTYPE html><html><head>{PLOTLY_JS}
    <style>
        body {{ margin:0; padding:0; background:{bg}; overflow:hidden; }}
        .plotly-graph-div {{ width:100% !important; }}
    </style></head><body>{body}</body></html>"""


def stat_card(label, value, unit="", color="#4a90c4"):
    frame = QFrame()
    frame.setStyleSheet(f"""
        QFrame {{
            background-color: {CARD};
            border: 1px solid {BORDER};
            border-radius: 7px;
        }}
    """)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.setSpacing(2)

    val_label = QLabel(f"{value}")
    val_label.setStyleSheet(
        f"font-size: 20px; font-weight: 700; color: {color}; border: none;")

    unit_label = QLabel(unit)
    unit_label.setStyleSheet("font-size: 11px; color: #6b7280; border: none;")

    lbl = QLabel(label)
    lbl.setStyleSheet("font-size: 10px; color: #4b5263; border: none; margin-top: 2px;")

    top = QHBoxLayout()
    top.addWidget(val_label)
    top.addWidget(unit_label)
    top.addStretch()

    layout.addLayout(top)
    layout.addWidget(lbl)
    return frame


class ChartPopup(QDialog):
    def __init__(self, parent, title, html):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1000, 580)
        self.setStyleSheet(parent.styleSheet())
        layout = QVBox(self)
        layout.setContentsMargins(8, 8, 8, 8)
        view = QWebEngineView()
        view.setHtml(_html_page(html, bg=BG), _BASE_URL)
        layout.addWidget(view)


class ChartCard(QFrame):
    """Kompakte Chart-Karte mit Aufklapp-Button"""
    def __init__(self, title, parent_widget):
        super().__init__()
        self.title_text = title
        self.parent_widget = parent_widget
        self.current_html = ""
        self._large_fn = None
        self.setStyleSheet(f"""
            QFrame {{
                background-color: {CARD};
                border: 1px solid {BORDER};
                border-radius: 7px;
            }}
        """)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet(f"background: transparent; border: none; border-bottom: 1px solid {BORDER};")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(10, 5, 8, 5)

        lbl = QLabel(title)
        lbl.setStyleSheet("font-size: 11px; font-weight: 600; color: #7a9ec4; border: none;")

        btn_expand = QPushButton("⤢ Vergrößern")
        btn_expand.setObjectName("expand")
        btn_expand.setFixedHeight(22)
        btn_expand.clicked.connect(self._open_popup)

        header_layout.addWidget(lbl)
        header_layout.addStretch()
        header_layout.addWidget(btn_expand)

        layout.addWidget(header)

        # Chart view - kompakt
        self.view = QWebEngineView()
        self.view.setFixedHeight(185)
        self.view.setStyleSheet("background: transparent; border: none;")
        layout.addWidget(self.view)

    def set_chart(self, small_html, large_fn=None):
        """large_fn ist ein callable, das erst beim Öffnen des Popups ausgeführt wird (lazy)."""
        self._large_fn = large_fn
        self.view.setHtml(_html_page(small_html), _BASE_URL)

    def _open_popup(self):
        html = self._large_fn() if self._large_fn else ""
        popup = ChartPopup(self.parent_widget, self.title_text, html)
        popup.exec()


class TabDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self._chart_data = {}
        _ensure_plotly_js()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 16, 16, 8)
        self.main_layout.setSpacing(12)

        title = QLabel("EV Tracker – Übersicht")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #7a9ec4;")
        self.main_layout.addWidget(title)

        # Stat cards
        self.stats_layout = QHBoxLayout()
        self.stats_layout.setSpacing(10)
        self.main_layout.addLayout(self.stats_layout)

        # Charts Grid 2x4
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.charts_widget = QWidget()
        self.charts_widget.setStyleSheet("background: transparent;")
        self.grid = QGridLayout(self.charts_widget)
        self.grid.setSpacing(10)
        self.grid.setContentsMargins(0, 0, 0, 0)

        chart_defs = [
            ("monatlich",  "Monatliche Kosten & Ersparnis"),
            ("kosten",     "Kraftstoffkosten Vergleich"),
            ("co2",        "CO2-Ersparnis"),
            ("verbrauch",  "Verbrauch kWh/100km"),
            ("benzin",     "Benzinpreisentwicklung"),
            ("strom",      "Stromtarifverlauf"),
            ("anbieter",   "Ladekosten nach Anbieter"),
            ("thg",        "THG-Quote Erträge"),
        ]

        self.chart_cards = {}
        for i, (key, label) in enumerate(chart_defs):
            card = ChartCard(label, self)
            self.chart_cards[key] = card
            row, col = divmod(i, 2)
            self.grid.addWidget(card, row, col)

        scroll.setWidget(self.charts_widget)
        self.main_layout.addWidget(scroll, 1)

    def refresh(self):
        fahrten = db.get_fahrten_alle_als_liste()
        lade = db.get_ladevorgaenge(limit=10000)
        benzin = db.get_benzinpreise()
        stromtarife = db.get_stromtarife()
        thg = db.get_thg_eintraege()
        cfg = db.get_config()

        benziner_l  = cfg["benziner_verbrauch"]
        co2_faktor  = cfg["co2_faktor_benzin"]
        ev_ref      = cfg["ev_verbrauch"]

        kz = berechnung.ersparnis_uebersicht()

        # Stat cards neu aufbauen
        while self.stats_layout.count():
            item = self.stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        cards = [
            ("Gesamtstrecke",     fmt_de(kz["gesamt_km"]),           "km",  "#4a90c4"),
            ("Geladene Energie",  fmt_de(kz["gesamt_kwh"], 1),       "kWh", "#7a6aaa"),
            ("Kraftst.-Ersparnis",fmt_de(kz["ersparnis_kraft"], 2),  "€",   "#5aaa78"),
            ("Steuer-Ersparnis",  fmt_de(kz["kfz_steuer"], 2),       "€",   "#c4963a"),
            ("THG-Ertrag",        fmt_de(kz["thg_gesamt"], 2),       "€",   "#5aaa78"),
            ("CO2 gespart",       fmt_de(kz["co2_gespart"]),         "kg",  "#3a9aaa"),
            ("Gesamt-Ersparnis",  fmt_de(kz["ersparnis_gesamt"], 2), "€",   "#4a90c4"),
        ]
        for label, val, unit, color in cards:
            self.stats_layout.addWidget(stat_card(label, val, unit, color))

        # Charts rendern – large_fn ist lazy (wird erst beim Klick auf „Vergrößern" ausgeführt)
        def render(key, small_html, large_fn):
            self.chart_cards[key].set_chart(small_html, large_fn)

        render("monatlich",
               charts.chart_monatliche_ersparnis(fahrten, benzin, lade, benziner_l=benziner_l, large=False),
               lambda: charts.chart_monatliche_ersparnis(fahrten, benzin, lade, benziner_l=benziner_l, large=True))
        render("kosten",
               charts.chart_kosten_vergleich(kz["benzin_kosten"], kz["strom_kosten"], large=False),
               lambda: charts.chart_kosten_vergleich(kz["benzin_kosten"], kz["strom_kosten"], large=True))
        render("co2",
               charts.chart_co2_ersparnis(fahrten, benziner_l=benziner_l, co2_faktor=co2_faktor, large=False),
               lambda: charts.chart_co2_ersparnis(fahrten, benziner_l=benziner_l, co2_faktor=co2_faktor, large=True))
        render("verbrauch",
               charts.chart_verbrauch_100km(lade, fahrten, ev_ref=ev_ref, large=False),
               lambda: charts.chart_verbrauch_100km(lade, fahrten, ev_ref=ev_ref, large=True))
        render("benzin",
               charts.chart_benzinpreise(benzin, large=False),
               lambda: charts.chart_benzinpreise(benzin, large=True))
        render("strom",
               charts.chart_stromtarif(stromtarife, large=False),
               lambda: charts.chart_stromtarif(stromtarife, large=True))
        render("anbieter",
               charts.chart_anbieter_verteilung(lade, large=False),
               lambda: charts.chart_anbieter_verteilung(lade, large=True))
        render("thg",
               charts.chart_thg(thg, large=False),
               lambda: charts.chart_thg(thg, large=True))
