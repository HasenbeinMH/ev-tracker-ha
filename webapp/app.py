"""
EV Tracker – Web-Version (FastAPI)
Nutzt dieselben Kern-Module wie die Desktop-App:
database.py, berechnung.py, ha_client.py, pdf_parser.py, charts.py
"""
import os
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
import berechnung
import charts
from ha_client import HAClient, InfluxClient
from pdf_parser import parse_rechnung_pdf, parse_rechnung_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]


def _ensure_plotly_js():
    path = os.path.join(STATIC_DIR, "plotly.min.js")
    if not os.path.exists(path):
        import plotly.offline
        os.makedirs(STATIC_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(plotly.offline.get_plotlyjs())


db.init_db()
db.init_ha_settings()
_ensure_plotly_js()

app = FastAPI(title="EV Tracker")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals["MONATE"] = MONATE


def render(request, template, **ctx):
    ctx["now"] = datetime.now()
    return templates.TemplateResponse(request, template, ctx)


def parse_de(text) -> float | None:
    """Komma/Punkt-tolerantes Zahlen-Parsen; None bei leer/ungültig."""
    t = (text or "").strip().replace(",", ".")
    if not t:
        return None
    try:
        return float(t)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────────
#  Dashboard
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    fahrten = db.get_fahrten_alle_als_liste()
    lade = db.get_ladevorgaenge(limit=10000)
    benzin = db.get_benzinpreise()
    stromtarife = db.get_stromtarife()
    thg = db.get_thg_eintraege()
    cfg = db.get_config()
    kz = berechnung.ersparnis_uebersicht()

    charts_html = {
        "monatlich": charts.chart_monatliche_ersparnis(
            fahrten, benzin, lade, benziner_l=cfg["benziner_verbrauch"], large=True),
        "kosten": charts.chart_kosten_vergleich(
            kz["benzin_kosten"], kz["strom_kosten"], large=True),
        "co2": charts.chart_co2_ersparnis(
            fahrten, benziner_l=cfg["benziner_verbrauch"],
            co2_faktor=cfg["co2_faktor_benzin"], large=True),
        "verbrauch": charts.chart_verbrauch_100km(
            lade, fahrten, ev_ref=cfg["ev_verbrauch"], large=True),
        "benzin": charts.chart_benzinpreise(benzin, large=True),
        "strom": charts.chart_stromtarif(stromtarife, large=True),
        "anbieter": charts.chart_anbieter_verteilung(lade, large=True),
        "thg": charts.chart_thg(thg, large=True),
    }
    return render(request, "dashboard.html", kz=kz, charts=charts_html, aktiv="dashboard")


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
    return render(request, "fahrten.html", rows=rows, aktiv="fahrten")


@app.post("/fahrten")
def fahrten_add(monat: str = Form(...), km: str = Form(...)):
    v = parse_de(km)
    if v is not None and v >= 0:
        db.set_fahrt_monat(monat, v)
    return RedirectResponse("/fahrten", status_code=303)


@app.post("/fahrten/delete")
def fahrten_delete(monat: str = Form(...)):
    db.delete_fahrt_monat(monat)
    return RedirectResponse("/fahrten", status_code=303)


# ─────────────────────────────────────────────────────────────
#  Laden
# ─────────────────────────────────────────────────────────────

@app.get("/laden", response_class=HTMLResponse)
def laden(request: Request):
    daten = db.get_ladevorgaenge(limit=500)
    anbieter = db.get_lade_anbieter()
    tarif = db.get_aktueller_stromtarif()
    pv_ct = db.get_einstellung("pv_preis_ct") or 13.0
    return render(request, "laden.html", rows=daten, anbieter=anbieter,
                  tarif=tarif, pv_ct=pv_ct, aktiv="laden",
                  heute=datetime.now().strftime("%Y-%m-%d"))


@app.post("/laden")
def laden_add(datum: str = Form(...), kwh: str = Form(...),
              preis_kwh: str = Form(""), gesamt: str = Form(""),
              anbieter: str = Form(...), leistung: str = Form(""),
              ladetyp: str = Form("AC"), notiz: str = Form("")):
    kwh_v = parse_de(kwh)
    ct_v = parse_de(preis_kwh)
    gesamt_v = parse_de(gesamt)
    if gesamt_v is None and kwh_v is not None and ct_v is not None:
        gesamt_v = round(kwh_v * ct_v / 100, 2)
    if kwh_v is not None and kwh_v > 0 and gesamt_v is not None:
        db.add_ladevorgang(datum, kwh_v, ct_v, gesamt_v, anbieter,
                           parse_de(leistung), ladetyp, notiz)
    return RedirectResponse("/laden", status_code=303)


@app.post("/laden/delete")
def laden_delete(id: int = Form(...)):
    db.delete_ladevorgang(id)
    return RedirectResponse("/laden", status_code=303)


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
    return RedirectResponse("/benzin", status_code=303)


@app.post("/benzin/delete")
def benzin_delete(monat: str = Form(...)):
    db.delete_benzinpreis(monat)
    return RedirectResponse("/benzin", status_code=303)


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
    return RedirectResponse("/stromtarif", status_code=303)


@app.post("/stromtarif/delete")
def stromtarif_delete(id: int = Form(...)):
    db.delete_stromtarif(id)
    return RedirectResponse("/stromtarif", status_code=303)


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
    v = parse_de(betrag)
    if v is not None and v >= 0:
        db.set_einstellung("kfz_steuer_benziner", v)
    return RedirectResponse("/steuer", status_code=303)


@app.post("/steuer/thg")
def steuer_thg_add(datum: str = Form(...), betrag: str = Form(...),
                   anbieter: str = Form(""), notiz: str = Form("")):
    v = parse_de(betrag)
    if v is not None and v > 0:
        db.add_thg(datum, v, anbieter or "Sonstige", notiz)
    return RedirectResponse("/steuer", status_code=303)


@app.post("/steuer/thg/delete")
def steuer_thg_delete(id: int = Form(...)):
    db.delete_thg(id)
    return RedirectResponse("/steuer", status_code=303)


# ─────────────────────────────────────────────────────────────
#  HA / InfluxDB Import
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


def _make_influx_client(cfg):
    return InfluxClient(
        url=cfg.get("influx_url", "http://localhost"),
        port=int(cfg.get("influx_port", "8086")),
        database=cfg.get("influx_database", "home_assistant"),
        user=cfg.get("influx_user", ""),
        password=cfg.get("influx_password", ""),
        meas_km=cfg.get("influx_measurement_km", "km"),
        meas_kwh=cfg.get("influx_measurement_kwh", "kWh"),
        meas_eur_l=cfg.get("influx_measurement_eur_l", "EUR/L"),
    )


def _fetch_monat(client, ic, cfg, use_influx, year, month):
    """Holt alle Werte eines Monats (InfluxDB primär, HA-API-Fallback)."""
    out = {}

    def influx(key):
        if not ic:
            return None
        meas_km = cfg.get("influx_measurement_km", "km")
        meas_kwh = cfg.get("influx_measurement_kwh", "kWh")
        meas_eur = cfg.get("influx_measurement_eur_l", "EUR/L")
        try:
            if key == "km":
                fn = cfg.get("fn_odometer", "").strip()
                return ic.get_month_delta(fn, meas_km, year, month) if fn else None
            if key == "pv":
                fn = cfg.get("fn_pv_production", "").strip()
                return ic.get_month_sum(fn, meas_kwh, year, month) if fn else None
            if key == "wallbox":
                fn = cfg.get("fn_wallbox_energy", "").strip()
                return ic.get_month_sum(fn, meas_kwh, year, month) if fn else None
            if key == "benzin":
                fns = [f for f in [cfg.get("fn_tankerkoenig", "").strip(),
                                   cfg.get("fn_tankerkoenig_2", "").strip()] if f]
                return ic.get_month_avg(fns, meas_eur, year, month) if fns else None
        except Exception:
            return None
        return None

    def ha(key):
        if not client:
            return None
        try:
            if key == "km":
                eid = cfg.get("ha_odometer", "")
                return client.get_month_delta(eid, year, month) if eid else None
            if key == "pv":
                eid = cfg.get("ha_pv_production", "")
                if not eid:
                    return None
                v = client.get_month_sum_from_daily(eid, year, month)
                return v if v is not None else client.get_month_delta(eid, year, month)
            if key == "wallbox":
                eid = cfg.get("ha_wallbox_energy", "")
                return client.get_month_delta(eid, year, month) if eid else None
            if key == "benzin":
                ids = [e for e in [cfg.get("ha_tankerkoenig", "").strip(),
                                   cfg.get("ha_tankerkoenig_2", "").strip()] if e]
                return client.get_month_avg_multi(ids, year, month) if ids else None
        except Exception:
            return None
        return None

    for key in ("km", "pv", "wallbox", "benzin"):
        val = influx(key) if use_influx else None
        if val is None:
            val = ha(key)
        out[key] = round(val, 3) if val is not None else None
    return out


def _import_worker(job_id, monate, cfg):
    job = _import_jobs[job_id]
    use_influx = cfg.get("datasource", "ha") == "influxdb"
    client = None
    if cfg.get("ha_url") and cfg.get("ha_token"):
        client = HAClient(cfg["ha_url"], cfg["ha_token"])
    ic = None
    if use_influx:
        try:
            ic = _make_influx_client(cfg)
        except Exception as e:
            job["fehler"].append(str(e))
    try:
        for i, (y, m) in enumerate(monate):
            werte = _fetch_monat(client, ic, cfg, use_influx, y, m)
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
                  jahre=list(range(2023, now.year + 2)), jahr=now.year,
                  monat=now.month)


