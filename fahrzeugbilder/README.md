# Fahrzeugbilder für den EV Tracker

Das Bild steht im Kopf des Dashboards neben dem Fahrzeugnamen. Die App leitet daraus
auch die **Akzentfarbe** ab (Farbverlauf und Fahrzeugname) – sie passt sich der
Lackfarbe an.

In diesem Ordner liegen fertige Bilder zum Herunterladen. Eigenes Auto nicht dabei?
Mit dem Prompt unten erzeugt eine Bild-KI (z.B. ChatGPT, Gemini, Midjourney) ein
passendes Bild – aus einem eigenen Foto oder ganz neu.

## Bild einsetzen

Die Bilder dieses Ordners sind im Add-on enthalten: **Einstellungen → Fahrzeugbild →
Aus der Galerie wählen**, ein Klick genügt. Urheber und Lizenz der Vorlage stehen danach
unter dem Bild. Ein eigenes Bild:

1. Mit dem Prompt unten erzeugen (oder ein Bild aus diesem Ordner herunterladen).
2. Im EV Tracker: **Einstellungen → Fahrzeugbild → Neues Bild** wählen → **Hochladen**.
3. Zurück zum Standardbild: **↺ Standardbild**.

**Neues Bild für die Galerie:** Datei hier ablegen, eine Zeile in die Tabelle
„Vorhandene Bilder“ (Anzeigename) und – bei einer Vorlage – eine in
[CREDITS.md](CREDITS.md). Mit dem nächsten Update erscheint es in der App; am Code
ändert sich nichts. Der Arbeitsordner `final/` wird nicht mitgeliefert.

JPG, PNG oder WebP, höchstens 8 MB.

## So sieht ein gutes Bild aus

| Vorgabe | Warum |
|---------|-------|
| **Querformat 16:9**, z.B. 1376 × 768 Pixel | Das Bild wird 125 Pixel hoch angezeigt, auf dem Handy in voller Breite |
| **Hintergrund transparent (PNG)** oder einfarbig **#14171E** | Das ist die Farbe des Dashboard-Kopfs – so gibt es keine sichtbare Kante |
| Auto **schräg von vorne links**, füllt das Bild fast aus | Alle Bilder wirken dann einheitlich; der Text steht links daneben |
| **Keine Schrift**, kein Wasserzeichen, kein Boden, keine Spiegelung | Stört auf dem dunklen Hintergrund |
| **Keine Umgebung in Lack und Scheiben** (Bäume, Gebäude, Himmel) | Verrät das Straßenfoto und passt nicht zum Studiohintergrund |
| Dateiname **`marke-modell-farbe.jpg`**, Marke und Modell wie in der Vorlage | So bleibt jedes Bild seiner Vorlage und deren Nachweis zuzuordnen |
| Kräftige, echte **Lackfarbe** | Aus ihr entsteht die Akzentfarbe; bei Weiß, Grau oder Schwarz bleibt es beim Standard-Orange |

## Prompt: Bild aus einem Foto

Für ein eigenes Foto oder ein frei lizenziertes (z.B. von Wikimedia Commons). Foto
hochladen (am besten schräg von vorne), `DATEINAME` durch den Namen der hochgeladenen
Datei ersetzen und `FARBE` durch die Lackfarbe auf Deutsch, dann:

