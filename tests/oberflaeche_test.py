# -*- coding: utf-8 -*-
"""
Oberflaechentest im echten Browser (Chromium ueber Playwright).

Startet die App mit uvicorn auf einer Test-Datenbank (gefuellt vom Funktionstest),
ruft alle Seiten auf, meldet JavaScript-Fehler und fehlgeschlagene Anfragen,
schickt ein Formular ab und legt Screenshots ab. Zusaetzlich: Zustand "Nur lesbar"
(Datenbank aus einer neueren Version).

Aufruf (aus dem Repo-Ordner):
    pip install playwright      (Browser: vorhandenes Chromium, sonst `playwright install chromium`)
    python tests/oberflaeche_test.py [Ordner fuer Screenshots]

Umgebungsvariable CHROMIUM: Pfad zu einem vorhandenen Chromium (Standard: /opt/pw-browsers/chromium,
falls vorhanden).
"""
import os, shutil, socket, sqlite3, subprocess, sys, tempfile, time

HIER = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HIER)
sys.path.insert(0, HIER)
import migrationstest  # db_fuellen

SEITEN = ["", "statistik", "berichte", "fahrten", "benzin", "laden", "ladetarife", "stromtarif",
          "rechnung", "steuer", "instandhaltung", "versicherung", "import", "backup",
          "einstellungen", "einrichtung", "hilfe", "?zeitraum=2025", "statistik?a=2025-S&b=2025-W"]
ERG = []


def check(bereich, test, ok, detail=""):
    ERG.append((bereich, test, bool(ok), detail))


def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def server_starten(db_pfad, port):
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--port", str(port),
                          "--log-level", "warning"], cwd=os.path.join(REPO, "webapp"),
                         env={**os.environ, "EV_TRACKER_DB": db_pfad, "PYTHONDONTWRITEBYTECODE": "1"},
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return p
        except OSError:
            time.sleep(0.1)
    p.kill()
    raise RuntimeError("Server startet nicht: " + p.stdout.read().decode()[-1500:])


def seiten_pruefen(browser, basis, bereich, bilder, praefix):
    seite = browser.new_page(viewport={"width": 1280, "height": 900})
    js_fehler, http_fehler = [], []
    seite.on("pageerror", lambda e: js_fehler.append(str(e)))
    # /favicon.ico fragt der Browser von sich aus an; die App hat (noch) keins – kein Fehler der Seite
    seite.on("console", lambda m: js_fehler.append(m.text)
             if m.type == "error" and not m.location.get("url", "").endswith("/favicon.ico") else None)
    seite.on("response", lambda r: http_fehler.append(f"{r.status} {r.url}")
             if r.status >= 400 and not r.url.endswith("/favicon.ico") else None)
    for pfad in SEITEN:
        js_fehler.clear()
        http_fehler.clear()
        r = seite.goto(basis + pfad, wait_until="networkidle")
        name = pfad.split("?")[0] or "dashboard"
        check(bereich, f"/{pfad} laedt (HTTP {r.status})", r.status == 200)
        check(bereich, f"/{pfad} ohne JS-Fehler und fehlgeschlagene Anfragen",
              not js_fehler and not http_fehler, "; ".join(js_fehler + http_fehler)[:400])
        if bilder and name in ("dashboard", "statistik", "steuer", "einstellungen", "backup"):
            seite.screenshot(path=os.path.join(bilder, f"{praefix}_{name}.png"), full_page=True)
    return seite


