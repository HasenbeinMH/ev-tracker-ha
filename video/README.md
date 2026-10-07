# Werbevideo

60 Sekunden, 1920×1080, Deutsch. Gebaut mit [Remotion](https://www.remotion.dev/) aus Aufnahmen
der App mit Demodaten – nie aus der echten Datenbank. Die Musik wird per Code erzeugt
(`skripte/musik.py`), ohne Samples und ohne fremde Rechte.

Nicht Teil des Add-ons: der Ordner steht in `.dockerignore`. Aufnahmen, Demo-Datenbank,
`node_modules` und das fertige Video stehen in `.gitignore`.

## Neu erzeugen

Voraussetzungen: Python mit den Paketen des Add-ons (`webapp/requirements-web.txt`) plus
`playwright`, `numpy` und `scipy`; Node.js; Microsoft Edge (wird für Aufnahmen und Rendern
genutzt, kein extra Browser-Download).

Aus dem Repo-Ordner:

```bash
python video/skripte/demo_daten.py
python video/skripte/aufnahmen.py
python video/skripte/musik.py
```

Dann im Ordner `video/`:

```bash
npm install
npm run render
```

Ergebnis: `video/out/ev-tracker-werbevideo.mp4`. Mit `npm run studio` öffnet sich die
Vorschau zum Bearbeiten im Browser.

## Aufbau

| Datei | Inhalt |
|---|---|
| `skripte/demo_daten.py` | Demo-Datenbank `demo/ev_tracker.db`: Kia EV3, 01/2025 bis 10/2026, EnBW-Abo mit Ad-hoc-Vergleich, PV und Wallbox |
| `skripte/aufnahmen.py` | Startet die App mit der Demo-Datenbank und fotografiert Dashboard, Ladetarife und Monatsbericht in dreifacher Auflösung nach `public/` |
| `skripte/musik.py` | Hintergrundmusik `public/musik.wav` (96 BPM, Am – F – C – G) |
| `src/Werbevideo.tsx` | Szenen, Texte, Kamerafahrten und Markierungen |

Die Demodaten enden im Oktober 2026. Später neu erzeugt, hat der laufende Monat keine
Daten – dann in `demo_daten.py` die Monate bis zum aktuellen Monat verlängern.
Kamerafahrten und Markierungen in `Werbevideo.tsx` stehen in CSS-Pixeln der Aufnahmen;
ändert sich das Layout der App, müssen sie angepasst werden (`aufnahmen.py` gibt die
Lage der Abschnitte aus).

Remotion ist für Einzelpersonen und Teams bis drei Personen kostenlos, siehe
[Lizenz](https://www.remotion.dev/license).