```text
Stelle das Auto auf diesem Foto frei und setze es auf einen komplett einfarbigen
Hintergrund in der Farbe #14171E (sehr dunkles Blaugrau), ohne Verlauf. Ansicht:
schräg von vorne links (Dreiviertelansicht), das Auto zeigt nach links. Querformat
16:9, 1376 × 768 Pixel, das Auto füllt etwa 90 % der Bildbreite und ist vollständig
zu sehen.

Spiegelungen: Entferne alle Spiegelungen der Umgebung aus Lack, Scheiben, Chrom und
Felgen – Bäume, Äste, Gebäude, Himmel, Wolken, Straßenlaternen, Personen, andere Autos
und den Fotografen. Ersetze sie durch ruhige, neutrale Studio-Reflexe: weiche
Lichtkanten auf Motorhaube, Dach und Flanken. Die Scheiben dunkel getönt und gleichmäßig,
der Innenraum nur schemenhaft. Die Lackfarbe dabei nicht verändern.

Lackfarbe, Felgen, Scheinwerfer und alle Details des Originals genau beibehalten –
Modell und Ausstattung dürfen sich nicht ändern. Studiobeleuchtung, weich und
gleichmäßig. Kein Boden, kein Schatten, keine Bodenspiegelung, keine Umgebung, kein
Text, kein Wasserzeichen. Das Kennzeichen neutral machen (leer oder nur Modellname).

Dateiname: Gib das Ergebnis als JPG mit dem Namen marke-modell-farbe.jpg aus – klein
geschrieben, Wörter mit Bindestrich, ohne Umlaute. Marke und Modell übernimmst du aus
dem Dateinamen der Vorlage „DATEINAME“, die Farbe ist FARBE. Beispiel: Vorlage
„BMW_iX1_1X7A6829.jpg“, Farbe grau → bmw-ix1-grau.jpg.
```

Auf Englisch:

```text
Cut out the car from this photo and place it on a solid flat background in #14171E
(very dark blue-gray), no gradient. Front three-quarter view from the left, the car
facing left. Landscape 16:9, 1376 × 768 pixels, the car fills about 90 % of the image
width and is fully visible.

Reflections: remove every reflection of the surroundings from the paint, windows,
chrome and wheels – trees, branches, buildings, sky, clouds, street lights, people,
other cars and the photographer. Replace them with calm, neutral studio reflections:
soft highlights along the hood, roof and sides. Windows evenly dark tinted, the
interior only faintly visible. Do not change the paint color.

Keep the paint color, wheels, headlights and all details of the original exactly –
model and trim must not change. Soft, even studio lighting. No floor, no shadow, no
floor reflection, no surroundings, no text, no watermark. Neutral license plate
(blank or model name only).

File name: deliver the result as a JPG named make-model-color.jpg – lower case, words
joined by hyphens, no umlauts, color in German. Take make and model from the file name
of the source "DATEINAME", the color is FARBE. Example: source "BMW_iX1_1X7A6829.jpg",
color grau → bmw-ix1-grau.jpg.
```

**Vorlage von Wikimedia Commons:** Urheber, Link zur Vorlage und Lizenz gehören in die
Tabelle unten. Der Dateiname der Vorlage steht in ihrem Link – deshalb Marke und Modell
im neuen Namen genau so übernehmen.

**Kann die KI keinen Dateinamen vergeben** (manche liefern nur ein Bild), die Datei nach
dem Herunterladen selbst nach demselben Schema umbenennen.

## Prompt: Bild ganz neu erzeugen

`MARKE MODELL`, `BAUJAHR` und `LACKFARBE` ersetzen, z.B. „Hyundai Ioniq 5“, „2024“, „Gravity Gold matt“:

```text
Fotorealistisches Studiobild eines MARKE MODELL (Baujahr BAUJAHR) in der Lackfarbe
LACKFARBE. Ansicht: schräg von vorne links (Dreiviertelansicht), das Auto zeigt nach
links. Komplett einfarbiger Hintergrund in #14171E (sehr dunkles Blaugrau), ohne
Verlauf. Querformat 16:9, 1376 × 768 Pixel, das Auto füllt etwa 90 % der Bildbreite
und ist vollständig zu sehen. Weiche, gleichmäßige Studiobeleuchtung, leichte
Lichtkante oben, originalgetreue Felgen und Scheinwerfer. Kein Boden, kein Schatten,
keine Spiegelung, keine Umgebung in Lack und Scheiben, keine Personen, kein Text, kein
Wasserzeichen. Kennzeichen neutral (leer oder nur Modellname). Gib das Ergebnis als JPG
mit dem Namen marke-modell-farbe.jpg aus – klein, mit Bindestrichen, ohne Umlaute,
z.B. hyundai-ioniq-5-gold.jpg.
```

