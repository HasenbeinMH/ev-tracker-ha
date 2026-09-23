# Changelog

Alle nennenswerten Aenderungen des EV Tracker Add-ons.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/1.1.0/).

## [2.0.4] - 2026-09-23
### Groessenlimits fuer Uploads, CHANGELOG.md fuer den Add-on-Store
- PDF-Rechnungsupload auf 20 MB begrenzt, Einstellungen-Import auf 2 MB – vorher unbegrenzt, konnte theoretisch viel Speicher/Platz belegen
- CHANGELOG.md ergaenzt, damit der Update-Dialog im Home-Assistant-Add-on-Store die Aenderungen anzeigt statt „No changelog found“

## [2.0.3] - 2026-09-23
### Ueberfluessige HA-Felder im Add-on-Betrieb ausgeblendet
- HA-URL, HA-Token und „HA testen“ auf der Einstellungen-Seite verschwinden im Add-on-Betrieb, solange der Supervisor automatisch verbindet – Datenquelle-Auswahl und InfluxDB-Verbindung bleiben unveraendert sichtbar

## [2.0.2] - 2026-09-23
### Redirect-Fehler unter Ingress behoben
- Alle POST-Formulare mit mehrsegmentigem Pfad (z.B. /einstellungen/parameter, /steuer/thg/delete) leiteten unter Home-Assistant-Ingress auf eine doppelte, nicht existierende URL weiter ("Not Found") – jetzt korrekt aufgeloest

## [2.0.1] - 2026-09-23
### Home-Assistant-Add-on, Fahrzeugbild und -name einstellbar
- Läuft jetzt auch als Home-Assistant-Add-on (Ingress, automatische Supervisor-Anbindung ohne manuelles Access-Token) – zusätzlich zum bestehenden Standalone-Docker-Betrieb
- Fahrzeugbild im Dashboard per Upload in den Einstellungen austauschbar (JPG/PNG/WebP), mit Zurücksetzen aufs Standardbild
- Fahrzeugname in den Einstellungen frei wählbar statt fest „Kia EV3“ – erscheint im Dashboard-Kopf und als Vorschlag auf der Versicherungsseite
- Backup-Seite im Add-on-Betrieb an Home Assistants eigene Sicherungen angepasst; der bisherige Cronjob-Weg bleibt fuer den Standalone-Betrieb

## [2.0.0] - 2026-09-23
### Version 2.0: Instandhaltung, Versicherung und neue Menueleiste
- Neue Seite Instandhaltung: Werkstatt, Reifen, Verschleiss und HU je Rechnung erfassen, umgerechnet auf € pro 100 km – je Jahr und je Kategorie
- Neue Seite Versicherung: Gesellschaft, Deckung, SF-Klassen, Selbstbeteiligung, Jahreslaufleistung und Zusatzbausteine (Fahrerschutz, Werkstattbindung, Auslandsschutz, Schutzbrief) mit Verlauf je Fahrzeug
- Instandhaltung und Versicherung sind eigene Werte ohne Benziner-Vergleich und fliessen nicht in die Ersparnis auf dem Dashboard ein
- Warnung, wenn die gefahrenen km der letzten zwoelf Monate ueber der vereinbarten Jahreslaufleistung liegen
- Die Menueleiste ist zusammengefasst: Dashboard, Auswertung, Fahrten, Laden, Kosten, Verwaltung und Hilfe
- Beim Drueberfahren mit der Maus klappen die Unterseiten auf, z. B. unter Laden: Ladevorgaenge, Ladetarife, Stromtarif und Rechnungen
- Auf Handy und Tablet oeffnet der erste Tipp das Menue, der zweite die Seite

## [1.9.0] - 2026-09-22
### Ladetarife und Blockiergebühr
- Neue Seite Ladetarife: eigene Abos wie EnBW S/M/L mit ct/kWh AC/DC, Grundgebuehr, Blockiergebuehr, Fremdnetz-Preisen und Ladekarte erfassen
- Preisaenderungen als neuer Eintrag mit „gueltig ab“ – die Tabelle zeigt die Aenderung zum Vorgaenger, das Diagramm den Preisverlauf neben dem Heimstrompreis
- Tabelle „Was der Tarif wirklich kostet“: effektiver Preis je Monat inklusive Grundgebuehr
- Laden: neues Feld Blockiergebuehr (im Gesamtpreis enthalten), ct/kWh wird aus dem aktuellen Ladetarif des Anbieters vorbelegt

