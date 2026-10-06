# -*- coding: utf-8 -*-
"""
Test der Sprachumschaltung Deutsch/Englisch (i18n.py, i18n/en.json).

  1. Vollstaendigkeit: jeder Text, der in Templates und Python ueber _()/_t() laeuft,
     steht in i18n/en.json (i18n/pruefen.py) – und en.json hat keine verwaisten Eintraege.
  2. Alle Seiten laden in DE und EN (ein Fahrzeug, mehrere/Gesamtsicht, mehrere/Fahrzeug 2).
  3. Jeder <script>-Block jeder gerenderten Seite ist gueltiges JavaScript (node --check),
     in beiden Sprachen – faengt kaputte Anfuehrungszeichen in Uebersetzungen ab.
  4. Deutsch: sichtbarer Text aller Seiten gleich wie im letzten Commit (git worktree HEAD).
  5. Englisch: kein typisch deutsches Wort mehr im sichtbaren Text (Spuertest).
  6. Monatsbericht (Mail) in EN; Zahlen bleiben deutsch formatiert.

Aufruf (aus dem Repo-Ordner):  python tests/i18n_test.py          (braucht Node.js)
"""
import html as html_mod
import json, os, re, shutil, subprocess, sys, tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
sys.path.insert(0, HIER)
import migrationstest  # db_fuellen

ERG = []
SEITEN = ["/", "/statistik", "/fahrten", "/laden", "/benzin", "/stromtarif", "/ladetarife", "/steuer",
          "/instandhaltung", "/versicherung", "/import", "/rechnung", "/berichte", "/backup",
          "/einstellungen", "/einrichtung", "/hilfe", "/statistik?a=2025-S&b=2025-W", "/?zeitraum=2025"]
# Woerter, die in der englischen Oberflaeche nicht mehr vorkommen duerfen (Spuertest).
# Eigennamen, Anbieter, gespeicherte Notizen ("HA-Ladung …"), das Importprotokoll ("Keine Datenquelle …")
# und das Aenderungslog bleiben deutsch – "Ladung"/"Keine" stehen deshalb nicht in der Liste.
DEUTSCHE_WOERTER = ["Speichern", "Hinzufügen", "Löschen", "Einstellungen", "Ladevorgänge", "Fahrten",
                    "Übersicht", "Zeitraum", "Gesamtstrecke", "Ersparnis", "Verbrauch", "Stromkosten",
                    "Einträge", "Anbieter", "Datum", "Betrag", "Notiz", "Monat", "Jahr", "Fahrzeug",
                    "Versicherung", "Instandhaltung", "Steuer", "Einrichtung", "Hilfe", "Berichte",
                    "Statistik", "Sicherung", "Wiederherstellen", "Kraftstoff", "Benzin", "Strom",
                    "geladen", "gefahrene", "wählen", "Bitte", "nicht", "und", "oder", "für", "mit",
                    "der", "die", "das", "ist", "wird", "werden", "Fahrzeuge", "Alle", "alle", "keine",
                    "Monate", "Ladungen", "Gesamt", "Zeile", "gespeichert", "noch", "auch"]


# Einheiten wie "kWh/100 km" oder "ct/kWh" – kein Text, der uebersetzt wird
EINHEIT = re.compile(r"(€|%|ct|km|kWh|kW|L)(/(\d+ )?(km|kWh|h|L))?")


def check(bereich, test, ok, detail=""):
    ERG.append((bereich, test, bool(ok), detail))


def sichtbar(h):
    h = re.sub(r"<script.*?</script>", " ", h, flags=re.S)
    h = re.sub(r"<style.*?</style>", " ", h, flags=re.S)
    h = re.sub(r"<[^>]+>", " ", h)
    return re.sub(r"\s+", " ", html_mod.unescape(h)).strip()


# Gewollt neu in 3.1 (Sprachwahl) – fuer den Vergleich mit dem Stand vor der Umstellung entfernt
NEU_IN_3_1 = [r'<form class="sprachwahl".*?</form>', r'<form[^>]*id="sprache".*?</form>',
              r'<p>🌐.*?</p>', r'<a href="hilfe#changelog" class="version".*?</a>',
              # 3.2: Einstellungen → Anschaffung (Amortisation)
              r'<h2 id="anschaffung">.*?(?=<h2 id="simulation">)']


def ohne_neues(h):
    for muster in NEU_IN_3_1:
        h = re.sub(muster, " ", h, flags=re.S)
    return h


