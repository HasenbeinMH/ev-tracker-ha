# -*- coding: utf-8 -*-
"""
Version und Aenderungslog des EV Trackers.

Einzige Quelle fuer beides: Die Versionsnummer steht in der Navigationsleiste,
der Aenderungslog auf der Hilfeseite unter /hilfe#changelog.

Pflege bei einer neuen Version:
  1. VERSION erhoehen (schema: major.minor.patch)
  2. Oben in CHANGELOG einen neuen Eintrag einfuegen - neueste Version zuerst
  3. Datum im Format YYYY-MM-DD

Zaehlweise: major = grosse Umbauten, minor = neue Funktion,
patch = Fehlerbehebung oder Detailverbesserung.
"""

VERSION = "1.5.2"

# Neueste Version zuerst. "aenderungen" ist eine Liste von Klartextzeilen.
CHANGELOG = [
    {
        "version": "1.5.2",
        "datum": "2026-09-17",
        "titel": "Schieberegler frueher sichtbar",
        "aenderungen": [
            "Der Zeitraum-Regler erscheint schon ab drei Monaten statt erst ab sechs",
        ],
    },
    {
        "version": "1.5.1",
        "datum": "2026-09-17",
        "titel": "Bedienelemente und Feinschliff",
        "aenderungen": [
            "Schieberegler unter den Charts zum Eingrenzen des Zeitraums",
            "Umschalter Balken/Linie und Zuruecksetzen oben rechts im Chart",
            "Kennzahl-Kacheln mit Symbol in der jeweiligen Kennzahlfarbe",
            "Kopfzeile nur noch halb so hoch",
            "Gesamt-Ersparnis steht nur noch in der Kopfzeile, nicht mehr als Kachel",
        ],
    },
    {
        "version": "1.5.0",
        "datum": "2026-09-17",
        "titel": "Neues Dashboard",
        "aenderungen": [
            "Kopfzeile im Dashboard mit Fahrzeugbild und der Gesamt-Ersparnis",
            "Charts auf Apache ECharts umgestellt: Farbverlaeufe, ruhigere Achsen, "
            "kompakte Legende und ein Tooltip mit allen Werten eines Monats",
            "Kraftstoffkosten-Vergleich als liegende Balken",
            "Benzinpreis-Chart beginnt nicht mehr bei 0 – Schwankungen sind wieder erkennbar",
            "Stromtarif-Verlauf reicht bis heute, da der letzte Tarif weiter gilt",
            "Datums- und Zahlenangaben in den Charts durchgaengig im deutschen Format",
            "Die Desktop-App (PyQt6) wurde entfernt; die Web-App loest sie vollstaendig ab",
        ],
    },
    {
        "version": "1.4.0",
        "datum": "2026-09-14",
        "titel": "Handbuch und Importprotokoll",
        "aenderungen": [
            "Neue Seite „Hilfe“: Bedienung aller Seiten und Herleitung jeder Kennzahl",
            "Protokoll fuer den HA-Datenabruf auf der Seite „HA Import“ – "
            "je Monat gelesene Sensorwerte und uebernommene Werte mit Zeitstempel",
            "Der Zeitraum-Import wird ebenfalls protokolliert",
            "Versionsnummer und Aenderungslog in der App sichtbar",
        ],
    },
    {
        "version": "1.3.0",
        "datum": "2026-08-27",
        "titel": "Naechtlicher Datenabruf",
        "aenderungen": [
            "Automatischer Abruf aus Home Assistant fuer laufenden Monat und Vormonat",
            "Ladevorgaenge nachtraeglich bearbeitbar",
            "Verbrauchsauswertung auf der Seite „Fahrten“ (kWh/100 km)",
            "Berichts-Zeitplan laeuft einmal taeglich statt stuendlich",
        ],
    },
    {
        "version": "1.2.0",
        "datum": "2026-08-26",
        "titel": "Berichte per E-Mail",
        "aenderungen": [
            "Monats- und Jahresberichte mit Vergleich zur Vorperiode",
            "Automatischer Versand mit Vorschau und Einzelversand",
            "Monatsabschluss-Pruefung: Bericht wartet auf vollstaendige Daten",
            "Ladeerkennung ueber den Batterieverlauf – meldet fehlende Belege",
        ],
    },
    {
        "version": "1.1.0",
        "datum": "2026-08-25",
        "titel": "Backup und Einstellungsverwaltung",
        "aenderungen": [
            "Taegliches Backup der Datenbank per rclone nach OneDrive",
            "Backup-Seite mit Status, Protokoll und Wiederherstellung",
            "Einstellungen als JSON-Datei sichern und laden",
            "Sensor-Konfiguration auf die tatsaechlich importierten Sensoren reduziert",
            "Fehlendes http:// in URLs wird automatisch ergaenzt",
            "Deutsches Zahlenformat in den Diagrammen",
        ],
    },
    {
        "version": "1.0.0",
        "datum": "2026-08-04",
        "titel": "Erste Web-Version",
        "aenderungen": [
            "Web-Oberflaeche fuer Docker – loest die Desktop-App ab",
            "Dashboard, Fahrten, Laden, Benzin, Stromtarif, Steuer & THG",
            "Datenimport aus Home Assistant und InfluxDB",
            "Rechnungsimport aus PDF und Text",
        ],
    },
]

# Hinweis: Die Versionsnummern bis 1.3.0 wurden nachtraeglich aus der
# Git-Historie abgeleitet – zu diesen Staenden gab es noch keine Zaehlung.
