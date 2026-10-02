# -*- coding: utf-8 -*-
"""
Sprachumschaltung Deutsch/Englisch.

Der deutsche Text ist der Schluessel; die englischen Uebersetzungen stehen in
i18n/en.json ({"Gesamtstrecke": "Total distance", …}). Fehlt eine Uebersetzung, bleibt
der deutsche Text stehen – nie leer, nie ein Fehler. Leerraum im Schluessel wird
zusammengefasst (Zeilenumbrueche in Templates spielen keine Rolle).

Die Sprache ist eine globale Einstellung ("sprache": "de" oder "en", Standard "de") und
gilt fuer Oberflaeche, Berichte und Mails. Zahlen und Datum bleiben in beiden Sprachen
deutsch formatiert.

    _("Gesamtstrecke")                -> Text (str)
    _("{0} Monate", n)                -> mit Werten (str.format)
In Templates: {{ _("…") }} (HTML im Text erlaubt, Werte werden maskiert) und
{{ _t("…") }} fuer Attribute (reiner Text, wird maskiert).
"""
import json
import os
import re

SPRACHEN = {"de": "Deutsch", "en": "English"}
_DATEI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n", "en.json")
_en = None
_leer = re.compile(r"\s+")


def schluessel(text: str) -> str:
    return _leer.sub(" ", str(text)).strip()


def _uebersetzungen() -> dict:
    global _en
    if _en is None:
        try:
            with open(_DATEI, encoding="utf-8") as f:
                _en = {schluessel(k): v for k, v in json.load(f).items()}
        except (OSError, ValueError):
            _en = {}
    return _en


def sprache() -> str:
    try:
        import database as db
        return db.sprache()
    except Exception:
        return "de"


def uebersetzen(text: str, sprache_: str | None = None) -> str:
    """Nur nachschlagen, ohne Werte einzusetzen."""
    if (sprache_ or sprache()) != "en":
        return text
    return _uebersetzungen().get(schluessel(text), text)


def _(text: str, *args, **kwargs) -> str:
    t = uebersetzen(text)
    if args or kwargs:
        try:
            return t.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return text.format(*args, **kwargs)
    return t


def template_text(text: str, *args, **kwargs):
    """Fuer Templates: Text darf HTML aus dem Template enthalten (vertrauenswuerdig),
    eingesetzte Werte werden maskiert."""
    from markupsafe import Markup
    t = Markup(uebersetzen(text))
    if args or kwargs:
        try:
            return t.format(*args, **kwargs)
        except (IndexError, KeyError, ValueError):
            return Markup(text).format(*args, **kwargs)
    return t


def attribut_text(text: str, *args, **kwargs) -> str:
    """Fuer Attribute: reiner Text, Jinja maskiert ihn."""
    return _(text, *args, **kwargs)


def N_(text: str) -> str:
    """Markiert einen Text fuer i18n/pruefen.py, der erst spaeter mit _() uebersetzt wird
    (z.B. Beschriftungen in Listen auf Modulebene). Gibt den Text unveraendert zurueck."""
    return text


def _k(kontext: str, text: str, *args, **kwargs) -> str:
    """Uebersetzung mit Kontext fuer mehrdeutige Woerter: Schluessel in en.json
    "kontext|text" (z.B. "Fahrzeug|Diesel" -> "diesel car", "Diesel" -> "diesel").
    Deutsch und fehlende Uebersetzung: der Text selbst."""
    t = text
    if sprache() == "en":
        t = _uebersetzungen().get(schluessel(f"{kontext}|{text}"), text)
    if args or kwargs:
        return t.format(*args, **kwargs)
    return t
