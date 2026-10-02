# -*- coding: utf-8 -*-
"""
Migrationstest: Datenbanken aus aelteren Versionen mit dem aktuellen Code oeffnen.

Fuer jede Altversion:
  1. Den alten Stand per `git worktree` auschecken und dessen eigenen Funktionstest
     laufen lassen – er fuellt eine Datenbank mit 20 Monaten Testdaten ueber die
     echten Formulare (Fahrten, Ladungen, Tarife, THG, Instandhaltung, Versicherung).
  2. Kennzahlen mit dem ALTEN Code berechnen (Kopie A).
  3. Dieselbe Datenbank mit dem AKTUELLEN Code oeffnen (init_db migriert) und die
     Kennzahlen berechnen (Kopie B).
  4. Vergleichen: alle Kennzahlen aller Zeitraeume, Berichte, Unterhalt sowie
     Zeilenzahl und Summen jeder Tabelle muessen gleich sein.
Zusaetzlich: Wiederherstellen einer Alt-Datenbank ueber /api/backup/restore.

Aufruf (aus dem Repo-Ordner):  python tests/migrationstest.py [commit ...]
Ohne Angabe: die letzten Versionen laut Git-Log (Commit-Nachricht "Version x.y.z").
"""
import json, os, shutil, sqlite3, subprocess, sys, tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
ERG = []

# Laeuft im jeweiligen Code-Stand (alt oder neu) und gibt die Kennzahlen als JSON aus
SNAPSHOT = r'''
import json, sys, os
sys.path.insert(0, os.getcwd())
import database as db
db.init_db()
import zeitraum, unterhalt, berichte
daten = zeitraum.laden()
erg = {"kennzahlen": {}, "berichte": {}}
for key in ("alles", "2025", "2026", "2025-Q3", "2026-Q1", "2025-S", "2025-W"):
    erg["kennzahlen"][key] = zeitraum.kennzahlen(zeitraum.aufloesen(key), daten)
erg["berichte"]["monat_2026_08"] = berichte.monatsbericht(2026, 8)
erg["berichte"]["jahr_2025"] = berichte.jahresbericht(2025)
erg["instandhaltung"] = unterhalt.instandhaltung_daten()
erg["versicherung"] = unterhalt.versicherung_daten()
print(json.dumps(erg, default=str, sort_keys=True))
'''


def check(bereich, test, ok, detail=""):
    ERG.append((bereich, test, bool(ok), detail))


def versionen(anzahl=5):
    log = subprocess.run(["git", "log", "--format=%h %s", "-n", "60"], cwd=REPO,
                         capture_output=True, text=True).stdout.splitlines()
    gefunden = []
    for zeile in log:
        h, _, msg = zeile.partition(" ")
        # HEAD zaehlt mit: verglichen wird mit dem Arbeitsstand (auch ungespeicherte Aenderungen)
        if msg.startswith("Version "):
            gefunden.append((h, msg.split(":")[0]))
    return gefunden[:anzahl]


def _kopf():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                          capture_output=True, text=True).stdout.strip()


def db_fuellen(code_dir, ziel_dir):
    """Fuehrt den Funktionstest des alten Stands aus; dessen Test-DB bleibt liegen."""
    wrapper = (
        "import tempfile, shutil, runpy, sys\n"
        f"tempfile.mkdtemp = lambda *a, **k: {ziel_dir!r}\n"
        "shutil.rmtree = lambda *a, **k: None\n"
        "try:\n"
        f"    runpy.run_path({os.path.join(code_dir, 'tests', 'funktionstest.py')!r}, run_name='__main__')\n"
        "except SystemExit:\n"
        "    pass\n")
    r = subprocess.run([sys.executable, "-c", wrapper], cwd=code_dir, capture_output=True,
                       text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    return os.path.join(ziel_dir, "ev_tracker.db"), r


def snapshot(code_dir, db_pfad):
    r = subprocess.run([sys.executable, "-c", SNAPSHOT], cwd=code_dir, capture_output=True,
                       text=True, env={**os.environ, "EV_TRACKER_DB": db_pfad,
                                       "PYTHONDONTWRITEBYTECODE": "1"})
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def tabellen(db_pfad):
    """Zeilenzahl und Summe jeder Zahlenspalte je Tabelle (ohne einstellungen)."""
    erg = {}
    with sqlite3.connect(db_pfad) as k:
        for (t,) in k.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name NOT LIKE 'sqlite_%' AND name != 'einstellungen'"):
            spalten = [r[1] for r in k.execute(f"PRAGMA table_info({t})")
                       if r[2].upper() in ("REAL", "INTEGER") and r[1] != "id"]
            werte = {"zeilen": k.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]}
            for s in spalten:
                werte[s] = round(k.execute(f"SELECT TOTAL({s}) FROM {t}").fetchone()[0], 6)
            erg[t] = werte
    return erg


