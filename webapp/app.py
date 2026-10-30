"""
EV Tracker – Web-Version (FastAPI)
Nutzt dieselben Kern-Module wie die Desktop-App:
database.py, berechnung.py, ha_client.py, pdf_parser.py, charts.py
"""
import os
import re
import shutil
import sys
import threading
import uuid
from datetime import datetime

# Kern-Module liegen im Elternordner (bzw. in Docker unter /app)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import (HTMLResponse, RedirectResponse, JSONResponse,
                               FileResponse, Response)
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from fastapi.templating import Jinja2Templates

import database as db
import i18n
from i18n import _, N_
import galerie
import akku as akku_mod
import energie as energie_mod
import fahrtenbuch as fahrtenbuch_mod
import akkuverbrauch
import berechnung
import berichte
import ladeerkennung
import ladetarife as ladetarife_mod
import leasing as leasing_mod
import module as module_mod
import profil as profil_mod
import dashboard_layout
import unterhalt
import mailer
import charts
import zeitraum as zeitraum_mod
from version import VERSION, CHANGELOG
import datenquellen
import diagnose
import heimladung
import zaehler
from ha_client import HAClient, IST_ADDON, ha_verbindung as _ha_verbindung
from pdf_parser import auswerten_pdf, auswerten_text, ohne_kwh_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
# Datenverzeichnis: hier liegen Datenbank, Backup- und Importprotokoll
DATA_DIR = os.path.dirname(db.DB_PATH) or "."
IMPORT_LOG_DATEI = os.path.join(DATA_DIR, "import.log")

MONATE = berichte.MONATE          # deutsche Namen (Schluessel); Anzeige ueber monatsname()
monatsname = berichte.monatsname


db.init_db()
db.init_ha_settings()
db.init_mail_settings()

# Einmalig (ab 2.0.7): Netzbezug aus dem Import wurde frueher immer mit dem neuesten
# Stromtarif bewertet – jetzt mit dem Tarif des jeweiligen Monats
if not db.SCHEMA_ZU_NEU and db.get_einstellung_str("migration_netzpreis_monat") != "1":
    berechnung.heimladungen_neu_bewerten()
    db.set_einstellung("migration_netzpreis_monat", "1")

# IST_ADDON (Add-on oder Standalone-Docker) und die HA-Verbindung stehen in ha_client.py,
# weil auch akkuverbrauch.py und ladeerkennung.py sie brauchen.

app =FastAPI(title="EV Tracker")


SCHREIBSPERRE_TEXT = N_("Die Datenbank stammt aus einer neueren Version des EV Trackers und ist "
                      "deshalb nur lesbar. Bitte die neue Version installieren oder unter "
                      "Backup eine Sicherung wiederherstellen.")


@app.middleware("http")
async def schreibsperre(request: Request, call_next):
    """Schema-Waechter: Ist die Datenbank neuer als diese Version, wird nichts
    geschrieben (sonst falsche Zahlen nach einem Downgrade). Nur das Wiederherstellen
    eines Backups bleibt erlaubt – es ist der Weg zurueck."""
    if (db.SCHEMA_ZU_NEU and request.method not in ("GET", "HEAD", "OPTIONS")
            and not request.url.path.endswith("/api/backup/restore")):
        if "/api/" in request.url.path:
            return JSONResponse({"ok": False, "error": _(SCHREIBSPERRE_TEXT)}, status_code=503)
        # Formular: zurueck zur Seite, das Banner meldet "nicht gespeichert"
        # nur Pfad und Query des Referers – nie auf eine fremde Adresse umleiten
        from urllib.parse import urlsplit
        teile = urlsplit(request.headers.get("referer") or "")
        ziel = (teile.path or ".") + (f"?{teile.query}" if teile.query else "")
        ziel += ("&" if "?" in ziel else "?") + "nicht_gespeichert=1"
        return RedirectResponse(ziel, status_code=303)
    return await call_next(request)


def _fahrzeug_wert(roh) -> int | str | None:
    """'alle' oder eine Fahrzeug-id aus Cookie/Formular; Unbekanntes -> None."""
    roh = str(roh or "").strip()
    if roh == db.ALLE:
        return db.ALLE
    return int(roh) if roh.isdigit() else None


@app.middleware("http")
async def fahrzeug_waehlen(request: Request, call_next):
    """Mehrere Fahrzeuge: gewaehltes Fahrzeug (?fahrzeug=… oder Cookie) als Kontext der
    Anfrage. Ein ?fahrzeug=… merkt sich die Auswahl im Cookie. Bei einem Fahrzeug
    wirkt das nicht – dann gilt immer das Hauptfahrzeug."""
    neu = _fahrzeug_wert(request.query_params.get("fahrzeug"))
    db.setze_fahrzeug(neu if neu is not None else _fahrzeug_wert(request.cookies.get("fahrzeug")))
    antwort = await call_next(request)
    if neu is not None:
        antwort.set_cookie("fahrzeug", str(neu), max_age=365 * 24 * 3600, samesite="lax")
    return antwort


def mit_fahrzeug(func):
    """Formular-Endpunkt: optionales Feld fahrzeug_id waehlt das Fahrzeug, fuer das
    gespeichert wird (sonst das gewaehlte bzw. Hauptfahrzeug)."""
    import functools
    import inspect
    from contextlib import nullcontext

    def kontext(wert):
        fid = _fahrzeug_wert(wert)
        if isinstance(fid, int) and fid in [f["id"] for f in db.fahrzeuge(alle=True)]:
            return db.fahrzeug_kontext(fid)
        return nullcontext()

    if inspect.iscoroutinefunction(func):
        @functools.wraps(func)
        async def wrapper(*args, fahrzeug_id: str = "", **kwargs):
            with kontext(fahrzeug_id):
                return await func(*args, **kwargs)
    else:
        @functools.wraps(func)
        def wrapper(*args, fahrzeug_id: str = "", **kwargs):
            with kontext(fahrzeug_id):
                return func(*args, **kwargs)
    sig = inspect.signature(func)
    wrapper.__signature__ = sig.replace(parameters=[
        *sig.parameters.values(),
        inspect.Parameter("fahrzeug_id", inspect.Parameter.KEYWORD_ONLY,
                          default=Form(""), annotation=str)])
    return wrapper


def modul(mid: str, seite: bool = True):
    """Route gehoert zum Modul `mid`: ist es ausgeschaltet, leitet eine Seite auf
    Einstellungen → Module um, andere Aufrufe (Formulare, API) bekommen 404.
    Innerster Decorator – direkt ueber der Funktion, unter @mit_fahrzeug."""
    import functools
    import inspect
    from urllib.parse import quote

    def aus():
        name = _(module_mod.MODULE[mid]["name"])
        if seite:
            return RedirectResponse("einstellungen?meldung="
                                    + quote(_("Das Modul „{0}“ ist ausgeschaltet.", name))
                                    + "#module", status_code=303)
        return JSONResponse({"ok": False, "error": _("Das Modul „{0}“ ist ausgeschaltet.", name)},
                            status_code=404)

    def deko(func):
        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                return await func(*args, **kwargs) if module_mod.an(mid) else aus()
        else:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs) if module_mod.an(mid) else aus()
        return wrapper
    return deko


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals["MONATE"] = MONATE
templates.env.globals["VERSION"] = VERSION
# Sprachumschaltung: {{ _("…") }} fuer Texte (HTML erlaubt), {{ _t("…") }} fuer Attribute
templates.env.globals["_"] = i18n.template_text
templates.env.globals["sprache"] = i18n.sprache
templates.env.globals["_t"] = i18n.attribut_text
# Module (Einstellungen → Module): Menue ohne die Seiten ausgeschalteter Module
templates.env.globals["menue_filter"] = module_mod.menue
# Deutsche Zahlen mit Tausenderpunkt: {{ wert | de(2) }} -> "1.519,88"
templates.env.filters["de"] = lambda wert, stellen=0: berichte.fmt(wert, stellen)


def render(request, template, **ctx):
    ctx["now"] = datetime.now()
    # Benzin oder Diesel – fuer Menue und Beschriftungen auf allen Seiten;
    # im Simulationsmodus zeigt base.html ein Banner
    cfg = db.get_config()
    ctx.setdefault("kf", berechnung.kraftstoff(cfg["kraftstoff"]))
    ctx.setdefault("simulation", cfg["simulation"])
    ctx.setdefault("schema_zu_neu", db.SCHEMA_ZU_NEU)
    ctx.setdefault("module", module_mod.alle())
    ctx.setdefault("nicht_gespeichert", request.query_params.get("nicht_gespeichert") == "1")
    # Mehrere Fahrzeuge: Liste fuer Umschalter und Formularfeld, gewaehltes (None = alle)
    ctx.setdefault("mehrere", db.mehrere_fahrzeuge())
    ctx.setdefault("fahrzeuge", db.fahrzeuge())
    ctx.setdefault("fahrzeug_aktuell", db.aktuelles_fahrzeug())
    ctx.setdefault("gesamtsicht", ctx["mehrere"] and ctx["fahrzeug_aktuell"] is None
                   and len(ctx["fahrzeuge"]) > 1)
    # Versionsmarke fuer api/auto-bild: aendert sich mit jedem Bildwechsel, damit der
    # Browser nicht das alte Bild aus dem Cache zeigt
    voll = _auto_bild_pfad()
    ctx.setdefault("bild_v", int(os.path.getmtime(voll)) if voll else 0)
    # Sprachumschalter: zurueck auf dieselbe Seite (pfad-relativ wegen Ingress)
    ctx.setdefault("zurueck", request.url.path.rsplit("/", 1)[-1]
                   + (f"?{request.url.query}" if request.url.query else ""))
    return templates.TemplateResponse(request, template, ctx)


def parse_de(text, tausender: bool = False) -> float | None:
    """Komma/Punkt-tolerantes Zahlen-Parsen; None bei leer/ungültig.

    "12,5" und "12.5" -> 12.5; mit Komma gelten Punkte als Tausendertrenner
    ("1.234,5" -> 1234.5), ebenso bei mehreren Punkten ("1.234.567").
    Ein einzelner Punkt mit genau drei Ziffern dahinter ist mehrdeutig
    ("1.234" km oder 1,234 €/L) – als Tausendertrenner nur mit tausender=True,
    also bei km und Euro-Betraegen, wo drei Nachkommastellen nicht vorkommen.
    """
    t = str(text or "").strip().replace(" ", "").replace("\xa0", "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") > 1 or (tausender and re.fullmatch(r"-?\d{1,3}\.\d{3}", t)):
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────
#  Fahrzeugbild (Dashboard-Kopf) – austauschbar, da andere Nutzer andere Autos fahren
# ─────────────────────────────────────────────────────────────

AUTO_BILD_ERLAUBT = {".jpg", ".jpeg", ".png", ".webp"}


def _auto_bild_pfad() -> str | None:
    """Pfad zum vom Nutzer hochgeladenen Fahrzeugbild, falls vorhanden."""
    datei = db.get_einstellung_str("auto_bild_datei")
    if not datei:
        return None
    voll = os.path.join(DATA_DIR, datei)
    return voll if os.path.exists(voll) else None


def _bild_name(ext: str) -> str:
    """Dateiname des Fahrzeugbilds: Fahrzeug 1 wie bisher, weitere mit ihrer id."""
    fid = db.schreib_fahrzeug()
    return f"auto_bild{ext}" if fid == 1 else f"auto_bild_{fid}{ext}"


@app.get("/api/auto-bild")
def auto_bild(fz: int | None = None):
    """Liefert das eigene Fahrzeugbild, sonst das mitgelieferte Standardbild.
    ?fz=<id>: Bild dieses Fahrzeugs (Umschalter, Uebersicht je Fahrzeug)."""
    if fz is not None:
        with db.fahrzeug_kontext(fz):
            voll = _auto_bild_pfad()
    else:
        voll = _auto_bild_pfad()
    if voll:
        return FileResponse(voll)
    return FileResponse(os.path.join(STATIC_DIR, "Auto.jpg"))


@app.post("/api/auto-bild")
@mit_fahrzeug
async def auto_bild_hochladen(bild: UploadFile = File(...)):
    ext = os.path.splitext(bild.filename or "")[1].lower()
    if ext not in AUTO_BILD_ERLAUBT:
        return JSONResponse(
            {"error": _("Nur JPG, PNG oder WebP erlaubt.")}, status_code=400)
    inhalt = await bild.read()
    if len(inhalt) > 8 * 1024 * 1024:
        return JSONResponse({"error": _("Datei zu groß (max. 8 MB).")}, status_code=400)

    alt = _auto_bild_pfad()
    if alt:
        os.remove(alt)
    dateiname = _bild_name(ext)
    with open(os.path.join(DATA_DIR, dateiname), "wb") as f:
        f.write(inhalt)
    db.set_einstellung("auto_bild_datei", dateiname)
    db.set_einstellung("auto_bild_galerie", "")      # eigenes Bild, kein Galeriebild
    return {"ok": True}


def auto_bild_galerie() -> dict | None:
    """Das gewaehlte Galeriebild mit Name und Nachweis – None bei eigenem oder Standardbild."""
    datei = db.get_einstellung_str("auto_bild_galerie")
    if not datei or not _auto_bild_pfad():
        return None
    return next((b for b in galerie.bilder() if b["datei"] == datei),
                {"datei": datei, "name": datei, "nachweis": None})


@app.get("/api/galerie/vorschau/{datei}")
def galerie_vorschau(datei: str):
    """Verkleinertes Galeriebild; ohne Pillow das Original."""
    daten = galerie.vorschau(datei)
    if daten is not None:
        return Response(daten, media_type="image/jpeg",
                        headers={"Cache-Control": "max-age=86400"})
    voll = galerie.pfad(datei)
    if not voll:
        return JSONResponse({"error": _("Bild nicht gefunden")}, status_code=404)
    return FileResponse(voll)


@app.post("/api/auto-bild/galerie")
@mit_fahrzeug
def auto_bild_aus_galerie(datei: str = Form(...)):
    """Galeriebild als Fahrzeugbild uebernehmen – als Kopie im Datenordner, damit es
    auch nach einem Update ohne dieses Bild erhalten bleibt."""
    voll = galerie.pfad(datei)
    if not voll:
        return JSONResponse({"error": _("Bild nicht gefunden")}, status_code=404)
    alt = _auto_bild_pfad()
    if alt:
        os.remove(alt)
    dateiname = _bild_name(os.path.splitext(datei)[1].lower())
    shutil.copyfile(voll, os.path.join(DATA_DIR, dateiname))
    db.set_einstellung("auto_bild_datei", dateiname)
    db.set_einstellung("auto_bild_galerie", datei)
    return {"ok": True}


@app.post("/api/auto-bild/reset")
@mit_fahrzeug
def auto_bild_zuruecksetzen():
    """Loescht das eigene Bild wieder – Dashboard zeigt danach das Standardbild."""
    voll = _auto_bild_pfad()
    if voll:
        os.remove(voll)
    db.set_einstellung("auto_bild_datei", "")
    db.set_einstellung("auto_bild_galerie", "")
    return {"ok": True}


# ─────────────────────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, zeitraum: str | None = None):
    # Auswahl per ?zeitraum=…; ohne Parameter gilt die zuletzt gewaehlte (Cookie)
    z = zeitraum_mod.aufloesen(zeitraum or request.cookies.get("zeitraum"))
    daten = zeitraum_mod.laden()
    f = zeitraum_mod.filtern(z, daten)
    cfg = daten["cfg"]
    kz = zeitraum_mod.kennzahlen(z, daten)
    # Gesamtsicht mehrerer Fahrzeuge: Liter/CO2 je Fahrzeug gerechnet (eigener Verbrauch)
    gesamt = bool(daten.get("fahrzeuge"))

    charts_html = {
        "monatlich": charts.chart_monatliche_ersparnis(
            f["fahrten"], f["benzin"], f["lade"], benziner_l=cfg["benziner_verbrauch"],
            ersatzpreis=berechnung.durchschnitt_benzinpreis(daten["benzin"]),
            liter_je_monat=daten["liter_je_monat"] if gesamt else None),
        "kosten": charts.chart_kosten_vergleich(
            kz["benzin_kosten"], kz["strom_kosten"]),
        "co2": charts.chart_co2_ersparnis(
            f["fahrten"], benziner_l=cfg["benziner_verbrauch"],
            co2_faktor=cfg["co2_faktor_benzin"],
            co2_je_monat=daten["co2_je_monat"] if gesamt else None),
        "verbrauch": charts.chart_verbrauch_100km(
            f["lade"], f["fahrten"], ev_ref=cfg["ev_verbrauch"], akku_monate=f["akku"],
            akku_entnahme=daten["akku_entnahme"]),
        "strommix": charts.chart_strommix(f["lade"]),
        "benzin": charts.chart_benzinpreise(f["benzin"]),
        "strom": charts.chart_stromtarif(daten["stromtarife"], von=z["von"], bis=z["bis"]),
        "anbieter": charts.chart_anbieter_verteilung(f["lade"]),
        "thg": charts.chart_thg(f["thg"]),
    }
    # Amortisation immer ueber den ganzen Datenbestand, unabhaengig vom Zeitraum
    amo = zeitraum_mod.amortisation(daten)
    if amo:
        charts_html["amortisation"] = charts.chart_amortisation(amo)
    # Elemente ausgeschalteter Module erscheinen auch im Bearbeiten-Modus nicht
    layout = dashboard_layout.ohne(dashboard_layout.laden(), module_mod.ausgeblendet())
    # Lade-Abo (Break-even) – auch ausgeblendet, damit es im Bearbeiten-Modus erscheint
    abo = ladetarife_mod.seite_daten()["rentabilitaet"]
    # Akku-Kacheln nur fuer ein einzelnes Fahrzeug und nur, wenn eine sichtbar ist
    akku = None
    if not gesamt and any(k["an"] and k["id"] in dashboard_layout.AKKU_KACHELN
                          for k in layout["kacheln"]):
        akku = akku_mod.auswertung()
    leasing = ([(fz, l) for fz, l in _je_fahrzeug(leasing_mod.auswertung) if l]
               if module_mod.an("leasing") else [])
    # Energie-Aufteilung: Kacheln und Diagramm im gewaehlten Zeitraum, nur ein Fahrzeug
    energie = None
    if not gesamt and module_mod.an("energie") and (
            any(k["an"] and k["id"] in dashboard_layout.ENERGIE_KACHELN for k in layout["kacheln"])
            or any(d["an"] and d["id"] == "energieaufteilung" for d in layout["diagramme"])):
        energie = energie_mod.auswertung(z)
    charts_html["energieaufteilung"] = (charts.chart_energie_monate(energie["monate_zeitraum"])
                                        if energie else charts._leer(_("Nur für ein einzelnes Fahrzeug")))
    antwort = render(request, "dashboard.html", kz=kz, charts=charts_html, amo=amo,
                     layout=layout, abo=abo, akku=akku, leasing=leasing, energie=energie,
                     zeitraum=z, zeitraum_optionen=zeitraum_mod.optionen(daten),
                     fahrzeug_name=(_("Alle Fahrzeuge") if gesamt else
                                    db.get_einstellung_str("fahrzeug_name") or "Mein Elektroauto"),
                     galerie_aktiv=auto_bild_galerie(),
                     aktiv="dashboard")
    if zeitraum is not None:
        antwort.set_cookie("zeitraum", z["schluessel"], max_age=365 * 24 * 3600,
                           samesite="lax")
    return antwort


