"""
EV Tracker – Web-Version (FastAPI)
Nutzt dieselben Kern-Module wie die Desktop-App:
database.py, berechnung.py, ha_client.py, pdf_parser.py, charts.py
"""
import os
import re
import sys
import threading
import uuid
from datetime import datetime

# Kern-Module liegen im Elternordner (bzw. in Docker unter /app)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, UploadFile, File, Form
from fastapi.responses import (HTMLResponse, RedirectResponse, JSONResponse,
                               FileResponse)
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from fastapi.templating import Jinja2Templates

import database as db
import akkuverbrauch
import berechnung
import berichte
import ladeerkennung
import ladetarife as ladetarife_mod
import unterhalt
import mailer
import charts
import zeitraum as zeitraum_mod
from version import VERSION, CHANGELOG
import datenquellen
from ha_client import HAClient, IST_ADDON, ha_verbindung as _ha_verbindung
from pdf_parser import parse_rechnung_pdf, parse_rechnung_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
# Datenverzeichnis: hier liegen Datenbank, Backup- und Importprotokoll
DATA_DIR = os.path.dirname(db.DB_PATH) or "."
IMPORT_LOG_DATEI = os.path.join(DATA_DIR, "import.log")

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]


db.init_db()
db.init_ha_settings()
db.init_mail_settings()

# Einmalig (ab 2.0.7): Netzbezug aus dem Import wurde frueher immer mit dem neuesten
# Stromtarif bewertet – jetzt mit dem Tarif des jeweiligen Monats
if db.get_einstellung_str("migration_netzpreis_monat") != "1":
    berechnung.heimladungen_neu_bewerten()
    db.set_einstellung("migration_netzpreis_monat", "1")

# IST_ADDON (Add-on oder Standalone-Docker) und die HA-Verbindung stehen in ha_client.py,
# weil auch akkuverbrauch.py und ladeerkennung.py sie brauchen.

app =FastAPI(title="EV Tracker")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals["MONATE"] = MONATE
templates.env.globals["VERSION"] = VERSION
# Deutsche Zahlen mit Tausenderpunkt: {{ wert | de(2) }} -> "1.519,88"
templates.env.filters["de"] = lambda wert, stellen=0: berichte.fmt(wert, stellen)


def render(request, template, **ctx):
    ctx["now"] = datetime.now()
    # Benzin oder Diesel – fuer Menue und Beschriftungen auf allen Seiten
    ctx.setdefault("kf", berechnung.kraftstoff())
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


@app.get("/api/auto-bild")
def auto_bild():
    """Liefert das eigene Fahrzeugbild, sonst das mitgelieferte Standardbild."""
    voll = _auto_bild_pfad()
    if voll:
        return FileResponse(voll)
    return FileResponse(os.path.join(STATIC_DIR, "Auto.jpg"))


@app.post("/api/auto-bild")
async def auto_bild_hochladen(bild: UploadFile = File(...)):
    ext = os.path.splitext(bild.filename or "")[1].lower()
    if ext not in AUTO_BILD_ERLAUBT:
        return JSONResponse(
            {"error": "Nur JPG, PNG oder WebP erlaubt."}, status_code=400)
    inhalt = await bild.read()
    if len(inhalt) > 8 * 1024 * 1024:
        return JSONResponse({"error": "Datei zu groß (max. 8 MB)."}, status_code=400)

    alt = _auto_bild_pfad()
    if alt:
        os.remove(alt)
    dateiname = f"auto_bild{ext}"
    with open(os.path.join(DATA_DIR, dateiname), "wb") as f:
        f.write(inhalt)
    db.set_einstellung("auto_bild_datei", dateiname)
    return {"ok": True}