def vergleich(alt, neu, pfad=""):
    """Liste der Abweichungen; Schluessel, die nur im neuen Stand existieren, zaehlen nicht."""
    abw = []
    if isinstance(alt, dict) and isinstance(neu, dict):
        for k, v in alt.items():
            if k not in neu:
                abw.append(f"{pfad}/{k}: fehlt im neuen Stand")
            else:
                abw += vergleich(v, neu[k], f"{pfad}/{k}")
    elif isinstance(alt, list) and isinstance(neu, list):
        if len(alt) != len(neu):
            abw.append(f"{pfad}: Laenge {len(alt)} -> {len(neu)}")
        for i, (a, b) in enumerate(zip(alt, neu)):
            abw += vergleich(a, b, f"{pfad}[{i}]")
    elif isinstance(alt, float) or isinstance(neu, float):
        if alt is None or neu is None or abs(alt - neu) > 1e-6:
            abw.append(f"{pfad}: {alt} -> {neu}")
    elif alt != neu:
        abw.append(f"{pfad}: {alt!r} -> {neu!r}")
    return abw


def restore_test(alt_db):
    """Alt-Datenbank ueber die Web-Oberflaeche wiederherstellen (aktueller Code)."""
    tmp = tempfile.mkdtemp(prefix="ev_restore_")
    try:
        code = (
            "import os, sys, json, shutil\n"
            f"os.environ['EV_TRACKER_DB'] = {os.path.join(tmp, 'ev_tracker.db')!r}\n"
            f"sys.path.insert(0, {REPO!r}); sys.path.insert(0, {os.path.join(REPO, 'webapp')!r})\n"
            "from fastapi.testclient import TestClient\n"
            "import app as webapp, database as db\n"
            "c = TestClient(webapp.app)\n"
            f"r = c.post('/api/backup/restore', files={{'datei': ('a.db', open({alt_db!r}, 'rb').read())}},"
            " data={'bestaetigt': 'ja'})\n"
            "seiten = [s for s in ('/', '/statistik', '/fahrten', '/laden', '/steuer', '/versicherung',"
            " '/instandhaltung', '/einstellungen', '/backup') if c.get(s).status_code != 200]\n"
            "print(json.dumps({'status': r.status_code, 'seiten': seiten,"
            " 'schema': db.get_einstellung_str('schema_version'), 'gesperrt': db.SCHEMA_ZU_NEU}))\n")
        r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-1500:])
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    import database as db_neu_modul  # nur fuer SCHEMA_VERSION
    sys.path.insert(0, REPO)
    ziel = sys.argv[1:]
    liste = [(h, h) for h in ziel] if ziel else versionen()
    basis = tempfile.mkdtemp(prefix="ev_migration_")
    try:
        for commit, name in liste:
            b = f"Migration {name} ({commit})"
            wt = os.path.join(basis, f"wt_{commit}")
            subprocess.run(["git", "worktree", "add", "--detach", wt, commit], cwd=REPO,
                           capture_output=True, check=True)
            try:
                d = os.path.join(basis, f"db_{commit}")
                os.makedirs(d)
                alt_db, lauf = db_fuellen(wt, d)
                check(b, "Alte Version erzeugt Test-Datenbank", os.path.exists(alt_db),
                      lauf.stderr[-500:])
                if not os.path.exists(alt_db):
                    continue
                kopie_a, kopie_b = alt_db + ".a", alt_db + ".b"
                shutil.copy(alt_db, kopie_a)
                shutil.copy(alt_db, kopie_b)
                vor = tabellen(kopie_b)
                s_alt = snapshot(wt, kopie_a)
                s_neu = snapshot(REPO, kopie_b)
                abw = vergleich(s_alt, s_neu)
                check(b, "Kennzahlen, Berichte, Unterhalt unveraendert", not abw,
                      f"{len(abw)} Abweichungen: " + "; ".join(abw[:8]))
                nach = tabellen(kopie_b)
                abw_t = vergleich(vor, nach)
                check(b, "Zeilenzahl und Summen jeder Tabelle unveraendert", not abw_t,
                      "; ".join(abw_t[:8]))
                with sqlite3.connect(kopie_b) as k:
                    st = k.execute("SELECT value FROM einstellungen WHERE key='schema_version'").fetchone()
                check(b, "Struktur-Stand gesetzt (Basis, kein Umbau)", st and st[0] == str(db_neu_modul.BASIS_SCHEMA), str(st))
                rs = restore_test(alt_db)
                check(b, "Wiederherstellen ueber Backup-Seite, alle Seiten laden",
                      rs["status"] == 200 and not rs["seiten"] and not rs["gesperrt"]
                      and rs["schema"] == str(db_neu_modul.BASIS_SCHEMA), str(rs))
            finally:
                subprocess.run(["git", "worktree", "remove", "--force", wt], cwd=REPO,
                               capture_output=True)
    finally:
        shutil.rmtree(basis, ignore_errors=True)
        subprocess.run(["git", "worktree", "prune"], cwd=REPO, capture_output=True)

    ok_n = sum(1 for e in ERG if e[2])
    print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
    for bereich, test, ok, detail in ERG:
        print(f"{'OK    ' if ok else 'FEHLER'}  [{bereich}] {test}" + ("" if ok else f"\n        {detail}"))
    sys.exit(0 if ok_n == len(ERG) else 1)


if __name__ == "__main__":
    sys.path.insert(0, REPO)
    main()