@app.post("/api/dashboard/layout")
def dashboard_layout_speichern(payload: dict):
    """Anordnung aus dem Bearbeiten-Modus des Dashboards speichern (global)."""
    return {"ok": True, "layout": dashboard_layout.speichern(payload, module_mod.ausgeblendet())}


@app.post("/api/dashboard/layout/standard")
def dashboard_layout_standard():
    dashboard_layout.zuruecksetzen()
    return {"ok": True, "layout": dashboard_layout.standard()}


# ─────────────────────────────────────────────────────────────
#  Statistik: zwei Zeitraeume vergleichen
# ─────────────────────────────────────────────────────────────

@app.get("/statistik", response_class=HTMLResponse)
def statistik(request: Request, a: str | None = None, b: str | None = None):
    heute = datetime.now()
    za = zeitraum_mod.aufloesen(a or str(heute.year))
    zb = zeitraum_mod.aufloesen(b or str(heute.year - 1))
    daten = zeitraum_mod.laden()
    ka = zeitraum_mod.kennzahlen(za, daten)
    kb = zeitraum_mod.kennzahlen(zb, daten)
    # Modul Energie: Verbrauch laut Bordcomputer (nur fuer ein einzelnes Fahrzeug)
    if module_mod.an("energie") and db.aktuelles_fahrzeug() is not None:
        tage = db.get_energie_tage()
        for z, k in ((za, ka), (zb, kb)):
            k["verbrauch_bordcomputer"] = energie_mod.summe(
                [t for t in tage if zeitraum_mod.enthaelt(z, t["datum"])])["bordcomputer"]
    wa = zeitraum_mod.monatswerte(za, daten)
    wb = zeitraum_mod.monatswerte(zb, daten)
    verlauf = {m: charts.chart_vergleich(wa, wb, za["titel"], zb["titel"], m)
               for m in charts.VERGLEICH_METRIKEN}
    # Nach dem Kauf: die Simulation aus den km als Prognose neben den echten Ladungen
    prognose = None
    if not daten["cfg"]["simulation"] and ka["ladevorgaenge"] and daten["lade_sim"]:
        kp = zeitraum_mod.kennzahlen(za, {**daten, "lade": daten["lade_sim"]})
        prognose = zeitraum_mod.vergleich_zeilen(ka, kp, nur=zeitraum_mod.PROGNOSE_ZEILEN)
    return render(request, "statistik.html", aktiv="statistik",
                  za=za, zb=zb, ka=ka, kb=kb,
                  zeilen=zeitraum_mod.vergleich_zeilen(ka, kb),
                  optionen=zeitraum_mod.optionen(daten),
                  vorlagen=zeitraum_mod.vorlagen(),
                  metriken=charts.VERGLEICH_METRIKEN, verlauf=verlauf,
                  akku_zeilen=zeitraum_mod.akku_monatszeilen(wa, wb),
                  prognose=prognose,
                  akku_min_km=akkuverbrauch.MIN_KM)


# ─────────────────────────────────────────────────────────────
#  Akku: SoH, Ladezyklen, Reichweite – und Profil: Nutzung, Laden, Jahresvergleich
# ─────────────────────────────────────────────────────────────

def _je_fahrzeug(funktion) -> list:
    """[(fahrzeug, ergebnis)] – das gewaehlte Fahrzeug bzw. in der Gesamtsicht jedes
    sichtbare (SoH, Zyklen und Reichweite lassen sich nicht addieren)."""
    fid = db.aktuelles_fahrzeug()
    liste = [f for f in db.fahrzeuge() if fid is None or f["id"] == fid] or db.fahrzeuge()[:1]
    erg = []
    for fz in liste:
        with db.fahrzeug_kontext(fz["id"]):
            erg.append((fz, funktion()))
    return erg


def _akku_seite(fz: dict, a: dict) -> dict:
    return {"fz": fz, "a": a, "charts": {
        "soh": charts.chart_soh(a),
        "zyklen": charts.chart_zyklen(a["zyklen"]["je_monat"]),
        "ladefenster": charts.chart_ladefenster(a["zyklen"]),
        "reichweite": charts.chart_reichweite(a["reichweite"]),
    }}


@app.get("/akku", response_class=HTMLResponse)
@modul("akku")
def akku_seite(request: Request, bearbeiten: int | None = None):
    autos = [_akku_seite(fz, a) for fz, a in _je_fahrzeug(akku_mod.auswertung)]
    # Akkustand jetzt nur fuer ein einzelnes Fahrzeug – fragt Home Assistant live
    live = {}
    if len(autos) == 1:
        with db.fahrzeug_kontext(autos[0]["fz"]["id"]):
            live = akku_mod.live(autos[0]["a"]["reichweite"]["jetzt"])
    eintrag = None
    if bearbeiten:
        eintrag = next((m for x in autos for m in x["a"]["messungen"] if m["id"] == bearbeiten), None)
    return render(request, "akku.html", autos=autos, live=live, eintrag=eintrag,
                  quellen=akku_mod.QUELLEN, soh_quellen=db.SOH_QUELLEN,
                  heute=datetime.now().strftime("%Y-%m-%d"), aktiv="akku")


def _soh_werte(form) -> dict | None:
    """Formularfelder -> DB-Werte; None ohne Datum oder plausiblen SoH (1–120 %)."""
    werte = {k: (str(form.get(k) or "").strip() or None) for k in ("datum", "quelle", "notiz")}
    werte["soh"] = parse_de(form.get("soh"))
    werte["km_stand"] = parse_de(form.get("km_stand"), tausender=True)
    if werte["quelle"] not in db.SOH_QUELLEN:
        werte["quelle"] = "sonstiges"
    if (not werte["datum"] or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", werte["datum"])
            or werte["soh"] is None or not 1 <= werte["soh"] <= 120):
        return None
    return werte


@app.post("/akku/soh")
@mit_fahrzeug
@modul("akku", seite=False)
async def akku_soh_add(request: Request):
    werte = _soh_werte(await request.form())
    if werte:
        db.add_soh_messung(werte)
    return RedirectResponse("../akku#soh", status_code=303)


@app.post("/akku/soh/update")
@modul("akku", seite=False)
async def akku_soh_update(request: Request):
    form = await request.form()
    werte = _soh_werte(form)
    if werte and str(form.get("id") or "").isdigit():
        db.update_soh_messung(int(form["id"]), werte)
    return RedirectResponse("../../akku#soh", status_code=303)


@app.post("/akku/soh/delete")
@modul("akku", seite=False)
def akku_soh_delete(id: int = Form(...)):
    db.delete_soh_messung(id)
    return RedirectResponse("../../akku#soh", status_code=303)


@app.post("/akku/einstellungen")
@mit_fahrzeug
@modul("akku", seite=False)
def akku_einstellungen(verlust: str = Form(""), garantie_jahre: str = Form(""),
                       garantie_km: str = Form(""), garantie_soh: str = Form(""),
                       fenster_oben: str = Form(""), fenster_unten: str = Form("")):
    """Ladeverlust-Annahme der SoH-Schaetzung, Akku-Garantie und Nutzungsfenster
    (leer = Standard)."""
    oben, unten = parse_de(fenster_oben), parse_de(fenster_unten)
    if oben is not None and unten is not None and 0 <= unten < oben <= 100:
        db.set_einstellung("akku_fenster_oben", oben)
        db.set_einstellung("akku_fenster_unten", unten)
    elif not fenster_oben.strip() and not fenster_unten.strip():
        db.set_einstellung("akku_fenster_oben", "")
        db.set_einstellung("akku_fenster_unten", "")
    for key, raw, grenzen, tausender in [
            ("akku_verlust_annahme", verlust, (0, akku_mod.VERLUST_MAX), False),
            ("akku_garantie_jahre", garantie_jahre, (1, 30), False),
            ("akku_garantie_km", garantie_km, (1000, 2000000), True),
            ("akku_garantie_soh", garantie_soh, (1, 100), False)]:
        if not raw.strip():
            db.set_einstellung(key, "")
            continue
        v = parse_de(raw, tausender=tausender)
        if v is not None and grenzen[0] <= v <= grenzen[1]:
            db.set_einstellung(key, v)
    return RedirectResponse("../akku#einstellungen", status_code=303)


@app.get("/energie", response_class=HTMLResponse)
@modul("energie")
def energie_seite(request: Request, zeitraum: str | None = None, meldung: str = ""):
    z = zeitraum_mod.aufloesen(zeitraum)

    def je_auto():
        e = energie_mod.auswertung(z)
        return {"e": e, "charts": {"monate": charts.chart_energie_monate(e["monate_zeitraum"]),
                                   "anteile": charts.chart_energie_anteile(e["summe"])}}
    return render(request, "energie.html", autos=_je_fahrzeug(je_auto), zeitraum=z,
                  zeitraum_optionen=zeitraum_mod.optionen(zeitraum_mod.laden()),
                  kategorien=energie_mod.KATEGORIEN, meldung=meldung,
                  sensor=db.get_ha_settings().get("ha_ev_tagesstatistik") or "",
                  aktiv="energie")


@app.post("/energie/nachholen")
@mit_fahrzeug
@modul("energie", seite=False)
def energie_nachholen():
    """Tage aus der Fahrstatistik holen, auch die aelteren aus dem Recorder."""
    from urllib.parse import quote
    try:
        meldung = energie_mod.aktualisieren(nachholen=True) or _("Kein Sensor für die Fahrstatistik eingetragen.")
    except Exception as e:
        meldung = _("Fehler beim Abruf: {0}", e)
    return RedirectResponse(f"../energie?meldung={quote(meldung)}", status_code=303)


def _im_hintergrund(funktion):
    threading.Thread(target=funktion, daemon=True).start()


def _energie_nachholen():
    """Nach dem Einschalten des Moduls: je Fahrzeug mit Fahrstatistik die Tage nachholen."""
    for fz in db.fahrzeuge(alle=True):
        try:
            with db.fahrzeug_kontext(fz["id"]):
                meldung = energie_mod.aktualisieren(nachholen=True)
            if meldung:
                _log_import([f"{meldung} ({fz['name']}, Modul eingeschaltet)"])
        except Exception as e:
            print(f"[Energie] Fehler beim Nachholen: {e}", flush=True)


@app.get("/fahrtenbuch", response_class=HTMLResponse)
@modul("fahrtenbuch")
def fahrtenbuch_seite(request: Request, monat: str = "", meldung: str = ""):
    if not re.fullmatch(r"\d{4}-\d{2}", monat or ""):
        monat = datetime.now().strftime("%Y-%m")

    def je_auto():
        liste = db.get_fahrten(monat + "-01", monat + "-31")
        tage = {}
        for f in reversed(liste):
            tage.setdefault(f["start"][:10], []).append(f)
        summe = {"km": sum(f["km"] for f in liste), "fahrten": len(liste), "je_kategorie": {}}
        for f in liste:
            k = f.get("kategorie") or ""
            summe["je_kategorie"][k] = summe["je_kategorie"].get(k, 0.0) + f["km"]
        ha = db.get_ha_settings()
        return {"tage": tage, "summe": summe, "ort_sensor": ha.get("ha_ev_ort") or "",
                "motor_sensor": ha.get("ha_ev_fahrt") or "",
                "orte": len(db.get_orte(monat + "-01"))}
    return render(request, "fahrtenbuch.html", autos=_je_fahrzeug(je_auto), monat=monat,
                  kategorien=fahrtenbuch_mod.KATEGORIEN, ort_text=fahrtenbuch_mod.ort_text,
                  einst=fahrtenbuch_mod.einstellungen(), meldung=meldung, aktiv="fahrtenbuch")


@app.post("/fahrtenbuch/update")
@mit_fahrzeug
@modul("fahrtenbuch", seite=False)
def fahrtenbuch_update(start: str = Form(...), kategorie: str = Form(""), notiz: str = Form(""),
                       monat: str = Form("")):
    db.update_fahrt(start, kategorie if kategorie in fahrtenbuch_mod.KATEGORIEN else None,
                    notiz.strip() or None)
    ziel = f"?monat={monat}" if re.fullmatch(r"\d{4}-\d{2}", monat) else ""
    return RedirectResponse(f"../fahrtenbuch{ziel}", status_code=303)


@app.post("/fahrtenbuch/neu")
@mit_fahrzeug
@modul("fahrtenbuch", seite=False)
def fahrtenbuch_neu():
    """Fahrten der letzten Tage neu erkennen (so weit der Recorder zurueckreicht)."""
    from urllib.parse import quote
    try:
        meldung = fahrtenbuch_mod.aktualisieren(tage=fahrtenbuch_mod.MAX_TAGE)
    except Exception as e:
        meldung = _("Fehler beim Abruf: {0}", e)
    return RedirectResponse(f"../fahrtenbuch?meldung={quote(meldung)}", status_code=303)