@app.post("/api/auto-bild/reset")
def auto_bild_zuruecksetzen():
    """Loescht das eigene Bild wieder – Dashboard zeigt danach das Standardbild."""
    voll = _auto_bild_pfad()
    if voll:
        os.remove(voll)
    db.set_einstellung("auto_bild_datei", "")
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

    charts_html = {
        "monatlich": charts.chart_monatliche_ersparnis(
            f["fahrten"], f["benzin"], f["lade"], benziner_l=cfg["benziner_verbrauch"],
            ersatzpreis=berechnung.durchschnitt_benzinpreis(daten["benzin"])),
        "kosten": charts.chart_kosten_vergleich(
            kz["benzin_kosten"], kz["strom_kosten"]),
        "co2": charts.chart_co2_ersparnis(
            f["fahrten"], benziner_l=cfg["benziner_verbrauch"],
            co2_faktor=cfg["co2_faktor_benzin"]),
        "verbrauch": charts.chart_verbrauch_100km(
            f["lade"], f["fahrten"], ev_ref=cfg["ev_verbrauch"], akku_monate=f["akku"]),
        "strommix": charts.chart_strommix(f["lade"]),
        "benzin": charts.chart_benzinpreise(f["benzin"]),
        "strom": charts.chart_stromtarif(daten["stromtarife"], von=z["von"], bis=z["bis"]),
        "anbieter": charts.chart_anbieter_verteilung(f["lade"]),
        "thg": charts.chart_thg(f["thg"]),
    }
    antwort = render(request, "dashboard.html", kz=kz, charts=charts_html,
                     zeitraum=z, zeitraum_optionen=zeitraum_mod.optionen(daten),
                     fahrzeug_name=db.get_einstellung_str("fahrzeug_name") or "Mein Elektroauto",
                     aktiv="dashboard")
    if zeitraum is not None:
        antwort.set_cookie("zeitraum", z["schluessel"], max_age=365 * 24 * 3600,
                           samesite="lax")
    return antwort


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
    wa = zeitraum_mod.monatswerte(za, daten)
    wb = zeitraum_mod.monatswerte(zb, daten)
    verlauf = {m: charts.chart_vergleich(wa, wb, za["titel"], zb["titel"], m)
               for m in charts.VERGLEICH_METRIKEN}
    return render(request, "statistik.html", aktiv="statistik",
                  za=za, zb=zb, ka=ka, kb=kb,
                  zeilen=zeitraum_mod.vergleich_zeilen(ka, kb),
                  optionen=zeitraum_mod.optionen(daten),
                  vorlagen=zeitraum_mod.vorlagen(),
                  metriken=charts.VERGLEICH_METRIKEN, verlauf=verlauf,
                  akku_zeilen=zeitraum_mod.akku_monatszeilen(wa, wb),
                  akku_min_km=akkuverbrauch.MIN_KM)


# ─────────────────────────────────────────────────────────────
#  Hilfe / Handbuch
# ─────────────────────────────────────────────────────────────

@app.get("/hilfe", response_class=HTMLResponse)
def hilfe(request: Request):
    return render(request, "hilfe.html", aktiv="hilfe", changelog=CHANGELOG)


# ─────────────────────────────────────────────────────────────
#  Fahrten
# ─────────────────────────────────────────────────────────────

@app.get("/fahrten", response_class=HTMLResponse)
def fahrten(request: Request):
    daten = db.get_fahrten_monate()
    cfg = db.get_config()
    rows = []
    for d in daten:
        liter = berechnung.benzin_liter(d["km"], cfg["benziner_verbrauch"])
        rows.append({**d, "liter": liter,
                     "co2": berechnung.co2_kg(liter, cfg["co2_faktor_benzin"])})
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

    return render(request, "fahrten.html", rows=rows, aktiv="fahrten",
                  verbrauch=verbrauch,
                  abschnitte=db.get_akku_abschnitte(limit=40),
                  akku_schnitt=akku_schnitt, akku_differenz=differenz,
                  akku_gemeinsam=len(gemeinsam), akku_min_km=akkuverbrauch.MIN_KM,
                  akku_meldung=request.query_params.get("akku"))


@app.post("/fahrten/akku")
def fahrten_akku_berechnen(zeitraum: str = Form("alles")):
    """Fahrtabschnitte aus dem Akkustand neu berechnen (ganze Historie oder 45 Tage)."""
    try:
        meldung = akkuverbrauch.aktualisieren(
            tage=None if zeitraum == "alles" else akkuverbrauch.TAGE_NACHTLAUF)
    except Exception as e:
        meldung = f"Fehler beim Abruf: {e}"
    from urllib.parse import quote
    return RedirectResponse(f"../fahrten?akku={quote(meldung)}#akku", status_code=303)