@app.post("/api/import/start")
def import_start(von_monat: int = Form(...), von_jahr: int = Form(...),
                 bis_monat: int = Form(...), bis_jahr: int = Form(...)):
    if (von_jahr, von_monat) > (bis_jahr, bis_monat):
        return JSONResponse({"error": "Von muss vor Bis liegen."}, status_code=400)
    cfg = db.get_ha_settings()
    if not (cfg.get("ha_url") and cfg.get("ha_token")) and \
            cfg.get("datasource") != "influxdb":
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
    tarif = db.get_aktueller_stromtarif()
    netz_ct = tarif["preis_kwh"] if tarif else 30.0
    log = []
    for r in rows:
        monat = r.get("monat", "")
        if not monat:
            continue
        teile = []
        km = parse_de(str(r.get("km") or ""))
        if km is not None and km > 0:
            db.set_fahrt_monat(monat, round(km, 1))
            teile.append(f"{km:.0f} km")
        benzin = parse_de(str(r.get("benzin") or ""))
        if benzin is not None and benzin > 0:
            db.set_benzinpreis(monat, round(benzin, 3))
            teile.append(f"{benzin:.3f} €/L")
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
                    teile.append(f"{key} {kwh:.1f} kWh")
        if teile:
            log.append(f"{monat}: " + ", ".join(teile))
    return {"log": log}


