# -*- coding: utf-8 -*-
"""
Baut die Vorlagen fuer die configuration.yaml (../*.yaml) aus den Home-Assistant-
Paketen in vorlagen/homeassistant/. Die Pakete bleiben die einzige Quelle – nach
jeder Aenderung dort dieses Skript laufen lassen:

    python vorlagen/configuration_yaml/quellen/bauen.py

Unterschied zum Paket: In der configuration.yaml darf jeder Schluessel nur einmal
vorkommen, und viele haben dort schon "template:", "sensor:" oder
"automation: !include automations.yaml". Deshalb:
  - sensor und automation bekommen einen eigenen Schluessel mit Namen
    ("sensor ev_tracker:", "automation ev_tracker:") – das versteht Home Assistant
    neben dem vorhandenen Schluessel;
  - bei allen anderen (template, input_number, ...) steht ein Kommentar, wie man
    die Eintraege an einen vorhandenen Schluessel anhaengt;
  - der Einrichtungsschritt "nach /config/packages/ kopieren" wird ersetzt.
"""
import os
import re

HIER = os.path.dirname(os.path.abspath(__file__))
ZIEL = os.path.dirname(HIER)
QUELLE = os.path.join(os.path.dirname(ZIEL), "homeassistant")
DATEIEN = ("ev_pv_anteil.yaml", "ev_pv_anteil_mit_zaehler.yaml",
           "ev_netzkosten.yaml", "ev_ladung_senden.yaml")

# Domains, die mehrere Schluessel mit Namen zulassen ("domain name:")
EIGENER_SCHLUESSEL = {"sensor", "automation"}
# Listen (Eintraege beginnen mit "-") oder Zuordnungen (Eintraege sind Namen)
LISTEN = {"template"}

SCHRITT = re.compile(r"^#  (\d+)\. ")
SCHLUESSEL = re.compile(r"^([a-z_]+):\s*$")


def einrichtung(nr: int) -> list:
    e = " " * (len(str(nr)) + 2)
    return [
        f"#  {nr}. Alles unterhalb dieses Kastens ans Ende der configuration.yaml kopieren.",
        f"#  {e}Jeder Schlüssel darf dort nur einmal vorkommen: Steht ein Schlüssel",
        f"#  {e}(template:, input_number: …) schon in der Datei, die Einträge darunter",
        f"#  {e}beim vorhandenen Schlüssel anhängen – die Kommentare „▼“ zeigen wie.",
        f"#  {e}Nutzt du schon Pakete (packages:), lieber die Paket-Fassung nehmen.",
    ]


def kopf(zeilen: list) -> list:
    """Kopfkommentar: Titel anpassen, den Kopierschritt ersetzen."""
    neu, i = [], 0
    while i < len(zeilen):
        z = zeilen[i].replace("(Home-Assistant-Paket", "(für die configuration.yaml")
        m = SCHRITT.match(z)
        if m:
            # ganzer Schritt bis zum naechsten Schritt bzw. Absatz
            j = i + 1
            while j < len(zeilen) and not SCHRITT.match(zeilen[j]) \
                    and zeilen[j].startswith("#     "):
                j += 1
            schritt = "\n".join(zeilen[i:j])
            if "/config/packages/" in schritt:
                neu += einrichtung(int(m.group(1)))
            else:
                neu += [z] + zeilen[i + 1:j]
            i = j
            continue
        neu.append(z)
        i += 1
    return neu


def hinweis(domain: str) -> list:
    if domain in EIGENER_SCHLUESSEL:
        return [f"# ▼ {domain} ev_tracker: – eigener Schlüssel, funktioniert auch, wenn"
                f" „{domain}:“ schon da ist"]
    art = ("die Einträge (ab „-“)" if domain in LISTEN
           else "die Einträge darunter (eingerückt)")
    return [f"# ▼ {domain}: – gibt es „{domain}:“ schon, nur {art} dort anhängen"]


def umwandeln(text: str) -> str:
    zeilen = text.split("\n")
    # Kopf = fuehrender Kommentarblock bis zur zweiten ═-Linie
    linien = [n for n, z in enumerate(zeilen) if z.startswith("# ═")]
    ende = linien[1] + 1
    aus = kopf(zeilen[:ende])
    for z in zeilen[ende:]:
        m = SCHLUESSEL.match(z)
        if m:
            d = m.group(1)
            aus += hinweis(d)
            if d in EIGENER_SCHLUESSEL:
                z = f"{d} ev_tracker:"
        aus.append(z)
    return "\n".join(aus)


def bauen() -> dict:
    """{dateiname: inhalt} – auch fuer den Test (Abgleich mit den Dateien)."""
    erg = {}
    for name in DATEIEN:
        with open(os.path.join(QUELLE, name), encoding="utf-8") as f:
            erg[name] = umwandeln(f.read())
    return erg


if __name__ == "__main__":
    for name, inhalt in bauen().items():
        with open(os.path.join(ZIEL, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(inhalt)
        print("geschrieben:", os.path.join("vorlagen", "configuration_yaml", name))
