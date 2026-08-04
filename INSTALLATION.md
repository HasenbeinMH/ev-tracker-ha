# ⚡ EV Tracker – Installationsanleitung (Windows)

## Voraussetzungen

### Python installieren (einmalig)

1. **Python herunterladen:**  
   👉 https://www.python.org/downloads/  
   Aktuelle Version (3.11 oder 3.12) herunterladen

2. **Installer starten** und dabei unbedingt aktivieren:  
   ☑️ **„Add Python to PATH"** (untere Checkbox im ersten Fenster!)  
   → Dann auf „Install Now" klicken

3. **Installation prüfen:**  
   `Win + R` → `cmd` → Enter → folgendes eingeben:
   ```
   python --version
   ```
   Ausgabe sollte sein: `Python 3.11.x` o.ä.

---

## EV Tracker installieren

### Schritt 1 – ZIP entpacken

ZIP-Datei in einen Ordner entpacken, z.B.:
```
C:\Users\Daniel\EV-Tracker\
```

### Schritt 2 – Abhängigkeiten installieren

**`install.bat` doppelklicken**

Das Skript installiert automatisch:
- PyQt6 (GUI-Framework)
- PyQt6-WebEngine (für interaktive Charts)
- Plotly (Chart-Bibliothek)

⏱️ Dauer: ca. 1–3 Minuten je nach Internetgeschwindigkeit.

Bei Erfolg erscheint:
```
Installation erfolgreich abgeschlossen!
Starte die App mit: start.bat
```

### Schritt 3 – App starten

**`start.bat` doppelklicken**

Die App öffnet sich. Die Datenbank `ev_tracker.db` wird beim ersten Start
automatisch im gleichen Ordner angelegt.

---

## Tägliche Nutzung

Zum Starten immer **`start.bat`** doppelklicken.  
`install.bat` muss nur **einmalig** ausgeführt werden.

Optional: Verknüpfung von `start.bat` auf den Desktop ziehen.

---

## Datensicherung

Alle Daten liegen in einer einzigen Datei:
```
ev_tracker\ev_tracker.db
```
Diese Datei regelmäßig kopieren (z.B. auf OneDrive/NAS) – das reicht als
vollständiges Backup.

---

## Fehlerbehebung

| Problem | Lösung |
|---------|--------|
| „Python nicht gefunden" | Python neu installieren, dabei PATH-Checkbox aktivieren |
| „Abhängigkeiten fehlen" | `install.bat` nochmals ausführen |
| App startet, aber Charts leer | Internetverbindung prüfen (Plotly lädt JS einmalig) |
| Schwarzes Fenster kurz sichtbar | Normal – schließt sich selbst beim Start |

---

## Technische Details

| Komponente | Version |
|------------|---------|
| Python | 3.10+ |
| PyQt6 | 6.5+ |
| PyQt6-WebEngine | 6.5+ |
| Plotly | 5.18+ |
| Datenbank | SQLite (lokal, keine Cloud) |

---

## Deinstallation

1. Ordner `ev_tracker\` löschen  
2. Optional Python deinstallieren (Systemsteuerung → Programme)

Die Datenbank `ev_tracker.db` vorher sichern falls die Daten noch benötigt werden.