Viele Bild-KIs verstehen Englisch besser. Dieselbe Anfrage auf Englisch:

```text
Photorealistic studio image of a MAKE MODEL (model year YEAR) in the paint color
COLOR. Front three-quarter view from the left, the car facing left. Solid flat
background in #14171E (very dark blue-gray), no gradient. Landscape 16:9,
1376 × 768 pixels, the car fills about 90 % of the image width and is fully visible.
Soft, even studio lighting with a subtle rim light on top, accurate wheels and
headlights. No floor, no shadow, no reflection, no surroundings mirrored in paint or
windows, no people, no text, no watermark. Neutral license plate (blank or model name
only). Deliver the result as a JPG named make-model-color.jpg – lower case, hyphens,
no umlauts, color in German, e.g. hyundai-ioniq-5-gold.jpg.
```

**Transparenter Hintergrund:** Kann die Bild-KI das (z.B. „als PNG mit transparentem
Hintergrund“), ist das die beste Wahl – dann statt #14171E einfach „transparenter
Hintergrund, PNG“ schreiben. Sonst ist der einfarbige Hintergrund der sichere Weg.

**Nachbessern:** Ein zweiter Durchgang hilft gezielt, ohne den Rest anzufassen:
- Hintergrund: „Ersetze den Hintergrund durch exakt #14171E, sonst nichts ändern.“
- Spiegelungen: „Entferne die restlichen Spiegelungen der Umgebung aus Lack und Scheiben
  und ersetze sie durch neutrale Studio-Reflexe. Lackfarbe, Form und alles andere
  unverändert lassen.“

## Bild beitragen

Eigenes Bild für andere freigeben? Gern als Pull Request in diesen Ordner, benannt
nach `marke-modell-farbe.jpg` (klein, mit Bindestrichen), z.B. `hyundai-ioniq-5-gold.jpg`.
Erlaubt sind selbst erzeugte oder fotografierte Bilder und Bilder unter einer freien
Lizenz (z.B. von Wikimedia Commons, CC BY / CC BY-SA / CC0) – dann mit Urheber, Quelle
und Lizenz in der Tabelle unten. Keine Pressefotos oder Bilder ohne klare Lizenz.

## Vorhandene Bilder