@app.post("/fahrten")
def fahrten_add(monat: str = Form(...), km: str = Form(...)):
    v = parse_de(km, tausender=True)
    if v is not None and v >= 0:
        db.set_fahrt_monat(monat, v)
    return RedirectResponse("fahrten", status_code=303)


@app.post("/fahrten/delete")
def fahrten_delete(monat: str = Form(...)):
    db.delete_fahrt_monat(monat)
    return RedirectResponse("../fahrten", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Laden
# ─────────────────────────────────────────────────────────────

@app.get("/laden", response_class=HTMLResponse)
def laden(request: Request):
    daten = db.get_ladevorgaenge(limit=500)
    anbieter = db.get_lade_anbieter()
    tarif = db.get_aktueller_stromtarif()
    pv_ct = db.get_einstellung("pv_preis_ct") or 13.0
    # Aktueller Abo-Preis je Anbieter fuer die Vorbelegung von ct/kWh
    abo = {a: {"ac": t["preis_ac"], "dc": t["preis_dc"] or t["preis_ac"],
               "name": t["tarif_name"] or ""}
           for a, t in db.get_aktuelle_ladetarife().items()}
    return render(request, "laden.html", rows=daten, anbieter=anbieter,
                  tarif=tarif, pv_ct=pv_ct, abo=abo, aktiv="laden",
                  heute=datetime.now().strftime("%Y-%m-%d"))


@app.post("/laden")
def laden_add(datum: str = Form(...), kwh: str = Form(...),
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
    if kwh_v is not None and kwh_v > 0 and gesamt_v is not None:
        db.add_ladevorgang(datum, kwh_v, ct_v, gesamt_v, anbieter,
                           parse_de(leistung), ladetyp, notiz, blockier_v)
    return RedirectResponse("laden", status_code=303)


@app.post("/laden/update")
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
        return JSONResponse({"error": "kWh und Gesamtpreis muessen Zahlen sein."},
                            status_code=400)
    db.update_ladevorgang(id, datum, kwh_v, ct_v, gesamt_v, anbieter,
                          parse_de(leistung), ladetyp, notiz, blockier_v)
    return {"ok": True}


@app.post("/laden/delete")
def laden_delete(id: int = Form(...)):
    db.delete_ladevorgang(id)
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
    return render(request, "ladetarife.html", tarife=d["tarife"], monate=d["monate"],
                  anbieter=anbieter,
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
        return JSONResponse({"error": "Anbieter, gültig ab und ct/kWh AC sind Pflicht."},
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
                  rows=db.get_thg_eintraege(), thg_gesamt=db.get_thg_gesamt(),
                  aktiv="steuer", heute=datetime.now().strftime("%Y-%m-%d"))


@app.post("/steuer/kfz")
def steuer_kfz(betrag: str = Form(...)):
    v = parse_de(betrag, tausender=True)
    if v is not None and v >= 0:
        db.set_einstellung("kfz_steuer_benziner", v)
    return RedirectResponse("../steuer", status_code=303)


@app.post("/steuer/thg")
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
async def instandhaltung_add(request: Request):
    werte = _instandhaltung_werte(await request.form())
    if werte:
        db.add_instandhaltung(werte)
    return RedirectResponse("instandhaltung", status_code=303)


@app.post("/instandhaltung/update")
async def instandhaltung_update(request: Request):
    form = await request.form()
    werte = _instandhaltung_werte(form)
    if werte is None:
        return JSONResponse({"error": "Datum, Kategorie und Betrag sind Pflicht."},
                            status_code=400)
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
async def versicherung_add(request: Request):
    werte = _versicherung_werte(await request.form())
    if werte:
        db.add_versicherung(werte)
    return RedirectResponse("versicherung", status_code=303)


@app.post("/versicherung/update")
async def versicherung_update(request: Request):
    form = await request.form()
    werte = _versicherung_werte(form)
    if werte is None:
        return JSONResponse({"error": "Fahrzeug, Gesellschaft, gültig ab, Deckung und "
                                      "Grundbeitrag sind Pflicht."}, status_code=400)
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


def _fetch_monat(client, quelle, cfg, year, month):
    """Holt alle Werte eines Monats: zuerst aus der eingestellten Datenbank
    (datenquellen.py), was dort fehlt aus der HA-API.
    Unter "_quelle" steht je Wert, woher er kam (Name der Datenbank, HA_API oder None),
    unter "_grund", warum die Datenbank nichts geliefert hat (nur wenn eine gewaehlt ist)."""
    out = {"_quelle": {}, "_grund": {}}

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
                def pv(e):
                    v = client.get_month_sum_from_daily(e, year, month)
                    return v if v is not None else client.get_month_delta(e, year, month)
                return erster_wert(ha_ids("ha_pv_production"), pv)
            if key == "wallbox":
                return erster_wert(ha_ids("ha_wallbox_energy"),
                                   lambda e: client.get_month_delta(e, year, month))
            if key == "benzin":
                ids = ha_ids("ha_tankerkoenig") + ha_ids("ha_tankerkoenig_2")
                return client.get_month_avg_multi(ids, year, month) if ids else None
        except Exception:
            return None
        return None

    for key in ("km", "pv", "wallbox", "benzin"):
        val = quelle.monatswert(key, year, month) if quelle else None
        herkunft = quelle.name if val is not None else None
        if val is None:
            if quelle is not None:
                kurz = quelle.grund.get(key, "keine Werte")
                out["_grund"][key] = {"kurz": kurz, "lang": f"{quelle.name}: {kurz} "
                                                            f"({quelle.beschreibung(key)})"}
            val = ha(key)
            herkunft = HA_API if val is not None else None
        out[key] = round(val, 3) if val is not None else None
        out["_quelle"][key] = herkunft
    return out


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
                                "label": f"{MONATE[m-1][:3]} {y}", **werte})
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
                  mail=db.get_mail_settings(),
                  jahre=list(range(2023, now.year + 2)), jahr=now.year,
                  monat=now.month)


