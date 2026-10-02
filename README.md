# ⚡ EV Tracker

> 🚧 **Noch in aktiver Entwicklung.** Dieses Add-on wird mit Unterstützung von KI (Claude)
> erstellt und getestet. Funktionen, Konfiguration und Datenstruktur können sich noch
> ändern; vor größeren Updates lohnt sich eine Sicherung über Home Assistants eigene
> Backups. Rückmeldungen und Fehlerberichte sind willkommen.

Web-App zur Erfassung und Auswertung der Kosteneinsparungen eines Elektroautos
gegenüber einem Benziner, Diesel oder Autogas-Auto. Fahrzeugname und -bild sind in den Einstellungen frei wählbar –
nicht auf ein bestimmtes Modell festgelegt.

![Dashboard des EV Trackers](https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-dashboard.png)

## Einblicke

*Alle Bilder mit Beispieldaten: 20 Monate, ein Elektroauto mit Wallbox und PV-Anlage.*

<table>
<tr>
<td width="50%"><a href="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-diagramme.png"><img src="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-diagramme.png" alt="Diagramme: CO2, Verbrauch, Ladekosten nach Anbieter, Strommix"></a>
<br><b>Alles auf einen Blick</b> – CO₂-Ersparnis, Verbrauch im Jahresverlauf, wohin das Geld fürs Laden geht und wie viel davon Solarstrom war.</td>
<td width="50%"><a href="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-statistik.png"><img src="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-statistik.png" alt="Statistik: Sommer gegen Winter"></a>
<br><b>Sommer gegen Winter</b> – zwei Zeiträume nebeneinander: Verbrauch, Kosten je 100 km, PV-Anteil, Ersparnis.</td>
</tr>
<tr>
<td><a href="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-verbrauch.png"><img src="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-verbrauch.png" alt="Verbrauch je Monat und aus dem Akkustand"></a>
<br><b>Echter Verbrauch</b> – je Monat aus den Ladungen und je Fahrt aus dem Akkustand. Die Differenz zeigt die Ladeverluste.</td>
<td><a href="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-ladetarife.png"><img src="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-ladetarife.png" alt="Ladetarife mit Preisverlauf"></a>
<br><b>Ladetarife im Griff</b> – Abos mit Preisverlauf, Grundgebühr und Blockiergebühr, im Vergleich zum Heimstrom.</td>
</tr>
<tr>
<td><a href="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-bericht.png"><img src="https://raw.githubusercontent.com/HasenbeinMH/ev-tracker-ha/main/docs/screenshot-bericht.png" alt="Monatsbericht per Mail" width="70%"></a>
<br><b>Monatsbericht per Mail</b> – kommt automatisch, sobald der Monat vollständig ist.</td>
<td valign="top"><br><b>Und außerdem:</b> Import aus Home Assistant oder einer Datenbank (InfluxDB 1.x/2.x/3.x, PostgreSQL/TimescaleDB, Prometheus/VictoriaMetrics), jede Nacht automatisch · Rechnungs-PDFs einlesen ([Musterrechnungen gesucht](#-rechnungsimport-musterrechnungen-gesucht)) · Ladeerkennung am Akkustand (meldet Ladungen unterwegs ohne Beleg) · THG-Quote und KFZ-Steuer · Instandhaltung und Versicherung · mehrere E-Autos (je Auto oder als Summe) · Oberfläche, Hilfe und Mail-Berichte auf Deutsch oder Englisch · Backup und Wiederherstellen</td>
</tr>
</table>

## Voraussetzungen

Der EV Tracker **misst selbst nichts** – er liest jeden Monat vorhandene Sensoren aus Home
Assistant (oder einer Datenbank wie InfluxDB) aus. Damit die Auswertung funktioniert, müssen diese Sensoren
vorher in Home Assistant eingerichtet sein:

| Was | Wozu | Hinweis |
|-----|------|---------|
| ⛽ **Tankerkönig-Integration** | Benzin-, Diesel- bzw. Autogaspreis für den Vergleich mit einem Verbrenner | Kostenlosen API-Key bei [Tankerkönig](https://creativecommons.tankerkoenig.de/) holen, Integration in HA einrichten und die Tankstelle(n) wählen, an der man sonst tanken würde. Bis zu zwei Preis-Sensoren (€/L) können eingetragen werden, es wird der Monatsdurchschnitt gebildet. |
| 🔌 **Geladene kWh aus dem Netz** | Stromkosten für das Laden zu Hause (Netzbezug) | Muss **außerhalb** des EV Trackers gezählt werden – z. B. durch den Energiezähler der Wallbox oder einen Zwischenzähler. Benötigt wird ein fortlaufender kWh-Zähler. Liefert die Wallbox nur die gesamte Ladeleistung: siehe [Vorlagen](https://github.com/HasenbeinMH/ev-tracker-ha/blob/main/vorlagen/README.md) unten. |
| ☀️ **Geladene kWh aus der PV** | Anteil des Solarstroms am Laden (mit eigenem PV-Preis bewertet) | Ebenfalls **außerhalb** des Tools zu ermitteln, z. B. über die Wallbox-/PV-Steuerung (evcc, go-e, OpenWB …) oder einen Template-/Utility-Meter-Sensor. Fortlaufender oder täglich zurückgesetzter kWh-Zähler. Oder mit den [Vorlagen](https://github.com/HasenbeinMH/ev-tracker-ha/blob/main/vorlagen/README.md) aus Netz- und Wallbox-Leistung berechnen. |
| 🚗 **Kilometerstand** | Gefahrene km pro Monat | Z. B. über die Fahrzeug-Integration des Herstellers |
| 💶 *Kosten Netz ins Auto (optional)* | Tatsächliche Stromkosten bei **dynamischem Tarif** (Tibber, aWATTar, Octopus …) statt eines festen Tarifs | Fortlaufender €-Zähler: jede kWh aus dem Netz × Preis in diesem Moment. Die Vorlage [`ev_netzkosten.yaml`](https://github.com/HasenbeinMH/ev-tracker-ha/blob/main/vorlagen/homeassistant/ev_netzkosten.yaml) legt ihn aus dem Preissensor an. |
| 📨 *Ladungen einzeln senden (optional)* | Heimladungen einzeln mit Datum statt als Monatssumme | Die Vorlage [`ev_ladung_senden.yaml`](https://github.com/HasenbeinMH/ev-tracker-ha/blob/main/vorlagen/homeassistant/ev_ladung_senden.yaml) – oder der [Blueprint](https://github.com/HasenbeinMH/ev-tracker-ha/blob/main/vorlagen/blueprints/README.md) – schickt am Ladeende kWh und Kosten an den EV Tracker; Adresse und Token stehen in den Einstellungen. |
| 🔋 *Batteriestand (optional)* | Ladeerkennung und Verbrauch aus dem Akkustand | Ebenfalls über die Fahrzeug-Integration |

Die Entity-IDs werden anschließend in den **Einstellungen** des EV Trackers eingetragen.

**PV/Netz ins Auto selbst berechnen:** Die [Vorlagen](https://github.com/HasenbeinMH/ev-tracker-ha/blob/main/vorlagen/README.md) – als Node-RED-Flow, als Home-Assistant-Paket oder zum Einfügen in die `configuration.yaml` – teilen die Ladeleistung der Wallbox nach „Haus zuerst, das Auto bekommt den Überschuss“ in PV und Netz auf (ein Hausakku zählt als PV) und legen die beiden kWh-Zähler an. Es genügen die Netzleistung und die Ladeleistung der Wallbox.
Die Aufteilung Netz/PV kann der EV Tracker nicht selbst berechnen – ohne diese beiden
Zähler fehlen die Kosten fürs Laden zu Hause. Ladevorgänge unterwegs (öffentliche
Ladesäulen) werden dagegen direkt in der App erfasst.

## Installation als Home-Assistant-Add-on

1. **Einstellungen → Add-ons → Add-on-Store** → oben rechts ⋮ → **Repositories**
2. URL einfügen: `https://github.com/HasenbeinMH/ev-tracker-ha`
3. **Hinzufügen**, Store neu laden
4. Unter „EV Tracker" erscheint **EV Tracker** → installieren, starten
5. Läuft komplett per Ingress (eigener Menüpunkt in der Seitenleiste) – kein offener Port,
   kein manuelles Access-Token nötig

## Erste Schritte

**Noch kein E-Auto?** Der **Simulationsmodus** (Einstellungen) rechnet aus den km und dem
Kraftstoffpreis des jetzigen Autos live, was ein E-Auto sparen würde – ohne etwas zu speichern.
Nach dem Kauf bleibt die Simulation als Prognose neben den echten Werten.

Nach dem Start im Menü **❓ Hilfe → Einrichtung** öffnen: Die Seite führt durch die
Grundeinstellungen und zeigt bei jedem Schritt, ob er schon erledigt ist.

1. **Einstellungen → Berechnungsparameter** – Fahrzeugname, Vergleich mit Benziner, Diesel
   oder Autogas, dessen Verbrauch, PV-Preis, KFZ-Steuer. Dazu ein **Fahrzeugbild**: fertige
   Bilder und ein Prompt für Bild-KIs unter
   [fahrzeugbilder](https://github.com/HasenbeinMH/ev-tracker-ha/tree/main/fahrzeugbilder).
2. **Verbindung zu Home Assistant** – im Add-on automatisch.
3. **Sensoren zuordnen** – Kilometerstand, PV und Netz ins Auto (kWh), Kraftstoffpreis,
   optional Batteriestand. Am einfachsten über „In HA suchen“ bzw. „In Datenbank suchen“.
4. **Datenbank** (optional) – nur wenn sie weiter zurückreicht als Home Assistant.
   **Erst speichern, dann testen:** Verbindungstest und Suche nutzen die gespeicherten Zugangsdaten.
5. **Stromtarif** anlegen, dann unter **HA Import** die vergangenen Monate holen.
6. **Ladungen unterwegs** unter Laden bzw. Rechnungen ergänzen, THG-Prämien unter Steuer & THG.

Danach holt der nächtliche Abruf km, kWh und Kraftstoffpreis jeden Monat von selbst.

## Funktionen

| Seite | Beschreibung |
|-------|-------------|
| 📊 Dashboard | Gesamtübersicht, Kennzahlen, alle Charts |
| 🚗 Fahrten | km erfassen, Kraftstoff-Äquivalent, Verbrauch kWh/100 km |
| 🔌 Laden | Ladevorgänge mit kWh, Preis, Anbieter, AC/DC, Blockiergebühr |
| 🔋 Ladetarife | Eigene Lade-Abos mit Preisverlauf |
| ⛽ Kraftstoffpreise | Benzin, Diesel oder Autogas: Monatsdurchschnitte + Preisverlauf |
| ⚡ Stromtarif | Tarifliste mit Preisverlauf |
| 💶 Steuer & THG | KFZ-Steuer-Ersparnis + THG-Quote-Erträge |
| 🔧 Instandhaltung | Werkstatt, Reifen, Verschleiß, HU – umgerechnet auf €/100 km |
| 🛡️ Versicherung | Gesellschaft, Deckung, SF-Klassen, Zusatzbausteine |
| 📥 HA Import | Nächtlicher Abruf aus Home Assistant, mit Protokoll |
| 🧾 Rechnungen | PDF-Rechnungen einlesen |
| 📄 Berichte | Monatsbericht als PDF, optional per Mail |
| 💾 Backup | Datenbank sichern und zurückspielen |
| ❓ Hilfe | Handbuch, Herleitung jeder Kennzahl, Änderungslog (Deutsch und Englisch) |

## Daten

Alle Daten liegen in einer eigenen SQLite-Datenbank (`ev_tracker.db`), im Add-on-Betrieb
unter `/data` – wird automatisch von Home Assistants eigenen Sicherungen mit erfasst.

## Benzin- bzw. Diesel-Äquivalent

Berechnung: `km / 100 × 7,0 L × Kraftstoffpreis`. Ob mit einem Benziner, einem Diesel oder einem
Autogas-Auto verglichen wird, steht in den Einstellungen – das ändert die Beschriftungen und den
Standard-CO2-Faktor (Benzin 2,37 kg/L, Diesel 2,65 kg/L, Autogas 1,64 kg/L).
Standard-Referenzverbrauch: **15 kWh/100 km** (in den Einstellungen pro Fahrzeug anpassbar)

## 🧾 Rechnungsimport: Musterrechnungen gesucht!

Der EV Tracker liest Ladeabrechnungen (PDF) automatisch ein. Damit das bei möglichst vielen
Anbietern klappt, brauche ich eure Hilfe: Wer bei einem dieser Anbieter lädt, kann mir gerne eine
Rechnung als PDF zur Verfügung stellen – gerne auch mehrere oder ältere, da sich die Layouts mit
der Zeit ändern.

| Anbieter | Stand |
|----------|-------|
| EnBW mobility+ | ✅ wird schon erkannt – weitere/ältere Layouts willkommen |
| Tesla Supercharger | ✅ wird schon erkannt – weitere/ältere Layouts willkommen |
| Shell Recharge | ✅ wird schon erkannt – weitere/ältere Layouts willkommen |
| EWE Go | ✅ wird schon erkannt – weitere/ältere Layouts willkommen |
| ADAC e-Charge | 🔍 gesucht |
| IONITY | 🔍 gesucht |
| Elli / Volkswagen Charging | 🔍 gesucht |
| Aral pulse | 🔍 gesucht |
| Maingau EinfachStromLaden | 🔍 gesucht |
| E.ON Drive | 🔍 gesucht |

Rechnungen von anderen Anbietern (z. B. Stadtwerke, Lidl, Plugsurfing) nehme ich ebenfalls gerne.
Schon erkannt werden außerdem medl, Charge myHyundai (Digital Charging Solutions), vaylens und reev.

**Bitte vorher persönliche Daten schwärzen:**
- Name und Anschrift
- Kunden-, Vertrags- und Rechnungsnummer
- Ladekarten-ID / EMA-ID
- IBAN bzw. Zahlungsdaten
- E-Mail-Adresse und Telefonnummer
- Kennzeichen bzw. Fahrzeug-ID (falls vorhanden)
- Ladeort (falls er Rückschlüsse auf euren Wohnort zulässt)

**Bitte NICHT schwärzen:**
- Anbietername und Firmenadresse des Anbieters
- Datum und Uhrzeit des Ladevorgangs
- geladene kWh, Preis pro kWh, Gesamtbetrag, MwSt.
- Ladeart (AC/DC) und, wenn möglich, die Ladeleistung

> ⚠️ **Wichtig:** Bitte richtig schwärzen und nicht einfach nur schwarze Kästen darüberlegen – bei
> vielen PDF-Programmen bleibt der Text darunter sonst auslesbar. Am sichersten ist die
> Schwärzen-Funktion (z. B. in Adobe Acrobat oder PDF24) oder ein Ausdruck, der danach wieder
> eingescannt wird.

Schickt mir die Rechnungen gerne per Mail an **[ev-tracker@email.de](mailto:ev-tracker@email.de)**
oder per PN in der
[simon42-Community (Thread zum EV Tracker)](https://community.simon42.com/t/ev-tracker-was-spart-mein-e-auto-wirklich-tester-gesucht/93110/29).
Bitte **nicht** als Anhang in einem GitHub-Issue – dort wäre die Rechnung für alle sichtbar.
Vielen Dank vorab, jede Rechnung hilft!

## Kontakt

Fragen, Rückmeldungen oder Musterrechnungen: **[ev-tracker@email.de](mailto:ev-tracker@email.de)**.
Fehler und Ideen gerne auch als [Issue auf GitHub](https://github.com/HasenbeinMH/ev-tracker-ha/issues)
oder im [Thread in der simon42-Community](https://community.simon42.com/t/ev-tracker-was-spart-mein-e-auto-wirklich-tester-gesucht/93110/29).

## Unterstützen

Der EV Tracker ist kostenlos und bleibt es auch. Wer die Weiterentwicklung unterstützen
möchte, kann das freiwillig über [Ko-fi](https://ko-fi.com/daniel71292) tun – danke! ☕

[![Unterstütze das Projekt auf Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/daniel71292)

---

## Für Entwickler: zwei Betriebsarten, eine Codebasis

Dieses Repo unterstützt zwei Deployments **derselben** App – das Home-Assistant-Add-on
(oben) und einen eigenständigen Docker-Betrieb (Portainer o.ä., siehe
[webapp/README.md](https://github.com/HasenbeinMH/ev-tracker-ha/blob/main/webapp/README.md)). Die eigentliche Anwendung (`webapp/app.py`,
`database.py`, `ha_client.py`, alle Templates usw.) ist bewusst **gemeinsamer Code** –
Änderungen dort wirken sich immer auf beide Betriebsarten aus, das ist gewollt (gleiche
Funktionen, nur anders verpackt). Nur diese Dateien sind jeweils exklusiv für eine
Betriebsart und beeinflussen die andere nicht:

| Datei | Gehört zu |
|-------|-----------|
| `Dockerfile`, `config.yaml`, `repository.yaml`, `icon.png`, `logo.png` | **Home-Assistant-Add-on** |
| `docker-compose.yml`, `webapp/Dockerfile`, `backup.sh`, `backup_db.py` | **Standalone-Docker** (Portainer o.ä.) |

Wo sich das Verhalten der App selbst je nach Betriebsart unterscheidet (Backup-Seite,
Home-Assistant-Verbindung), steht im Code immer die Variable `IST_ADDON`
(`ha_client.py`, dort auch `ha_verbindung()`) – erkennt automatisch, ob `SUPERVISOR_TOKEN` gesetzt ist. Danach
suchen, wenn unklar ist, wo genau sich beide Wege unterscheiden.

### Aufbau

| Ordner / Datei | Inhalt |
|----------------|--------|
| `webapp/` | FastAPI-Anwendung, Templates, statische Dateien, Dockerfile |
| `charts.py` | Chart-Definitionen (Apache ECharts), werden im Browser gezeichnet |
| `berechnung.py` | Alle Kennzahlen und Ersparnis-Berechnungen |
| `database.py` | SQLite-Zugriff und Schema |
| `ha_client.py` | Home Assistant (REST, WebSocket, Supervisor) |
| `datenquellen.py` | Datenbanken: InfluxDB 1.x/2.x/3.x, PostgreSQL/TimescaleDB (LTSS), Prometheus/VictoriaMetrics |
| `berichte.py`, `mailer.py` | Monatsbericht als PDF, Mailversand |
| `pdf_parser.py`, `ladeerkennung.py` | Rechnungs-PDFs, Erkennung von Ladevorgängen |
| `backup_db.py`, `backup.sh` | Sicherung der Datenbank (nur Standalone-Docker) |
| `settings_tool.py` | Einstellungen als JSON exportieren/importieren |
| `i18n.py`, `i18n/` | Sprachumschaltung: der deutsche Text ist der Schlüssel, `i18n/en.json` die englische Übersetzung; `i18n/pruefen.py` meldet fehlende Einträge. Neue Texte in Templates mit `{{ _("…") }}`, in Python mit `_("…")` schreiben |
| `testdaten.py`, `testdaten.bat` | Testdaten anlegen |
| `tests/funktionstest.py` | Funktions- und Plausibilitätstest mit eigener Test-DB: `python tests/funktionstest.py` (braucht zusätzlich `httpx`) |
| `tests/datenquellen_test.py` | Test der Datenbank-Anbindungen gegen nachgebaute Server: `python tests/datenquellen_test.py` |
| `vorlagen/` | Node-RED-Flow, HA-Pakete, Fassungen für die `configuration.yaml` und Blueprint: PV-/Netz-Anteil beim Laden, Netzkosten, Ladung senden (`node-red/quellen/flow_bauen.py` baut den Flow aus den `.js`-Quellen, `configuration_yaml/quellen/bauen.py` die configuration.yaml-Fassungen aus den Paketen) |
| `fahrzeugbilder/` | Galerie der Fahrzeugbilder (im Add-on enthalten, `galerie.py` liest Namen aus der README und Nachweise aus `CREDITS.md`) und der Prompt für eigene Bilder |
| `tests/vorlagen_test.py` | Test der Vorlagen (Node.js + Jinja2): `python tests/vorlagen_test.py` |
| `tests/migrationstest.py` | Datenbanken der letzten Versionen (per `git worktree`) mit dem aktuellen Code öffnen und Kennzahlen, Berichte und Tabellensummen vergleichen: `python tests/migrationstest.py` |
| `tests/fahrzeuge_test.py` | Mehrere Fahrzeuge: Umschalten, Gesamtsicht, Verteilung der Wallbox, Push, Ausblenden/Löschen, Abbruch des Umbaus, Vergleich mit 2.16: `python tests/fahrzeuge_test.py` |
| `tests/i18n_test.py` | Sprachumschaltung: jeder Text übersetzt, alle Seiten in Deutsch und Englisch, JavaScript gültig, Deutsch unverändert, keine deutschen Wörter in Englisch, Bericht auf Englisch (braucht Node.js): `python tests/i18n_test.py` |
| `tests/oberflaeche_test.py` | Alle Seiten im echten Browser (Playwright/Chromium), JS-Fehler, Formular, Zustand „Nur lesbar“; optional Screenshots: `python tests/oberflaeche_test.py [ordner]` |
| `tests/datenquellen_docker_test.py` | Dieselben Anbindungen gegen echte Server in Docker (InfluxDB 1.8/2.7, TimescaleDB, VictoriaMetrics, Prometheus): `python tests/datenquellen_docker_test.py` |
| `version.py` | Versionsnummer und Änderungslog |