def main():
    from playwright.sync_api import sync_playwright
    bilder = sys.argv[1] if len(sys.argv) > 1 else None
    if bilder:
        os.makedirs(bilder, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="ev_oberflaeche_")
    chromium = os.environ.get("CHROMIUM") or (
        "/opt/pw-browsers/chromium" if os.path.exists("/opt/pw-browsers/chromium") else None)
    server = None
    try:
        db_pfad, _ = migrationstest.db_fuellen(REPO, tmp)
        port = freier_port()
        basis = f"http://127.0.0.1:{port}/"
        server = server_starten(db_pfad, port)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=chromium) if chromium else pw.chromium.launch()

            # Normalbetrieb
            seite = seiten_pruefen(browser, basis, "Normal", bilder, "normal")
            seite.goto(basis + "steuer")
            seite.fill("form[action='steuer/kfz'] input[name=betrag]", "210,00")
            seite.click("form[action='steuer/kfz'] button[type=submit]")
            seite.wait_for_load_state("networkidle")
            check("Normal", "Formular abschicken (KFZ-Steuer 210 €) und Wert sichtbar",
                  seite.input_value("form[action='steuer/kfz'] input[name=betrag]") == "210,00")
            check("Normal", "Kein Nur-lesbar-Banner", "Nur lesbar" not in seite.content())

            # Mehrere Fahrzeuge ueber die Oberflaeche einschalten und bedienen
            seite = browser.new_page(viewport={"width": 1280, "height": 900})
            dialoge = []
            seite.on("dialog", lambda d: (dialoge.append(d.message), d.accept()))
            seite.goto(basis + "einstellungen")
            seite.select_option("#fz-modus", "mehrere")
            with seite.expect_navigation():
                seite.click("#fz-modus-form button[type=submit]")
            check("Mehrere", "Umschalten fragt nach (Sicherung, Downgrade-Hinweis)",
                  dialoge and "gesichert" in dialoge[-1], "; ".join(dialoge))
            check("Mehrere", "Meldung nach dem Umschalten", "Mehrere Fahrzeuge eingeschaltet" in seite.content())
            seite.fill("form[action='einstellungen/fahrzeuge/neu'] input[name=name]", "Zweitwagen")
            with seite.expect_navigation():
                seite.click("form[action='einstellungen/fahrzeuge/neu'] button[type=submit]")
            check("Mehrere", "Neues Fahrzeug angelegt und im Umschalter gewaehlt",
                  seite.locator("#fz-wahl").input_value() not in ("", "alle")
                  and "Zweitwagen" in seite.locator("#fz-wahl").inner_text())
            if bilder:
                seite.screenshot(path=os.path.join(bilder, "mehrere_einstellungen.png"), full_page=False)
            # km fuer das Zweitauto ueber das Formular
            seite.goto(basis + "fahrten")
            seite.fill("form[action='fahrten'] input[name=monat]", "2026-07")
            seite.fill("form[action='fahrten'] input[name=km]", "900")
            with seite.expect_navigation():
                seite.click("form[action='fahrten'] button[type=submit]")
            # Umschalter auf "Alle Fahrzeuge"
            seite.goto(basis)
            with seite.expect_navigation():
                seite.select_option("#fz-wahl", "alle")
            seite.wait_for_load_state("networkidle")
            check("Mehrere", "Gesamtsicht: Tabelle je Fahrzeug mit beiden Autos",
                  seite.locator(".je-fahrzeug").is_visible()
                  and "Zweitwagen" in seite.locator(".je-fahrzeug").inner_text())
            if bilder:
                seite.screenshot(path=os.path.join(bilder, "mehrere_dashboard_alle.png"), full_page=True)
            seite.goto(basis + "laden")
            check("Mehrere", "Gesamtsicht: Ladeformular verlangt ein Fahrzeug",
                  seite.locator("form[action='laden'] select[name=fahrzeug_id]").is_visible())
            if bilder:
                seite.locator("form[action='laden']").screenshot(
                    path=os.path.join(bilder, "mehrere_laden_formular.png"))
            seite.close()
            for wahl in ("1", "2", "alle"):
                ctx = browser.new_context(viewport={"width": 1280, "height": 900})
                ctx.add_cookies([{"name": "fahrzeug", "value": wahl, "url": basis}])
                class _B:                       # seiten_pruefen erwartet browser.new_page()
                    new_page = staticmethod(lambda **kw: ctx.new_page())
                seiten_pruefen(_B, basis, f"Mehrere ({wahl})", None, "")
                ctx.close()
            # Handy-Breite: Umschalter und Seite ohne waagrechtes Scrollen
            ctx = browser.new_context(viewport={"width": 390, "height": 844})
            ctx.add_cookies([{"name": "fahrzeug", "value": "alle", "url": basis}])
            handy = ctx.new_page()
            handy.goto(basis, wait_until="networkidle")
            breite = handy.evaluate("document.documentElement.scrollWidth")
            check("Mehrere", "Handy (390 px): Umschalter sichtbar",
                  handy.locator("#fz-wahl").is_visible(), f"scrollWidth {breite}")
            if bilder:
                handy.screenshot(path=os.path.join(bilder, "mehrere_handy.png"))
            ctx.close()

            # Englisch: Umschalter DE | EN in der Navigation, alle Seiten, Bericht, Handy
            seite = browser.new_page(viewport={"width": 1280, "height": 900})
            seite.goto(basis + "statistik?a=2025-S&b=2025-W", wait_until="networkidle")
            with seite.expect_navigation():
                seite.click(".sprachwahl button[value=en]")
            check("Englisch", "Klick auf EN: gleiche Seite, englisch",
                  "/statistik?a=2025-S" in seite.url and seite.get_attribute("html", "lang") == "en"
                  and "Statistics" in seite.locator("nav").text_content(), seite.url)
            seite.close()
            ctx = browser.new_context(viewport={"width": 1280, "height": 900})
            ctx.add_cookies([{"name": "fahrzeug", "value": "alle", "url": basis}])
            class _B:                           # seiten_pruefen erwartet browser.new_page()
                new_page = staticmethod(lambda **kw: ctx.new_page())
            seite = seiten_pruefen(_B, basis, "Englisch (alle)", bilder, "en")
            seite.goto(basis + "hilfe")
            check("Englisch", "Englische Hilfe", "Manual & calculation basics" in seite.locator("h1").inner_text())
            if bilder:
                seite.goto(basis + "api/bericht/vorschau?typ=monat&jahr=2026&monat=7", wait_until="networkidle")
                seite.screenshot(path=os.path.join(bilder, "en_bericht.png"), full_page=True)
                seite.goto(basis + "laden", wait_until="networkidle")
                seite.screenshot(path=os.path.join(bilder, "en_laden.png"), full_page=False)
            ctx.close()
            ctx = browser.new_context(viewport={"width": 390, "height": 844})
            handy = ctx.new_page()
            handy.goto(basis, wait_until="networkidle")
            breite = handy.evaluate("document.documentElement.scrollWidth")
            check("Englisch", "Handy (390 px): DE | EN sichtbar, kein waagrechtes Scrollen",
                  handy.locator(".sprachwahl").is_visible() and breite <= 390, f"scrollWidth {breite}")
            if bilder:
                handy.screenshot(path=os.path.join(bilder, "en_handy.png"))
            ctx.close()
            seite = browser.new_page(viewport={"width": 1280, "height": 900})
            seite.goto(basis + "einstellungen")
            with seite.expect_navigation():
                seite.select_option("#sprache select[name=sprache]", "de")
            check("Englisch", "Zurueck auf Deutsch ueber das Feld in den Einstellungen",
                  seite.get_attribute("html", "lang") == "de" and "Einstellungen" in seite.locator("nav").text_content())
            seite.close()

            # Nur lesbar: Datenbank aus einer neueren Version
            server.terminate()
            server.wait()
            with sqlite3.connect(db_pfad) as k:
                k.execute("UPDATE einstellungen SET value='99' WHERE key='schema_version'")
            server = server_starten(db_pfad, port)
            seite = browser.new_page(viewport={"width": 1280, "height": 900})
            seite.goto(basis)
            check("Nur lesbar", "Banner sichtbar", seite.locator(".warn-banner").is_visible())
            if bilder:
                seite.screenshot(path=os.path.join(bilder, "nur_lesbar_dashboard.png"))
            seite.goto(basis + "steuer")
            seite.fill("form[action='steuer/kfz'] input[name=betrag]", "999")
            with seite.expect_navigation():
                seite.click("form[action='steuer/kfz'] button[type=submit]")
            seite.wait_for_load_state("networkidle")
            check("Nur lesbar", "Speichern abgelehnt: zurueck auf der Seite mit \"Nicht gespeichert\"",
                  seite.url.split("?")[0].endswith("/steuer")
                  and "Nicht gespeichert" in seite.locator(".warn-banner").inner_text())
            if bilder:
                seite.screenshot(path=os.path.join(bilder, "nur_lesbar_speichern.png"))
            seite.goto(basis + "steuer")
            check("Nur lesbar", "Wert unveraendert (210,00)",
                  seite.input_value("form[action='steuer/kfz'] input[name=betrag]") == "210,00")
            alle = [p for p in SEITEN if seite.goto(basis + p).status != 200]
            check("Nur lesbar", "Alle Seiten laden weiter", not alle, str(alle))
            browser.close()
    finally:
        if server:
            server.terminate()
        shutil.rmtree(tmp, ignore_errors=True)

    ok_n = sum(1 for e in ERG if e[2])
    print(f"\n{ok_n}/{len(ERG)} Pruefungen bestanden\n")
    for b, t, ok, d in ERG:
        if not ok:
            print(f"FEHLER  [{b}] {t}\n        {d}")
    sys.exit(0 if ok_n == len(ERG) else 1)


if __name__ == "__main__":
    main()
