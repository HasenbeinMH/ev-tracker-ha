# -*- coding: utf-8 -*-
"""
Galerie der mitgelieferten Fahrzeugbilder (Ordner fahrzeugbilder/ im Repo).

Die Bilder kommen mit dem Add-on; in den Einstellungen waehlt man eins per Klick.
Namen und Bildnachweise stehen nicht im Code, sondern in den Dateien des Ordners:
    README.md   Tabelle "Vorhandene Bilder": Datei -> Anzeigename
    CREDITS.md  je Modell die Vorlage (Wikimedia): Titel, Link, Urheber, Lizenz
Ein neues Bild braucht also nur die Datei und je eine Zeile dort – ohne Code-Aenderung.
"""
import io
import os
import re

ORDNER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fahrzeugbilder")
ERLAUBT = {".jpg", ".jpeg", ".png", ".webp"}
VORSCHAU_BREITE = 320

_vorschau_cache = {}        # (datei, mtime) -> JPEG-Bytes

# README: | [`datei.jpg`](datei.jpg) | Anzeigename | …
_README_ZEILE = re.compile(r"^\|\s*\[`([^`]+)`\]\([^)]*\)\s*\|\s*([^|]+?)\s*\|", re.M)
# CREDITS: - **slug**: [File:Titel](url) von Urheber, Lizenz [CC …](url), bearbeitet
_CREDITS_ZEILE = re.compile(
    r"^- \*\*([\w-]+)\*\*: \[(?:File:)?([^\]]+?)(?:\.jpe?g|\.png)?\]\((\S+)\) von (.+?), "
    r"Lizenz \[([^\]]+)\]\(([^)]+)\)", re.M | re.I)
# Schreibweisen fuer Namen aus dem Dateinamen (solange das Bild nicht in der README steht)
_SCHREIBWEISE = {"bmw": "BMW", "vw": "VW", "ev": "EV", "gt": "GT", "gtx": "GTX", "mg": "MG",
                 "byd": "BYD", "eqa": "EQA", "eqb": "EQB", "eqe": "EQE", "eqs": "EQS",
                 "glc": "GLC", "cla": "CLA", "etron": "e-tron", "etech": "E-Tech",
                 "ix": "iX", "ix1": "iX1", "ix2": "iX2", "ix3": "iX3", "i3": "i3", "i4": "i4",
                 "i5": "i5", "i7": "i7", "ec3": "ë-C3", "id": "ID.", "id3": "ID.3", "id4": "ID.4",
                 "id5": "ID.5", "id7": "ID.7", "t03": "T03", "citroen": "Citroën", "skoda": "Škoda"}


def _lesen(name: str) -> str:
    try:
        with open(os.path.join(ORDNER, name), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _namen() -> dict:
    return {d: n for d, n in _README_ZEILE.findall(_lesen("README.md"))}


def nachweise() -> dict:
    """slug -> {"titel", "url", "autor", "lizenz", "lizenz_url"} aus CREDITS.md."""
    return {m[0].lower().replace("-", "_"): {"titel": m[1], "url": m[2], "autor": m[3],
                                             "lizenz": m[4], "lizenz_url": m[5]}
            for m in _CREDITS_ZEILE.findall(_lesen("CREDITS.md"))}


def _nachweis_fuer(datei: str, alle: dict) -> dict | None:
    """Vorlage zum Bild: der laengste Slug, mit dem der Dateiname beginnt –
    "bmw-ix1-grau.jpg" gehoert zu "bmw_ix1", nicht zu "bmw_i" o.ae."""
    stamm = os.path.splitext(datei)[0].lower().replace("-", "_")
    passend = [s for s in alle if stamm == s or stamm.startswith(s + "_")]
    return alle[max(passend, key=len)] if passend else None


def _name_aus_datei(datei: str) -> str:
    worte = re.split(r"[-_]+", os.path.splitext(datei)[0])
    return " ".join(_SCHREIBWEISE.get(w.lower(), w.capitalize()) for w in worte if w)


def bilder() -> list:
    """[{"datei", "name", "nachweis"}] aller Bilder im Ordner, nach Namen sortiert."""
    try:
        dateien = [d for d in os.listdir(ORDNER)
                   if os.path.splitext(d)[1].lower() in ERLAUBT
                   and os.path.isfile(os.path.join(ORDNER, d))]
    except OSError:
        return []
    namen, alle = _namen(), nachweise()
    liste = [{"datei": d, "name": namen.get(d) or _name_aus_datei(d),
              "nachweis": _nachweis_fuer(d, alle)} for d in dateien]
    return sorted(liste, key=lambda b: b["name"].lower())


def pfad(datei: str) -> str | None:
    """Voller Pfad eines Galeriebilds – nur fuer Dateien, die wirklich im Ordner liegen
    (kein Pfad aus der Anfrage wird ungeprueft geoeffnet)."""
    if not datei or datei != os.path.basename(datei):
        return None
    if datei not in {b["datei"] for b in bilder()}:
        return None
    return os.path.join(ORDNER, datei)


def vorschau(datei: str) -> bytes | None:
    """Verkleinertes JPEG fuer die Galerie (zwischengespeichert). Ohne Pillow: None –
    dann zeigt die Seite das Original."""
    voll = pfad(datei)
    if not voll:
        return None
    schluessel = (datei, os.path.getmtime(voll))
    if schluessel not in _vorschau_cache:
        try:
            from PIL import Image
        except ImportError:
            return None
        with Image.open(voll) as bild:
            bild = bild.convert("RGBA" if bild.mode in ("RGBA", "LA", "P") else "RGB")
            if bild.mode == "RGBA":     # Transparenz auf den Dashboard-Hintergrund legen
                grund = Image.new("RGB", bild.size, (20, 23, 30))
                grund.paste(bild, mask=bild.split()[3])
                bild = grund
            bild.thumbnail((VORSCHAU_BREITE, VORSCHAU_BREITE))
            puffer = io.BytesIO()
            bild.save(puffer, "JPEG", quality=82)
        _vorschau_cache[schluessel] = puffer.getvalue()
    return _vorschau_cache[schluessel]
