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
import berichte
import ladeerkennung
import mailer
import charts
from version import VERSION, CHANGELOG
from ha_client import HAClient, InfluxClient
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

app = FastAPI(title="EV Tracker")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals["MONATE"] = MONATE
templates.env.globals["VERSION"] = VERSION


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
            fahrten, benzin, lade, benziner_l=cfg["benziner_verbrauch"]),
        "kosten": charts.chart_kosten_vergleich(
            kz["benzin_kosten"], kz["strom_kosten"]),
        "co2": charts.chart_co2_ersparnis(
            fahrten, benziner_l=cfg["benziner_verbrauch"],
            co2_faktor=cfg["co2_faktor_benzin"]),
        "verbrauch": charts.chart_verbrauch_100km(
            lade, fahrten, ev_ref=cfg["ev_verbrauch"]),
        "benzin": charts.chart_benzinpreise(benzin),
        "strom": charts.chart_stromtarif(stromtarife),
        "anbieter": charts.chart_anbieter_verteilung(lade),
        "thg": charts.chart_thg(thg),
    }
    return render(request, "dashboard.html", kz=kz, charts=charts_html, aktiv="dashboard")


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
    return render(request, "fahrten.html", rows=rows, aktiv="fahrten",
                  verbrauch=berechnung.verbrauch_statistik())


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


@app.post("/laden/update")
def laden_update(id: int = Form(...), datum: str = Form(...), kwh: str = Form(...),
                 preis_kwh: str = Form(""), gesamt: str = Form(""),
                 anbieter: str = Form(...), leistung: str = Form(""),
                 ladetyp: str = Form("AC"), notiz: str = Form("")):
    kwh_v = parse_de(kwh)
    ct_v = parse_de(preis_kwh)
    gesamt_v = parse_de(gesamt)
    if gesamt_v is None and kwh_v is not None and ct_v is not None:
        gesamt_v = round(kwh_v * ct_v / 100, 2)
    if kwh_v is None or kwh_v <= 0 or gesamt_v is None:
        return JSONResponse({"error": "kWh und Gesamtpreis muessen Zahlen sein."},
                            status_code=400)
    db.update_ladevorgang(id, datum, kwh_v, ct_v, gesamt_v, anbieter,
                          parse_de(leistung), ladetyp, notiz)
    return {"ok": True}


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
                  mail=db.get_mail_settings(),
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
    _log_import([f"Zeitraum-Import übernommen ({len(log)} Monat(e))"] + log,
                trenner=True)
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
#  Sensor-Suche und -Diagnose
# ─────────────────────────────────────────────────────────────

def _ha_client():
    cfg = db.get_ha_settings()
    if not (cfg.get("ha_url") and cfg.get("ha_token")):
        return None
    return HAClient(cfg["ha_url"], cfg["ha_token"])


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
        offen.append("Benzinpreis fehlt")
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
    return RedirectResponse("/berichte", status_code=303)


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
    """Gelesene Sensorwerte lesbar machen – '—' fuer nicht gelieferte Werte."""
    namen = [("km", "km"), ("pv", "PV kWh"), ("wallbox", "Netz kWh"),
             ("benzin", "€/L")]
    return " · ".join(
        f"{label}={werte.get(key) if werte.get(key) is not None else '—'}"
        for key, label in namen)


