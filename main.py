import sys
import os
import logging

# Ensure imports work from project root
sys.path.insert(0, os.path.dirname(__file__))

from PyQt6.QtWidgets import QApplication, QMessageBox
from ui.main_window import MainWindow
import database as db

LOG_PATH = os.path.join(os.path.dirname(__file__), "ev_tracker.log")


def _setup_logging():
    logging.basicConfig(
        filename=LOG_PATH,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _excepthook(exc_type, exc, tb):
    """Unbehandelte Fehler loggen und dem Nutzer anzeigen statt still zu crashen."""
    logging.critical("Unbehandelter Fehler", exc_info=(exc_type, exc, tb))
    if QApplication.instance() is not None:
        QMessageBox.critical(
            None, "Unerwarteter Fehler",
            f"{exc_type.__name__}: {exc}\n\nDetails im Logfile:\n{LOG_PATH}")
    sys.__excepthook__(exc_type, exc, tb)


def main():
    _setup_logging()
    sys.excepthook = _excepthook

    app = QApplication(sys.argv)
    app.setApplicationName("EV Tracker")
    app.setOrganizationName("Daniel")

    try:
        db.init_db()
        db.init_ha_settings()
    except Exception as e:
        logging.critical("Datenbank-Initialisierung fehlgeschlagen", exc_info=True)
        QMessageBox.critical(
            None, "Datenbank-Fehler",
            f"Die Datenbank konnte nicht initialisiert werden:\n{e}\n\n"
            f"Details im Logfile:\n{LOG_PATH}")
        sys.exit(1)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
