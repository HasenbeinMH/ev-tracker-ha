"""Aufnahmen der Demo-App fuer das Video: 1280 px breit, dreifache Aufloesung.

Startet die App mit video/demo/ev_tracker.db und fotografiert sie mit Playwright
(Microsoft Edge). Ergebnis in video/public/.
Aufruf aus dem Repo-Ordner:  python video/skripte/aufnahmen.py
"""
import os, shutil, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright

VIDEO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(VIDEO)
OUT = os.path.join(VIDEO, "public")
os.makedirs(OUT, exist_ok=True)
PORT = 8768
URL = f"http://127.0.0.1:{PORT}"

env = {**os.environ, "EV_TRACKER_DB": os.path.join(VIDEO, "demo", "ev_tracker.db"),
       "PYTHONIOENCODING": "utf-8"}
server = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.app:app", "--port", str(PORT)],
                          cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
lage = {}
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(URL + "/", timeout=2)
            break
        except Exception:
            time.sleep(0.5)
    AUFNAHMEN = [
        # name, pfad, breite, ganze Seite
        ("dashboard", "/", 1280, True),
        ("dashboard_sommer", "/?zeitraum=2026-S", 1280, False),
        ("ladetarife", "/ladetarife", 1280, True),
        ("bericht", "/api/bericht/vorschau?typ=monat&jahr=2026&monat=9", 680, True),
    ]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="msedge")
        for name, pfad, breite, ganz in AUFNAHMEN:
            seite = browser.new_page(viewport={"width": breite, "height": 720},
                                     device_scale_factor=3, color_scheme="dark", locale="de-DE")
            seite.goto(URL + pfad, wait_until="networkidle")
            seite.wait_for_timeout(1800)             # Diagramm-Animationen
            seite.screenshot(path=os.path.join(OUT, name + ".png"), full_page=ganz)
            for sel in ("#amortisation", "h2", ".chartgrid > .chart"):
                for el in seite.locator(sel).all()[:20]:
                    b = el.bounding_box()
                    if b:
                        txt = (el.inner_text() or "")[:30].replace("\n", " ")
                        print(name, sel, [round(v) for v in b.values()], txt)
            seite.close()
        browser.close()
finally:
    server.terminate()
shutil.copy(os.path.join(REPO, "logo.png"), os.path.join(OUT, "logo.png"))
print("fertig")