def _auto_import(monate: list | None = None, quelle: str = "automatisch") -> list:
    """Holt die aktuellen Monatswerte aus HA/InfluxDB und schreibt sie fort.

    Standardmaessig laufender Monat und Vormonat – so wird der Vormonat noch
    vervollstaendigt, falls spaet Daten nachkommen.
    Jeder Lauf wird in import.log protokolliert.
    """
    cfg = db.get_ha_settings()
    use_influx = cfg.get("datasource", "ha") == "influxdb"
    quelle_text = "InfluxDB (Fallback HA-API)" if use_influx else "Home Assistant API"
    _log_import([f"Abruf gestartet ({quelle}) · Quelle: {quelle_text}"], trenner=True)

    client = None
    if cfg.get("ha_url") and cfg.get("ha_token"):
        client = HAClient(cfg["ha_url"], cfg["ha_token"])
    ic = None
    if use_influx:
        try:
            ic = _make_influx_client(cfg)
        except Exception as e:
            _log_import([f"✗ InfluxDB nicht nutzbar: {e}", "Abruf abgebrochen"])
            return [f"InfluxDB nicht nutzbar: {e}"]
    if client is None and ic is None:
        _log_import(["✗ Keine Datenquelle konfiguriert", "Abruf abgebrochen"])
        return ["Keine Datenquelle konfiguriert"]

    if monate is None:
        jetzt = datetime.now()
        vorher = ((jetzt.year, jetzt.month - 1) if jetzt.month > 1
                  else (jetzt.year - 1, 12))
        monate = [vorher, (jetzt.year, jetzt.month)]

    pv_ct = db.get_einstellung("pv_preis_ct") or 13.0
    tarif = db.get_aktueller_stromtarif()
    netz_ct = tarif["preis_kwh"] if tarif else 30.0

    protokoll = []
    fehler = 0
    for jahr, monat in monate:
        schluessel = f"{jahr}-{monat:02d}"
        try:
            werte = _fetch_monat(client, ic, cfg, use_influx, jahr, monat)
        except Exception as e:
            fehler += 1
            _log_import([f"✗ {schluessel}: Abruf fehlgeschlagen ({e})"])
            protokoll.append(f"{schluessel}: Abruf fehlgeschlagen ({e})")
            continue

        _log_import([f"{schluessel}: gelesen {_rohwerte_text(werte)}"])

        teile = []
        if werte.get("km"):
            db.set_fahrt_monat(schluessel, round(werte["km"], 1))
            teile.append(f"{werte['km']:.0f} km")
        if werte.get("benzin"):
            db.set_benzinpreis(schluessel, round(werte["benzin"], 3))
            teile.append(f"{werte['benzin']:.3f} €/L")
        for key, anbieter, ct in [("pv", "Privat – PV", pv_ct),
                                  ("wallbox", "Privat – Netzbezug", netz_ct)]:
            kwh = werte.get(key)
            if kwh:
                ergebnis = db.upsert_auto_ladevorgang(
                    f"{schluessel}-01", round(kwh, 3), ct,
                    round(kwh * ct / 100, 2), anbieter)
                if ergebnis != "unveraendert":
                    teile.append(f"{key} {kwh:.1f} kWh ({ergebnis})")
        zeile = ", ".join(teile) if teile else "keine neuen Werte"
        _log_import([f"{schluessel}: übernommen {zeile}"])
        protokoll.append(f"{schluessel}: {zeile}")

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


@app.get("/backup", response_class=HTMLResponse)
def backup_seite(request: Request):
    return render(request, "backup.html", aktiv="backup", db_pfad=db.DB_PATH)


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
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    sicherung = os.path.join(DATA_DIR, f"vor_restore_{stamp}.db")
    if os.path.exists(db.DB_PATH):
        quelle = sqlite3.connect(db.DB_PATH)
        kopie = sqlite3.connect(sicherung)
        try:
            with kopie:
                quelle.backup(kopie)
        finally:
            kopie.close()
            quelle.close()

    os.replace(tmp, db.DB_PATH)
    db.init_db()
    return {"ok": True, "sicherung": os.path.basename(sicherung),
            "meldung": "Datenbank wiederhergestellt."}


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

# Nur diese Sensoren werden tatsaechlich importiert.
SENSOR_FELDER = [
    ("ha_odometer",       "fn_odometer",       "Kilometerstand (km)"),
    ("ha_pv_production",  "fn_pv_production",  "PV ins Auto geladen (kWh)"),
    ("ha_wallbox_energy", "fn_wallbox_energy", "Netz ins Auto geladen (kWh)"),
    ("ha_tankerkoenig",   "fn_tankerkoenig",   "Benzinpreis Sensor 1 (€/L)"),
    ("ha_tankerkoenig_2", "fn_tankerkoenig_2", "Benzinpreis Sensor 2 (€/L)"),
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
