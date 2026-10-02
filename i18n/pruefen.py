# -*- coding: utf-8 -*-
"""
Prueft die Uebersetzungen: sammelt alle Texte aus _("…") / _t("…") in den Templates und
_("…") / N_("…") im Python-Code und vergleicht sie mit i18n/en.json.

    python i18n/pruefen.py            Liste fehlender und verwaister Eintraege
    python i18n/pruefen.py --json     dasselbe als JSON (fuer tests/i18n_test.py)
    python i18n/pruefen.py --neu      fehlende Schluessel ausgeben (zum Uebersetzen)

N_("…") markiert Texte, die erst zur Laufzeit uebersetzt werden (z.B. Beschriftungen in
Listen) – ohne Wirkung, nur damit sie hier gefunden werden.
"""
import ast
import glob
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
import i18n  # noqa: E402

# Erstes Argument von _( / _t( / N_( : ein String-Literal in " oder '
LITERAL = r'''("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')'''
AUFRUF = re.compile(r"(?<![\w.])(?:_|_t|N_)\(\s*" + LITERAL, re.S)
# Uebersetzung mit Kontext: _k("Kontext", "Text") -> Schluessel "Kontext|Text"
MIT_KONTEXT = re.compile(r"(?<![\w.])_k\(\s*" + LITERAL + r"\s*,\s*" + LITERAL)
# Makro stand("art", "Text") in einrichtung.html uebersetzt seinen Text zur Laufzeit
STAND = re.compile(r"stand\(\s*\"[a-z]+\",\s*" + LITERAL)


def _wert(literal: str) -> str:
    return ast.literal_eval(literal)


def _python_texte(text: str):
    """(schluessel, zeile) aller _("…") / _t("…") / N_("…") / _k("…", "…") mit Literal."""
    for n in ast.walk(ast.parse(text)):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.args):
            continue
        arg = [a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None
               for a in n.args[:2]]
        if n.func.id in ("_", "_t", "N_") and arg[0]:
            yield i18n.schluessel(arg[0]), n.lineno
        elif n.func.id == "_k" and len(arg) == 2 and arg[0] and arg[1]:
            yield i18n.schluessel(arg[0] + "|" + arg[1]), n.lineno


def gefundene() -> dict:
    """{schluessel: [fundorte]}"""
    erg = {}
    dateien = (glob.glob(os.path.join(REPO, "webapp", "templates", "*.html"))
               + glob.glob(os.path.join(REPO, "*.py")) + glob.glob(os.path.join(REPO, "webapp", "*.py")))
    for pfad in dateien:
        name = os.path.relpath(pfad, REPO)
        if name in ("i18n.py",) or name.endswith("_test.py"):
            continue
        text = open(pfad, encoding="utf-8").read()
        if pfad.endswith(".py"):
            # Python: ueber den Syntaxbaum, damit "Teil 1 " "Teil 2" als ein Text zaehlt
            for k, zeile in _python_texte(text):
                erg.setdefault(k, []).append(f"{name}:{zeile}")
            muster_liste = ()
        else:
            muster_liste = (AUFRUF, STAND)
        for muster in muster_liste:
            for m in muster.finditer(text):
                try:
                    k = i18n.schluessel(_wert(m.group(1)))
                except (ValueError, SyntaxError):
                    continue
                if k:
                    erg.setdefault(k, []).append(f"{name}:{text[:m.start()].count(chr(10)) + 1}")
        for m in MIT_KONTEXT.finditer(text):
            try:
                k = i18n.schluessel(_wert(m.group(1)) + "|" + _wert(m.group(2)))
            except (ValueError, SyntaxError):
                continue
            erg.setdefault(k, []).append(f"{name}:{text[:m.start()].count(chr(10)) + 1}")
    return erg


def main():
    with open(i18n._DATEI, encoding="utf-8") as f:
        en = {i18n.schluessel(k): v for k, v in json.load(f).items()}
    da = gefundene()
    fehlend = sorted(k for k in da if k not in en)
    verwaist = sorted(k for k in en if k not in da)
    if "--json" in sys.argv:
        print(json.dumps({"fehlend": fehlend, "verwaist": verwaist, "anzahl": len(da)}, ensure_ascii=False))
    elif "--neu" in sys.argv:
        print(json.dumps({k: "" for k in fehlend}, ensure_ascii=False, indent=1))
    else:
        print(f"{len(da)} Texte, {len(en)} Uebersetzungen")
        for k in fehlend:
            print(f"FEHLT    {k!r}  ({da[k][0]})")
        for k in verwaist:
            print(f"VERWAIST {k!r}")
    return 0 if not fehlend and not verwaist else 1


if __name__ == "__main__":
    sys.exit(main())