@app.get("/fahrtenbuch/csv")
@modul("fahrtenbuch", seite=False)
def fahrtenbuch_csv(monat: str = ""):
    if not re.fullmatch(r"\d{4}-\d{2}", monat or ""):
        monat = datetime.now().strftime("%Y-%m")
    text = fahrtenbuch_mod.csv_text(db.get_fahrten(monat + "-01", monat + "-31"))
    # BOM vorneweg: Excel erkennt die Datei sonst nicht als UTF-8
    return Response(chr(0xFEFF) + text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="fahrtenbuch_{monat}.csv"'})


@app.post("/einstellungen/fahrtenbuch")
def einstellungen_fahrtenbuch(pause_min: str = Form(""), min_km: str = Form(""),
                              adressen: str = Form("")):
    """Pausengrenze, Mindeststrecke und Adressen ueber OpenStreetMap (gilt fuer alle)."""
    pause, km = parse_de(pause_min), parse_de(min_km)
    if pause is not None and 1 <= pause <= 24 * 60:
        db.set_einstellung("fahrt_pause_min", pause)
    if km is not None and 0 <= km <= 100:
        db.set_einstellung("fahrt_min_km", km)
    db.set_einstellung("fahrt_adressen", "1" if adressen else "0")
    return RedirectResponse("../einstellungen#fahrtenbuch", status_code=303)


@app.get("/profil", response_class=HTMLResponse)
@modul("profil")
def profil_seite(request: Request):
    def je_auto():
        a = akku_mod.auswertung()
        n = profil_mod.nutzung(db.get_fahrten_tage(), a["reichweite"]["jetzt"])
        l = profil_mod.laden(a["ladungen"], db.get_ladevorgaenge(limit=100000))
        fp = (fahrtenbuch_mod.profil(db.get_fahrten()) if module_mod.an("fahrtenbuch") else None)
        if fp:
            fp["charts"] = {
                "klassen": charts.chart_balken_liste([_(t) for t, _n in fp["klassen"]],
                                                     [n for _t, n in fp["klassen"]], _("Fahrten"), "teal"),
                "stunden": charts.chart_balken_liste([f"{h}" for h in range(24)], fp["stunden"],
                                                     _("Fahrten"), "blue")}
        return {"nutzung": n, "laden": l, "reichweite": a["reichweite"]["jetzt"], "fahrten": fp,
                "charts": {
                    "wochentage": charts.chart_balken_liste(
                        [_(t) for t in profil_mod.WOCHENTAGE], n["je_wochentag"] if n else [],
                        _("Ø km je Tag"), "blue", "fn:km0"),
                    "klassen": charts.chart_balken_liste(
                        [_(t) for t, _b in profil_mod.KLASSEN], n["klassen"] if n else [],
                        _("Tage"), "teal"),
                    "ladetage": charts.chart_balken_liste(
                        [_(t) for t in profil_mod.WOCHENTAGE], l["je_wochentag"], _("Ladungen"), "purple"),
                    "ladestunden": charts.chart_balken_liste(
                        [f"{h}" for h in range(24)], l["je_stunde"], _("Ladungen"), "purple"),
                    "orte": charts.chart_strommix(db.get_ladevorgaenge(limit=100000)),
                }}
    autos = _je_fahrzeug(je_auto)
    daten = zeitraum_mod.laden()
    jv = profil_mod.jahresvergleich(daten)
    jahre_charts = {m: charts.chart_jahre(jv, m) for m in profil_mod.JAHR_METRIKEN}
    return render(request, "profil.html", autos=autos, jv=jv, jahre_charts=jahre_charts,
                  metriken=profil_mod.JAHR_METRIKEN, aktiv="profil")


# ─────────────────────────────────────────────────────────────
#  Hilfe / Handbuch
# ─────────────────────────────────────────────────────────────

@app.get("/hilfe", response_class=HTMLResponse)
def hilfe(request: Request):
    # Englische Hilfe als eigenes Template mit denselben Ankern; das Aenderungslog bleibt deutsch
    vorlage = "hilfe_en.html" if i18n.sprache() == "en" else "hilfe.html"
    return render(request, vorlage, aktiv="hilfe", changelog=CHANGELOG)


# ─────────────────────────────────────────────────────────────
#  Einrichtung: Schnellstart mit Stand je Schritt
# ─────────────────────────────────────────────────────────────

def _sensor_stand(ha: dict, ha_key: str, fn_key: str, influx: bool) -> tuple[str, str]:
    """(stand, text) einer Sensorzeile: "ok", "pruefen" (noch der Beispielwert
    aus der Erstinstallation) oder "fehlt"."""
    wert = (ha.get(fn_key) if influx else ha.get(ha_key)) or ""
    if not wert.strip():
        return "fehlt", _("nicht eingetragen")
    if wert == db.HA_ENTITY_DEFAULTS.get(fn_key if influx else ha_key):
        return "pruefen", _("{0} – Beispielwert, bitte prüfen", wert)
    return "ok", wert


@app.get("/einrichtung", response_class=HTMLResponse)
def einrichtung(request: Request):
    ha = db.get_ha_settings()
    mail = db.get_mail_settings()
    simulation = db.get_config()["simulation"]
    influx = ha.get("datasource") in ("influxdb", "influxdb2", "influxdb3")
    felder = [s for s in SENSOR_FELDER if s[0] not in SENSOR_NUR_AKKU]
    sensoren = [(_sensor_label(label), *_sensor_stand(ha, h, f, influx))
                for h, f, label in felder]
    # Zweiter Preis-Sensor und Akkustand sind optional – leer ist dort kein Mangel
    optional = {"ha_tankerkoenig_2", "ha_ev_battery", "ha_wallbox_cost"}
    if simulation:              # ohne E-Auto gibt es keine Ladezaehler
        optional |= {"ha_pv_production", "ha_wallbox_energy"}
    sensoren = [(l, "optional" if st == "fehlt" and h in optional else st, t)
                for (l, st, t), (h, _f, _l) in zip(sensoren, felder)]
    return render(request, "einrichtung.html", aktiv="einrichtung",
                  fahrzeug_name=db.get_einstellung_str("fahrzeug_name") or "",
                  verbunden=_ha_verbindung(ha) is not None,
                  add_on_modus=IST_ADDON,
                  datenquelle=datenquellen.QUELLEN.get(ha.get("datasource")),
                  influx=influx,
                  sensoren=sensoren,
                  tarife=len(db.get_stromtarife()),
                  monate_km=len(db.get_fahrten_monate()),
                  ladungen=len(db.get_ladevorgaenge(limit=100000)),
                  preise=len(db.get_benzinpreise()),
                  kfz=db.get_einstellung("kfz_steuer_benziner") or 0.0,
                  mail_aktiv=mail.get("mail_aktiv") == "1",
                  auto_import=mail.get("auto_import") == "1")


# ─────────────────────────────────────────────────────────────
#  Fahrten
# ─────────────────────────────────────────────────────────────

@app.get("/fahrten", response_class=HTMLResponse)
def fahrten(request: Request):
    daten = db.get_fahrten_monate()
    cfg = db.get_config()
    # Gesamtsicht mehrerer Fahrzeuge: Liter/CO2 je Fahrzeug mit dessen Verbrauch
    je_monat = zeitraum_mod.laden() if db.aktuelles_fahrzeug() is None else None
    rows = []
    for d in daten:
        if je_monat is not None:
            liter = je_monat["liter_je_monat"].get(d["monat"], 0.0)
            co2 = je_monat["co2_je_monat"].get(d["monat"], 0.0)
        else:
            liter = berechnung.benzin_liter(d["km"], cfg["benziner_verbrauch"])
            co2 = berechnung.co2_kg(liter, cfg["co2_faktor_benzin"])
        rows.append({**d, "liter": liter, "co2": co2})
    verbrauch = berechnung.verbrauch_statistik()
    akku_monate = akkuverbrauch.pro_monat()
    akku_km = sum(m["km"] for m in akku_monate)
    akku_schnitt = (sum(m["kwh"] for m in akku_monate) / akku_km * 100) if akku_km else None

    # Vergleich Akku ↔ Ladung nur ueber Monate, fuer die beides vorliegt
    ladung_m = {m["monat"]: m for m in verbrauch["monate"]}
    gemeinsam = [a for a in akku_monate if a["monat"] in ladung_m]
    differenz = None
    if gemeinsam:
        l_km = sum(ladung_m[a["monat"]]["km"] for a in gemeinsam)
        l_kwh = sum(ladung_m[a["monat"]]["kwh"] for a in gemeinsam)
        a_km = sum(a["km"] for a in gemeinsam)
        a_kwh = sum(a["kwh"] for a in gemeinsam)
        if l_km and a_km and l_kwh:
            differenz = (1 - (a_kwh / a_km) / (l_kwh / l_km)) * 100

    leasing = ([(fz, l, charts.chart_leasing(l)) for fz, l in _je_fahrzeug(leasing_mod.auswertung)
                if l] if module_mod.an("leasing") else [])
    return render(request, "fahrten.html", rows=rows, aktiv="fahrten",
                  verbrauch=verbrauch, leasing=leasing,
                  abschnitte=db.get_akku_abschnitte(limit=40),
                  akku_schnitt=akku_schnitt, akku_differenz=differenz,
                  akku_gemeinsam=len(gemeinsam), akku_min_km=akkuverbrauch.MIN_KM,
                  akku_meldung=request.query_params.get("akku"))


@app.post("/fahrten/akku")
@mit_fahrzeug
def fahrten_akku_berechnen(zeitraum: str = Form("alles")):
    """Fahrtabschnitte aus dem Akkustand neu berechnen (ganze Historie oder 45 Tage)."""
    tage = None if zeitraum == "alles" else akkuverbrauch.TAGE_NACHTLAUF
    try:
        meldung = akkuverbrauch.aktualisieren(tage=tage)
    except Exception as e:
        meldung = _("Fehler beim Abruf: {0}", e)
    try:
        soh = akku_mod.soh_aktualisieren(tage=tage) if module_mod.an("akku") else ""
    except Exception as e:
        soh = _("SoH-Sensor: Fehler ({0})", e)
    if soh:
        meldung += " · " + soh
    from urllib.parse import quote
    return RedirectResponse(f"../fahrten?akku={quote(meldung)}#akku", status_code=303)


@app.post("/fahrten")
@mit_fahrzeug
def fahrten_add(monat: str = Form(...), km: str = Form(...)):
    v = parse_de(km, tausender=True)
    if v is not None and v >= 0:
        db.set_fahrt_monat(monat, v)
    return RedirectResponse("fahrten", status_code=303)


@app.post("/fahrten/delete")
@mit_fahrzeug
def fahrten_delete(monat: str = Form(...)):
    db.delete_fahrt_monat(monat)
    return RedirectResponse("../fahrten", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Laden
# ─────────────────────────────────────────────────────────────

def _lade_gruppen(rows: list) -> list:
    """Teile einer Heimladung als eine Zeile: eine aus Home Assistant geschickte Ladung
    (Kennung "ha:<Beginn>:netz" / ":pv") bzw. die importierte Monatssumme aus PV und Netz
    (naechtlicher Abruf oder Zeitraum-Import).
    Rueckgabe in der Reihenfolge der Liste: [{"kopf": Summenzeile, "teile": [Zeilen]}] –
    bei nur einem Teil ist der Kopf die Zeile selbst."""
    gruppen = {}
    for r in rows:
        schluessel = berechnung.ladung_schluessel(r) or ("einzeln", r["id"])
        gruppen.setdefault(schluessel, []).append(r)
    erg = []
    for teile in gruppen.values():
        if len(teile) == 1:
            erg.append({"kopf": teile[0], "teile": teile})
            continue
        teile.sort(key=lambda t: t["anbieter"] != berechnung.NETZBEZUG)    # Netz zuerst
        kwh = sum(t["menge_kwh"] for t in teile)
        gesamt = sum(t["gesamtpreis"] for t in teile)
        pv = sum(t["menge_kwh"] for t in teile if t["anbieter"] == heimladung.PV)
        erg.append({"teile": teile, "kopf": {
            **teile[0], "menge_kwh": kwh, "gesamtpreis": gesamt,
            "preis_kwh": gesamt / kwh * 100 if kwh else None,
            "blockiergebuehr": None, "pv_anteil": pv / kwh * 100 if kwh else 0.0}})
    return erg


@app.get("/laden", response_class=HTMLResponse)
def laden(request: Request, datum: str = "", anbieter: str = "", typ: str = "",
          kw: str = "", fz: str = "", ok: str = ""):
    daten = db.get_ladevorgaenge(limit=500)
    anbieter_liste = db.get_lade_anbieter()
    tarif = db.get_aktueller_stromtarif()
    pv_ct = db.get_einstellung("pv_preis_ct") or 13.0
    # Aktueller Abo-Preis je Anbieter fuer die Vorbelegung von ct/kWh
    abo = {a: {"ac": t["preis_ac"], "dc": t["preis_dc"] or t["preis_ac"],
               "name": t["tarif_name"] or ""}
           for a, t in db.get_aktuelle_ladetarife().items()}
    # Nach dem Hinzufuegen bleiben Datum, Anbieter, Typ, kW und Fahrzeug stehen –
    # so lassen sich mehrere Ladungen eines Monats zuegig nachtragen
    letzte = {"datum": datum if re.fullmatch(r"\d{4}-\d{2}-\d{2}", datum) else "",
              "anbieter": anbieter, "typ": typ if typ in ("AC", "DC") else "",
              "kw": kw, "fz": int(fz) if fz.isdigit() else None, "ok": ok == "1"}
    return render(request, "laden.html", gruppen=_lade_gruppen(daten), anbieter=anbieter_liste,
                  tarif=tarif, pv_ct=pv_ct, abo=abo, aktiv="laden", letzte=letzte,
                  heute=datetime.now().strftime("%Y-%m-%d"))


@app.post("/laden")
@mit_fahrzeug
def laden_add(datum: str = Form(...), kwh: str = Form(...),
              preis_kwh: str = Form(""), gesamt: str = Form(""),
              anbieter: str = Form(...), leistung: str = Form(""),
              ladetyp: str = Form("AC"), notiz: str = Form(""),
              blockier: str = Form("")):
    from urllib.parse import urlencode
    kwh_v = parse_de(kwh)
    ct_v = parse_de(preis_kwh)
    gesamt_v = parse_de(gesamt, tausender=True)
    blockier_v = parse_de(blockier, tausender=True)
    # Der Gesamtpreis enthaelt die Blockiergebuehr
    if gesamt_v is None and kwh_v is not None and ct_v is not None:
        gesamt_v = round(kwh_v * ct_v / 100 + (blockier_v or 0), 2)
    gespeichert = kwh_v is not None and kwh_v > 0 and gesamt_v is not None
    if gespeichert:
        db.add_ladevorgang(datum, kwh_v, ct_v, gesamt_v, anbieter,
                           parse_de(leistung), ladetyp, notiz, blockier_v)
    # Eingaben fuer den naechsten Eintrag stehen lassen (in der Gesamtsicht auch
    # das Fahrzeug – mit_fahrzeug hat es hier schon ausgewaehlt)
    fz = db.aktuelles_fahrzeug() if db.mehrere_fahrzeuge() else None
    teile = {k: v for k, v in (("datum", datum), ("anbieter", anbieter), ("typ", ladetyp),
                               ("kw", leistung.strip()), ("fz", fz),
                               ("ok", "1" if gespeichert else "")) if v}
    return RedirectResponse("laden?" + urlencode(teile), status_code=303)


@app.post("/laden/update")
@mit_fahrzeug
def laden_update(id: int = Form(...), datum: str = Form(...), kwh: str = Form(...),
                 preis_kwh: str = Form(""), gesamt: str = Form(""),
                 anbieter: str = Form(...), leistung: str = Form(""),
                 ladetyp: str = Form("AC"), notiz: str = Form(""),
                 blockier: str = Form("")):
    kwh_v = parse_de(kwh)
    ct_v = parse_de(preis_kwh)
    gesamt_v = parse_de(gesamt, tausender=True)
    blockier_v = parse_de(blockier, tausender=True)
    # Der Gesamtpreis enthaelt die Blockiergebuehr
    if gesamt_v is None and kwh_v is not None and ct_v is not None:
        gesamt_v = round(kwh_v * ct_v / 100 + (blockier_v or 0), 2)
    if kwh_v is None or kwh_v <= 0 or gesamt_v is None:
        return JSONResponse({"error": _("kWh und Gesamtpreis muessen Zahlen sein.")},
                            status_code=400)
    # Mit Fahrzeugauswahl (Gesamtsicht) wird die Ladung dem gewaehlten Fahrzeug
    # zugeordnet; sonst ist es das angezeigte – die Zuordnung bleibt gleich
    db.update_ladevorgang(id, datum, kwh_v, ct_v, gesamt_v, anbieter,
                          parse_de(leistung), ladetyp, notiz, blockier_v,
                          fahrzeug_id=db.aktuelles_fahrzeug())
    return {"ok": True}


@app.post("/laden/delete")
def laden_delete(id: list[int] = Form(...)):
    # mehrere ids: alle Teile einer Ladung (PV und Netz) auf einmal
    for i in id:
        db.delete_ladevorgang(i)
    return RedirectResponse("../laden", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Benzinpreise
# ─────────────────────────────────────────────────────────────

@app.get("/benzin", response_class=HTMLResponse)
def benzin(request: Request):
    return render(request, "benzin.html", rows=db.get_benzinpreise(), aktiv="benzin")


@app.post("/benzin")
def benzin_add(monat: str = Form(...), preis: str = Form(...)):
    v = parse_de(preis)
    if v is not None and v > 0:
        db.set_benzinpreis(monat, v)
    return RedirectResponse("benzin", status_code=303)


@app.post("/benzin/delete")
def benzin_delete(monat: str = Form(...)):
    db.delete_benzinpreis(monat)
    return RedirectResponse("../benzin", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Stromtarif
# ─────────────────────────────────────────────────────────────

@app.get("/stromtarif", response_class=HTMLResponse)
def stromtarif(request: Request):
    return render(request, "stromtarif.html", rows=db.get_stromtarife(),
                  aktuell=db.get_aktueller_stromtarif(), aktiv="stromtarif",
                  heute=datetime.now().strftime("%Y-%m-%d"))


@app.post("/stromtarif")
def stromtarif_add(gueltig_ab: str = Form(...), preis: str = Form(...),
                   name: str = Form("")):
    v = parse_de(preis)
    if v is not None and v > 0:
        db.add_stromtarif(gueltig_ab, v, name)
        berechnung.heimladungen_neu_bewerten()
    return RedirectResponse("stromtarif", status_code=303)


@app.post("/stromtarif/delete")
def stromtarif_delete(id: int = Form(...)):
    db.delete_stromtarif(id)
    berechnung.heimladungen_neu_bewerten()
    return RedirectResponse("../stromtarif", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Ladetarife (eigene Abos)
# ─────────────────────────────────────────────────────────────

@app.get("/ladetarife", response_class=HTMLResponse)
def ladetarife(request: Request):
    d = ladetarife_mod.seite_daten()
    # Nur oeffentliche Anbieter – fuer Laden zuhause gibt es die Seite Stromtarif
    anbieter = [a for a in db.get_lade_anbieter() if not a["name"].startswith("Privat")]
    for r in d["rentabilitaet"]:
        r["chart"] = charts.chart_rentabilitaet(r["verlauf"])
    return render(request, "ladetarife.html", tarife=d["tarife"], monate=d["monate"],
                  rentabilitaet=d["rentabilitaet"], anbieter=anbieter,
                  chart=charts.chart_ladetarife(d["roh"], db.get_stromtarife()),
                  aktiv="ladetarife", heute=datetime.now().strftime("%Y-%m-%d"))


def _ladetarif_werte(form) -> dict | None:
    """Formularfelder -> DB-Werte; None, wenn Pflichtangaben fehlen."""
    werte = {k: (str(form.get(k) or "").strip() or None)
             for k in ("anbieter", "tarif_name", "gueltig_ab", "gueltig_bis", "notiz")}
    for k in ("preis_ac", "preis_dc", "grundgebuehr", "blockier_ct_min", "blockier_ab_min",
              "blockier_max_eur", "fremd_ab_ct", "fremd_max_ct", "ladekarte_eur"):
        werte[k] = parse_de(form.get(k), tausender=k.endswith(("_eur", "gebuehr")))
    werte["grundgebuehr"] = werte["grundgebuehr"] or 0.0
    # Nur zum Vergleich: nicht abgeschlossen, kostet nichts, belegt keine Preise vor
    werte["nur_vergleich"] = 1 if form.get("nur_vergleich") else 0
    # Mehrere Fahrzeuge: Tarif eines Fahrzeugs oder gemeinsam (leer = NULL, nach km verteilt)
    if "tarif_fahrzeug" in form:
        roh = str(form.get("tarif_fahrzeug") or "")
        werte["fahrzeug_id"] = int(roh) if roh.isdigit() else None
    if not werte["anbieter"] or not werte["gueltig_ab"] or not werte["preis_ac"]:
        return None
    return werte


@app.post("/ladetarife")
async def ladetarife_add(request: Request):
    werte = _ladetarif_werte(await request.form())
    if werte:
        db.add_ladetarif(werte)
    return RedirectResponse("ladetarife", status_code=303)


@app.post("/ladetarife/update")
async def ladetarife_update(request: Request):
    form = await request.form()
    werte = _ladetarif_werte(form)
    if werte is None:
        return JSONResponse({"error": _("Anbieter, gültig ab und ct/kWh AC sind Pflicht.")},
                            status_code=400)
    db.update_ladetarif(int(form["id"]), werte)
    return {"ok": True}


@app.post("/ladetarife/delete")
def ladetarife_delete(id: int = Form(...)):
    db.delete_ladetarif(id)
    return RedirectResponse("../ladetarife", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Steuer & THG
# ─────────────────────────────────────────────────────────────

@app.get("/steuer", response_class=HTMLResponse)
def steuer(request: Request):
    return render(request, "steuer_thg.html",
                  kfz=db.get_einstellung("kfz_steuer_benziner") or 0.0,
                  kfz_eauto=db.get_einstellung("kfz_steuer_eauto") or 0.0,
                  kfz_eauto_ab=db.get_einstellung_str("kfz_steuer_eauto_ab") or "",
                  erstzulassung=zeitraum_mod.erstzulassung(),
                  steuerfrei_bis=zeitraum_mod.steuerfrei_bis(zeitraum_mod.erstzulassung()),
                  rows=db.get_thg_eintraege(), thg_gesamt=db.get_thg_gesamt(),
                  aktiv="steuer", heute=datetime.now().strftime("%Y-%m-%d"))


@app.post("/steuer/kfz")
@mit_fahrzeug
def steuer_kfz(betrag: str = Form(...)):
    v = parse_de(betrag, tausender=True)
    if v is not None and v >= 0:
        db.set_einstellung("kfz_steuer_benziner", v)
    return RedirectResponse("../steuer", status_code=303)


@app.post("/steuer/eauto")
@mit_fahrzeug
def steuer_eauto(betrag: str = Form(...), ab: str = Form("")):
    """Jahressteuer des E-Autos, sobald die Steuerbefreiung endet. Ab-Monat 'YYYY-MM';
    ohne Angabe ab dem laufenden Monat (nicht rueckwirkend auf alle Daten)."""
    v = parse_de(betrag, tausender=True)
    if v is None or v < 0:
        return RedirectResponse("../steuer", status_code=303)
    ab = ab.strip()[:7]
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", ab):
        ab = datetime.now().strftime("%Y-%m")
    db.set_einstellung("kfz_steuer_eauto", v)
    db.set_einstellung("kfz_steuer_eauto_ab", ab if v > 0 else "")
    return RedirectResponse("../steuer", status_code=303)


@app.post("/steuer/thg")
@mit_fahrzeug
def steuer_thg_add(datum: str = Form(...), betrag: str = Form(...),
                   anbieter: str = Form(""), notiz: str = Form("")):
    v = parse_de(betrag, tausender=True)
    if v is not None and v > 0:
        db.add_thg(datum, v, anbieter or "Sonstige", notiz)
    return RedirectResponse("../steuer", status_code=303)


@app.post("/steuer/thg/delete")
def steuer_thg_delete(id: int = Form(...)):
    db.delete_thg(id)
    return RedirectResponse("../../steuer", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Instandhaltung
# ─────────────────────────────────────────────────────────────

@app.get("/instandhaltung", response_class=HTMLResponse)
def instandhaltung(request: Request):
    return render(request, "instandhaltung.html", d=unterhalt.instandhaltung_daten(),
                  kategorien=unterhalt.KATEGORIEN, aktiv="instandhaltung",
                  heute=datetime.now().strftime("%Y-%m-%d"))


def _instandhaltung_werte(form) -> dict | None:
    """Formularfelder -> DB-Werte; None, wenn Datum, Kategorie oder Betrag fehlen."""
    werte = {k: (str(form.get(k) or "").strip() or None)
             for k in ("datum", "kategorie", "beschreibung", "werkstatt", "notiz")}
    werte["km_stand"] = parse_de(form.get("km_stand"), tausender=True)
    werte["betrag"] = parse_de(form.get("betrag"), tausender=True)
    if not werte["datum"] or not werte["kategorie"] or werte["betrag"] is None:
        return None
    return werte


@app.post("/instandhaltung")
@mit_fahrzeug
async def instandhaltung_add(request: Request):
    werte = _instandhaltung_werte(await request.form())
    if werte:
        db.add_instandhaltung(werte)
    return RedirectResponse("instandhaltung", status_code=303)


@app.post("/instandhaltung/update")
@mit_fahrzeug
async def instandhaltung_update(request: Request):
    form = await request.form()
    werte = _instandhaltung_werte(form)
    if werte is None:
        return JSONResponse({"error": _("Datum, Kategorie und Betrag sind Pflicht.")},
                            status_code=400)
    if form.get("fahrzeug_id"):          # Fahrzeugauswahl: Eintrag ggf. umhaengen
        werte["fahrzeug_id"] = db.aktuelles_fahrzeug()
    db.update_instandhaltung(int(form["id"]), werte)
    return {"ok": True}


@app.post("/instandhaltung/delete")
def instandhaltung_delete(id: int = Form(...)):
    db.delete_instandhaltung(id)
    return RedirectResponse("../instandhaltung", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Versicherung
# ─────────────────────────────────────────────────────────────

@app.get("/versicherung", response_class=HTMLResponse)
def versicherung(request: Request):
    return render(request, "versicherung.html", d=unterhalt.versicherung_daten(),
                  deckungen=unterhalt.DECKUNGEN, zusatz=unterhalt.ZUSATZ,
                  fahrzeug_name=db.get_einstellung_str("fahrzeug_name") or "",
                  aktiv="versicherung", heute=datetime.now().strftime("%Y-%m-%d"))


def _versicherung_werte(form) -> dict | None:
    """Formularfelder -> DB-Werte; None, wenn Pflichtangaben fehlen.
    Zusatzbausteine: leer = nicht gebucht, 0 = inklusive, negativ = Rabatt."""
    werte = {k: (str(form.get(k) or "").strip() or None)
             for k in ("fahrzeug", "gesellschaft", "tarif_name", "gueltig_ab", "gueltig_bis",
                       "deckung", "sf_haftpflicht", "sf_kasko", "notiz")}
    for k in ("jahreslaufleistung", "sb_teilkasko", "sb_vollkasko", "grundbeitrag",
              *(k for k, _ in unterhalt.ZUSATZ)):
        werte[k] = parse_de(form.get(k), tausender=True)   # km und Euro-Betraege
    if (not werte["fahrzeug"] or not werte["gesellschaft"] or not werte["gueltig_ab"]
            or not werte["deckung"] or werte["grundbeitrag"] is None):
        return None
    return werte


@app.post("/versicherung")
@mit_fahrzeug
async def versicherung_add(request: Request):
    werte = _versicherung_werte(await request.form())
    if werte:
        db.add_versicherung(werte)
    return RedirectResponse("versicherung", status_code=303)


@app.post("/versicherung/update")
@mit_fahrzeug
async def versicherung_update(request: Request):
    form = await request.form()
    werte = _versicherung_werte(form)
    if werte is None:
        return JSONResponse({"error": _("Fahrzeug, Gesellschaft, gültig ab, Deckung und "
                                        "Grundbeitrag sind Pflicht.")}, status_code=400)
    if form.get("fahrzeug_id"):          # Fahrzeugauswahl: Vertrag ggf. umhaengen
        werte["fahrzeug_id"] = db.aktuelles_fahrzeug()
    db.update_versicherung(int(form["id"]), werte)
    return {"ok": True}


@app.post("/versicherung/delete")
def versicherung_delete(id: int = Form(...)):
    db.delete_versicherung(id)
    return RedirectResponse("../versicherung", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Import aus HA oder einer Datenbank (InfluxDB, PostgreSQL, Prometheus)
# ─────────────────────────────────────────────────────────────

_import_jobs: dict = {}   # job_id -> {"progress", "total", "rows", "done", "fehler"}


def _monat_liste(von_y, von_m, bis_y, bis_m):
    result, y, m = [], von_y, von_m
    while (y, m) <= (bis_y, bis_m):
        result.append((y, m))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return result


HA_API = "HA-API"
# Monatswerte des Imports; "kosten" (EUR fuer "Netz ins Auto") ist optional
IMPORT_WERTE = ("km", "pv", "wallbox", "kosten", "benzin")


def _fetch_monat(client, quelle, cfg, year, month, nur=None):
    """Holt alle Werte eines Monats: zuerst aus der eingestellten Datenbank
    (datenquellen.py), was dort fehlt aus der HA-API.
    Unter "_quelle" steht je Wert, woher er kam (Name der Datenbank, HA_API oder None),
    unter "_grund", warum die Datenbank nichts geliefert hat (nur wenn eine gewaehlt ist),
    unter "_reset", wann ein Zaehler-Reset verrechnet wurde (siehe zaehler.py)."""
    out = {"_quelle": {}, "_grund": {}, "_reset": {}}

    def ha_ids(feld):
        # Mehrere Entity-IDs mit "|" moeglich (umbenannter Sensor) – aktuelle zuerst probieren
        return list(reversed(datenquellen.namen_liste(cfg.get(feld))))

    def erster_wert(ids, abruf):
        for eid in ids:
            v = abruf(eid)
            if v is not None:
                return v
        return None

    def ha(key):
        if not client:
            return None
        try:
            if key == "km":
                return erster_wert(ha_ids("ha_odometer"),
                                   lambda e: client.get_month_delta(e, year, month))
            if key == "pv":
                # kWh-/Kostenzaehler koennen zurueckgesetzt werden (siehe zaehler.py)
                def pv(e):
                    v = client.get_month_sum_from_daily(e, year, month, reset_erkennen=True)
                    return v if v is not None else client.get_month_delta(e, year, month, True)
                return erster_wert(ha_ids("ha_pv_production"), pv)
            if key == "wallbox":
                return erster_wert(ha_ids("ha_wallbox_energy"),
                                   lambda e: client.get_month_delta(e, year, month, True))
            if key == "kosten":
                # Nur mit Stand vor dem Monat – sonst passen Kosten und kWh nicht zusammen
                return erster_wert(ha_ids("ha_wallbox_cost"),
                                   lambda e: client.get_month_value_stats(
                                       e, year, month, "delta", braucht_vorwert=True,
                                       reset_erkennen=True))
            if key == "benzin":
                ids = ha_ids("ha_tankerkoenig") + ha_ids("ha_tankerkoenig_2")
                return client.get_month_avg_multi(ids, year, month) if ids else None
        except Exception:
            return None
        return None

    for key in nur or IMPORT_WERTE:
        if key == "kosten" and not (cfg.get("ha_wallbox_cost") or cfg.get("fn_wallbox_cost")):
            out[key] = None             # optional – ohne Sensor kein Hinweis
            out["_quelle"][key] = None
            continue
        val = quelle.monatswert(key, year, month) if quelle else None
        herkunft = quelle.name if val is not None else None
        if val is None:
            if quelle is not None:
                kurz = quelle.grund.get(key, "keine Werte")
                out["_grund"][key] = {"kurz": kurz, "lang": f"{quelle.name}: {kurz} "
                                                            f"({quelle.beschreibung(key)})"}
            if client:
                client.letzter_reset = None
            val = ha(key)
            herkunft = HA_API if val is not None else None
            if val is not None and client and client.letzter_reset is not None:
                out["_reset"][key] = client.letzter_reset
        elif getattr(quelle, "reset_bei", {}).get(key) is not None:
            # val kommt aus der Datenbank (quelle ist hier gesetzt)
            out["_reset"][key] = quelle.reset_bei[key]
        if key == "km" and cfg.get("km_bei_kauf") and cfg.get("kauf_monat") == f"{year}-{month:02d}":
            val, herkunft = _km_kaufmonat(client, quelle, cfg, year, month, val, herkunft)
            if quelle is not None and herkunft == quelle.name:
                out["_grund"].pop(key, None)
        out[key] = round(val, 3) if val is not None else None
        out["_quelle"][key] = herkunft
    return out


def _km_kaufmonat(client, quelle, cfg, year, month, val, herkunft):
    """km im Kaufmonat: Kilometerstand am Monatsende minus km-Stand bei Kauf. Die
    Differenz zum Vormonat fehlt dort oft (Sensor erst seit dem Kauf in HA) oder
    enthielte die km des Vorbesitzers. Ohne Stand am Monatsende bleibt der Wert."""
    stand = quelle.monat_stand("km", year, month) if quelle else None
    if stand is not None:
        herkunft = quelle.name
    elif client:
        for eid in reversed(datenquellen.namen_liste(cfg.get("ha_odometer"))):
            try:
                stand = client.get_month_end_state(eid, year, month)
            except Exception:
                stand = None
            if stand is not None:
                herkunft = HA_API
                break
    if stand is None or stand < cfg["km_bei_kauf"]:
        return val, herkunft
    return stand - cfg["km_bei_kauf"], herkunft


def _import_worker(job_id, monate, cfg):
    job = _import_jobs[job_id]
    verbindung = _ha_verbindung(cfg)
    client = HAClient(**verbindung) if verbindung else None
    quelle = None
    try:
        quelle = datenquellen.aus_einstellungen(cfg)
    except Exception as e:
        job["fehler"].append(str(e))
    job["quelle"] = (f"{quelle.name}, fehlende Werte aus der HA-API" if quelle
                     else "Home Assistant API")
    try:
        for i, (y, m) in enumerate(monate):
            werte = _fetch_monat(client, quelle, cfg, y, m)
            job["rows"].append({"monat": f"{y}-{m:02d}",
                                "label": f"{monatsname(m)[:3]} {y}", **werte})
            job["progress"] = i + 1
    except Exception as e:
        job["fehler"].append(str(e))
    finally:
        job["done"] = True


@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    cfg = db.get_ha_settings()
    now = datetime.now()
    return render(request, "import.html", cfg=cfg, aktiv="import",
                  quelle_name=datenquellen.QUELLEN.get(cfg.get("datasource")),
                  mit_kosten=bool(cfg.get("ha_wallbox_cost") or cfg.get("fn_wallbox_cost")),
                  mail=db.get_mail_settings(),
                  jahre=list(range(2023, now.year + 2)), jahr=now.year,
                  monat=now.month)


@app.post("/api/import/start")
@mit_fahrzeug
def import_start(von_monat: int = Form(...), von_jahr: int = Form(...),
                 bis_monat: int = Form(...), bis_jahr: int = Form(...)):
    if (von_jahr, von_monat) > (bis_jahr, bis_monat):
        return JSONResponse({"error": _("Von muss vor Bis liegen.")}, status_code=400)
    # Sensoren des gewaehlten Fahrzeugs (eigene Ladezaehler, wenn so eingestellt) –
    # der Abruf laeuft in einem eigenen Thread und bekommt sie fertig mit
    cfg = db.get_ha_settings(eigene_zaehler=db.mehrere_fahrzeuge()
                             and db.heimladung_modus() == "eigen")
    if not _ha_verbindung(cfg) and cfg.get("datasource") not in datenquellen.QUELLEN:
        return JSONResponse({"error": _("Keine Datenquelle konfiguriert.")}, status_code=400)
    monate = _monat_liste(von_jahr, von_monat, bis_jahr, bis_monat)
    job_id = uuid.uuid4().hex[:12]
    _import_jobs[job_id] = {"progress": 0, "total": len(monate),
                            "rows": [], "done": False, "fehler": []}
    threading.Thread(target=_import_worker, args=(job_id, monate, cfg),
                     daemon=True).start()
    return {"job_id": job_id, "total": len(monate)}


@app.get("/api/import/status/{job_id}")
def import_status(job_id: str):
    job = _import_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": _("unbekannter Job")}, status_code=404)
    return job


@app.post("/api/import/apply")
def import_apply(payload: dict):
    with _json_fahrzeug(payload):
        return _import_apply(payload)


def _json_fahrzeug(payload: dict):
    """Kontext fuer JSON-Endpunkte: payload["fahrzeug_id"] waehlt das Fahrzeug."""
    from contextlib import nullcontext
    fid = _fahrzeug_wert(payload.get("fahrzeug_id"))
    if isinstance(fid, int) and fid in [f["id"] for f in db.fahrzeuge(alle=True)]:
        return db.fahrzeug_kontext(fid)
    return nullcontext()


def _wallbox_quelle():
    """Stundenwerte-Abruf der gemeinsamen Wallbox mit den aktuellen Einstellungen."""
    cfg = db.get_ha_settings(db.hauptfahrzeug())
    verbindung = _ha_verbindung(cfg)
    client = HAClient(**verbindung) if verbindung else None
    try:
        dq = datenquellen.aus_einstellungen(cfg)
    except Exception:
        dq = None
    return _wallbox_stundenwerte(client, dq, cfg)


def _import_apply(payload: dict):
    """Schreibt die (ggf. editierten) Vorschauzeilen in die DB."""
    rows = payload.get("rows", [])
    pv_ct = db.get_einstellung("pv_preis_ct") or 13.0
    tarife = db.get_stromtarife()
    log = []
    for r in rows:
        monat = r.get("monat", "")
        if not monat:
            continue
        # Herkunft je Wert aus der Vorschau (Datenbank, HA-API oder "von Hand")
        herkunft = r.get("_quelle") or {}

        def mit_quelle(text, key):
            return f"{text} ({herkunft[key]})" if herkunft.get(key) else text

        # Netzbezug mit dem Tarif bewerten, der in diesem Monat galt – nicht dem heutigen
        netz_ct = berechnung.netzpreis_monat(monat, tarife)
        teile = []
        km = parse_de(str(r.get("km") or ""))
        if km is not None and km > 0:
            db.set_fahrt_monat(monat, round(km, 1))
            teile.append(mit_quelle(f"{km:.0f} km", "km"))
        benzin = parse_de(str(r.get("benzin") or ""))
        if benzin is not None and benzin > 0:
            db.set_benzinpreis(monat, round(benzin, 3))
            teile.append(mit_quelle(f"{benzin:.3f} €/L", "benzin"))
        kosten = parse_de(str(r.get("kosten") or ""))
        # Ladezaehler: bei mehreren Fahrzeugen mit gemeinsamer Wallbox nach km verteilt
        # (bzw. ueber den Akkustand, Modus "akku")
        fid = db.schreib_fahrzeug()
        ids = heimladung.gruppe(fid)
        akku = {}
        if len(ids) > 1 and any(db.heimladung_modus(i) == "akku" for i in ids):
            akku, hinweis = heimladung.akku_anteile(monat, ids, _wallbox_quelle())
            if hinweis:
                teile.append(hinweis)
        for key, anbieter, ct in [("pv", "Privat – PV", pv_ct),
                                  ("wallbox", "Privat – Netzbezug", netz_ct)]:
            kwh = parse_de(str(r.get(key) or ""))
            if kwh is not None and kwh > 0:
                # Einzelladungen aus HA abziehen, nur der Rest wird Monatssumme
                for ziel, summe in heimladung.verteilen(monat, anbieter, kwh, kosten, ct, ids,
                                                        akku=akku.get(key)):
                    if not summe["kwh"]:
                        teile.append(mit_quelle(f"{key} {kwh:.1f} kWh", key) + summe["text"])
                        continue
                    # Ersetzt die Monatssumme beider Importe – sonst zaehlt der Monat doppelt.
                    # Ein von Hand geaenderter Wert wird markiert: der naechtliche Abruf laesst ihn.
                    hand = f" · {db.VON_HAND}" if herkunft.get(key) == "von Hand" else ""
                    ergebnis = db.upsert_monatssumme(
                        f"{monat}-01", summe["kwh"], summe["ct"], summe["gesamt"], anbieter,
                        f"{db.IMPORT_NOTIZ}{monat}{summe['zusatz']}{hand}", fahrzeug_id=ziel)
                    teile.append(mit_quelle(f"{key} {kwh:.1f} kWh", key) + summe["text"]
                                 + ("" if ergebnis == "neu" else f" – {ergebnis}"))
        if teile:
            log.append(f"{monat}: " + ", ".join(teile))
    kopf = f"Zeitraum-Import übernommen ({len(log)} Monat(e))"
    if payload.get("quelle"):
        kopf += f" · Quelle: {payload['quelle']}"
    _log_import([kopf] + log, trenner=True)
    return {"log": log}


@app.post("/api/test/ha")
def test_ha():
    cfg = db.get_ha_settings()
    verbindung = _ha_verbindung(cfg)
    if not verbindung:
        return {"ok": False, "text": _("URL oder Token fehlt")}
    ok = HAClient(**verbindung).test_connection()
    return {"ok": ok, "text": _("Verbunden") if ok else _("Keine Verbindung")}


@app.post("/api/test/{typ}")
def test_datenquelle(typ: str):
    """Verbindungstest einer Datenbank mit den gespeicherten Einstellungen –
    unabhaengig davon, welche Datenquelle gerade ausgewaehlt ist."""
    typ = {"influx": "influxdb"}.get(typ, typ)       # alter Name des Knopfs
    if typ not in datenquellen.QUELLEN:
        return JSONResponse({"ok": False, "text": "Unbekannte Datenquelle"}, status_code=404)
    try:
        ok, text = datenquellen.aus_einstellungen({**db.get_ha_settings(), "datasource": typ}).test()
    except Exception as e:
        ok, text = False, str(e)
    return {"ok": ok, "text": text}


@app.get("/api/datenbank/suche")
def datenbank_suche(q: str = ""):
    """Sucht Sensoren in der eingestellten Datenbank (gespeicherte Verbindungsdaten).
    spalte: "entity" -> Treffer gehoert in die Entity-ID-Spalte, "name" -> in die
    InfluxDB-Namensspalte."""
    try:
        dq = datenquellen.aus_einstellungen(db.get_ha_settings())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if dq is None:
        return JSONResponse({"error": _("Keine Datenbank als Datenquelle gewählt und gespeichert.")},
                            status_code=400)
    try:
        treffer = dq.suche(q)
    except Exception as e:
        return JSONResponse({"error": dq.fehlertext(e)}, status_code=400)

    def monat(t):
        return t.astimezone().strftime("%m/%Y") if t else None
    return {"quelle": dq.name, "spalte": "entity" if dq.nutzt_entity_ids else "name",
            "treffer": [{**t, "von": monat(t["von"]), "bis": monat(t["bis"])} for t in treffer]}


# ─────────────────────────────────────────────────────────────
#  Sensor-Suche und -Diagnose
# ─────────────────────────────────────────────────────────────

def _ha_client():
    verbindung = _ha_verbindung(db.get_ha_settings())
    return HAClient(**verbindung) if verbindung else None


@app.get("/api/entities")
def entities_suchen(q: str = ""):
    """Sucht Entities in Home Assistant nach Namensbestandteil."""
    client = _ha_client()
    if client is None:
        return JSONResponse({"error": _("HA nicht konfiguriert.")}, status_code=400)
    try:
        alle = client._get("/api/states")
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    begriffe = [t for t in q.lower().split() if t]
    treffer = []
    for st in alle or []:
        eid = st.get("entity_id", "")
        attr = st.get("attributes", {})
        name = attr.get("friendly_name", "")
        heu = f"{eid} {name}".lower()
        if begriffe and not all(t in heu for t in begriffe):
            continue
        treffer.append({
            "entity_id": eid,
            "name": name,
            "state": st.get("state"),
            "einheit": attr.get("unit_of_measurement", ""),
            "klasse": attr.get("state_class", ""),
        })
    treffer.sort(key=lambda t: t["entity_id"])
    return {"anzahl": len(treffer), "treffer": treffer[:60]}


# Welche Spalte der Diagnose der Import fuer eine Sensorzeile nutzt (siehe _fetch_monat);
# "" = keine (Akkustand: nur Stundenwerte fuer Ladeerkennung und Akkuverbrauch)
DIAGNOSE_SPALTE = {"ha_odometer": "delta", "ha_wallbox_energy": "delta", "ha_wallbox_cost": "delta",
                   "ha_pv_production": "summe", "ha_tankerkoenig": "mittel",
                   "ha_tankerkoenig_2": "mittel", "ha_ev_battery": ""}


def _diagnose_spalte(zeile, einheit: str):
    """Genutzte Spalte: aus der Sensorzeile, in der der Sensor eingetragen ist, sonst aus
    der Einheit geraten. None = unbekannt (dann wird nichts ausgegraut)."""
    if zeile in DIAGNOSE_SPALTE:
        return DIAGNOSE_SPALTE[zeile]
    e = (einheit or "").strip().lower()
    if "/l" in e:
        return "mittel"
    if e in ("km", "kwh", "wh", "€", "eur"):
        return "delta"
    if e == "%":
        return ""
    return None


@app.get("/api/diagnose")
def sensor_diagnose(entity: str, jahr: int = 0, monat: int = 0):
    """Prueft einen Sensor: aktueller Wert + Monatswerte der letzten 3 Monate."""
    client = _ha_client()
    if client is None:
        return JSONResponse({"error": _("HA nicht konfiguriert.")}, status_code=400)
    if not entity.strip():
        return JSONResponse({"error": _("Keine Entity angegeben.")}, status_code=400)

    ergebnis = {"entity": entity, "state": None, "einheit": "", "monate": []}
    try:
        st = client._get(f"/api/states/{entity}")
        ergebnis["state"] = st.get("state")
        ergebnis["einheit"] = st.get("attributes", {}).get("unit_of_measurement", "")
        ergebnis["name"] = st.get("attributes", {}).get("friendly_name", "")
        attr = st.get("attributes", {})
    except Exception as e:
        return JSONResponse({"error": _("Entity nicht gefunden: {0}", e)}, status_code=400)

    cfg = db.get_ha_settings()
    zeile = next((h for h, _f, _l in SENSOR_FELDER
                  if entity in datenquellen.namen_liste(cfg.get(h))), None)
    ergebnis["zeile"] = _sensor_label(next(l for h, _f, l in SENSOR_FELDER if h == zeile)) if zeile else ""
    ergebnis["genutzt"] = _diagnose_spalte(zeile, ergebnis["einheit"])
    ergebnis["state_class"] = attr.get("state_class", "")
    # Resets erkennen wie beim Import – nur der Kilometerstand ist immer fortlaufend
    reset_erkennen = zeile != "ha_odometer" and ergebnis["einheit"].strip().lower() != "km"
    jetzt = datetime.now()
    j, m = (jahr or jetzt.year), (monat or jetzt.month)
    for _i in range(3):
        delta = client.get_month_delta(entity, j, m, reset_erkennen)
        reset = client.letzter_reset if delta is not None else None
        verworfen = client.sum_verworfen if delta is not None else None
        summe = client.get_month_sum_from_daily(entity, j, m, reset_erkennen)
        mittel = client.get_month_avg(entity, j, m)
        ergebnis["monate"].append({
            "monat": f"{monatsname(m)[:3]} {j}",
            "delta": delta, "summe": summe, "mittel": mittel,
            "reset": _reset_text(reset) if reset is not None else None,
            "ha_sum": verworfen,
        })
        m -= 1
        if m < 1:
            m, j = 12, j - 1
    return ergebnis


# ─────────────────────────────────────────────────────────────
#  Rechnungsimport (PDF / Text)
# ─────────────────────────────────────────────────────────────

@app.get("/rechnung", response_class=HTMLResponse)
def rechnung(request: Request):
    return render(request, "rechnung.html", aktiv="rechnung")


@app.post("/api/rechnung/parse")
async def rechnung_parse(pdf: UploadFile | None = File(None),
                         text: str = Form("")):
    try:
        if pdf is not None and pdf.filename:
            inhalt = await pdf.read()
            if len(inhalt) > 20 * 1024 * 1024:
                return JSONResponse({"error": _("PDF zu groß (max. 20 MB).")}, status_code=400)
            tmp = os.path.join(STATIC_DIR, f"_upload_{uuid.uuid4().hex}.pdf")
            with open(tmp, "wb") as f:
                f.write(inhalt)
            try:
                anbieter, vorgaenge, hinweise = auswerten_pdf(tmp)
            finally:
                os.remove(tmp)
        elif text.strip():
            anbieter, vorgaenge, hinweise = auswerten_text(text)
        else:
            return JSONResponse({"error": _("Keine PDF und kein Text.")}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    for v in vorgaenge:
        if not v.datum:
            continue
        if v.menge_kwh and db.ladevorgang_exists(v.datum, v.menge_kwh, v.anbieter):
            v.warnungen.append(_("Bereits importiert – wird beim Übernehmen übersprungen"))
        elif not v.menge_kwh:
            # Ohne kWh (Tesla nach Minuten): Duplikat am Betrag erkennen
            if any(l["anbieter"] == v.anbieter and abs((l["gesamtpreis"] or 0) - v.gesamtpreis) < 0.005
                   for l in db.get_ladevorgaenge_zeitraum(v.datum, v.datum)):
                v.warnungen.append(_("Bereits importiert – gleicher Betrag am selben Tag"))
            else:
                _kwh_aus_akkustand(v)
    return {"anbieter": anbieter, "hinweise": hinweise,
            "vorgaenge": [{"datum": v.datum, "kwh": v.menge_kwh or None,
                           "ct": v.preis_kwh or None, "gesamt": v.gesamtpreis,
                           "anbieter": v.anbieter, "kw": v.ladeleistung_kw,
                           "ladetyp": v.ladetyp, "notiz": v.notiz,
                           "warnungen": v.warnungen}
                          for v in vorgaenge]}


def _kwh_aus_akkustand(v):
    """Rechnung ohne kWh: die kWh einer noch nicht erfassten Ladung aus dem
    Akkustand (HA) am selben Tag vorschlagen – Schaetzung, der Nutzer prueft."""
    try:
        ergebnis = ladeerkennung.pruefe_monat(int(v.datum[:4]), int(v.datum[5:7]))
    except Exception:
        return
    passend = [l for l in ergebnis.get("fehlend", [])
               if ladeerkennung._tage_abstand(l["datum"], v.datum) <= ladeerkennung.TOLERANZ_TAGE]
    if not passend:
        return
    l = max(passend, key=lambda l: l.get("leistung_kw") or 0)
    v.menge_kwh = l["kwh"]
    v.warnungen = [w for w in v.warnungen if w != ohne_kwh_text()]
    v.warnungen.append(_("kWh aus dem Akkustand geschätzt ({0} → {1} %, {2}) – bitte mit der Fahrzeug-App "
                         "vergleichen", f"{l['von_prozent']:g}".replace(".", ","),
                         f"{l['bis_prozent']:g}".replace(".", ","), l["datum"]))


@app.post("/api/rechnung/apply")
def rechnung_apply(payload: dict):
    with _json_fahrzeug(payload):
        return _rechnung_apply(payload)


def _rechnung_apply(payload: dict):
    rows = payload.get("rows", [])
    log, fehler = [], []
    for i, r in enumerate(rows):
        datum = (r.get("datum") or "").strip()
        kwh = parse_de(str(r.get("kwh") or ""))
        gesamt = parse_de(str(r.get("gesamt") or ""))
        ct = parse_de(str(r.get("ct") or ""))
        anbieter = (r.get("anbieter") or "").strip()
        if not datum or not anbieter or kwh is None or kwh <= 0 or gesamt is None:
            fehler.append(_("Zeile {0}: unvollständig/ungültig", i + 1))
            continue
        if ct is None and kwh:
            ct = round(gesamt / kwh * 100, 2)
        if db.ladevorgang_exists(datum, round(kwh, 3), anbieter):
            log.append(_("{0}: bereits vorhanden – übersprungen", datum))
            continue
        # Neuer Anbieter aus der Rechnung soll auch in der Anbieterauswahl stehen
        if anbieter != "Unbekannt":
            db.add_lade_anbieter(anbieter)
        db.add_ladevorgang(datum, round(kwh, 3), round(ct or 0, 2),
                           round(gesamt, 2), anbieter,
                           parse_de(str(r.get("kw") or "")),
                           r.get("ladetyp") or "AC",
                           r.get("notiz") or "Rechnungsimport")
        log.append(f"{datum}: {kwh:.2f} kWh · {gesamt:.2f} € ({anbieter})")
    return {"log": log, "fehler": fehler}


# ─────────────────────────────────────────────────────────────
#  Einstellungen als Datei sichern / laden
# ─────────────────────────────────────────────────────────────

GEHEIM_KEYS = diagnose.GEHEIM


@app.get("/api/settings/export")
def settings_export(secrets: int = 1):
    """Exportiert alle Einstellungen + Anbieter als JSON-Datei."""
    import json
    werte = db.get_alle_einstellungen()
    if not secrets:
        werte = {k: v for k, v in werte.items() if k.split("@", 1)[0] not in GEHEIM_KEYS}

    daten = {
        "typ": "ev-tracker-einstellungen",
        "version": 1,
        "exportiert": datetime.now().isoformat(timespec="seconds"),
        "enthaelt_zugangsdaten": bool(secrets),
        "einstellungen": werte,
        "lade_anbieter": [
            {"name": a["name"], "gruenstrom": a["gruenstrom"],
             "ist_system": a["ist_system"]}
            for a in db.get_lade_anbieter()
        ],
        "fahrzeuge": db.get_fahrzeug_liste_roh(),
    }
    pfad = os.path.join(STATIC_DIR, f"_settings_{uuid.uuid4().hex}.json")
    with open(pfad, "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=2, ensure_ascii=False)

    stamp = datetime.now().strftime("%Y-%m-%d")
    return FileResponse(pfad, filename=f"ev_tracker_einstellungen_{stamp}.json",
                        media_type="application/json",
                        background=BackgroundTask(os.remove, pfad))


@app.post("/api/settings/import")
async def settings_import(datei: UploadFile = File(...)):
    """Liest eine zuvor exportierte JSON-Datei ein."""
    import json
    inhalt = await datei.read()
    if len(inhalt) > 2 * 1024 * 1024:
        return JSONResponse({"error": _("Datei zu groß (max. 2 MB).")}, status_code=400)
    try:
        daten = json.loads(inhalt.decode("utf-8"))
    except Exception as e:
        return JSONResponse({"error": _("Datei nicht lesbar: {0}", e)}, status_code=400)

    if daten.get("typ") != "ev-tracker-einstellungen":
        return JSONResponse(
            {"error": _("Das ist keine EV-Tracker-Einstellungsdatei.")}, status_code=400)

    werte = daten.get("einstellungen") or {}
    if not isinstance(werte, dict) or not werte:
        return JSONResponse({"error": _("Keine Einstellungen in der Datei.")},
                            status_code=400)

    # Leere Zugangsdaten nicht über vorhandene schreiben
    vorhanden = db.get_alle_einstellungen()
    werte = {k: v for k, v in werte.items()
             if not (k in GEHEIM_KEYS and not str(v).strip() and vorhanden.get(k))
             and k not in db.NICHT_IMPORTIEREN}
    # Mehrere Fahrzeuge aus der Datei: Tabellen vorher umbauen (mit Sicherung) – sonst
    # bleibt es bei einem Fahrzeug
    if str(werte.get("mehrere_fahrzeuge")) == "1" and db.schema_stand() < 3:
        _sicherungskopie("vor_mehrere_fahrzeuge")
        try:
            db.struktur_mehrere_fahrzeuge()
        except Exception:
            werte["mehrere_fahrzeuge"] = "0"
    db.set_einstellungen(werte)
    db.set_fahrzeug_liste_roh(daten.get("fahrzeuge"))

    neue_anbieter = 0
    bekannt = {a["name"] for a in db.get_lade_anbieter()}
    for a in daten.get("lade_anbieter") or []:
        name = (a.get("name") or "").strip()
        if name and name not in bekannt:
            db.add_lade_anbieter(name, 1 if a.get("gruenstrom") else 0)
            neue_anbieter += 1

    return {"anzahl": len(werte), "anbieter": neue_anbieter,
            "exportiert": daten.get("exportiert", "?")}


# ─────────────────────────────────────────────────────────────
#  Berichte (Monat / Jahr) und Mailversand
# ─────────────────────────────────────────────────────────────

def _bericht_bauen(typ: str, jahr: int, monat: int) -> dict:
    return (berichte.jahresbericht(jahr) if typ == "jahr"
            else berichte.monatsbericht(jahr, monat))


@app.get("/berichte", response_class=HTMLResponse)
def berichte_seite(request: Request):
    jetzt = datetime.now()
    # Voreinstellung: der zuletzt abgeschlossene Monat
    v_jahr, v_monat = (jetzt.year, jetzt.month - 1) if jetzt.month > 1         else (jetzt.year - 1, 12)
    return render(request, "berichte.html", aktiv="berichte",
                  mail=db.get_mail_settings(),
                  jahre=list(range(2023, jetzt.year + 1)),
                  jahr=v_jahr, monat=v_monat)


def _monat_pruefen(jahr: int, monat: int) -> dict:
    """Ist der Monat abschlussreif? Prueft Datenbestand und offene Ladevorgaenge.
    Gesamtsicht mehrerer Fahrzeuge: jedes Fahrzeug fuer sich (eigener Akkustand)."""
    if db.aktuelles_fahrzeug() is None:
        je = []
        for fz in db.fahrzeuge():
            with db.fahrzeug_kontext(fz["id"]):
                je.append((fz, _monat_pruefen(jahr, monat)))
        offen = [f"{fz['name']}: {o}" for fz, p in je for o in p["offen"]]
        erst = je[0][1]
        return {"monat": erst["monat"], "bereit": not offen, "offen": offen,
                "ladeerkennung": erst["ladeerkennung"],
                "km": sum(p["km"] or 0 for _f, p in je),
                "ladevorgaenge": sum(p["ladevorgaenge"] for _f, p in je),
                "je_fahrzeug": [{"name": fz["name"], **p} for fz, p in je]}
    import calendar
    schluessel = f"{jahr}-{monat:02d}"
    letzter = calendar.monthrange(jahr, monat)[1]

    fahrten = {f["monat"]: f["km"] for f in db.get_fahrten_monate()}
    preise = {b["monat"] for b in db.get_benzinpreise()}
    lade = berechnung.nur_ladungen(
        berechnung.ladevorgaenge(f"{schluessel}-01", f"{schluessel}-{letzter:02d}"))

    offen = []
    if not fahrten.get(schluessel):
        offen.append(_("Gefahrene Kilometer fehlen"))
    if schluessel not in preise:
        offen.append(_("{0}preis fehlt", berechnung.kraftstoff()['name']))
    if not lade:
        offen.append(_("Keine Ladevorgänge erfasst"))

    # Auswärts geladen, aber kein Beleg erfasst?
    ladung = ladeerkennung.pruefe_monat(jahr, monat)
    if ladung["status"] == "fehlend":
        offen.append(ladung["meldung"])

    return {"monat": schluessel, "bereit": not offen, "offen": offen,
            "ladeerkennung": ladung,
            "km": fahrten.get(schluessel), "ladevorgaenge": berechnung.anzahl_ladungen(lade)}


@app.get("/api/bericht/pruefung")
def bericht_pruefung(jahr: int = 0, monat: int = 0):
    jetzt = datetime.now()
    return _monat_pruefen(jahr or jetzt.year, monat or jetzt.month)


@app.get("/api/bericht/vorschau", response_class=HTMLResponse)
def bericht_vorschau(typ: str = "monat", jahr: int = 0, monat: int = 0):
    jetzt = datetime.now()
    bericht = _bericht_bauen(typ, jahr or jetzt.year, monat or jetzt.month)
    return HTMLResponse(berichte.als_html(bericht))


@app.post("/api/bericht/senden")
def bericht_senden(typ: str = Form("monat"), jahr: int = Form(0),
                   monat: int = Form(0), empfaenger: str = Form("")):
    jetzt = datetime.now()
    bericht = _bericht_bauen(typ, jahr or jetzt.year, monat or jetzt.month)
    ok, meldung = mailer.sende_mail(
        betreff=f"EV Tracker – {bericht['titel']}",
        html=berichte.als_html(bericht),
        text=berichte.als_text(bericht),
        empfaenger=empfaenger.strip())
    return {"ok": ok, "meldung": meldung}


@app.post("/einstellungen/mail")
async def einstellungen_mail(request: Request):
    form = await request.form()
    felder = ["mail_smtp_server", "mail_smtp_port", "mail_benutzer",
              "mail_passwort", "mail_absender", "mail_empfaenger",
              "mail_uhrzeit", "bericht_max_wartetage",
              "akku_kapazitaet_kwh", "lade_min_anstieg"]
    werte = {k: str(form.get(k, "")).strip() for k in felder if k in form}
    # Leeres Passwortfeld = gespeichertes Passwort behalten
    if werte.get("mail_passwort") == "":
        werte.pop("mail_passwort", None)
    for schalter in ["mail_aktiv", "mail_monat_aktiv", "mail_jahr_aktiv",
                     "bericht_warten", "auto_import"]:
        werte[schalter] = "1" if form.get(schalter) else "0"
    db.set_einstellungen(werte)
    return RedirectResponse("../berichte", status_code=303)


# ── Zeitplan: prueft stuendlich, ob ein Bericht faellig ist ──────────────────

# ── Naechtlicher Datenabruf aus Home Assistant ──────────────────────────────

def _log_import(zeilen: list, trenner: bool = False):
    """Haengt Zeilen mit Zeitstempel an das Importprotokoll an.

    Analog zu backup.log, damit sich nachvollziehen laesst, wann der Abruf lief
    und welche Werte dabei aus Home Assistant kamen.
    """
    if not zeilen:
        return
    stempel = f"{datetime.now():%Y-%m-%d %H:%M:%S}"
    try:
        with open(IMPORT_LOG_DATEI, "a", encoding="utf-8") as f:
            if trenner:
                f.write(f"[{stempel}] " + "=" * 50 + "\n")
            for zeile in zeilen:
                f.write(f"[{stempel}] {zeile}\n")
    except Exception as e:
        print(f"[Auto-Import] Protokoll nicht schreibbar: {e}", flush=True)
        return
    _log_kuerzen()


def _log_kuerzen(grenze: int = 4000, behalten: int = 2000):
    """Haelt das Protokoll klein: ab `grenze` Zeilen bleiben die letzten `behalten`."""
    try:
        if not os.path.exists(IMPORT_LOG_DATEI):
            return
        with open(IMPORT_LOG_DATEI, encoding="utf-8", errors="replace") as f:
            alle = f.readlines()
        if len(alle) <= grenze:
            return
        with open(IMPORT_LOG_DATEI, "w", encoding="utf-8") as f:
            f.writelines(alle[-behalten:])
    except Exception:
        pass


def _rohwerte_text(werte: dict) -> str:
    """Gelesene Sensorwerte lesbar machen – '—' fuer nicht gelieferte Werte,
    dahinter in Klammern die Herkunft (Datenbank oder HA-API)."""
    namen = [("km", "km"), ("pv", "PV kWh"), ("wallbox", "Netz kWh"),
             ("kosten", "Netz €"), ("benzin", "€/L")]
    herkunft = werte.get("_quelle") or {}
    grund = werte.get("_grund") or {}
    teile = []
    for key, label in namen:
        if key == "kosten" and werte.get(key) is None and key not in grund:
            continue                    # kein Kostenzaehler eingetragen
        if werte.get(key) is not None:
            teile.append(f"{label}={werte[key]} ({herkunft.get(key)})")
        else:
            teile.append(f"{label}=—")
    text = " · ".join(teile)
    # Warum die Datenbank nichts lieferte – je Wert eine Zeile darunter
    for key, label in namen:
        if grund.get(key):
            text += f"\n      {label}: {grund[key]['lang']}"
    # Zurueckgesetzte Zaehler: Summe der Zuwaechse statt Ende minus Vormonat
    for key, label in namen:
        zeit = (werte.get("_reset") or {}).get(key)
        if zeit is not None and werte.get(key) is not None:
            text += f"\n      {label}: Zähler-Reset ({_reset_text(zeit)}) verrechnet"
    return text


def _reset_text(zeit) -> str:
    """Zeitpunkt eines Zaehler-Resets fuer Log und Diagnose (datetime, ISO-Text oder Index)."""
    if isinstance(zeit, datetime):
        return zeit.astimezone().strftime("%d.%m. %H:%M")
    try:
        return datetime.fromisoformat(str(zeit).replace("Z", "+00:00")).strftime("%d.%m. %H:%M")
    except ValueError:
        return str(zeit)


def _wallbox_stundenwerte(client, dq, cfg):
    """Stundenwerte der gemeinsamen Wallbox-Zaehler fuer die Zuordnung ueber den Akkustand:
    zuerst aus der eingestellten Datenbank, sonst aus der HA-Langzeitstatistik."""
    felder = {"wallbox": "ha_wallbox_energy", "pv": "ha_pv_production"}

    def stundenwerte(schluessel, start, ende):
        # Zurueckgesetzte Zaehler fortlaufend machen – sonst ergaebe der Reset eine
        # negative Stunde
        if dq is not None and dq.hat(schluessel):
            try:
                werte = dq.stundenwerte(schluessel, start, ende, "last")
                if werte:
                    return zaehler.fortlaufend_machen(werte)
            except Exception:
                pass
        entity = (datenquellen.namen_liste(cfg.get(felder[schluessel])) or [""])[-1]
        if client is None or not entity:
            return []
        return zaehler.fortlaufend_machen(
            akkuverbrauch._stundenwerte(client, entity, start, ende, ("state", "sum")))
    return stundenwerte


def _auto_import(monate: list | None = None, quelle: str = "automatisch") -> list:
    """Holt die aktuellen Monatswerte aus HA bzw. der eingestellten Datenbank und
    schreibt sie fort.

    Standardmaessig laufender Monat und Vormonat – so wird der Vormonat noch
    vervollstaendigt, falls spaet Daten nachkommen.
    Jeder Lauf wird in import.log protokolliert.
    """
    if db.SCHEMA_ZU_NEU:
        return ["Übersprungen: Datenbank aus einer neueren Version, nur lesbar"]
    cfg = db.get_ha_settings()
    name = datenquellen.QUELLEN.get(cfg.get("datasource"))
    quelle_text = f"{name} (Fallback HA-API)" if name else "Home Assistant API"
    _log_import([f"Abruf gestartet ({quelle}) · Quelle: {quelle_text}"], trenner=True)

    verbindung = _ha_verbindung(cfg)
    client = HAClient(**verbindung) if verbindung else None
    try:
        dq = datenquellen.aus_einstellungen(cfg)
    except Exception as e:
        _log_import([f"✗ {name} nicht nutzbar: {e}", "Abruf abgebrochen"])
        return [f"{name} nicht nutzbar: {e}"]
    if client is None and dq is None:
        _log_import(["✗ Keine Datenquelle konfiguriert", "Abruf abgebrochen"])
        return ["Keine Datenquelle konfiguriert"]

    if monate is None:
        jetzt = datetime.now()
        vorher = ((jetzt.year, jetzt.month - 1) if jetzt.month > 1
                  else (jetzt.year - 1, 12))
        monate = [vorher, (jetzt.year, jetzt.month)]

    pv_ct = db.get_einstellung("pv_preis_ct") or 13.0
    tarife = db.get_stromtarife()

    # Fahrzeuge und ihre Zaehler: bei einem Fahrzeug nur das Hauptfahrzeug mit den
    # bisherigen Einstellungen. Bei mehreren je Fahrzeug Kilometer (und eigene
    # Ladezaehler); die gemeinsame Wallbox wird einmal nach km verteilt.
    mehrere = db.mehrere_fahrzeuge()
    fahrzeuge = db.fahrzeuge() if mehrere else [{"id": db.hauptfahrzeug(), "name": ""}]
    quellen = {}
    for fz in fahrzeuge:
        eigen = mehrere and db.heimladung_modus(fz["id"]) == "eigen"
        cfg_fz = db.get_ha_settings(fz["id"], eigene_zaehler=eigen)
        try:
            dq_fz = datenquellen.aus_einstellungen(cfg_fz) if dq is not None else None
        except Exception:
            dq_fz = dq
        quellen[fz["id"]] = (cfg_fz, dq_fz, eigen)

    protokoll = []
    fehler = 0
    for jahr, monat in monate:
        schluessel = f"{jahr}-{monat:02d}"
        netz_ct = berechnung.netzpreis_monat(schluessel, tarife)
        werte_je = {}
        try:
            for fz in fahrzeuge:
                cfg_fz, dq_fz, _w = quellen[fz["id"]]
                werte_je[fz["id"]] = _fetch_monat(client, dq_fz, cfg_fz, jahr, monat)
        except Exception as e:
            fehler += 1
            _log_import([f"✗ {schluessel}: Abruf fehlgeschlagen ({e})"])
            protokoll.append(f"{schluessel}: Abruf fehlgeschlagen ({e})")
            continue

        teile = []
        for fz in fahrzeuge:
            werte = werte_je[fz["id"]]
            vor = f"{fz['name']}: " if mehrere and len(fahrzeuge) > 1 else ""
            zeilen = _rohwerte_text(werte).split("\n")
            _log_import([f"{schluessel}: {vor}gelesen {zeilen[0]}"]
                        + [f"{schluessel}:   {z.strip()}" for z in zeilen[1:]])
            if werte.get("km"):
                db.set_fahrt_monat(schluessel, round(werte["km"], 1), fahrzeug_id=fz["id"])
                teile.append(f"{vor}{werte['km']:.0f} km ({werte['_quelle']['km']})")
        erste = werte_je[fahrzeuge[0]["id"]]
        if erste.get("benzin"):
            db.set_benzinpreis(schluessel, round(erste["benzin"], 3))
            teile.append(f"{erste['benzin']:.3f} €/L ({erste['_quelle']['benzin']})")

        # Ladezaehler: je Gruppe (eigene Zaehler = ein Fahrzeug, gemeinsame Wallbox = alle
        # mit gemeinsamer Wallbox) einmal lesen und verteilen
        km_je = db.get_fahrten_je_fahrzeug()
        erledigt = set()
        for fz in fahrzeuge:
            ids = heimladung.gruppe(fz["id"]) if mehrere else [fz["id"]]
            if fz["id"] in erledigt or not ids:
                continue
            erledigt |= set(ids)
            werte = werte_je[fz["id"]]
            herkunft = werte["_quelle"]
            # Gemeinsame Wallbox mit Modus "akku": Stunden dem Auto zuordnen, dessen Akkustand stieg
            akku, hinweis = ({}, "")
            if mehrere and len(ids) > 1:
                cfg_fz, dq_fz, _w = quellen[fz["id"]]
                akku, hinweis = heimladung.akku_anteile(
                    schluessel, ids, _wallbox_stundenwerte(client, dq_fz, cfg_fz))
                if hinweis:
                    _log_import([f"{schluessel}: {hinweis}"])
            for key, anbieter, ct in [("pv", "Privat – PV", pv_ct),
                                      ("wallbox", "Privat – Netzbezug", netz_ct)]:
                kwh = werte.get(key)
                if not kwh:
                    continue
                # Einzelladungen aus HA abziehen, nur der Rest wird Monatssumme
                for fid, summe in heimladung.verteilen(schluessel, anbieter, kwh,
                                                       werte.get("kosten"), ct, ids, km_je,
                                                       akku=akku.get(key)):
                    name = next((f["name"] for f in fahrzeuge if f["id"] == fid), "")
                    vor = f"{name}: " if mehrere and len(fahrzeuge) > 1 else ""
                    if not summe["kwh"]:
                        if db.delete_auto_ladevorgang(f"{schluessel}-01", anbieter, fahrzeug_id=fid):
                            teile.append(f"{vor}{key} {kwh:.1f} kWh ({herkunft[key]}{summe['text']}, "
                                         f"Monatssumme entfernt)")
                        continue
                    ergebnis = db.upsert_auto_ladevorgang(
                        f"{schluessel}-01", summe["kwh"], summe["ct"], summe["gesamt"], anbieter,
                        db.AUTO_NOTIZ + summe["zusatz"], fahrzeug_id=fid)
                    if ergebnis == "von Hand":
                        teile.append(f"{vor}{key} {kwh:.1f} kWh ({herkunft[key]}) nicht übernommen – "
                                     f"Wert von Hand bleibt")
                    elif ergebnis != "unveraendert":
                        teile.append(f"{vor}{key} {kwh:.1f} kWh ({ergebnis}, {herkunft[key]}{summe['text']})")
        zeile = ", ".join(teile) if teile else "keine neuen Werte"
        _log_import([f"{schluessel}: übernommen {zeile}"])
        protokoll.append(f"{schluessel}: {zeile}")

    # Verbrauch aus dem Akkustand fortschreiben (Datenbank oder HA-API, wie eingestellt)
    if client is not None or dq is not None:
        for fz in fahrzeuge:
            vor = f" {fz['name']}" if mehrere and len(fahrzeuge) > 1 else ""
            try:
                with db.fahrzeug_kontext(fz["id"]):
                    meldung = akkuverbrauch.aktualisieren()
            except Exception as e:
                meldung = f"Fehler ({e})"
            _log_import([f"Akkuverbrauch{vor}: {meldung}"])
            protokoll.append(f"Akkuverbrauch{vor}: {meldung}")
            try:
                with db.fahrzeug_kontext(fz["id"]):
                    soh = akku_mod.soh_aktualisieren() if module_mod.an("akku") else ""
            except Exception as e:
                soh = f"SoH-Sensor: Fehler ({e})"
            if soh:
                _log_import([f"Akku{vor}: {soh}"])
            if module_mod.an("fahrtenbuch"):
                try:
                    with db.fahrzeug_kontext(fz["id"]):
                        meldung = fahrtenbuch_mod.aktualisieren()
                except Exception as e:
                    meldung = f"Fahrtenbuch: Fehler ({e})"
                _log_import([f"{meldung}{vor}"])
                protokoll.append(f"{meldung}{vor}")
            if module_mod.an("energie"):
                try:
                    with db.fahrzeug_kontext(fz["id"]):
                        meldung = energie_mod.aktualisieren()
                except Exception as e:
                    meldung = f"Energie: Fehler ({e})"
                if meldung:
                    _log_import([f"{meldung}{vor}"])
                    protokoll.append(f"{meldung}{vor}")

    _log_import([f"Abruf beendet – {len(monate)} Monat(e), {fehler} Fehler"])
    return protokoll


@app.post("/api/import/auto")
def auto_import_jetzt():
    """Naechtlichen Abruf manuell ausloesen."""
    protokoll = _auto_import(quelle="manuell")
    db.set_einstellung("auto_import_letzter",
                       f"{datetime.now():%Y-%m-%d %H:%M} · " + " | ".join(protokoll))
    return {"ok": True, "protokoll": protokoll}


# ── Einzelne Heimladungen aus Home Assistant (Push) ─────────────────────────

def _push_url(request: Request) -> str:
    """Adresse, unter der HA den Endpunkt erreicht. Im Add-on ueber das interne Netz
    (Hostname des Add-ons, Port 8099) – nicht ueber Ingress, das eine Anmeldung braucht."""
    if IST_ADDON:
        import socket
        host = os.environ.get("HOSTNAME") or socket.gethostname()
        return f"http://{host}:8099/api/ladung"
    return str(request.base_url).rstrip("/") + "/api/ladung"


@app.post("/api/ladung")
async def ladung_empfangen(request: Request):
    """Nimmt eine Heimladung aus HA an (Vorlage ev_ladung_senden.yaml).
    Header: Authorization: Bearer <Token aus den Einstellungen>."""
    if not heimladung.token():
        return JSONResponse({"ok": False, "error": _("Empfang ausgeschaltet – in den Einstellungen "
                                                     "unter „Ladungen aus Home Assistant“ einen "
                                                     "Token erzeugen.")}, status_code=403)
    auth = request.headers.get("authorization", "")
    if not heimladung.token_ok(auth[7:].strip() if auth.lower().startswith("bearer ") else ""):
        return JSONResponse({"ok": False, "error": _("Token fehlt oder falsch")}, status_code=401)
    try:
        daten = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": _("Kein gültiges JSON")}, status_code=400)
    try:
        ergebnis = heimladung.annehmen(daten)
    except heimladung.UngueltigeLadung as e:
        _log_import([f"✗ Ladung aus HA abgelehnt: {e} · {str(daten)[:200]}"])
        return JSONResponse({"ok": False, "error": str(e)}, status_code=422)
    _log_import([heimladung.protokoll_text(ergebnis)])
    # Die km des Monats gleich mit holen – sonst stuende die Ladung bis zum naechtlichen
    # Abruf ohne km da (Dashboard: Ersparnis des Monats unvollstaendig)
    threading.Thread(target=_km_nachziehen, args=(ergebnis["datum"][:7], ergebnis["fahrzeug"]),
                     daemon=True).start()
    return ergebnis


_km_zuletzt = {}
_km_sperre = threading.Lock()
KM_NACHZIEHEN_ABSTAND = 600     # Sekunden je Fahrzeug und Monat


def _km_nachziehen(monat: str, fid: int) -> float | None:
    """Kilometer eines Monats nach einer Ladung aus HA aktualisieren – hoechstens alle
    10 Minuten je Fahrzeug und Monat (mehrere Ladungen kurz hintereinander). Nur mit
    eingeschaltetem automatischem Abruf. Gibt die km zurueck (None = nicht gelesen)."""
    import time
    if db.SCHEMA_ZU_NEU or db.get_mail_settings().get("auto_import", "1") != "1":
        return None
    jetzt = time.monotonic()
    with _km_sperre:
        if jetzt - _km_zuletzt.get((fid, monat), -KM_NACHZIEHEN_ABSTAND) < KM_NACHZIEHEN_ABSTAND:
            return None
        _km_zuletzt[(fid, monat)] = jetzt
    try:
        cfg = db.get_ha_settings(fid)
        verbindung = _ha_verbindung(cfg)
        client = HAClient(**verbindung) if verbindung else None
        dq = datenquellen.aus_einstellungen(cfg)
        if client is None and dq is None:
            return None
        werte = _fetch_monat(client, dq, cfg, int(monat[:4]), int(monat[5:7]), nur=("km",))
        km = werte.get("km")
        if km:
            db.set_fahrt_monat(monat, round(km, 1), fahrzeug_id=fid)
            _log_import([f"{monat}: km nach Ladung aus HA aktualisiert: {km:.0f} km "
                         f"({werte['_quelle']['km']})"])
            return km
        grund = (werte["_grund"].get("km") or {}).get("lang") or "keine Werte im Monat"
        _log_import([f"{monat}: km nach Ladung aus HA nicht gelesen – {grund}"])
    except Exception as e:
        _log_import([f"{monat}: km nach Ladung aus HA nicht aktualisiert ({e})"])
    return None


@app.post("/einstellungen/push-token")
def push_token(aktion: str = Form("neu")):
    """Token fuer den Empfang erzeugen ("neu") oder den Empfang ausschalten ("aus")."""
    if aktion == "aus":
        db.set_einstellung(heimladung.TOKEN_KEY, "")
    else:
        heimladung.token_neu()
    return RedirectResponse("../einstellungen#ladung-senden", status_code=303)


@app.get("/api/import/log")
def import_log(zeilen: int = 200):
    """Letzte Zeilen des Importprotokolls (neueste zuletzt)."""
    if not os.path.exists(IMPORT_LOG_DATEI):
        return {"zeilen": [], "meldung": _("Noch kein Abruf protokolliert")}
    try:
        with open(IMPORT_LOG_DATEI, encoding="utf-8", errors="replace") as f:
            alle = f.readlines()
        return {"zeilen": [z.rstrip() for z in alle[-zeilen:]]}
    except Exception as e:
        return {"zeilen": [], "meldung": str(e)}


def _versand_pruefen():
    """Verschickt faellige Berichte. Merker verhindert Doppelversand.
    Bei mehreren Fahrzeugen ein Bericht ueber alle (Summe und je Fahrzeug)."""
    if db.SCHEMA_ZU_NEU:      # Merker waere nicht speicherbar -> sonst taeglich dieselbe Mail
        return
    with db.fahrzeug_kontext(db.ALLE):
        _versand_pruefen_kontext()


def _versand_pruefen_kontext():
    cfg = db.get_mail_settings()
    if cfg.get("mail_aktiv") != "1":
        return
    jetzt = datetime.now()

    # Monatsbericht: ab dem 1. des Folgemonats, einmal pro Monat
    if cfg.get("mail_monat_aktiv") == "1":
        v_jahr, v_monat = ((jetzt.year, jetzt.month - 1) if jetzt.month > 1
                           else (jetzt.year - 1, 12))
        marke = f"{v_jahr}-{v_monat:02d}"
        if cfg.get("mail_letzter_monat") != marke:
            hinweis = ""
            if cfg.get("bericht_warten", "1") == "1":
                try:
                    wartetage = int(cfg.get("bericht_max_wartetage") or 10)
                except ValueError:
                    wartetage = 10
                pruefung = _monat_pruefen(v_jahr, v_monat)
                if not pruefung["bereit"]:
                    if jetzt.day <= wartetage:
                        print(f"[Bericht] {marke} noch nicht abschlussreif: "
                              f"{'; '.join(pruefung['offen'])}", flush=True)
                        return
                    hinweis = _("Hinweis: Der Monat war beim Versand noch unvollständig – {0}",
                                "; ".join(pruefung["offen"]))
            bericht = berichte.monatsbericht(v_jahr, v_monat)
            if hinweis:
                bericht["hinweis"] = hinweis
            ok, meldung = mailer.sende_mail(
                betreff=f"EV Tracker – {bericht['titel']}",
                html=berichte.als_html(bericht),
                text=berichte.als_text(bericht), cfg=cfg)
            if ok:
                db.set_einstellung("mail_letzter_monat", marke)
            print(f"[Bericht] Monat {marke}: {meldung}", flush=True)

    # Jahresbericht: ab dem 1. Januar, einmal pro Jahr
    if cfg.get("mail_jahr_aktiv") == "1":
        vorjahr = str(jetzt.year - 1)
        if cfg.get("mail_letztes_jahr") != vorjahr:
            bericht = berichte.jahresbericht(int(vorjahr))
            ok, meldung = mailer.sende_mail(
                betreff=f"EV Tracker – {bericht['titel']}",
                html=berichte.als_html(bericht),
                text=berichte.als_text(bericht), cfg=cfg)
            if ok:
                db.set_einstellung("mail_letztes_jahr", vorjahr)
            print(f"[Bericht] Jahr {vorjahr}: {meldung}", flush=True)


def _naechster_lauf(jetzt: datetime) -> datetime:
    """Naechster Zeitpunkt der eingestellten Uhrzeit (Standard 00:00)."""
    from datetime import timedelta
    roh = (db.get_mail_settings().get("mail_uhrzeit") or "00:00").strip()
    try:
        stunde, minute = (int(t) for t in roh.split(":")[:2])
    except ValueError:
        stunde, minute = 0, 0
    ziel = jetzt.replace(hour=min(stunde, 23), minute=min(minute, 59),
                         second=0, microsecond=0)
    if ziel <= jetzt:
        ziel += timedelta(days=1)
    return ziel


def _zeitplan_schleife():
    """Prueft einmal taeglich zur eingestellten Uhrzeit, ob ein Bericht faellig ist."""
    import time
    while True:
        jetzt = datetime.now()
        ziel = _naechster_lauf(jetzt)
        schlafen = max(60, (ziel - jetzt).total_seconds())
        print(f"[Bericht] Naechste Pruefung: {ziel:%d.%m.%Y %H:%M}", flush=True)
        time.sleep(schlafen)
        # 1. Daten aus Home Assistant nachziehen
        try:
            if not db.SCHEMA_ZU_NEU and db.get_mail_settings().get("auto_import", "1") == "1":
                protokoll = _auto_import()
                db.set_einstellung(
                    "auto_import_letzter",
                    f"{datetime.now():%Y-%m-%d %H:%M} · " + " | ".join(protokoll))
                for zeile in protokoll:
                    print(f"[Auto-Import] {zeile}", flush=True)
        except Exception as e:
            print(f"[Auto-Import] Fehler: {e}", flush=True)
        # 2. Bericht pruefen und ggf. versenden
        try:
            _versand_pruefen()
        except Exception as e:
            print(f"[Bericht] Fehler im Zeitplan: {e}", flush=True)


threading.Thread(target=_zeitplan_schleife, daemon=True).start()
# Modul Fahrtenbuch: Standort mitschreiben (prueft selbst, ob das Modul an ist)
fahrtenbuch_mod.starten()


# ─────────────────────────────────────────────────────────────
#  Backup der Datenbank (Token-geschützt)
# ─────────────────────────────────────────────────────────────

BACKUP_TOKEN = os.environ.get("EV_TRACKER_BACKUP_TOKEN", "")
STATUS_DATEI = os.path.join(DATA_DIR, "backup_status.json")
LOG_DATEI = os.path.join(DATA_DIR, "backup.log")
TRIGGER_DATEI = os.path.join(DATA_DIR, ".backup_now")


def _sicherungskopie(praefix: str) -> str:
    """Legt eine konsistente Kopie der Datenbank als <praefix>_<zeit>.db im
    Datenordner an und gibt den Dateinamen zurueck ("" wenn keine DB da ist).
    Bei gleichem Zeitstempel wird durchnummeriert, damit zwei Aufrufe in
    derselben Sekunde nicht die erste Kopie ueberschreiben."""
    import sqlite3
    if not os.path.exists(db.DB_PATH):
        return ""
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    ziel = os.path.join(DATA_DIR, f"{praefix}_{stamp}.db")
    nr = 2
    while os.path.exists(ziel):
        ziel = os.path.join(DATA_DIR, f"{praefix}_{stamp}_{nr}.db")
        nr += 1

    quelle = sqlite3.connect(db.DB_PATH)
    kopie = sqlite3.connect(ziel)
    try:
        with kopie:
            quelle.backup(kopie)
    finally:
        kopie.close()
        quelle.close()
    return os.path.basename(ziel)


def _doppelte_monatssummen_bereinigen():
    """Einmalig (ab 3.6.1): Zeitraum-Import und naechtlicher Abruf legten fuer denselben
    Monat je eine Monatssumme an – der Monat zaehlte doppelt. Behalten wird je Monat eine
    (siehe db.doppelte_monatssummen); vorher Sicherungskopie, Ergebnis im Importprotokoll."""
    if db.SCHEMA_ZU_NEU or db.get_einstellung_str("migration_monatssumme_doppelt") == "1":
        return
    doppelt = db.doppelte_monatssummen()
    if doppelt:
        sicherung = _sicherungskopie("vor_bereinigung")
        db.doppelte_monatssummen(entfernen=True)
        zeilen = [f"Doppelte Monatssummen entfernt (Sicherung: {sicherung})"]
        for d in doppelt:
            weg = ", ".join(f"{k:.2f}" for k in d["entfernt"])
            zeilen.append(f"{d['datum'][:7]}: {d['anbieter']} behalten {d['behalten']:.2f} kWh, "
                          f"entfernt {weg} kWh")
        _log_import(zeilen, trenner=True)
    db.set_einstellung("migration_monatssumme_doppelt", "1")


_doppelte_monatssummen_bereinigen()


@app.get("/backup", response_class=HTMLResponse)
def backup_seite(request: Request):
    return render(request, "backup.html", aktiv="backup", db_pfad=db.DB_PATH,
                  add_on_modus=IST_ADDON, support_mail=diagnose.SUPPORT_MAIL, version=VERSION,
                  datenquelle=datenquellen.QUELLEN.get(db.get_ha_settings().get("datasource"),
                                                      "Home Assistant API"))


@app.get("/api/backup/status")
def backup_status():
    """Status des letzten Backups (wird von backup.sh geschrieben)."""
    import json
    if not os.path.exists(STATUS_DATEI):
        return {"status": "never", "meldung": _("Noch kein Backup gelaufen")}
    try:
        with open(STATUS_DATEI, encoding="utf-8") as f:
            daten = json.load(f)
    except Exception as e:
        return {"status": "error", "meldung": _("Statusdatei unlesbar: {0}", e)}

    roh = daten.get("last_backup_iso") or daten.get("last_backup", "")
    try:
        if "_" in roh:   # Format 2026-08-25_02-30-01
            datum, zeit = roh.split("_")
            roh = f"{datum} {zeit.replace('-', ':')}"
        letzte = datetime.fromisoformat(roh)
        if letzte.tzinfo is not None:
            letzte = letzte.replace(tzinfo=None)
        stunden = (datetime.now() - letzte).total_seconds() / 3600
        daten["alter_stunden"] = round(stunden, 1)
        daten["aktuell"] = stunden < 26
    except Exception:
        daten["alter_stunden"] = None
        daten["aktuell"] = False

    daten["wartet"] = os.path.exists(TRIGGER_DATEI)
    daten["db_groesse_kb"] = (round(os.path.getsize(db.DB_PATH) / 1024)
                              if os.path.exists(db.DB_PATH) else 0)
    return daten


@app.get("/api/backup/log")
def backup_log(zeilen: int = 100):
    if not os.path.exists(LOG_DATEI):
        return {"zeilen": [], "meldung": _("Noch kein Protokoll vorhanden")}
    try:
        with open(LOG_DATEI, encoding="utf-8", errors="replace") as f:
            alle = f.readlines()
        return {"zeilen": [z.rstrip() for z in alle[-zeilen:]]}
    except Exception as e:
        return {"zeilen": [], "meldung": str(e)}


@app.post("/api/backup/run")
def backup_ausloesen():
    """Legt die Trigger-Datei an – der Cronjob auf dem Host startet backup.sh."""
    try:
        with open(TRIGGER_DATEI, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat())
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"ok": True,
            "meldung": _("Backup angefordert – startet innerhalb der naechsten Minuten.")}


@app.post("/api/backup/restore")
async def backup_restore(datei: UploadFile = File(...), bestaetigt: str = Form("")):
    """Stellt eine gesicherte Datenbank wieder her (mit Sicherheitskopie vorher)."""
    import sqlite3
    if bestaetigt != "ja":
        return JSONResponse({"error": _("Nicht bestaetigt.")}, status_code=400)

    roh = await datei.read()
    if not roh.startswith(b"SQLite format 3"):
        return JSONResponse({"error": _("Das ist keine SQLite-Datenbank.")}, status_code=400)

    tmp = os.path.join(DATA_DIR, f"_restore_{uuid.uuid4().hex}.db")
    with open(tmp, "wb") as f:
        f.write(roh)

    # Pruefen, ob die erwarteten Tabellen vorhanden sind
    try:
        pruef = sqlite3.connect(tmp)
        tabellen = {r[0] for r in pruef.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        pruef.close()
        fehlend = {"einstellungen", "ladevorgang", "fahrten_monat"} - tabellen
        if fehlend:
            os.remove(tmp)
            return JSONResponse(
                {"error": _("Datei ist keine EV-Tracker-Datenbank (fehlend: {0})", ", ".join(sorted(fehlend)))},
                status_code=400)
    except Exception as e:
        os.remove(tmp)
        return JSONResponse({"error": _("Datei nicht lesbar: {0}", e)}, status_code=400)

    # Sicherheitskopie der aktuellen Datenbank
    sicherung = _sicherungskopie("vor_restore")

    os.replace(tmp, db.DB_PATH)
    db.init_db()
    return {"ok": True, "sicherung": sicherung,
            "meldung": _("Datenbank wiederhergestellt.")}


@app.get("/api/reset/vorschau")
def reset_vorschau():
    """Was ein Zuruecksetzen loeschen wuerde – Grundlage fuer die Rueckfrage."""
    anzahl = db.zaehle_messdaten()
    return {"bereiche": [{"key": k, "titel": _(titel), "anzahl": anzahl.get(k, 0)}
                         for k, (_tab, titel) in db.MESSDATEN_BEREICHE.items()]}


@app.post("/api/reset")
@mit_fahrzeug
def reset_messdaten(bereiche: str = Form(""), bestaetigt: str = Form("")):
    """Leert die gewaehlten Messdaten-Tabellen (Fahrzeugwechsel, Testdaten raus).

    Einstellungen, Stromtarife, Lade-Anbieter und die HA-Konfiguration bleiben.
    Vorher wird die Datenbank als vor_reset_….db im Datenordner gesichert.
    """
    if bestaetigt != "ja":
        return JSONResponse({"error": _("Nicht bestaetigt.")}, status_code=400)
    gewaehlt = [b for b in bereiche.split(",") if b in db.MESSDATEN_BEREICHE]
    if not gewaehlt:
        return JSONResponse({"error": _("Kein Bereich gewaehlt.")}, status_code=400)

    sicherung = _sicherungskopie("vor_reset")
    geloescht = db.loesche_messdaten(gewaehlt)
    text = ", ".join(f"{_(db.MESSDATEN_BEREICHE[b][1])}: {n}"
                     for b, n in geloescht.items())
    return {"ok": True, "sicherung": sicherung,
            "geloescht": geloescht, "meldung": _("Zurückgesetzt – {0}", text)}


@app.get("/api/diagnose/paket")
def diagnose_paket():
    """ZIP zum Weitergeben bei Importproblemen: Datenbank ohne Zugangsdaten,
    Importprotokoll und die Rohdaten der eingetragenen HA-Sensoren (diagnose.py)."""
    client = _ha_client()
    inhalt = diagnose.paket_bauen(VERSION, {"import.log": IMPORT_LOG_DATEI}, client, IST_ADDON)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    return Response(inhalt, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="ev_tracker_diagnose_{stamp}.zip"'})


@app.get("/api/backup")
def backup(token: str = ""):
    """Liefert eine konsistente Kopie der SQLite-Datenbank.
    Als Add-on reicht die Ingress-Authentifizierung durch HA, daher kein Token
    nötig. Im Standalone-Docker-Betrieb weiterhin nur mit EV_TRACKER_BACKUP_TOKEN,
    weil der Endpunkt dort ohne HA-Login direkt aus dem Netz erreichbar ist."""
    if not IST_ADDON:
        if not BACKUP_TOKEN:
            return JSONResponse(
                {"error": _("Backup deaktiviert – EV_TRACKER_BACKUP_TOKEN nicht gesetzt.")},
                status_code=403)
        if token != BACKUP_TOKEN:
            return JSONResponse({"error": _("Ungültiger Token.")}, status_code=403)

    import sqlite3
    ziel = os.path.join(STATIC_DIR, f"_backup_{uuid.uuid4().hex}.db")
    quelle = sqlite3.connect(db.DB_PATH)
    kopie = sqlite3.connect(ziel)
    try:
        with kopie:
            quelle.backup(kopie)   # konsistent auch bei laufenden Schreibzugriffen
    finally:
        kopie.close()
        quelle.close()

    stamp = datetime.now().strftime("%Y-%m-%d")
    return FileResponse(ziel, filename=f"ev_tracker_{stamp}.db",
                        media_type="application/octet-stream",
                        background=BackgroundTask(os.remove, ziel))


# ─────────────────────────────────────────────────────────────
#  Einstellungen
# ─────────────────────────────────────────────────────────────

# Nur diese Sensoren werden tatsaechlich importiert.
SENSOR_FELDER = [
    ("ha_odometer",       "fn_odometer",       N_("Kilometerstand (km)")),
    ("ha_pv_production",  "fn_pv_production",  N_("PV ins Auto geladen (kWh)")),
    ("ha_wallbox_energy", "fn_wallbox_energy", N_("Netz ins Auto geladen (kWh)")),
    # Optional, fuer dynamische Stromtarife (Vorlage vorlagen/homeassistant/ev_netzkosten.yaml)
    ("ha_wallbox_cost",   "fn_wallbox_cost",   N_("Kosten Netz ins Auto (€, dynamischer Tarif)")),
    ("ha_tankerkoenig",   "fn_tankerkoenig",   N_("{0}preis Sensor 1 (€/L)")),
    ("ha_tankerkoenig_2", "fn_tankerkoenig_2", N_("{0}preis Sensor 2 (€/L)")),
    # Fuer Ladeerkennung und Verbrauch aus dem Akkustand
    ("ha_ev_battery",     "fn_ev_battery",     N_("Batteriestand Auto (%)")),
    # Optional, fuer die Akku-Seite: Reichweite laut Auto und Akku-Gesundheit (SoH)
    ("ha_ev_range",       "fn_ev_range",       N_("Reichweite laut Auto (km, optional)")),
    ("ha_ev_soh",         "fn_ev_soh",         N_("Akku-Gesundheit SoH (%, optional)")),
    # Module Energie und Fahrtenbuch
    ("ha_ev_tagesstatistik", "fn_ev_tagesstatistik", N_("Tägliche Fahrstatistik (Attribute je Tag)")),
    ("ha_ev_ort",         "",                  N_("Standort (Auto, Handy oder Person)")),
    ("ha_ev_fahrt",       "fn_ev_fahrt",       N_("Motor / Zündung an (optional)")),
]
# Nur fuer Module genutzt (Akku, Energie, Fahrtenbuch) – in der Einrichtung kein eigener Schritt
SENSOR_NUR_AKKU = {"ha_ev_range", "ha_ev_soh", "ha_ev_tagesstatistik", "ha_ev_ort", "ha_ev_fahrt"}


def _sensor_label(label: str) -> str:
    """Anzeige einer Sensorzeile in der eingestellten Sprache; {0} = Kraftstoff (Benzinpreis …)."""
    return _(label, berechnung.kraftstoff()["name"]) if "{0}" in label else _(label)


@app.get("/einstellungen", response_class=HTMLResponse)
def einstellungen(request: Request, meldung: str = ""):
    mehrere = db.mehrere_fahrzeuge()
    modus = db.heimladung_modus()
    # Bei "eigene Zaehler" zeigt das Sensor-Formular die Ladezaehler dieses Fahrzeugs
    ha_settings = db.get_ha_settings(eigene_zaehler=mehrere and modus == "eigen")
    alle_fz = db.fahrzeuge(alle=True)
    for f in alle_fz:
        f["heimladung"] = db.heimladung_modus(f["id"])
        hs = db.get_ha_settings(f["id"])
        f["ohne_akku"] = not (hs.get("ha_ev_battery") or hs.get("fn_ev_battery"))
    return render(request, "einstellungen.html",
                  meldung=meldung,
                  fahrzeuge_alle=alle_fz,
                  hauptfahrzeug=db.hauptfahrzeug(),
                  heimladung=modus, heimladung_modi=db.HEIMLADUNG_MODI,
                  einstellungs_fahrzeug=db.schreib_fahrzeug(),
                  cfg=db.get_config(),
                  fahrzeug_name=db.get_einstellung_str("fahrzeug_name") or "",
                  kfz=db.get_einstellung("kfz_steuer_benziner") or 0.0,
                  anschaffung={k: db.get_einstellung(f"anschaffung_{k}") or 0.0
                               for k in ("eauto", "verbrenner", "foerderung")},
                  zulassung={"erst": zeitraum_mod.erstzulassung(),
                             "eigen": zeitraum_mod.zulassung_eigen(),
                             "km": db.get_einstellung("km_bei_kauf") or 0.0},
                  leasing={k: db.get_einstellung_str(f"leasing_{k}") or ""
                           for k in LEASING_FELDER},
                  kraftstoffe=berechnung.kraftstoffe(),
                  galerie=galerie.bilder(),
                  galerie_aktiv=auto_bild_galerie(),
                  ha=ha_settings,
                  add_on_modus=IST_ADDON,
                  supervisor_aktiv=IST_ADDON
                                   and not (ha_settings.get("ha_url") and ha_settings.get("ha_token")),
                  anbieter=db.get_lade_anbieter(),
                  sensor_felder=[(h, f, _sensor_label(l), m,
                                  _(module_mod.MODULE[m]["name"]) if m else None)
                                 for h, f, l in SENSOR_FELDER
                                 for m in [module_mod.sensor_modul(h)]
                                 if h not in module_mod.sensoren_aus()],
                  modul_liste=_modul_stand(ha_settings),
                  fahrtenbuch=fahrtenbuch_mod.einstellungen(),
                  quellen=datenquellen.QUELLEN,
                  prom_standard=datenquellen.PROM_SELEKTOR_STANDARD,
                  push_token=heimladung.token(),
                  push_url=_push_url(request),
                  aktiv="einstellungen")


@app.post("/einstellungen/parameter")
@mit_fahrzeug
def einstellungen_parameter(benziner_verbrauch: str = Form(...),
                            ev_verbrauch: str = Form(...),
                            pv_preis: str = Form(...),
                            co2_benzin: str = Form(...),
                            kfz_steuer: str = Form(...),
                            fahrzeug_name: str = Form(""),
                            kraftstoff: str = Form("")):
    # Beim Wechsel Benzin <-> Diesel den CO2-Faktor mitziehen, solange noch der
    # Standardwert der alten Art eingetragen ist – ein eigener Wert bleibt stehen
    alt = berechnung.kraftstoff()
    neu = berechnung.KRAFTSTOFFE.get(kraftstoff)
    if neu and neu["art"] != alt["art"]:
        db.set_einstellung("kraftstoff", neu["art"])
        if parse_de(co2_benzin) == alt["co2_standard"]:
            co2_benzin = str(neu["co2_standard"])
    for key, raw in [("benziner_verbrauch", benziner_verbrauch),
                     ("ev_verbrauch_default", ev_verbrauch),
                     ("pv_preis_ct", pv_preis),
                     ("co2_faktor_benzin", co2_benzin),
                     ("kfz_steuer_benziner", kfz_steuer)]:
        v = parse_de(raw, tausender=key == "kfz_steuer_benziner")
        if v is not None:
            db.set_einstellung(key, v)
    db.set_einstellung("fahrzeug_name", fahrzeug_name.strip())
    return RedirectResponse("../einstellungen", status_code=303)


@app.post("/einstellungen/anschaffung")
@mit_fahrzeug
def einstellungen_anschaffung(eauto: str = Form(""), verbrenner: str = Form(""),
                              foerderung: str = Form(""), km_bei_kauf: str = Form(""),
                              erstzulassung: str = Form(""), zulassung_eigen: str = Form("")):
    """Kaufpreise fuer die Amortisation (ein leerer Preis des E-Autos blendet sie aus),
    Zulassung und km-Stand bei Kauf. Datum 'YYYY-MM-DD', leer = unbekannt."""
    for key, raw in [("anschaffung_eauto", eauto), ("anschaffung_verbrenner", verbrenner),
                     ("anschaffung_foerderung", foerderung), ("km_bei_kauf", km_bei_kauf)]:
        v = parse_de(raw, tausender=True) if raw.strip() else 0.0
        if v is not None and v >= 0:
            db.set_einstellung(key, v)
    for key, raw in [("erstzulassung", erstzulassung), ("zulassung_eigen", zulassung_eigen)]:
        raw = raw.strip()
        if not raw or re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            db.set_einstellung(key, raw)
    return RedirectResponse("../einstellungen#anschaffung", status_code=303)


def _modul_stand(ha: dict) -> list:
    """Module fuer Einstellungen → Module: [(id, Modul, an?, [(Voraussetzung, erfuellt?)])] –
    die Voraussetzungen fuer das aktuelle Fahrzeug."""
    def da(*keys):
        return any((ha.get(k) or "").strip() for k in keys)
    braucht = {
        "akku": [(_("Batteriestand"), da("ha_ev_battery", "fn_ev_battery")),
                 (_("Kilometerstand"), da("ha_odometer", "fn_odometer"))],
        "profil": [(_("Kilometerstand"), da("ha_odometer", "fn_odometer")),
                   (_("Batteriestand"), da("ha_ev_battery", "fn_ev_battery"))],
        "leasing": [(_("Vertrag eingetragen"), leasing_mod.vertrag() is not None)],
        "energie": [(_("Tägliche Fahrstatistik"), da("ha_ev_tagesstatistik"))],
        "fahrtenbuch": [(_("Kilometerstand"), da("ha_odometer", "fn_odometer")),
                        (_("Standort"), da("ha_ev_ort"))],
    }
    zustand = module_mod.alle()
    return [(mid, m, zustand[mid], braucht.get(mid, [])) for mid, m in module_mod.MODULE.items()]


@app.post("/einstellungen/module")
async def einstellungen_module(request: Request):
    """Module ein- und ausschalten (gilt fuer die ganze App)."""
    form = await request.form()
    vorher = module_mod.alle()
    module_mod.speichern({mid: bool(form.get(mid)) for mid in module_mod.MODULE})
    # Energie frisch eingeschaltet: vorhandene Tage aus Home Assistant nachholen
    if module_mod.an("energie") and not vorher["energie"]:
        _im_hintergrund(_energie_nachholen)
    return RedirectResponse("../einstellungen#module", status_code=303)


LEASING_FELDER = ("aktiv", "start", "ende", "km_jahr", "km_start", "toleranz_km",
                  "mehr_ct", "minder_ct")


@app.post("/einstellungen/leasing")
@mit_fahrzeug
def einstellungen_leasing(aktiv: str = Form(""), start: str = Form(""), ende: str = Form(""),
                          km_jahr: str = Form(""), km_start: str = Form(""),
                          toleranz_km: str = Form(""), mehr_ct: str = Form(""),
                          minder_ct: str = Form("")):
    """Leasingvertrag des Fahrzeugs: Laufzeit, km je Jahr, Freigrenze, Saetze je km."""
    db.set_einstellung("leasing_aktiv", "1" if aktiv else "0")
    for key, raw in [("start", start), ("ende", ende)]:
        raw = raw.strip()
        if not raw or re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            db.set_einstellung(f"leasing_{key}", raw)
    for key, raw in [("km_jahr", km_jahr), ("km_start", km_start), ("toleranz_km", toleranz_km),
                     ("mehr_ct", mehr_ct), ("minder_ct", minder_ct)]:
        v = parse_de(raw, tausender=key.startswith("km") or key == "toleranz_km") if raw.strip() else None
        if not raw.strip():
            db.set_einstellung(f"leasing_{key}", "")
        elif v is not None and v >= 0:
            db.set_einstellung(f"leasing_{key}", v)
    return RedirectResponse("../einstellungen#leasing", status_code=303)


@app.post("/einstellungen/sprache")
def einstellungen_sprache(sprache: str = Form("de"), zurueck: str = Form("")):
    """Sprache der Oberflaeche und der Mail-Berichte (global): "de" oder "en"."""
    db.set_einstellung("sprache", "en" if sprache == "en" else "de")
    # Nur eine Seite dieser App (ein Pfadteil, ohne Schema/Host) – kein Sprung nach aussen
    if not re.fullmatch(r"[a-z_-]*(\?[^\s#]*)?(#[\w-]*)?", zurueck or ""):
        zurueck = "einstellungen"
    return RedirectResponse("../" + zurueck, status_code=303)


@app.post("/einstellungen/simulation")
async def einstellungen_simulation(request: Request):
    form = await request.form()
    db.set_einstellung("simulation", "1" if form.get("simulation") else "0")
    for key in ("sim_anteil_pv", "sim_anteil_netz", "sim_anteil_oeffentlich",
                "sim_preis_oeffentlich", "sim_ladeverlust"):
        v = parse_de(form.get(key))
        if v is not None and v >= 0:
            db.set_einstellung(key, v)
    return RedirectResponse("../einstellungen#simulation", status_code=303)


@app.post("/einstellungen/anbieter")
def anbieter_add(name: str = Form(...), gruenstrom: str = Form("")):
    if name.strip():
        db.add_lade_anbieter(name.strip(), 1 if gruenstrom else 0)
    return RedirectResponse("../einstellungen", status_code=303)


@app.post("/einstellungen/anbieter/delete")
def anbieter_delete(id: int = Form(...)):
    db.delete_lade_anbieter(id)
    return RedirectResponse("../../einstellungen", status_code=303)


@app.post("/einstellungen/ha")
@mit_fahrzeug
async def einstellungen_ha(request: Request):
    form = await request.form()
    # Alle HA-/Datenbank-Einstellungen, die das Formular mitschickt
    settings = {k: str(form[k]).strip() for k in db.HA_ENTITY_DEFAULTS if k in form}
    if settings.get("datasource") not in (None, "ha", *datenquellen.QUELLEN):
        settings.pop("datasource")
    # Leeres Token-/Passwortfeld = gespeicherten Wert behalten (Maskierung)
    for key in GEHEIM_KEYS:
        if settings.get(key) == "":
            settings.pop(key)
    if db.mehrere_fahrzeuge() and db.heimladung_modus() == "eigen":
        # Eigene Ladezaehler dieses Fahrzeugs statt der gemeinsamen Wallbox
        fid = db.schreib_fahrzeug()
        for key in db.WALLBOX_SCHLUESSEL:
            if key in settings:
                db.save_ha_settings({f"{key}@{fid}": settings.pop(key)})
    db.save_ha_settings(settings)
    return RedirectResponse("../einstellungen", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Fahrzeuge: ein oder mehrere, Verwaltung
# ─────────────────────────────────────────────────────────────

def _zu_einstellungen(meldung: str = "", fahrzeug=None):
    from urllib.parse import urlencode
    teile = {k: v for k, v in (("meldung", meldung), ("fahrzeug", fahrzeug)) if v}
    return RedirectResponse("../../einstellungen" + (f"?{urlencode(teile)}" if teile else "")
                            + "#fahrzeuge", status_code=303)


@app.post("/einstellungen/fahrzeuge/modus")
def fahrzeuge_modus(modus: str = Form(...), haupt: str = Form("")):
    """Ein Fahrzeug <-> mehrere. Beim ersten Umschalten auf mehrere werden zwei Tabellen
    umgebaut – vorher wird die Datenbank gesichert. Zurueck auf ein Fahrzeug loescht
    nichts: die anderen Fahrzeuge werden nur nicht mehr angezeigt."""
    if modus == "mehrere":
        if not db.mehrere_fahrzeuge():
            sicherung = ""
            if db.schema_stand() < 3:
                sicherung = _sicherungskopie("vor_mehrere_fahrzeuge")
                try:
                    db.struktur_mehrere_fahrzeuge()
                except Exception as e:
                    return _zu_einstellungen(_("Umschalten abgebrochen, nichts geändert: {0}", e))
            db.set_einstellung("mehrere_fahrzeuge", "1")
            return _zu_einstellungen(_("Mehrere Fahrzeuge eingeschaltet")
                                     + (_(" – Sicherung: {0}", sicherung) if sicherung else ""))
        return _zu_einstellungen()
    if modus == "ein":
        ids = [f["id"] for f in db.fahrzeuge(alle=True)]
        neu_haupt = int(haupt) if haupt.isdigit() and int(haupt) in ids else db.hauptfahrzeug()
        db.set_einstellung("hauptfahrzeug", neu_haupt)
        db.set_einstellung("mehrere_fahrzeuge", "0")
        weitere = len(ids) - 1
        return _zu_einstellungen(
            _("Ein Fahrzeug: {0}", next(f["name"] for f in db.fahrzeuge(alle=True) if f["id"] == neu_haupt))
            + (_(" – {0} weitere(s) ausgeblendet, alle Daten bleiben erhalten", weitere) if weitere else ""))
    return _zu_einstellungen()


@app.post("/einstellungen/fahrzeuge/neu")
def fahrzeuge_neu(name: str = Form(...)):
    if not db.mehrere_fahrzeuge():
        return _zu_einstellungen(_("Erst „Mehrere Fahrzeuge“ einschalten"))
    fid = db.fahrzeug_anlegen(name)
    return _zu_einstellungen(_("Fahrzeug „{0}“ angelegt und ausgewählt – "
                               "jetzt Sensoren und Vergleichswerte eintragen", name.strip()), fahrzeug=fid)


@app.post("/einstellungen/fahrzeuge/aendern")
def fahrzeuge_aendern(id: int = Form(...), name: str = Form(""), heimladung: str = Form(""),
                      aktiv: str = Form(""), haupt: str = Form("")):
    ids = [f["id"] for f in db.fahrzeuge(alle=True)]
    if id not in ids:
        return _zu_einstellungen(_("Fahrzeug nicht gefunden"))
    with db.fahrzeug_kontext(id):
        if name.strip():
            db.set_einstellung("fahrzeug_name", name.strip())
        if heimladung in db.HEIMLADUNG_MODI:
            db.set_einstellung("heimladung", heimladung)
    einblenden = aktiv == "1"
    if haupt == "1":
        db.set_einstellung("hauptfahrzeug", id)
        einblenden = True
    if not einblenden and id == db.hauptfahrzeug():
        return _zu_einstellungen(_("Das Hauptfahrzeug kann nicht ausgeblendet werden – "
                                   "erst ein anderes zum Hauptfahrzeug machen"))
    db.fahrzeug_aktiv(id, einblenden)
    return _zu_einstellungen(_("Gespeichert"))


@app.post("/einstellungen/fahrzeuge/loeschen")
def fahrzeuge_loeschen(id: int = Form(...), bestaetigung: str = Form("")):
    """Loescht ein Fahrzeug mit allen Daten – nur nach Eingabe seines Namens; vorher
    wird die Datenbank gesichert."""
    fz = next((f for f in db.fahrzeuge(alle=True) if f["id"] == id), None)
    if fz is None:
        return _zu_einstellungen(_("Fahrzeug nicht gefunden"))
    if bestaetigung.strip() != fz["name"]:
        return _zu_einstellungen(_("Nicht gelöscht: der eingegebene Name passt nicht"))
    try:
        if id == db.hauptfahrzeug() or len(db.fahrzeuge(alle=True)) <= 1:
            raise ValueError(_("Hauptfahrzeug bzw. letztes Fahrzeug lässt sich nicht löschen"))
        sicherung = _sicherungskopie("vor_fahrzeug_loeschen")
        anzahl = db.fahrzeug_loeschen(id)
    except ValueError as e:
        return _zu_einstellungen(_("Nicht gelöscht: {0}", e))
    return _zu_einstellungen(_("„{0}“ gelöscht ({1} Datensätze) – Sicherung: {2}",
                               fz["name"], sum(anzahl.values()), sicherung))