@app.post("/api/test/ha")
def test_ha():
    cfg = db.get_ha_settings()
    if not (cfg.get("ha_url") and cfg.get("ha_token")):
        return {"ok": False, "text": "URL oder Token fehlt"}
    ok = HAClient(cfg["ha_url"], cfg["ha_token"]).test_connection()
    return {"ok": ok, "text": "Verbunden" if ok else "Keine Verbindung"}


@app.post("/api/test/influx")
def test_influx():
    cfg = db.get_ha_settings()
    try:
        ok = _make_influx_client(cfg).test_connection()
    except Exception as e:
        return {"ok": False, "text": str(e)}
    return {"ok": ok, "text": f"Verbunden · '{cfg.get('influx_database')}' gefunden"
            if ok else "Keine Verbindung oder Datenbank nicht gefunden"}


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
            tmp = os.path.join(STATIC_DIR, f"_upload_{uuid.uuid4().hex}.pdf")
            with open(tmp, "wb") as f:
                f.write(await pdf.read())
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

GEHEIM_KEYS = {"ha_token", "influx_password"}


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
    try:
        daten = json.loads((await datei.read()).decode("utf-8"))
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
#  Backup der Datenbank (Token-geschützt)
# ─────────────────────────────────────────────────────────────

BACKUP_TOKEN = os.environ.get("EV_TRACKER_BACKUP_TOKEN", "")