| Datei | Fahrzeug | Vorlage, Urheber, Lizenz |
|-------|----------|--------------------------|
| [`audi-a6-etron-schwarz.jpg`](audi-a6-etron-schwarz.jpg) | Audi A6 e-tron, Schwarz | [Audi A6 Avant e-tron DSC 7425](https://commons.wikimedia.org/wiki/File:Audi_A6_Avant_e-tron_DSC_7425.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`audi-q4-etron-grau.jpg`](audi-q4-etron-grau.jpg) | Audi Q4 e-tron, Grau | [Audi Q4 Sportback e-tron IAA 2021 1X7A0159](https://commons.wikimedia.org/wiki/File:Audi_Q4_Sportback_e-tron_IAA_2021_1X7A0159.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`audi-q6-etron-grau.jpg`](audi-q6-etron-grau.jpg) | Audi Q6 e-tron, Grau | [Audi Q6 e-tron Sportback DSC 9276](https://commons.wikimedia.org/wiki/File:Audi_Q6_e-tron_Sportback_DSC_9276.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`bmw-i4-weiss.jpg`](bmw-i4-weiss.jpg) | BMW i4, Weiß | [BMW i4 IAA 2021 1X7A0307](https://commons.wikimedia.org/wiki/File:BMW_i4_IAA_2021_1X7A0307.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`bmw-i5-weiss.jpg`](bmw-i5-weiss.jpg) | BMW i5, Weiß | [BMW G60 520i 1X7A2443](https://commons.wikimedia.org/wiki/File:BMW_G60_520i_1X7A2443.jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`bmw-ix1-silber.jpg`](bmw-ix1-silber.jpg) | BMW iX1, Silber | [BMW iX1 1X7A6829](https://commons.wikimedia.org/wiki/File:BMW_iX1_1X7A6829.jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`bmw-ix3-blau.jpg`](bmw-ix3-blau.jpg) | BMW iX3, Blau | [BMW iX3, IAA Summit 2025, Munich (20250908-P1049823)](https://commons.wikimedia.org/wiki/File:BMW_iX3,_IAA_Summit_2025,_Munich_(20250908-P1049823).jpg) von Matti Blume, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/deed.en), bearbeitet |
| [`citroen-ec3-silber.jpg`](citroen-ec3-silber.jpg) | Citroën ë-C3, Silber | [Citroen ë-C3 IMG 4539](https://commons.wikimedia.org/wiki/File:Citroen_%C3%AB-C3_IMG_4539.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`cupra-born-grau.jpg`](cupra-born-grau.jpg) | Cupra Born, Grau | [Cupra Born IMG 8234](https://commons.wikimedia.org/wiki/File:Cupra_Born_IMG_8234.jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`cupra-tavascan-grau.jpg`](cupra-tavascan-grau.jpg) | Cupra Tavascan, Grau | [Cupra Tavascan Leonberg 2024 IMG 0881](https://commons.wikimedia.org/wiki/File:Cupra_Tavascan_Leonberg_2024_IMG_0881.jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`dacia-spring-schwarz.jpg`](dacia-spring-schwarz.jpg) | Dacia Spring, Schwarz | [2023 Dacia Spring 1X7A6282](https://commons.wikimedia.org/wiki/File:2023_Dacia_Spring_1X7A6282.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`fiat-500e-blau.jpg`](fiat-500e-blau.jpg) | Fiat 500e, Blau | [Fiat 500e in München](https://commons.wikimedia.org/wiki/File:Fiat_500e_in_M%C3%BCnchen.jpg) von AuHaidhausen, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0), bearbeitet |
| [`ford-explorer-ev-hellblau.jpg`](ford-explorer-ev-hellblau.jpg) | Ford Explorer EV, Hellblau | [2024 Ford Explorer Premium EV AWD](https://commons.wikimedia.org/wiki/File:2024_Ford_Explorer_Premium_EV_AWD.jpg) von Calreyn88, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`hyundai-inster-weiss.jpg`](hyundai-inster-weiss.jpg) | Hyundai Inster, Weiß | [Hyundai Inster DSC 8778](https://commons.wikimedia.org/wiki/File:Hyundai_Inster_DSC_8778.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`kia-ev3-orange.jpg`](kia-ev3-orange.jpg) | Kia EV3, Orange (Standardbild der App) | – |
| [`leapmotor-t03-hellblau.jpg`](leapmotor-t03-hellblau.jpg) | Leapmotor T03, Hellblau | [Leapmotor T03 IAA 2023 1X7A0244](https://commons.wikimedia.org/wiki/File:Leapmotor_T03_IAA_2023_1X7A0244.jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`mercedes-cla-ev-hellblau.jpg`](mercedes-cla-ev-hellblau.jpg) | Mercedes CLA (elektrisch), Hellblau | [Mercedes-Benz Electric CLA 001](https://commons.wikimedia.org/wiki/File:Mercedes-Benz_Electric_CLA_001.jpg) von JustAnotherCarDesigner, [CC0](http://creativecommons.org/publicdomain/zero/1.0/deed.en), bearbeitet |
| [`mercedes-eqb-silber.jpg`](mercedes-eqb-silber.jpg) | Mercedes EQB, Silber | [MERCEDES-EQ EQB China (3)](https://commons.wikimedia.org/wiki/File:MERCEDES-EQ_EQB_China_(3).jpg) von Dinkun Chen, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`mercedes-glc-ev-blau.jpg`](mercedes-glc-ev-blau.jpg) | Mercedes GLC (elektrisch), Blau | [Mercedes-Benz GLC with EQ Technology IMG 6100](https://commons.wikimedia.org/wiki/File:Mercedes-Benz_GLC_with_EQ_Technology_IMG_6100.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`mini-cooper-e-blau.jpg`](mini-cooper-e-blau.jpg) | Mini Cooper E, Blau | [2005 Mini Cooper S](https://commons.wikimedia.org/wiki/File:2005_Mini_Cooper_S.jpg) von Calreyn88, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`opel-grandland-ev-kupfer.jpg`](opel-grandland-ev-kupfer.jpg) | Opel Grandland Electric, Kupfer | [Opel Grandland Electric Sindelfingen 2025 DSC 9106](https://commons.wikimedia.org/wiki/File:Opel_Grandland_Electric_Sindelfingen_2025_DSC_9106.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`renault-5-etech-gelb.jpg`](renault-5-etech-gelb.jpg) | Renault 5 E-Tech, Gelb | [Renault 5 E-Tech Electric Auto Zuerich 2024 DSC 6501](https://commons.wikimedia.org/wiki/File:Renault_5_E-Tech_Electric_Auto_Zuerich_2024_DSC_6501.jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`skoda-elroq-gruen.jpg`](skoda-elroq-gruen.jpg) | Škoda Elroq, Grün | [Škoda Elroq - 01](https://commons.wikimedia.org/wiki/File:%C5%A0koda_Elroq_-_01.jpg) von Y.Leclercq, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`skoda-enyaq-gruen.jpg`](skoda-enyaq-gruen.jpg) | Škoda Enyaq, Grün | [Škoda Enyaq IMG 1190](https://commons.wikimedia.org/wiki/File:%C5%A0koda_Enyaq_IMG_1190.jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`tesla-model-3-weiss.jpg`](tesla-model-3-weiss.jpg) | Tesla Model 3, Weiß | [Tesla Model 3 (2023) IMG 9488 (cropped)](https://commons.wikimedia.org/wiki/File:Tesla_Model_3_(2023)_IMG_9488_(cropped).jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`tesla-model-y-weiss.jpg`](tesla-model-y-weiss.jpg) | Tesla Model Y, Weiß | [Tesla Model Y 2025 at Santana Row dllu 02](https://commons.wikimedia.org/wiki/File:Tesla_Model_Y_2025_at_Santana_Row_dllu_02.jpg) von Dllu, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`vw-id-buzz-orange.jpg`](vw-id-buzz-orange.jpg) | VW ID. Buzz, Orange-Weiß | [Volkswagen ID. Buzz 1X7A6264](https://commons.wikimedia.org/wiki/File:Volkswagen_ID._Buzz_1X7A6264.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`vw-id3-weiss.jpg`](vw-id3-weiss.jpg) | VW ID.3, Weiß | [2020 Volkswagen ID.3 1st Front](https://commons.wikimedia.org/wiki/File:2020_Volkswagen_ID.3_1st_Front.jpg) von Vauxford, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`vw-id4-silber.jpg`](vw-id4-silber.jpg) | VW ID.4, Silber | [Volkswagen ID.5 GTX 1X7A0318](https://commons.wikimedia.org/wiki/File:Volkswagen_ID.5_GTX_1X7A0318.jpg) von Alexander Migl, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |
| [`vw-id7-silber.jpg`](vw-id7-silber.jpg) | VW ID.7, Silber | [Volkswagen ID.7 IAA 2023 1X7A0375](https://commons.wikimedia.org/wiki/File:Volkswagen_ID.7_IAA_2023_1X7A0375.jpg) von Alexander-93, [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0), bearbeitet |

**Alle Vorlagen** mit Urheber und Lizenz stehen in [CREDITS.md](CREDITS.md).

**Lizenz der bearbeiteten Bilder:** Die Bilder sind Bearbeitungen ihrer Vorlage
(freigestellt, auf den Hintergrund #14171E gesetzt, Spiegelungen entfernt, zum Teil
KI-überarbeitet). Bei CC BY-SA stehen sie unter derselben Lizenz; wer sie weitergibt,
nennt den Urheber der Vorlage wie oben. Bei CC0 ist keine Nennung nötig.