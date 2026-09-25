# -*- coding: utf-8 -*-
"""
Version und Aenderungslog des EV Trackers.

Einzige Quelle fuer beides: Die Versionsnummer steht in der Navigationsleiste,
der Aenderungslog auf der Hilfeseite unter /hilfe#changelog.

CHANGELOG.md (Repo-Root) ist eine separate Datei nur fuer den Update-Dialog des
Home-Assistant-Add-on-Stores – wird aus diesem CHANGELOG generiert, nicht von Hand
gepflegt. Bei einer neuen Version mit erzeugen (siehe Kommentar dort).

Pflege bei einer neuen Version:
  1. VERSION erhoehen (schema: major.minor.patch), config.yaml "version:" mitziehen
  2. Oben in CHANGELOG einen neuen Eintrag einfuegen - neueste Version zuerst
  3. Datum im Format YYYY-MM-DD
  4. CHANGELOG.md aus diesen Daten neu erzeugen (nicht von Hand editieren)

Zaehlweise: major = grosse Umbauten, minor = neue Funktion,
patch = Fehlerbehebung oder Detailverbesserung.
"""

VERSION = "2.3.0"

# Neueste Version zuerst. "aenderungen" ist eine Liste von Klartextzeilen.
CHANGELOG = [
    {
        "version": "2.3.0",
        "datum": "2026-09-25",
        "titel": "Vergleich mit einem Diesel statt einem Benziner",
        "aenderungen": [
            "Einstellungen → Berechnungsparameter: neues Feld \"Vergleich mit\" – Benziner oder Diesel",
            "Mit Diesel heissen Menue, Seiten, Diagramme, Statistik, Mailbericht und Hilfe entsprechend (Dieselpreise, Diesel-Kosten, Ersparnis vs. Diesel …); gerechnet wird wie bisher Liter × Preis des Monats",
            "CO2-Faktor: beim Wechsel springt der Standardwert mit um (Benzin 2,37, Diesel 2,65 kg/L); ein selbst eingetragener Wert bleibt stehen",
            "Vorhandene Preise und Sensoren bleiben erhalten – fuer Diesel den Dieselpreis-Sensor (z.B. Tankerkoenig) eintragen",
        ],
    },
    {
        "version": "2.2.1",
        "datum": "2026-09-25",
        "titel": "Farben bei Veraenderungen, Anleitung fuer den Node-RED-Import",
        "aenderungen": [
            "Statistik: Anteil Netzbezug und Anteil oeffentlich werden jetzt gewertet – weniger ist besser (gruen), mehr schlechter (orange), wie bei Verbrauch und Kosten",
            "Monats- und Jahresbericht per Mail: die Veraenderung zur Vorperiode ist farbig – Stromkosten mit Minus gruen, Ersparnis und CO2 mit Plus gruen; km und kWh bleiben grau",
            "Mailbericht: Prozent der Veraenderung stimmt jetzt auch, wenn die Ersparnis der Vorperiode negativ war",
            "Benzinpreise: steigender Preis im selben Orange wie auf der Statistikseite",
            "Vorlagen: Schritt-fuer-Schritt-Anleitung zum Import des Node-RED-Flows (vorlagen/node-red/README.md); die .js-Quellen liegen jetzt in quellen/, damit nur die importierbare JSON-Datei im Ordner steht – eingefuegter .js-Code fuehrte zu \"is not valid JSON\"",
        ],
    },
    {
        "version": "2.2.0",
        "datum": "2026-09-24",
        "titel": "Vorlagen: PV- und Netz-Anteil beim Laden selbst berechnen",
        "aenderungen": [
            "Neu im Repo unter vorlagen/: ein Node-RED-Flow und ein Home-Assistant-Paket, die "
            "die Ladeleistung der Wallbox in PV und Netz aufteilen und die Zaehler "
            "sensor.ev_ladung_pv / sensor.ev_ladung_netz anlegen – fuer \"PV ins Auto\" und "
            "\"Netz ins Auto\" im EV Tracker und fuers Energie-Dashboard",
            "Regel \"Haus zuerst, das Auto bekommt den Ueberschuss\": Netz ins Auto = "
            "min(Netzbezug, Wallbox-Leistung); ein Hausakku, der ins Auto entlaedt, zaehlt als PV "
            "(einstellbar). Es genuegen Netz- und Wallbox-Leistung, mit Energiezaehler der "
            "Wallbox wird dieser genau aufgeteilt",
            "Node-RED-Flow nur mit Standard-Knoten, im Node-RED-Add-on ohne Token; nur ein "
            "Einstellungs-Knoten auszufuellen, Einheiten W/kW und Wh/kWh werden erkannt",
            "Einstellungen und Hilfe verweisen auf die Vorlagen",
        ],
    },
    {
        "version": "2.1.4",
        "datum": "2026-09-24",
        "titel": "Keine Mehrmonats-Strecke nach einer Datenluecke",
        "aenderungen": [
            "Import aus einer Datenbank: Liegt der letzte Kilometer- bzw. Zaehlerstand vor dem "
            "Monat mehr als 45 Tage zurueck, wird die Differenz nicht mehr uebernommen – sie "
            "waere die Strecke mehrerer Monate (z.B. 8.847 km fuer einen Monat nach einer "
            "Luecke). Stattdessen springt die HA-API ein; Vorschau und Protokoll nennen den Grund",
        ],
    },
    {
        "version": "2.1.3",
        "datum": "2026-09-24",
        "titel": "Umbenannte Sensoren und Grund, wenn die Datenbank nichts liefert",
        "aenderungen": [
            "Mehrere Namen je Sensor mit \"|\" (z.B. \"Alter Name | Neuer Name\"): die Werte "
            "werden zusammengefuehrt, beim Kilometerstand stimmt auch der Monat der Umbenennung",
            "Import-Vorschau und Protokoll nennen den Grund, wenn die Datenbank fuer einen Wert "
            "nichts liefert (keine Werte im Monat, kein Vorwert, Fehlermeldung der Datenbank) – "
            "vorher sprang die App still auf Home Assistant um",
            "Datenbanksuche: \"Uebernehmen\" setzt bei InfluxDB auch das passende Measurement "
            "(z.B. \"€\" statt \"EUR/L\") und fragt, ob ein weiterer Name ergaenzt oder der "
            "vorhandene ersetzt werden soll",
        ],
    },
    {
        "version": "2.1.2",
        "datum": "2026-09-24",
        "titel": "Import zeigt, woher jeder Wert kommt",
        "aenderungen": [
            "Zeitraum-Import: die Vorschau nennt die Quelle und markiert jeden Wert mit "
            "\"DB\" (aus der Datenbank) oder \"HA\" (Rueckfall auf Home Assistant)",
            "Importprotokoll: bei jedem Wert steht die Herkunft, z.B. \"790 km (InfluxDB 1.x)\" "
            "oder \"2.151 €/L (HA-API)\"; in der Vorschau geaenderte Werte als \"von Hand\"",
            "Importseite: veraltete Hinweise korrigiert (Stromtarif des Monats statt "
            "aktueller Tarif, naechtlicher Abruf auch aus der Datenbank)",
        ],
    },
    {
        "version": "2.1.1",
        "datum": "2026-09-24",
        "titel": "Sensoren direkt in der Datenbank suchen",
        "aenderungen": [
            "Einstellungen: neuer Knopf \"In Datenbank suchen\" – findet Sensoren in der "
            "gewaehlten Datenbank (InfluxDB, PostgreSQL, Prometheus) samt Einheit und Zeitraum "
            "mit Daten; \"Uebernehmen\" traegt den Treffer in die passende Zeile ein",
            "PostgreSQL: Fehlermeldungen beim Verbindungstest verstaendlich (z.B. \"Benutzer "
            "oder Passwort falsch\", \"Tabelle nicht gefunden – ist LTSS eingerichtet?\")",
            "Alle Datenbank-Anbindungen gegen echte Server getestet (InfluxDB 1.8 und 2.7, "
            "TimescaleDB, VictoriaMetrics, Prometheus) – Testskript "
            "tests/datenquellen_docker_test.py",
        ],
    },
    {
        "version": "2.1.0",
        "datum": "2026-09-24",
        "titel": "Weitere Datenbanken: InfluxDB 2.x, PostgreSQL/TimescaleDB, Prometheus",
        "aenderungen": [
            "Neben der HA-API und InfluxDB 1.x lassen sich jetzt auch InfluxDB 2.x (Flux, "
            "Token), PostgreSQL/TimescaleDB (HA-Integration LTSS) und Prometheus/"
            "VictoriaMetrics als Datenquelle waehlen – fuer Import, naechtlichen Abruf, "
            "Akkuverbrauch und Ladeerkennung; was die Datenbank nicht liefert, kommt weiter "
            "aus der HA-API. Die drei neuen Anbindungen sind als \"neu\" gekennzeichnet",
            "Einstellungen: je Datenquelle ein eigener Verbindungsblock mit Test-Knopf; die "
            "Spalte \"Name in der InfluxDB\" erscheint nur noch bei InfluxDB",
            "InfluxDB: der Tag, ueber den der Sensor gefunden wird, ist einstellbar "
            "(friendly_name oder entity_id); Monatsgrenzen jetzt in Ortszeit statt UTC",
            "Stundenwerte fuer den Akkuverbrauch beginnen jetzt mit der ersten Stunde des "
            "Zeitraums (vorher fehlte sie)",
        ],
    },
    {
        "version": "2.0.7",
        "datum": "2026-09-24",
        "titel": "Korrekturen aus dem Funktionstest: Tarif je Monat, KFZ-Steuer, Ladeerkennung",
        "aenderungen": [
            "Verbrauch aus dem Akkustand und Ladeerkennung funktionieren jetzt auch im "
            "Add-on ohne eigenen HA-Token (nutzen wie der Import den Supervisor-Zugang)",
            "Importierter Netzbezug wird mit dem Stromtarif des jeweiligen Monats bewertet "
            "statt immer mit dem neuesten – bei einem Wechsel mitten im Monat tagesgenau "
            "gewichtet. Wird ein Tarif nachgetragen oder geloescht, werden die importierten "
            "Monate neu bewertet; bestehende Daten einmalig beim Start korrigiert",
            "Ladeerkennung: Heimladungen (aus HA nur als Monatssumme am 1.) gelten nicht "
            "mehr als \"auswaerts geladen\" – der Monatsbericht wartet dadurch nicht mehr "
            "grundlos bis zu 10 Tage",
            "KFZ-Steuer ist ein Jahresbetrag und wird jetzt auch im Gesamtzeitraum anteilig "
            "nach Monaten gerechnet (vorher nur einmal, egal wie viele Jahre erfasst sind)",
            "Zahleneingabe: \"1.234,50\" wird ueberall verstanden, bei km und Euro-Betraegen "
            "auch \"1.234\" als Tausenderpunkt (vorher 1,234 km bzw. stillschweigend verworfen)",
            "Benziner-Vergleich Monat fuer Monat mit dem Benzinpreis des jeweiligen Monats "
            "(Ø-Preis damit km-gewichtet) – Monatsdiagramm, Kachel und Jahresbericht ergeben "
            "jetzt dieselbe Summe; Monate ohne Benzinpreis erscheinen im Diagramm mit dem Ø-Preis",
            "Monatsbericht (Mail): \"CO₂\" wurde als \"CO&sub2;\" angezeigt, und die vier Kacheln "
            "standen untereinander statt zu zweit nebeneinander",
        ],
    },
    {
        "version": "2.0.6",
        "datum": "2026-09-23",
        "titel": "Farbverlauf im Dashboard passt sich dem Fahrzeugbild an",
        "aenderungen": [
            "Farbverlauf und Fahrzeugname oben im Dashboard waren fest orange (passend zum "
            "Standardbild) – die Akzentfarbe wird jetzt aus dem hochgeladenen Fahrzeugbild "
            "ermittelt, bei Weiss/Silber/Schwarz ein neutraler Ton",
        ],
    },
    {
        "version": "2.0.5",
        "datum": "2026-09-23",
        "titel": "Hinweistext zur Supervisor-Verbindung entfernt",
        "aenderungen": [
            "Der gruene Hinweis „Laeuft als Home-Assistant-Add-on ...“ auf der "
            "Einstellungen-Seite ist weg – die HA-URL/Token-Felder blenden sich weiterhin "
            "automatisch aus, wenn der Supervisor ohne manuelle Zugangsdaten verbindet",
        ],
    },
    {
        "version": "2.0.4",
        "datum": "2026-09-23",
        "titel": "Groessenlimits fuer Uploads, CHANGELOG.md fuer den Add-on-Store",
        "aenderungen": [
            "PDF-Rechnungsupload auf 20 MB begrenzt, Einstellungen-Import auf 2 MB – "
            "vorher unbegrenzt, konnte theoretisch viel Speicher/Platz belegen",
            "CHANGELOG.md ergaenzt, damit der Update-Dialog im Home-Assistant-Add-on-Store "
            "die Aenderungen anzeigt statt „No changelog found“",
        ],
    },
    {
        "version": "2.0.3",
        "datum": "2026-09-23",
        "titel": "Ueberfluessige HA-Felder im Add-on-Betrieb ausgeblendet",
        "aenderungen": [
            "HA-URL, HA-Token und „HA testen“ auf der Einstellungen-Seite verschwinden im "
            "Add-on-Betrieb, solange der Supervisor automatisch verbindet – Datenquelle-Auswahl "
            "und InfluxDB-Verbindung bleiben unveraendert sichtbar",
        ],
    },
    {
        "version": "2.0.2",
        "datum": "2026-09-23",
        "titel": "Redirect-Fehler unter Ingress behoben",
        "aenderungen": [
            "Alle POST-Formulare mit mehrsegmentigem Pfad (z.B. /einstellungen/parameter, "
            "/steuer/thg/delete) leiteten unter Home-Assistant-Ingress auf eine doppelte, "
            "nicht existierende URL weiter (\"Not Found\") – jetzt korrekt aufgeloest",
        ],
    },
    {
        "version": "2.0.1",
        "datum": "2026-09-23",
        "titel": "Home-Assistant-Add-on, Fahrzeugbild und -name einstellbar",
        "aenderungen": [
            "Läuft jetzt auch als Home-Assistant-Add-on (Ingress, automatische "
            "Supervisor-Anbindung ohne manuelles Access-Token) – zusätzlich zum "
            "bestehenden Standalone-Docker-Betrieb",
            "Fahrzeugbild im Dashboard per Upload in den Einstellungen austauschbar "
            "(JPG/PNG/WebP), mit Zurücksetzen aufs Standardbild",
            "Fahrzeugname in den Einstellungen frei wählbar statt fest „Kia EV3“ – "
            "erscheint im Dashboard-Kopf und als Vorschlag auf der Versicherungsseite",
            "Backup-Seite im Add-on-Betrieb an Home Assistants eigene Sicherungen "
            "angepasst; der bisherige Cronjob-Weg bleibt fuer den Standalone-Betrieb",
        ],
    },
    {
        "version": "2.0.0",
        "datum": "2026-09-23",
        "titel": "Version 2.0: Instandhaltung, Versicherung und neue Menueleiste",
        "aenderungen": [
            "Neue Seite Instandhaltung: Werkstatt, Reifen, Verschleiss und HU je Rechnung "
            "erfassen, umgerechnet auf € pro 100 km – je Jahr und je Kategorie",
            "Neue Seite Versicherung: Gesellschaft, Deckung, SF-Klassen, Selbstbeteiligung, "
            "Jahreslaufleistung und Zusatzbausteine (Fahrerschutz, Werkstattbindung, "
            "Auslandsschutz, Schutzbrief) mit Verlauf je Fahrzeug",
            "Instandhaltung und Versicherung sind eigene Werte ohne Benziner-Vergleich und "
            "fliessen nicht in die Ersparnis auf dem Dashboard ein",
            "Warnung, wenn die gefahrenen km der letzten zwoelf Monate ueber der vereinbarten "
            "Jahreslaufleistung liegen",
            "Die Menueleiste ist zusammengefasst: Dashboard, Auswertung, Fahrten, Laden, "
            "Kosten, Verwaltung und Hilfe",
            "Beim Drueberfahren mit der Maus klappen die Unterseiten auf, z. B. unter Laden: "
            "Ladevorgaenge, Ladetarife, Stromtarif und Rechnungen",
            "Auf Handy und Tablet oeffnet der erste Tipp das Menue, der zweite die Seite",
        ],
    },
    {
        "version": "1.9.0",
        "datum": "2026-09-22",
        "titel": "Ladetarife und Blockiergebühr",
        "aenderungen": [
            "Neue Seite Ladetarife: eigene Abos wie EnBW S/M/L mit ct/kWh AC/DC, "
            "Grundgebuehr, Blockiergebuehr, Fremdnetz-Preisen und Ladekarte erfassen",
            "Preisaenderungen als neuer Eintrag mit „gueltig ab“ – die Tabelle zeigt die "
            "Aenderung zum Vorgaenger, das Diagramm den Preisverlauf neben dem Heimstrompreis",
            "Tabelle „Was der Tarif wirklich kostet“: effektiver Preis je Monat inklusive "
            "Grundgebuehr",
            "Laden: neues Feld Blockiergebuehr (im Gesamtpreis enthalten), ct/kWh wird aus "
            "dem aktuellen Ladetarif des Anbieters vorbelegt",
        ],
    },
    {
        "version": "1.8.0",
        "datum": "2026-09-22",
        "titel": "Ladeschwelle angeglichen, Monatswerte in der Statistik",
        "aenderungen": [
            "Der Verbrauch aus dem Akkustand trennt Fahrtabschnitte jetzt erst ab dem "
            "eingestellten „Mindestanstieg Ladung“ (Standard 5 Prozentpunkte) statt ab fest "
            "verdrahteten 0,5 – dieselbe Schwelle wie die Ladeerkennung",
            "Gemessen wird der Anstieg ab dem Tiefststand statt von Stunde zu Stunde: "
            "eine ueber Nacht schleichende AC-Ladung zaehlt als eine Ladung, und das Rauschen "
            "des Stundenmittels zerlegt einen Abschnitt nicht mehr in Ein-Prozent-Schnipsel",
            "Neue Tabelle auf der Statistikseite: Verbrauch aus dem Akkustand je Monat mit "
            "km, kWh und kWh/100 km fuer beide Zeitraeume und gewichteter Summenzeile",
            "Hinweis auf der Seite Berichte, dass „Ladung ab % Anstieg“ auch die "
            "Fahrtabschnitte steuert",
            "Das Stylesheet wird mit der Versionsnummer geladen – nach einem Update zeigt "
            "der Browser nicht mehr die alte Datei aus dem Cache",
        ],
    },
    {
        "version": "1.7.2",
        "datum": "2026-09-22",
        "titel": "Messdaten zuruecksetzen",
        "aenderungen": [
            "Neu auf der Backup-Seite: „Messdaten zuruecksetzen“ – fuer den Fahrzeugwechsel "
            "oder um Testdaten zu entfernen",
            "Je Bereich waehlbar: gefahrene Kilometer, Ladevorgaenge, Benzinpreise, "
            "Akku-Abschnitte, THG-Eintraege; leere Bereiche sind gesperrt",
            "Der Knopf loescht nicht sofort, sondern klappt eine Rueckfrage mit der genauen "
            "Anzahl je Bereich auf – erst „Ja, endgueltig loeschen“ fuehrt es aus",
            "Einstellungen, Stromtarife, Lade-Anbieter und HA-Konfiguration bleiben erhalten; "
            "die Datenbank wird vorher als vor_reset_….db gesichert",
        ],
    },
    {
        "version": "1.7.1",
        "datum": "2026-09-18",
        "titel": "Batteriestand auch aus InfluxDB",
        "aenderungen": [
            "Friendly Name fuer den Batteriestand in den Einstellungen, dazu das "
            "InfluxDB-Measurement fuer Prozentwerte (Standard „%“)",
            "Verbrauch aus dem Akkustand und Ladeerkennung lesen bei Datenquelle InfluxDB "
            "den Verlauf von dort; sonst oder als Rueckfall aus der HA-API",
            "Meldung nach dem Neuberechnen nennt die genutzte Quelle",
        ],
    },
    {
        "version": "1.7.0",
        "datum": "2026-09-18",
        "titel": "Zeitraumauswahl und Statistikseite",
        "aenderungen": [
            "Zeitraumauswahl im Dashboard fuer alle Kennzahlen und Charts: gesamt, Jahre, "
            "Quartale des laufenden und letzten Jahres, Sommer (Apr–Sep) und Winter (Okt–Mär)",
            "Die gewaehlte Ansicht wird im Browser gemerkt",
            "KFZ-Steuer in Teilzeitraeumen anteilig nach Monaten",
            "Neue Seite Statistik: zwei Zeitraeume nebeneinander mit Differenz und Wertung, "
            "Schnellauswahl (Jahr gegen Vorjahr, Sommer gegen Winter …) und Monatsverlauf",
            "Stromtarif-Verlauf zeigt im Zeitraum den zu Beginn gueltigen Tarif",
            "Batteriestand-Sensor in den Einstellungen waehlbar",
            "Betraege im Dashboard mit Tausenderpunkt",
        ],
    },
    {
        "version": "1.6.0",
        "datum": "2026-09-18",
        "titel": "Verbrauch aus dem Akkustand, Strommix",
        "aenderungen": [
            "Neues Ringdiagramm: Anteil der geladenen kWh aus PV, Netzbezug und oeffentlichem Laden",
            "Verbrauch aus dem Akkustand: Fahrtabschnitte zwischen zwei Ladungen, "
            "Akku-Abfall × 58,3 kWh ÷ gefahrene km – ohne Ladeverluste",
            "Verbrauchs-Chart zeigt beide Werte: laut Ladung und laut Akku",
            "Seite Fahrten: Liste der Fahrtabschnitte, Vergleich mit dem Verbrauch aus den "
            "Ladungen und Hinweis, wenn Ladevorgaenge zu fehlen scheinen",
            "Naechtlicher Abruf rechnet die letzten 45 Tage neu; die ganze Historie per Knopf",
            "Referenzlinie im Verbrauchs-Chart ist immer sichtbar",
            "Kennzahl-Kacheln auf anderen Seiten wieder richtig untereinander dargestellt",
        ],
    },
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
