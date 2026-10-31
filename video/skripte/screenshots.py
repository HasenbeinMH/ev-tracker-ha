"""Screenshots fuer die README (docs/screenshot-*.png): 1280 px breit, doppelte Aufloesung, dunkel.

Startet die App mit video/demo/ev_tracker.db (vorher demo_daten.py laufen lassen) und
fotografiert sie mit Playwright (Microsoft Edge).
Aufruf aus dem Repo-Ordner:  python video/skripte/screenshots.py [name ...]
"""
import os, subprocess, sys, time, urllib.request
from playwright.sync_api import sync_playwright

VIDEO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(VIDEO)
OUT = os.path.join(REPO, "docs")
PORT = 8768
URL = f"http://127.0.0.1:{PORT}"

# name, pfad, breite, anker (alles davor wird ausgeblendet), ende:
#   ("vor", sel)   bis kurz vor dieses Element
#   ("nach", sel)  bis zum Ende dieses Elements
#   ("hoehe", px)  feste Hoehe
#   None           ganze Seite
AUFNAHMEN = [
    ("dashboard", "/", 1280, None, ("nach", "#amortisation")),
    ("diagramme", "/", 1280, None, None),
    ("statistik", "/statistik?a=2025-S&b=2025-W", 1280, None,
     ("vor", "h2:has-text('Verlauf Monat für Monat')")),
    ("verbrauch", "/fahrten", 1280, "h2:has-text('Verbrauchsauswertung')", ("hoehe", 1370)),
    ("ladetarife", "/ladetarife", 1280, "#rentabilitaet-1", ("hoehe", 1420)),
    ("bericht", "/api/bericht/vorschau?typ=monat&jahr=2026&monat=9", 680, None, None),
    ("akku", "/akku", 1280, None, ("vor", "h2:has-text('SoH-Werte von Hand')")),
    ("energie", "/energie", 1280, None, ("nach", "table.vergleich")),
    ("profil", "/profil", 1280, None, ("vor", "h2:has-text('Ladeprofil')")),
    ("fahrtenbuch", "/fahrtenbuch?monat=2026-09", 1280, None, ("hoehe", 820)),
]
# Diagramme fuer "diagramme": diese vier aus dem Dashboard, die uebrigen ausgeblendet
DIAGRAMME = ("CO2-Ersparnis", "Verbrauch kWh/100km", "Ladekosten nach Anbieter",
             "Geladene kWh nach Stromquelle")

AUSBLENDEN_VOR = """n => {
  while (n && n.parentElement && n !== document.body) {
    for (let s = n.previousElementSibling; s; s = s.previousElementSibling)
      if (s.tagName !== 'NAV') s.style.display = 'none';
    n = n.parentElement;
  }
  window.scrollTo(0, 0);
}"""

NUR_DIAGRAMME = """titel => {
  for (const c of document.querySelectorAll('.chartgrid > .chart')) {
    const t = (c.querySelector('h2, h3, .chart-titel, .titel') || c).innerText.split('\\n')[0].trim();
    if (!titel.includes(t)) c.style.display = 'none';
  }
  window.dispatchEvent(new Event('resize'));
}"""


def main(namen):
    env = {**os.environ, "EV_TRACKER_DB": os.path.join(VIDEO, "demo", "ev_tracker.db"),
           "PYTHONIOENCODING": "utf-8"}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "webapp.app:app", "--port", str(PORT)],
                              cwd=REPO, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(URL + "/", timeout=2)
                break
            except Exception:
                time.sleep(0.5)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel="msedge")
            for name, pfad, breite, anker, ende in AUFNAHMEN:
                if namen and name not in namen:
                    continue
                seite = browser.new_page(viewport={"width": breite, "height": 900},
                                         device_scale_factor=2, color_scheme="dark", locale="de-DE")
                seite.goto(URL + pfad, wait_until="networkidle")
                if anker:
                    seite.locator(anker).first.evaluate(AUSBLENDEN_VOR)
                if name == "diagramme":
                    seite.evaluate(NUR_DIAGRAMME, list(DIAGRAMME))
                seite.wait_for_timeout(1800)             # Diagramm-Animationen
                datei = os.path.join(OUT, f"screenshot-{name}.png")
                if name == "diagramme":
                    seite.locator(".chartgrid").first.screenshot(path=datei)
                elif ende is None:
                    seite.screenshot(path=datei, full_page=True)
                else:
                    art, wert = ende
                    if art == "hoehe":
                        hoehe = wert
                    else:
                        b = seite.locator(wert).first.bounding_box()
                        hoehe = b["y"] - 8 if art == "vor" else b["y"] + b["height"] + 4
                    seite.screenshot(path=datei, full_page=True,
                                     clip={"x": 0, "y": 0, "width": breite, "height": hoehe})
                print(name, "->", os.path.relpath(datei, REPO))
                seite.close()
            browser.close()
    finally:
        server.terminate()


main(sys.argv[1:])