RENDER = r'''
import os, sys, json
os.environ["EV_TRACKER_DB"] = sys.argv[2]
sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "webapp")]
from fastapi.testclient import TestClient
import app as webapp, database as db
c = TestClient(webapp.app)
seiten = json.loads(sys.argv[3]); sprache = sys.argv[4]
erg = {}
def alle(vor):
    for s in seiten:
        r = c.get(s)
        erg[vor + s] = [r.status_code, r.text]
if sprache != "-":
    db.set_einstellung("sprache", sprache)
alle("ein")
c.post("/einstellungen/fahrzeuge/modus", data={"modus": "mehrere"})
c.post("/einstellungen/fahrzeuge/neu", data={"name": "Zweitwagen"})
for wahl in ("alle", "2"):
    c.get("/?fahrzeug=" + wahl)
    alle(f"mehr_{wahl}")
print(json.dumps(erg))
'''


def rendern(code_dir, db_vorlage, sprache, tmp):
    d = os.path.join(tmp, f"r_{os.path.basename(code_dir)}_{sprache}.db")
    shutil.copy(db_vorlage, d)
    p = subprocess.run([sys.executable, "-c", RENDER, code_dir, d, json.dumps(SEITEN), sprache],
                       capture_output=True, text=True, cwd=code_dir,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if p.returncode:
        raise RuntimeError(p.stderr[-1500:])
    return json.loads(p.stdout.strip().splitlines()[-1])


UMSCHALTEN = r'''
import os, sys, json
os.environ["EV_TRACKER_DB"] = sys.argv[2]
sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "webapp")]
from fastapi.testclient import TestClient
import app as webapp, database as db
c = TestClient(webapp.app)
def post(sprache, zurueck):
    r = c.post("/einstellungen/sprache", data={"sprache": sprache, "zurueck": zurueck}, follow_redirects=False)
    return [r.status_code, r.headers.get("location"), db.sprache()]
erg = {"en": post("en", "statistik?a=2025-S&b=2025-W"), "de": post("de", ""),
       "fremd": [post("de", z) for z in ("//boese.example/x", "https://boese.example", "../../x", "a/b")],
       "xx": post("xx", "")}
print(json.dumps(erg))
'''


def umschalten(code_dir, db_vorlage, tmp):
    d = os.path.join(tmp, "umschalten.db")
    shutil.copy(db_vorlage, d)
    p = subprocess.run([sys.executable, "-c", UMSCHALTEN, code_dir, d], capture_output=True, text=True,
                       cwd=code_dir, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if p.returncode:
        raise RuntimeError(p.stderr[-1500:])
    return json.loads(p.stdout.strip().splitlines()[-1])


def jinja_reste():
    """Texte in Jinja-Ausdruecken ohne _()/_t() – z.B. {{ "gemeinsam" if … }} – ueber den Syntaxbaum."""
    import glob
    import jinja2
    from jinja2 import nodes
    env, funde = jinja2.Environment(), []
    for p in sorted(glob.glob(os.path.join(REPO, "webapp", "templates", "*.html"))):
        if os.path.basename(p) in ("hilfe.html", "hilfe_en.html"):      # eigene Hilfe je Sprache
            continue
        baum = env.parse(open(p, encoding="utf-8").read())
        frei = set()
        for c in baum.find_all(nodes.Call):         # _("…"), Makro-/Methoden-Argumente
            for k in c.find_all(nodes.Const) if isinstance(c.node, nodes.Name) and c.node.name in ("_", "_t") \
                    else [a for a in c.args if isinstance(a, nodes.Const)]:
                frei.add(id(k))
        for f in baum.find_all(nodes.Filter):
            for k in f.args + [kw.value for kw in f.kwargs]:
                if isinstance(k, nodes.Const):
                    frei.add(id(k))
        for k in baum.find_all(nodes.Const):
            v = k.value
            if isinstance(v, str) and EINHEIT.fullmatch(v.strip()):
                continue                            # Einheiten sind in beiden Sprachen gleich
            if id(k) not in frei and isinstance(v, str) and re.search(r"[A-Za-zÄÖÜäöüß]{3,}", v) \
                    and (" " in v.strip() or re.search(r"[äöüÄÖÜß]", v) or v[:1].isupper()):
                funde.append(f"{os.path.basename(p)}:{k.lineno} {v!r}")
    # einrichtung.html: das Makro stand() uebersetzt seinen Text selbst
    return [f for f in funde if not f.startswith("einrichtung.html")]


def js_pruefen(seiten_html, tmp, sprache):
    """Alle Inline-Skripte (ohne JSON-Daten) mit node --check pruefen."""
    fehler = []
    for name, (status, text) in seiten_html.items():
        for i, m in enumerate(re.finditer(r"<script(?![^>]*application/json)(?![^>]*\bsrc=)[^>]*>(.*?)</script>",
                                          text, re.S)):
            pfad = os.path.join(tmp, "skript.js")
            with open(pfad, "w", encoding="utf-8") as f:
                f.write(m.group(1))
            p = subprocess.run(["node", "--check", pfad], capture_output=True, text=True)
            if p.returncode:
                fehler.append(f"{sprache}{name} Skript {i + 1}: {p.stderr.strip().splitlines()[-1][:160]}")
    return fehler


def main():
    tmp = tempfile.mkdtemp(prefix="ev_i18n_")
    try:
        db_vorlage, _ = migrationstest.db_fuellen(REPO, tmp)
        vorlage = os.path.join(tmp, "vorlage.db")
        shutil.copy(db_vorlage, vorlage)

        # 1. Vollstaendigkeit
        p = subprocess.run([sys.executable, os.path.join(REPO, "i18n", "pruefen.py"), "--json"],
                           capture_output=True, text=True, cwd=REPO)
        try:
            pr = json.loads(p.stdout)
        except ValueError:
            pr = {"fehlend": ["(pruefen.py lief nicht: " + p.stderr[-300:] + ")"], "verwaist": []}
        check("Vollstaendig", "Jeder Text hat eine englische Uebersetzung", not pr["fehlend"],
              f"{len(pr['fehlend'])} fehlen, z.B. {pr['fehlend'][:6]}")
        check("Vollstaendig", "Keine verwaisten Eintraege in en.json", not pr["verwaist"],
              f"{len(pr['verwaist'])}, z.B. {pr['verwaist'][:6]}")

        reste = jinja_reste()
        check("Vollstaendig", "Keine Texte in Jinja-Ausdruecken ohne _()", not reste, "; ".join(reste[:6]))

        de = rendern(REPO, vorlage, "de", tmp)
        en = rendern(REPO, vorlage, "en", tmp)
        # 2. Seiten laden
        for sprache, seiten in (("DE", de), ("EN", en)):
            kaputt = [k for k, (st, _t) in seiten.items() if st != 200]
            check("Seiten", f"Alle {len(seiten)} Seiten laden ({sprache})", not kaputt, str(kaputt))
        # 3. JavaScript
        for sprache, seiten in (("DE", de), ("EN", en)):
            fehler = js_pruefen(seiten, tmp, sprache)
            check("JavaScript", f"Alle Inline-Skripte gueltig ({sprache})", not fehler, "; ".join(fehler[:4]))
        # 4. Deutsch wie im letzten Commit
        wt = os.path.join(tmp, "wt_head")
        subprocess.run(["git", "worktree", "add", "--detach", wt, "HEAD"], cwd=REPO, capture_output=True)
        try:
            alt = rendern(wt, vorlage, "-", tmp)
        finally:
            subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=REPO, capture_output=True)
            subprocess.run(["git", "worktree", "prune"], cwd=REPO, capture_output=True)
        # Hilfe ausgenommen: dort ist der Abschnitt zur Sprache gewollt neu (eigene Pruefung unten)
        verglichen = [k for k in alt if not k.endswith("/hilfe")]
        abw = [k for k in verglichen if sichtbar(ohne_neues(alt[k][1])) != sichtbar(ohne_neues(de[k][1]))]
        check("Deutsch", f"Sichtbarer Text aller {len(verglichen)} Seiten wie im letzten Commit", not abw,
              ", ".join(abw[:6]))
        for k in abw[:3]:
            x, y = sichtbar(ohne_neues(alt[k][1])), sichtbar(ohne_neues(de[k][1]))
            i = next((n for n in range(min(len(x), len(y))) if x[n] != y[n]), min(len(x), len(y)))
            check("Deutsch", f"  Abweichung {k}", False, f"vorher …{x[max(0, i - 70):i + 70]}… / "
                                                         f"jetzt …{y[max(0, i - 70):i + 70]}…")
        # 5. Englisch: keine deutschen Woerter
        funde = {}
        for k, (_st, text) in en.items():
            if k.endswith("/hilfe"):                    # Aenderungslog bleibt deutsch
                text = text.split('id="changelog"')[0]
            t = sichtbar(text)
            for w in DEUTSCHE_WOERTER:
                if re.search(r"(?<![\wÄÖÜäöüß])" + re.escape(w) + r"(?![\wÄÖÜäöüß])", t):
                    funde.setdefault(k, []).append(w)
        check("Englisch", "Kein typisch deutsches Wort in der englischen Oberflaeche", not funde,
              "; ".join(f"{k}: {v[:5]}" for k, v in list(funde.items())[:6]))
        check("Englisch", "<html lang=\"en\">", all('<html lang="en">' in t for _st, t in en.values()))
        check("Deutsch", "<html lang=\"de\">", all('<html lang="de">' in t for _st, t in de.values()))
        # Hilfe: beide Sprachen mit denselben Ankern, Inhaltsverzeichnis zeigt nur auf vorhandene
        for sprache, seiten in (("DE", de), ("EN", en)):
            h = seiten["ein/hilfe"][1]
            anker = set(re.findall(r'id="([^"]+)"', h))
            ziele = set(re.findall(r'href="#([^"]+)"', h))
            check("Hilfe", f"Inhaltsverzeichnis zeigt nur auf vorhandene Anker ({sprache})", ziele <= anker,
                  str(ziele - anker))
        a_de = set(re.findall(r'id="([^"]+)"', de["ein/hilfe"][1]))
        a_en = set(re.findall(r'id="([^"]+)"', en["ein/hilfe"][1]))
        check("Hilfe", "Deutsche und englische Hilfe haben dieselben Anker", a_de == a_en, str(a_de ^ a_en))
        check("Hilfe", "Englische Hilfe ist englisch, Aenderungslog bleibt deutsch",
              "Manual &amp; calculation basics" in en["ein/hilfe"][1] and "Handbuch" in de["ein/hilfe"][1]
              and en["ein/hilfe"][1].count('class="hb-rel"') == de["ein/hilfe"][1].count('class="hb-rel"'))
        # Umschalter DE | EN
        check("Umschalter", "DE | EN in der Navigation (beide Sprachen, aktive markiert)",
              all('class="sprachwahl"' in t for _st, t in de.values())
              and 'value="de" lang="de" title="Deutsch"\n            class="aktiv"' in de["ein/"][1]
              and 'value="en" lang="en" title="English"\n            class="aktiv"' in en["ein/"][1])
        sw = umschalten(REPO, vorlage, tmp)
        check("Umschalter", "POST einstellungen/sprache setzt EN und fuehrt zur Seite zurueck",
              sw["en"] == [303, "../statistik?a=2025-S&b=2025-W", "en"], str(sw["en"]))
        check("Umschalter", "… und wieder DE", sw["de"] == [303, "../", "de"], str(sw["de"]))
        check("Umschalter", "Fremde Ziele werden abgewiesen (kein Sprung nach aussen)",
              all(z[1] == "../einstellungen" for z in sw["fremd"]), str(sw["fremd"]))
        check("Umschalter", "Unbekannte Sprache faellt auf Deutsch zurueck", sw["xx"][2] == "de", str(sw["xx"]))
        # 6. Bericht in EN
        code = (
            "import os, sys, json\n"
            f"os.environ['EV_TRACKER_DB'] = {os.path.join(tmp, 'r_' + os.path.basename(REPO) + '_en.db')!r}\n"
            f"sys.path[:0] = [{REPO!r}]\n"
            "import berichte\n"
            "b = berichte.monatsbericht(2026, 7)\n"
            "print(json.dumps({'titel': b['titel'], 'html': berichte.als_html(b), 'text': berichte.als_text(b)}))\n")
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO)
        try:
            b = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            b = {"titel": "", "html": p.stderr[-400:], "text": ""}
        check("Bericht", "Monatsbericht auf Englisch (Titel, Kennzahlen)",
              "July 2026" in b["titel"] and "Distance driven" in b["html"], b["titel"])
        check("Bericht", "Zahlen bleiben deutsch formatiert (Komma, Tausenderpunkt)",
              re.search(r"\d,\d", b["html"]) is not None and re.search(r"\d\.\d{3}(?!\d)", b["html"]) is not None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok_n = sum(1 for e in ERG if e[2])
    print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
    for bereich, test, ok, detail in ERG:
        if not ok:
            print(f"FEHLER  [{bereich}] {test}\n        {detail}")
    sys.exit(0 if ok_n == len(ERG) else 1)


if __name__ == "__main__":
    main()
