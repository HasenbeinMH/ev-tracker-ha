# Fahrzeugbilder für den EV Tracker

Das Bild steht im Kopf des Dashboards neben dem Fahrzeugnamen. Die App leitet daraus
auch die **Akzentfarbe** ab (Farbverlauf und Fahrzeugname) – sie passt sich der
Lackfarbe an.

In diesem Ordner liegen fertige Bilder zum Herunterladen. Eigenes Auto nicht dabei?
Mit dem Prompt unten erzeugt eine Bild-KI (z.B. ChatGPT, Gemini, Midjourney) ein
passendes Bild – aus einem eigenen Foto oder ganz neu.

## Bild einsetzen

1. Bild aus diesem Ordner öffnen → **Download** (Symbol oben rechts), oder ein eigenes erzeugen.
2. Im EV Tracker: **Einstellungen → Fahrzeugbild → Neues Bild** wählen → **Hochladen**.
3. Zurück zum Standardbild: **↺ Standardbild**.

JPG, PNG oder WebP, höchstens 8 MB.

## So sieht ein gutes Bild aus

| Vorgabe | Warum |
|---------|-------|
| **Querformat 16:9**, z.B. 1376 × 768 Pixel | Das Bild wird 125 Pixel hoch angezeigt, auf dem Handy in voller Breite |
| **Hintergrund transparent (PNG)** oder einfarbig **#14171E** | Das ist die Farbe des Dashboard-Kopfs – so gibt es keine sichtbare Kante |
| Auto **schräg von vorne links**, füllt das Bild fast aus | Alle Bilder wirken dann einheitlich; der Text steht links daneben |
| **Keine Schrift**, kein Wasserzeichen, kein Boden, keine Spiegelung | Stört auf dem dunklen Hintergrund |
| Kräftige, echte **Lackfarbe** | Aus ihr entsteht die Akzentfarbe; bei Weiß, Grau oder Schwarz bleibt es beim Standard-Orange |

## Prompt: Bild aus einem eigenen Foto

Foto des eigenen Autos hochladen (am besten schräg von vorne), dann:

```text
Stelle das Auto auf diesem Foto frei und setze es auf einen komplett einfarbigen
Hintergrund in der Farbe #14171E (sehr dunkles Blaugrau). Ansicht: schräg von vorne
links (Dreiviertelansicht), das Auto zeigt nach links. Querformat 16:9, 1376 × 768
Pixel, das Auto füllt etwa 90 % der Bildbreite und ist vollständig zu sehen.
Lackfarbe, Felgen und Details des Originals genau beibehalten. Studiobeleuchtung,
weich und gleichmäßig, leichte Lichtkante oben. Kein Boden, kein Schatten, keine
Spiegelung, keine Umgebung, kein Text, kein Wasserzeichen. Das Kennzeichen neutral
machen (leer oder nur Modellname).
```

## Prompt: Bild ganz neu erzeugen

`MARKE MODELL`, `BAUJAHR` und `LACKFARBE` ersetzen, z.B. „Hyundai Ioniq 5“, „2024“, „Gravity Gold matt“:

```text
Fotorealistisches Studiobild eines MARKE MODELL (Baujahr BAUJAHR) in der Lackfarbe
LACKFARBE. Ansicht: schräg von vorne links (Dreiviertelansicht), das Auto zeigt nach
links. Komplett einfarbiger Hintergrund in #14171E (sehr dunkles Blaugrau), ohne
Verlauf. Querformat 16:9, 1376 × 768 Pixel, das Auto füllt etwa 90 % der Bildbreite
und ist vollständig zu sehen. Weiche, gleichmäßige Studiobeleuchtung, leichte
Lichtkante oben, originalgetreue Felgen und Scheinwerfer. Kein Boden, kein Schatten,
keine Spiegelung, keine Personen, kein Text, kein Wasserzeichen. Kennzeichen neutral
(leer oder nur Modellname).
```

Viele Bild-KIs verstehen Englisch besser. Dieselbe Anfrage auf Englisch:

```text
Photorealistic studio image of a MAKE MODEL (model year YEAR) in the paint color
COLOR. Front three-quarter view from the left, the car facing left. Solid flat
background in #14171E (very dark blue-gray), no gradient. Landscape 16:9,
1376 × 768 pixels, the car fills about 90 % of the image width and is fully visible.
Soft, even studio lighting with a subtle rim light on top, accurate wheels and
headlights. No floor, no shadow, no reflection, no people, no text, no watermark.
Neutral license plate (blank or model name only).
```

**Transparenter Hintergrund:** Kann die Bild-KI das (z.B. „als PNG mit transparentem
Hintergrund“), ist das die beste Wahl – dann statt #14171E einfach „transparenter
Hintergrund, PNG“ schreiben. Sonst ist der einfarbige Hintergrund der sichere Weg.

**Nachbessern:** Passt der Hintergrund nicht genau, hilft ein zweiter Durchgang:
„Ersetze den Hintergrund durch exakt #14171E, sonst nichts ändern.“

## Bild beitragen

Eigenes Bild für andere freigeben? Gern als Pull Request in diesen Ordner, benannt
nach `marke-modell-farbe.jpg` (klein, mit Bindestrichen), z.B. `hyundai-ioniq5-gold.jpg`.
Bitte nur Bilder, die du selbst erzeugt oder fotografiert hast – keine Pressefotos
oder Bilder aus dem Netz.

## Vorhandene Bilder

| Datei | Fahrzeug |
|-------|----------|
| [`audi-a6-etron-schwarz.jpg`](audi-a6-etron-schwarz.jpg) | Audi A6 e-tron, Schwarz |
| [`audi-q4-etron-sportback-grau.jpg`](audi-q4-etron-sportback-grau.jpg) | Audi Q4 e-tron Sportback, Grau |
| [`audi-q6-etron-silber.jpg`](audi-q6-etron-silber.jpg) | Audi Q6 e-tron, Silber (Erlkönig-Folie) |
| [`bmw-i5-schwarz.jpg`](bmw-i5-schwarz.jpg) | BMW i5, Schwarz |
| [`bmw-ix1-grau.jpg`](bmw-ix1-grau.jpg) | BMW iX1, Grau |
| [`bmw-ix3-blau.jpg`](bmw-ix3-blau.jpg) | BMW iX3, Blau |
| [`kia-ev3-orange.jpg`](kia-ev3-orange.jpg) | Kia EV3, Orange (Standardbild der App) |