@app.post("/api/import/start")
def import_start(von_monat: int = Form(...), von_jahr: int = Form(...),
                 bis_monat: int = Form(...), bis_jahr: int = Form(...)):
    if (von_jahr, von_monat) > (bis_jahr, bis_monat):
        return JSONResponse({"error": "Von muss vor Bis liegen."}, status_code=400)
    cfg = db.get_ha_settings()
    if not _ha_verbindung(cfg) and cfg.get("datasource") not in datenquellen.QUELLEN:
        return JSONResponse({"error": "Keine Datenquelle konfiguriert."}, status_code=400)
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
        return JSONResponse({"error": "unbekannter Job"}, status_code=404)
    return job


@app.post("/api/import/apply")
def import_apply(payload: dict):
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
        for key, anbieter, ct in [("pv", "Privat – PV", pv_ct),
                                  ("wallbox", "Privat – Netzbezug", netz_ct)]:
            kwh = parse_de(str(r.get(key) or ""))
            if kwh is not None and kwh > 0:
                if db.ladevorgang_exists(f"{monat}-01", kwh, anbieter):
                    teile.append(f"{key} übersprungen (Duplikat)")
                else:
                    db.add_ladevorgang(f"{monat}-01", kwh, ct,
                                       round(kwh * ct / 100, 2), anbieter,
                                       11, "AC", f"Import {monat}")
                    teile.append(mit_quelle(f"{key} {kwh:.1f} kWh", key))
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
        return {"ok": False, "text": "URL oder Token fehlt"}
    ok = HAClient(**verbindung).test_connection()
    return {"ok": ok, "text": "Verbunden" if ok else "Keine Verbindung"}


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
        return JSONResponse({"error": "Keine Datenbank als Datenquelle gewählt und gespeichert."},
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
        return JSONResponse({"error": "HA nicht konfiguriert."}, status_code=400)
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


@app.get("/api/diagnose")
def sensor_diagnose(entity: str, jahr: int = 0, monat: int = 0):
    """Prueft einen Sensor: aktueller Wert + Monatswerte der letzten 3 Monate."""
    client = _ha_client()
    if client is None:
        return JSONResponse({"error": "HA nicht konfiguriert."}, status_code=400)
    if not entity.strip():
        return JSONResponse({"error": "Keine Entity angegeben."}, status_code=400)

    ergebnis = {"entity": entity, "state": None, "einheit": "", "monate": []}
    try:
        st = client._get(f"/api/states/{entity}")
        ergebnis["state"] = st.get("state")
        ergebnis["einheit"] = st.get("attributes", {}).get("unit_of_measurement", "")
        ergebnis["name"] = st.get("attributes", {}).get("friendly_name", "")
    except Exception as e:
        return JSONResponse({"error": f"Entity nicht gefunden: {e}"}, status_code=400)

    jetzt = datetime.now()
    j, m = (jahr or jetzt.year), (monat or jetzt.month)
    for _ in range(3):
        delta = client.get_month_delta(entity, j, m)
        summe = client.get_month_sum_from_daily(entity, j, m)
        mittel = client.get_month_avg(entity, j, m)
        ergebnis["monate"].append({
            "monat": f"{MONATE[m-1][:3]} {j}",
            "delta": delta, "summe": summe, "mittel": mittel,
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
                return JSONResponse({"error": "PDF zu groß (max. 20 MB)."}, status_code=400)
            tmp = os.path.join(STATIC_DIR, f"_upload_{uuid.uuid4().hex}.pdf")
            with open(tmp, "wb") as f:
                f.write(inhalt)
            try:
                anbieter, vorgaenge = parse_rechnung_pdf(tmp)
            finally:
                os.remove(tmp)
        elif text.strip():
            anbieter, vorgaenge = parse_rechnung_text(text)
        else:
            return JSONResponse({"error": "Keine PDF und kein Text."}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"anbieter": anbieter,
            "vorgaenge": [{"datum": v.datum, "kwh": v.menge_kwh,
                           "ct": v.preis_kwh, "gesamt": v.gesamtpreis,
                           "anbieter": v.anbieter, "kw": v.ladeleistung_kw,
                           "ladetyp": v.ladetyp, "notiz": v.notiz}
                          for v in vorgaenge]}


@app.post("/api/rechnung/apply")
def rechnung_apply(payload: dict):
    rows = payload.get("rows", [])
    log, fehler = [], []
    for i, r in enumerate(rows):
        datum = (r.get("datum") or "").strip()
        kwh = parse_de(str(r.get("kwh") or ""))
        gesamt = parse_de(str(r.get("gesamt") or ""))
        ct = parse_de(str(r.get("ct") or ""))
        anbieter = (r.get("anbieter") or "").strip()
        if not datum or not anbieter or kwh is None or kwh <= 0 or gesamt is None:
            fehler.append(f"Zeile {i+1}: unvollständig/ungültig")
            continue
        if ct is None and kwh:
            ct = round(gesamt / kwh * 100, 2)
        if db.ladevorgang_exists(datum, round(kwh, 3), anbieter):
            log.append(f"{datum}: bereits vorhanden – übersprungen")
            continue
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

GEHEIM_KEYS = {"ha_token"} | datenquellen.GEHEIM


@app.get("/api/settings/export")
def settings_export(secrets: int = 1):
    """Exportiert alle Einstellungen + Anbieter als JSON-Datei."""
    import json
    werte = db.get_alle_einstellungen()
    if not secrets:
        werte = {k: v for k, v in werte.items() if k not in GEHEIM_KEYS}

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
        return JSONResponse({"error": "Datei zu groß (max. 2 MB)."}, status_code=400)
    try:
        daten = json.loads(inhalt.decode("utf-8"))
    except Exception as e:
        return JSONResponse({"error": f"Datei nicht lesbar: {e}"}, status_code=400)

    if daten.get("typ") != "ev-tracker-einstellungen":
        return JSONResponse(
            {"error": "Das ist keine EV-Tracker-Einstellungsdatei."}, status_code=400)

    werte = daten.get("einstellungen") or {}
    if not isinstance(werte, dict) or not werte:
        return JSONResponse({"error": "Keine Einstellungen in der Datei."},
                            status_code=400)

    # Leere Zugangsdaten nicht über vorhandene schreiben
    vorhanden = db.get_alle_einstellungen()
    werte = {k: v for k, v in werte.items()
             if not (k in GEHEIM_KEYS and not str(v).strip() and vorhanden.get(k))}
    db.set_einstellungen(werte)

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
    """Ist der Monat abschlussreif? Prueft Datenbestand und offene Ladevorgaenge."""
    import calendar
    schluessel = f"{jahr}-{monat:02d}"
    letzter = calendar.monthrange(jahr, monat)[1]

    fahrten = {f["monat"]: f["km"] for f in db.get_fahrten_monate()}
    preise = {b["monat"] for b in db.get_benzinpreise()}
    lade = db.get_ladevorgaenge_zeitraum(f"{schluessel}-01", f"{schluessel}-{letzter:02d}")

    offen = []
    if not fahrten.get(schluessel):
        offen.append("Gefahrene Kilometer fehlen")
    if schluessel not in preise:
        offen.append(f"{berechnung.kraftstoff()['name']}preis fehlt")
    if not lade:
        offen.append("Keine Ladevorgänge erfasst")

    # Auswärts geladen, aber kein Beleg erfasst?
    ladung = ladeerkennung.pruefe_monat(jahr, monat)
    if ladung["status"] == "fehlend":
        offen.append(ladung["meldung"])

    return {"monat": schluessel, "bereit": not offen, "offen": offen,
            "ladeerkennung": ladung,
            "km": fahrten.get(schluessel), "ladevorgaenge": len(lade)}


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
             ("benzin", "€/L")]
    herkunft = werte.get("_quelle") or {}
    grund = werte.get("_grund") or {}
    teile = []
    for key, label in namen:
        if werte.get(key) is not None:
            teile.append(f"{label}={werte[key]} ({herkunft.get(key)})")
        else:
            teile.append(f"{label}=—")
    text = " · ".join(teile)
    # Warum die Datenbank nichts lieferte – je Wert eine Zeile darunter
    for key, label in namen:
        if grund.get(key):
            text += f"\n      {label}: {grund[key]['lang']}"
    return text


def _auto_import(monate: list | None = None, quelle: str = "automatisch") -> list:
    """Holt die aktuellen Monatswerte aus HA bzw. der eingestellten Datenbank und
    schreibt sie fort.

    Standardmaessig laufender Monat und Vormonat – so wird der Vormonat noch
    vervollstaendigt, falls spaet Daten nachkommen.
    Jeder Lauf wird in import.log protokolliert.
    """
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

    protokoll = []
    fehler = 0
    for jahr, monat in monate:
        schluessel = f"{jahr}-{monat:02d}"
        netz_ct = berechnung.netzpreis_monat(schluessel, tarife)
        try:
            werte = _fetch_monat(client, dq, cfg, jahr, monat)
        except Exception as e:
            fehler += 1
            _log_import([f"✗ {schluessel}: Abruf fehlgeschlagen ({e})"])
            protokoll.append(f"{schluessel}: Abruf fehlgeschlagen ({e})")
            continue

        zeilen = _rohwerte_text(werte).split("\n")
        _log_import([f"{schluessel}: gelesen {zeilen[0]}"]
                    + [f"{schluessel}:   {z.strip()}" for z in zeilen[1:]])

        teile = []
        herkunft = werte["_quelle"]
        if werte.get("km"):
            db.set_fahrt_monat(schluessel, round(werte["km"], 1))
            teile.append(f"{werte['km']:.0f} km ({herkunft['km']})")
        if werte.get("benzin"):
            db.set_benzinpreis(schluessel, round(werte["benzin"], 3))
            teile.append(f"{werte['benzin']:.3f} €/L ({herkunft['benzin']})")
        for key, anbieter, ct in [("pv", "Privat – PV", pv_ct),
                                  ("wallbox", "Privat – Netzbezug", netz_ct)]:
            kwh = werte.get(key)
            if kwh:
                ergebnis = db.upsert_auto_ladevorgang(
                    f"{schluessel}-01", round(kwh, 3), ct,
                    round(kwh * ct / 100, 2), anbieter)
                if ergebnis != "unveraendert":
                    teile.append(f"{key} {kwh:.1f} kWh ({ergebnis}, {herkunft[key]})")
        zeile = ", ".join(teile) if teile else "keine neuen Werte"
        _log_import([f"{schluessel}: übernommen {zeile}"])
        protokoll.append(f"{schluessel}: {zeile}")

    # Verbrauch aus dem Akkustand fortschreiben (Datenbank oder HA-API, wie eingestellt)
    if client is not None or dq is not None:
        try:
            meldung = akkuverbrauch.aktualisieren()
        except Exception as e:
            meldung = f"Fehler ({e})"
        _log_import([f"Akkuverbrauch: {meldung}"])
        protokoll.append(f"Akkuverbrauch: {meldung}")

    _log_import([f"Abruf beendet – {len(monate)} Monat(e), {fehler} Fehler"])
    return protokoll


@app.post("/api/import/auto")
def auto_import_jetzt():
    """Naechtlichen Abruf manuell ausloesen."""
    protokoll = _auto_import(quelle="manuell")
    db.set_einstellung("auto_import_letzter",
                       f"{datetime.now():%Y-%m-%d %H:%M} · " + " | ".join(protokoll))
    return {"ok": True, "protokoll": protokoll}


@app.get("/api/import/log")
def import_log(zeilen: int = 200):
    """Letzte Zeilen des Importprotokolls (neueste zuletzt)."""
    if not os.path.exists(IMPORT_LOG_DATEI):
        return {"zeilen": [], "meldung": "Noch kein Abruf protokolliert"}
    try:
        with open(IMPORT_LOG_DATEI, encoding="utf-8", errors="replace") as f:
            alle = f.readlines()
        return {"zeilen": [z.rstrip() for z in alle[-zeilen:]]}
    except Exception as e:
        return {"zeilen": [], "meldung": str(e)}


def _versand_pruefen():
    """Verschickt faellige Berichte. Merker verhindert Doppelversand."""
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
                    hinweis = ("Hinweis: Der Monat war beim Versand noch unvollständig – "
                               + "; ".join(pruefung["offen"]))
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
            if db.get_mail_settings().get("auto_import", "1") == "1":
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


@app.get("/backup", response_class=HTMLResponse)
def backup_seite(request: Request):
    return render(request, "backup.html", aktiv="backup", db_pfad=db.DB_PATH,
                  add_on_modus=IST_ADDON)


@app.get("/api/backup/status")
def backup_status():
    """Status des letzten Backups (wird von backup.sh geschrieben)."""
    import json
    if not os.path.exists(STATUS_DATEI):
        return {"status": "never", "meldung": "Noch kein Backup gelaufen"}
    try:
        with open(STATUS_DATEI, encoding="utf-8") as f:
            daten = json.load(f)
    except Exception as e:
        return {"status": "error", "meldung": f"Statusdatei unlesbar: {e}"}

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
        return {"zeilen": [], "meldung": "Noch kein Protokoll vorhanden"}
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
            "meldung": "Backup angefordert – startet innerhalb der naechsten Minuten."}


@app.post("/api/backup/restore")
async def backup_restore(datei: UploadFile = File(...), bestaetigt: str = Form("")):
    """Stellt eine gesicherte Datenbank wieder her (mit Sicherheitskopie vorher)."""
    import sqlite3
    if bestaetigt != "ja":
        return JSONResponse({"error": "Nicht bestaetigt."}, status_code=400)

    roh = await datei.read()
    if not roh.startswith(b"SQLite format 3"):
        return JSONResponse({"error": "Das ist keine SQLite-Datenbank."}, status_code=400)

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
                {"error": f"Datei ist keine EV-Tracker-Datenbank (fehlend: {', '.join(sorted(fehlend))})"},
                status_code=400)
    except Exception as e:
        os.remove(tmp)
        return JSONResponse({"error": f"Datei nicht lesbar: {e}"}, status_code=400)

    # Sicherheitskopie der aktuellen Datenbank
    sicherung = _sicherungskopie("vor_restore")

    os.replace(tmp, db.DB_PATH)
    db.init_db()
    return {"ok": True, "sicherung": sicherung,
            "meldung": "Datenbank wiederhergestellt."}