@app.get("/api/backup")
def backup(token: str = ""):
    """Liefert eine konsistente Kopie der SQLite-Datenbank.
    Nur aktiv, wenn EV_TRACKER_BACKUP_TOKEN gesetzt ist."""
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

SENSOR_FELDER = [
    ("ha_odometer",         "fn_odometer",         "Odometer (km)"),
    ("ha_ev_battery",       None,                  "EV Batterie (%)"),
    ("ha_ev_range",         None,                  "Reichweite (km)"),
    ("ha_pv_production",    "fn_pv_production",    "PV Erzeugung (kWh)"),
    ("ha_grid_consumption", "fn_grid_consumption", "Netzbezug (kWh)"),
    ("ha_grid_export",      "fn_grid_export",      "Netzeinspeisung (kWh)"),
    ("ha_wallbox_energy",   "fn_wallbox_energy",   "Wallbox geladen (kWh)"),
    ("ha_tankerkoenig",     "fn_tankerkoenig",     "Tankerkönig E10 Sensor 1"),
    ("ha_tankerkoenig_2",   "fn_tankerkoenig_2",   "Tankerkönig E10 Sensor 2"),
]


@app.get("/einstellungen", response_class=HTMLResponse)
def einstellungen(request: Request):
    return render(request, "einstellungen.html",
                  cfg=db.get_config(),
                  kfz=db.get_einstellung("kfz_steuer_benziner") or 0.0,
                  ha=db.get_ha_settings(),
                  anbieter=db.get_lade_anbieter(),
                  sensor_felder=SENSOR_FELDER,
                  aktiv="einstellungen")


@app.post("/einstellungen/parameter")
def einstellungen_parameter(benziner_verbrauch: str = Form(...),
                            ev_verbrauch: str = Form(...),
                            pv_preis: str = Form(...),
                            co2_benzin: str = Form(...),
                            kfz_steuer: str = Form(...)):
    for key, raw in [("benziner_verbrauch", benziner_verbrauch),
                     ("ev_verbrauch_default", ev_verbrauch),
                     ("pv_preis_ct", pv_preis),
                     ("co2_faktor_benzin", co2_benzin),
                     ("kfz_steuer_benziner", kfz_steuer)]:
        v = parse_de(raw)
        if v is not None:
            db.set_einstellung(key, v)
    return RedirectResponse("/einstellungen", status_code=303)


@app.post("/einstellungen/anbieter")
def anbieter_add(name: str = Form(...), gruenstrom: str = Form("")):
    if name.strip():
        db.add_lade_anbieter(name.strip(), 1 if gruenstrom else 0)
    return RedirectResponse("/einstellungen", status_code=303)


@app.post("/einstellungen/anbieter/delete")
def anbieter_delete(id: int = Form(...)):
    db.delete_lade_anbieter(id)
    return RedirectResponse("/einstellungen", status_code=303)


@app.post("/einstellungen/ha")
async def einstellungen_ha(request: Request):
    form = await request.form()
    keys = ["ha_url", "ha_token", "datasource",
            "influx_url", "influx_port", "influx_database",
            "influx_user", "influx_password",
            "influx_measurement_km", "influx_measurement_kwh",
            "influx_measurement_eur_l"]
    keys += [k for k, _, _ in ((h, f, l) for h, f, l in SENSOR_FELDER)]
    keys += [f for _, f, _ in SENSOR_FELDER if f]
    settings = {}
    for key in keys:
        if key in form:
            settings[key] = str(form[key]).strip()
    # Leeres Token-Feld = Token behalten (Maskierung)
    if settings.get("ha_token") == "":
        settings.pop("ha_token")
    if settings.get("influx_password") == "":
        settings.pop("influx_password")
    db.save_ha_settings(settings)
    return RedirectResponse("/einstellungen", status_code=303)