## [1.8.0] - 2026-09-22
### Ladeschwelle angeglichen, Monatswerte in der Statistik
- Der Verbrauch aus dem Akkustand trennt Fahrtabschnitte jetzt erst ab dem eingestellten „Mindestanstieg Ladung“ (Standard 5 Prozentpunkte) statt ab fest verdrahteten 0,5 – dieselbe Schwelle wie die Ladeerkennung
- Gemessen wird der Anstieg ab dem Tiefststand statt von Stunde zu Stunde: eine ueber Nacht schleichende AC-Ladung zaehlt als eine Ladung, und das Rauschen des Stundenmittels zerlegt einen Abschnitt nicht mehr in Ein-Prozent-Schnipsel
- Neue Tabelle auf der Statistikseite: Verbrauch aus dem Akkustand je Monat mit km, kWh und kWh/100 km fuer beide Zeitraeume und gewichteter Summenzeile
- Hinweis auf der Seite Berichte, dass „Ladung ab % Anstieg“ auch die Fahrtabschnitte steuert
- Das Stylesheet wird mit der Versionsnummer geladen – nach einem Update zeigt der Browser nicht mehr die alte Datei aus dem Cache

## [1.7.2] - 2026-09-22
### Messdaten zuruecksetzen
- Neu auf der Backup-Seite: „Messdaten zuruecksetzen“ – fuer den Fahrzeugwechsel oder um Testdaten zu entfernen
- Je Bereich waehlbar: gefahrene Kilometer, Ladevorgaenge, Benzinpreise, Akku-Abschnitte, THG-Eintraege; leere Bereiche sind gesperrt
- Der Knopf loescht nicht sofort, sondern klappt eine Rueckfrage mit der genauen Anzahl je Bereich auf – erst „Ja, endgueltig loeschen“ fuehrt es aus
- Einstellungen, Stromtarife, Lade-Anbieter und HA-Konfiguration bleiben erhalten; die Datenbank wird vorher als vor_reset_….db gesichert

## [1.7.1] - 2026-09-18
### Batteriestand auch aus InfluxDB
- Friendly Name fuer den Batteriestand in den Einstellungen, dazu das InfluxDB-Measurement fuer Prozentwerte (Standard „%“)
- Verbrauch aus dem Akkustand und Ladeerkennung lesen bei Datenquelle InfluxDB den Verlauf von dort; sonst oder als Rueckfall aus der HA-API
- Meldung nach dem Neuberechnen nennt die genutzte Quelle

## [1.7.0] - 2026-09-18
### Zeitraumauswahl und Statistikseite
- Zeitraumauswahl im Dashboard fuer alle Kennzahlen und Charts: gesamt, Jahre, Quartale des laufenden und letzten Jahres, Sommer (Apr–Sep) und Winter (Okt–Mär)
- Die gewaehlte Ansicht wird im Browser gemerkt
- KFZ-Steuer in Teilzeitraeumen anteilig nach Monaten
- Neue Seite Statistik: zwei Zeitraeume nebeneinander mit Differenz und Wertung, Schnellauswahl (Jahr gegen Vorjahr, Sommer gegen Winter …) und Monatsverlauf
- Stromtarif-Verlauf zeigt im Zeitraum den zu Beginn gueltigen Tarif
- Batteriestand-Sensor in den Einstellungen waehlbar
- Betraege im Dashboard mit Tausenderpunkt