@app.get("/api/reset/vorschau")
def reset_vorschau():
    """Was ein Zuruecksetzen loeschen wuerde – Grundlage fuer die Rueckfrage."""
    anzahl = db.zaehle_messdaten()
    return {"bereiche": [{"key": k, "titel": titel, "anzahl": anzahl.get(k, 0)}
                         for k, (_, titel) in db.MESSDATEN_BEREICHE.items()]}


@app.post("/api/reset")
def reset_messdaten(bereiche: str = Form(""), bestaetigt: str = Form("")):
    """Leert die gewaehlten Messdaten-Tabellen (Fahrzeugwechsel, Testdaten raus).

    Einstellungen, Stromtarife, Lade-Anbieter und die HA-Konfiguration bleiben.
    Vorher wird die Datenbank als vor_reset_….db im Datenordner gesichert.
    """
    if bestaetigt != "ja":
        return JSONResponse({"error": "Nicht bestaetigt."}, status_code=400)
    gewaehlt = [b for b in bereiche.split(",") if b in db.MESSDATEN_BEREICHE]
    if not gewaehlt:
        return JSONResponse({"error": "Kein Bereich gewaehlt."}, status_code=400)

    sicherung = _sicherungskopie("vor_reset")
    geloescht = db.loesche_messdaten(gewaehlt)
    text = ", ".join(f"{db.MESSDATEN_BEREICHE[b][1]}: {n}"
                     for b, n in geloescht.items())
    return {"ok": True, "sicherung": sicherung,
            "geloescht": geloescht, "meldung": f"Zurückgesetzt – {text}"}


