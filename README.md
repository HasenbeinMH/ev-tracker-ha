# ⚡ EV Tracker – Kia EV3

Lokale Desktop-App zur Erfassung und Auswertung der Kosteneinsparungen gegenüber einem Benziner.

## Voraussetzungen

- Python 3.10+
- pip

## Installation

```bash
cd ev_tracker
pip install -r requirements.txt
python main.py
```

## Funktionen

| Tab | Beschreibung |
|-----|-------------|
| 📊 Dashboard | Gesamtübersicht, Stat-Cards, alle Charts |
| 🚗 Fahrten | km erfassen, Benzin-Äquivalent (7L/100km) |
| 🔌 Laden | Ladevorgänge mit kWh, Preis, Anbieter, AC/DC |
| ⛽ Benzinpreise | Monatsdurchschnitte + Preisverlauf |
| ⚡ Stromtarif | Tarifliste mit Preisverlauf |
| 💶 Steuer & THG | KFZ-Steuer Ersparnis + THG-Quote Erträge |

## Daten

Alle Daten werden lokal in `ev_tracker.db` (SQLite) gespeichert.

## Anbieter (Laden)

- **Privat**: Strompreis wird aus aktivem Tarif vorgeschlagen
- **mEDL / EnBW / Ionity / ARAL Pulse**: Vollständige Eingabe Preis/kWh + Gesamtpreis

## Benzin-Äquivalent

Berechnung: `km / 100 × 7,0 L × Benzinpreis`  
Kia EV3 Standard-Verbrauch: **15 kWh/100km**