## [1.6.0] - 2026-09-18
### Verbrauch aus dem Akkustand, Strommix
- Neues Ringdiagramm: Anteil der geladenen kWh aus PV, Netzbezug und oeffentlichem Laden
- Verbrauch aus dem Akkustand: Fahrtabschnitte zwischen zwei Ladungen, Akku-Abfall × 58,3 kWh ÷ gefahrene km – ohne Ladeverluste
- Verbrauchs-Chart zeigt beide Werte: laut Ladung und laut Akku
- Seite Fahrten: Liste der Fahrtabschnitte, Vergleich mit dem Verbrauch aus den Ladungen und Hinweis, wenn Ladevorgaenge zu fehlen scheinen
- Naechtlicher Abruf rechnet die letzten 45 Tage neu; die ganze Historie per Knopf
- Referenzlinie im Verbrauchs-Chart ist immer sichtbar
- Kennzahl-Kacheln auf anderen Seiten wieder richtig untereinander dargestellt

## [1.5.2] - 2026-09-17
### Schieberegler frueher sichtbar
- Der Zeitraum-Regler erscheint schon ab drei Monaten statt erst ab sechs

## [1.5.1] - 2026-09-17
### Bedienelemente und Feinschliff
- Schieberegler unter den Charts zum Eingrenzen des Zeitraums
- Umschalter Balken/Linie und Zuruecksetzen oben rechts im Chart
- Kennzahl-Kacheln mit Symbol in der jeweiligen Kennzahlfarbe
- Kopfzeile nur noch halb so hoch
- Gesamt-Ersparnis steht nur noch in der Kopfzeile, nicht mehr als Kachel

## [1.5.0] - 2026-09-17
### Neues Dashboard
- Kopfzeile im Dashboard mit Fahrzeugbild und der Gesamt-Ersparnis
- Charts auf Apache ECharts umgestellt: Farbverlaeufe, ruhigere Achsen, kompakte Legende und ein Tooltip mit allen Werten eines Monats
- Kraftstoffkosten-Vergleich als liegende Balken
- Benzinpreis-Chart beginnt nicht mehr bei 0 – Schwankungen sind wieder erkennbar
- Stromtarif-Verlauf reicht bis heute, da der letzte Tarif weiter gilt
- Datums- und Zahlenangaben in den Charts durchgaengig im deutschen Format
- Die Desktop-App (PyQt6) wurde entfernt; die Web-App loest sie vollstaendig ab

## [1.4.0] - 2026-09-14
### Handbuch und Importprotokoll
- Neue Seite „Hilfe“: Bedienung aller Seiten und Herleitung jeder Kennzahl
- Protokoll fuer den HA-Datenabruf auf der Seite „HA Import“ – je Monat gelesene Sensorwerte und uebernommene Werte mit Zeitstempel
- Der Zeitraum-Import wird ebenfalls protokolliert
- Versionsnummer und Aenderungslog in der App sichtbar

## [1.3.0] - 2026-08-27
### Naechtlicher Datenabruf
- Automatischer Abruf aus Home Assistant fuer laufenden Monat und Vormonat
- Ladevorgaenge nachtraeglich bearbeitbar
- Verbrauchsauswertung auf der Seite „Fahrten“ (kWh/100 km)
- Berichts-Zeitplan laeuft einmal taeglich statt stuendlich

## [1.2.0] - 2026-08-26
### Berichte per E-Mail
- Monats- und Jahresberichte mit Vergleich zur Vorperiode
- Automatischer Versand mit Vorschau und Einzelversand
- Monatsabschluss-Pruefung: Bericht wartet auf vollstaendige Daten
- Ladeerkennung ueber den Batterieverlauf – meldet fehlende Belege

## [1.1.0] - 2026-08-25
### Backup und Einstellungsverwaltung
- Taegliches Backup der Datenbank per rclone nach OneDrive
- Backup-Seite mit Status, Protokoll und Wiederherstellung
- Einstellungen als JSON-Datei sichern und laden
- Sensor-Konfiguration auf die tatsaechlich importierten Sensoren reduziert
- Fehlendes http:// in URLs wird automatisch ergaenzt
- Deutsches Zahlenformat in den Diagrammen

## [1.0.0] - 2026-08-04
### Erste Web-Version
- Web-Oberflaeche fuer Docker – loest die Desktop-App ab
- Dashboard, Fahrten, Laden, Benzin, Stromtarif, Steuer & THG
- Datenimport aus Home Assistant und InfluxDB
- Rechnungsimport aus PDF und Text