@app.get("/api/backup")
def backup(token: str = ""):
    """Liefert eine konsistente Kopie der SQLite-Datenbank.
    Als Add-on reicht die Ingress-Authentifizierung durch HA, daher kein Token
    nötig. Im Standalone-Docker-Betrieb weiterhin nur mit EV_TRACKER_BACKUP_TOKEN,
    weil der Endpunkt dort ohne HA-Login direkt aus dem Netz erreichbar ist."""
    if not IST_ADDON:
        if not BACKUP_TOKEN:
            return JSONResponse(
                {"error": "Backup deaktiviert – EV_TRACKER_BACKUP_TOKEN nicht gesetzt."},
                status_code=403)
        if token != BACKUP_TOKEN:
            return JSONResponse({"error": "Ungültiger Token."}, status_code=403)

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
    ("ha_odometer",       "fn_odometer",       "Kilometerstand (km)"),
    ("ha_pv_production",  "fn_pv_production",  "PV ins Auto geladen (kWh)"),
    ("ha_wallbox_energy", "fn_wallbox_energy", "Netz ins Auto geladen (kWh)"),
    ("ha_tankerkoenig",   "fn_tankerkoenig",   "Benzinpreis Sensor 1 (€/L)"),
    ("ha_tankerkoenig_2", "fn_tankerkoenig_2", "Benzinpreis Sensor 2 (€/L)"),
    # Fuer Ladeerkennung und Verbrauch aus dem Akkustand
    ("ha_ev_battery",     "fn_ev_battery",     "Batteriestand Auto (%)"),
]


@app.get("/einstellungen", response_class=HTMLResponse)
def einstellungen(request: Request):
    ha_settings = db.get_ha_settings()
    return render(request, "einstellungen.html",
                  cfg=db.get_config(),
                  fahrzeug_name=db.get_einstellung_str("fahrzeug_name") or "",
                  kfz=db.get_einstellung("kfz_steuer_benziner") or 0.0,
                  kraftstoffe=berechnung.KRAFTSTOFFE,
                  ha=ha_settings,
                  add_on_modus=IST_ADDON,
                  supervisor_aktiv=IST_ADDON
                                   and not (ha_settings.get("ha_url") and ha_settings.get("ha_token")),
                  anbieter=db.get_lade_anbieter(),
                  sensor_felder=[(h, f, l.replace("Benzinpreis", berechnung.kraftstoff()["name"] + "preis"))
                                 for h, f, l in SENSOR_FELDER],
                  quellen=datenquellen.QUELLEN,
                  prom_standard=datenquellen.PROM_SELEKTOR_STANDARD,
                  aktiv="einstellungen")


@app.post("/einstellungen/parameter")
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
    db.save_ha_settings(settings)
    return RedirectResponse("../einstellungen", status_code=303)
