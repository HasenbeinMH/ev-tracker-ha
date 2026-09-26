"""
Chart-Definitionen fuer das Dashboard (Apache ECharts).

Jede Funktion liefert ein ECharts-Option-Dict, das als JSON an den Browser geht
und dort von static/charts.js gezeichnet wird. Zahlen- und Datumsformatierung
laeuft im Browser: Strings der Form "fn:<name>" werden in charts.js durch die
gleichnamige Formatierfunktion ersetzt (JSON kann keine Funktionen transportieren).

Kurven werden bewusst nicht geglaettet – bei Monatswerten wuerden Zwischenwerte
vorgetaeuscht, die es nicht gibt.
"""
import calendar
import math
from datetime import date

# Gedaempfte, professionelle Farbpalette (passend zu webapp/static/style.css)
COLORS = {
    "bg":       "#12141a",
    "card":     "#1c1f28",
    "blue":     "#4a90c4",
    "green":    "#5aaa78",
    "orange":   "#c47a3a",
    "purple":   "#7a6aaa",
    "teal":     "#3a9aaa",
    "red":      "#aa5a5a",
    "text":     "#c8ccd4",
    "subtext":  "#6b7280",
    "grid":     "#252830",
    "border":   "#2e3340",
}

# Hellere Variante je Farbe fuer das obere Ende der Balken-Verlaeufe
_HELL = {
    "blue":   "#6fb0e0",
    "green":  "#7cc896",
    "orange": "#e8984f",
    "purple": "#9a8acb",
    "teal":   "#5cbccc",
}


def _rgba(hex_farbe, alpha):
    h = hex_farbe.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _verlauf(oben, unten, horizontal=False):
    """Linearer Farbverlauf; vertikal von oben nach unten, horizontal von links nach rechts."""
    return {
        "type": "linear", "x": 0, "y": 0,
        "x2": 1 if horizontal else 0, "y2": 0 if horizontal else 1,
        "colorStops": [{"offset": 0, "color": oben}, {"offset": 1, "color": unten}],
    }


def _balken_farbe(name, horizontal=False):
    if horizontal:
        return _verlauf(COLORS[name], _HELL[name], horizontal=True)
    return _verlauf(_HELL[name], COLORS[name])


def _flaeche(name):
    return {"color": _verlauf(_rgba(COLORS[name], 0.35), _rgba(COLORS[name], 0.02))}


def _achse_wert(**extra):
    achse = {
        "type": "value",
        "axisLine": {"show": False},
        "axisTick": {"show": False},
        "axisLabel": {"color": COLORS["subtext"], "fontSize": 10,
                      "formatter": "fn:zahl"},
        "splitLine": {"lineStyle": {"color": COLORS["grid"], "type": "dashed"}},
    }
    achse.update(extra)
    return achse


def _achse_kategorie(werte, formatter="fn:monat", **extra):
    """Kategorie-Achse; formatter gilt fuer Achsenbeschriftung und Tooltip-Kopfzeile."""
    achse = {
        "type": "category",
        "data": werte,
        "axisLine": {"lineStyle": {"color": COLORS["border"]}},
        "axisTick": {"show": False},
        "axisLabel": {"color": COLORS["subtext"], "fontSize": 10},
    }
    if formatter:
        achse["axisLabel"]["formatter"] = formatter
        achse["axisPointer"] = {"label": {"formatter": formatter + ":ap"}}
    achse.update(extra)
    return achse


def _zoom(anzahl, kategorie=True):
    """Schieberegler zum Eingrenzen des Zeitraums – ab 3 Werten gibt es etwas einzugrenzen."""
    if anzahl < 3:
        return None
    regler = {
        "type": "slider",
        "height": 16,
        "bottom": 6,
        "borderColor": COLORS["border"],
        "backgroundColor": "rgba(0,0,0,0)",
        "fillerColor": _rgba(COLORS["blue"], 0.10),
        "handleStyle": {"color": COLORS["border"], "borderColor": COLORS["subtext"]},
        "moveHandleStyle": {"color": COLORS["border"]},
        "dataBackground": {"lineStyle": {"color": COLORS["border"]},
                           "areaStyle": {"color": _rgba(COLORS["subtext"], 0.15)}},
        "selectedDataBackground": {"lineStyle": {"color": COLORS["subtext"]},
                                   "areaStyle": {"color": _rgba(COLORS["subtext"], 0.25)}},
        "textStyle": {"color": COLORS["subtext"], "fontSize": 10},
        "brushSelect": False,
    }
    if kategorie:
        regler["labelFormatter"] = "fn:zoomMonat"
    else:
        regler["labelFormatter"] = "fn:zoomDatum"
    return [regler]


def _werkzeuge(umschalten=True):
    """Kleine Werkzeugleiste oben rechts: Darstellung wechseln, Ansicht zuruecksetzen."""
    werkzeug = {
        "show": True,
        "right": 6,
        "top": 2,
        "itemSize": 13,
        "itemGap": 10,
        "iconStyle": {"borderColor": COLORS["subtext"]},
        "emphasis": {"iconStyle": {"borderColor": COLORS["text"]}},
        "feature": {"restore": {"title": "Zurücksetzen"}},
    }
    if umschalten:
        werkzeug["feature"] = {
            "magicType": {"type": ["bar", "line"],
                          "title": {"bar": "Als Balken", "line": "Als Linie"}},
            "restore": {"title": "Zurücksetzen"},
        }
    return werkzeug


def _basis(**extra):
    opt = {
        "backgroundColor": "transparent",
        "textStyle": {"fontFamily": "Segoe UI, system-ui, sans-serif",
                      "color": COLORS["text"]},
        "animationDuration": 600,
        "grid": {"left": 8, "right": 16, "top": 40, "bottom": 8,
                 "containLabel": True},
        "legend": {"show": False, "top": 4, "left": 4, "icon": "roundRect",
                   "itemWidth": 10, "itemHeight": 10, "itemGap": 16,
                   "textStyle": {"color": COLORS["text"], "fontSize": 11}},
        "tooltip": {
            "trigger": "axis",
            "backgroundColor": COLORS["bg"],
            "borderColor": COLORS["border"],
            "textStyle": {"color": COLORS["text"], "fontSize": 12},
            "axisPointer": {"type": "line",
                            "lineStyle": {"color": COLORS["border"]}},
        },
    }
    opt.update(extra)
    return opt


def _linie(name, farbe, werte, formatter, flaeche=False, **extra):
    serie = {
        "name": name,
        "type": "line",
        "data": werte,
        "lineStyle": {"width": 2.5, "color": COLORS[farbe]},
        "itemStyle": {"color": COLORS[farbe]},
        "symbol": "circle",
        "symbolSize": 6,
        "showSymbol": len(werte) <= 24,
        "tooltip": {"valueFormatter": formatter},
    }
    if flaeche:
        serie["areaStyle"] = _flaeche(farbe)
    serie.update(extra)
    return serie


def _balken(name, farbe, werte, formatter, **extra):
    serie = {
        "name": name,
        "type": "bar",
        "data": werte,
        "barMaxWidth": 28,
        "itemStyle": {"color": _balken_farbe(farbe), "borderRadius": [4, 4, 0, 0]},
        "tooltip": {"valueFormatter": formatter},
    }
    serie.update(extra)
    return serie


def _bedienung(opt, anzahl, umschalten=True, kategorie=True):
    """Werkzeugleiste und – ab genug Werten – den Zeitraum-Schieberegler ergaenzen."""
    regler = _zoom(anzahl, kategorie)
    if regler:
        opt["dataZoom"] = regler
        opt["grid"]["bottom"] = 32
    # Ohne Umschalter und ohne Regler gaebe es nichts zurueckzusetzen
    if umschalten or regler:
        opt["toolbox"] = _werkzeuge(umschalten)
    return opt


def _leer(msg):
    return {"leer": msg}


# ─────────────────────────────────────────────────────────────
#  Charts
# ─────────────────────────────────────────────────────────────

def _kf() -> dict:
    """Beschriftungen des Vergleichsfahrzeugs (Benzin oder Diesel)."""
    from berechnung import kraftstoff
    return kraftstoff()


def chart_monatliche_ersparnis(fahrten_daten, benzinpreise_daten, lade_daten,
                               benziner_l=7.0, ersatzpreis=None):
    """Benziner- und Stromkosten je Monat. Alle Monate mit km oder Ladungen, damit die
    Summe der Ersparnis-Linie der Kachel „Kraftstoff-Ersparnis“ entspricht; Monate
    ohne Benzinpreis werden mit `ersatzpreis` (Ø aller erfassten Preise) gerechnet."""
    if not fahrten_daten:
        return _leer("Keine Fahrtdaten")

    km_pro_monat = {d["datum"]: d["km"] for d in fahrten_daten}
    bp = {d["monat"]: d["preis_liter"] for d in benzinpreise_daten or []}
    if ersatzpreis is None:
        from berechnung import durchschnitt_benzinpreis
        ersatzpreis = durchschnitt_benzinpreis(benzinpreise_daten or [])
    strom_pro_monat = {}
    for l in lade_daten:
        m = l["datum"][:7]
        strom_pro_monat[m] = strom_pro_monat.get(m, 0) + l["gesamtpreis"]

    monate = sorted(set(km_pro_monat) | set(strom_pro_monat))

    benzin_k, strom_k, ersparnis = [], [], []
    for m in monate:
        km = km_pro_monat.get(m, 0)
        bk = round((km / 100) * benziner_l * bp.get(m, ersatzpreis), 2)
        sk = round(strom_pro_monat.get(m, 0), 2)
        benzin_k.append(bk)
        strom_k.append(sk)
        ersparnis.append(round(bk - sk, 2))

    opt = _basis(
        xAxis=_achse_kategorie(monate),
        yAxis=[_achse_wert(axisLabel={"color": COLORS["subtext"], "fontSize": 10,
                                      "formatter": "fn:euro0"}),
               _achse_wert(splitLine={"show": False},
                           axisLabel={"color": COLORS["subtext"], "fontSize": 10,
                                      "formatter": "fn:euro0"})],
        series=[
            _balken(_kf()["fahrzeug"], "orange", benzin_k, "fn:euro2"),
            _balken("Strom", "blue", strom_k, "fn:euro2"),
            _linie("Ersparnis", "green", ersparnis, "fn:euro2", yAxisIndex=1, z=3),
        ],
    )
    opt["legend"]["show"] = True
    opt["tooltip"]["axisPointer"] = {"type": "shadow",
                                     "shadowStyle": {"color": "rgba(255,255,255,0.03)"}}
    opt["yAxis"][0]["alignTicks"] = True
    opt["yAxis"][1]["alignTicks"] = True
    return _bedienung(opt, len(monate))


def chart_kosten_vergleich(benzin_kosten, strom_kosten):
    # Liegende Balken: bei nur zwei Werten besser lesbar als stehende
    opt = _basis(
        grid={"left": 8, "right": 70, "top": 16, "bottom": 8, "containLabel": True},
        xAxis=_achse_wert(axisLabel={"color": COLORS["subtext"], "fontSize": 10,
                                     "formatter": "fn:euro0"}),
        yAxis=_achse_kategorie(["E-Auto (tatsächlich)", f"{_kf()['fahrzeug']} (hochgerechnet)"],
                               formatter=None,
                               axisLabel={"color": COLORS["text"], "fontSize": 11}),
        series=[{
            "type": "bar",
            "barWidth": 34,
            "data": [
                {"value": round(strom_kosten, 2),
                 "itemStyle": {"color": _balken_farbe("blue", horizontal=True),
                               "borderRadius": [0, 6, 6, 0]}},
                {"value": round(benzin_kosten, 2),
                 "itemStyle": {"color": _balken_farbe("orange", horizontal=True),
                               "borderRadius": [0, 6, 6, 0]}},
            ],
            "label": {"show": True, "position": "right", "color": COLORS["text"],
                      "fontSize": 12, "fontWeight": 600, "formatter": "fn:labelEuro0"},
            "tooltip": {"valueFormatter": "fn:euro2"},
        }],
    )
    opt["tooltip"]["axisPointer"] = {"type": "none"}
    return opt


def chart_co2_ersparnis(fahrten_daten, benziner_l=7.0, co2_faktor=2.37):
    if not fahrten_daten:
        return _leer("Keine Fahrtdaten")
    monate = [d["datum"] for d in fahrten_daten]
    co2_werte = [(d["km"] / 100) * benziner_l * co2_faktor for d in fahrten_daten]
    kumulativ, total = [], 0
    for v in co2_werte:
        total += v
        kumulativ.append(round(total, 1))

    opt = _basis(
        xAxis=_achse_kategorie(monate),
        yAxis=[_achse_wert(), _achse_wert(splitLine={"show": False})],
        series=[
            _balken("CO2/Monat (kg)", "green", [round(v, 1) for v in co2_werte], "fn:kg1"),
            _linie("Kumuliert (kg)", "teal", kumulativ, "fn:kg1", yAxisIndex=1, z=3),
        ],
    )
    opt["legend"]["show"] = True
    opt["tooltip"]["axisPointer"] = {"type": "shadow",
                                     "shadowStyle": {"color": "rgba(255,255,255,0.03)"}}
    opt["yAxis"][0]["alignTicks"] = True
    opt["yAxis"][1]["alignTicks"] = True
    return _bedienung(opt, len(monate))


def chart_verbrauch_100km(lade_daten, fahrten_daten, ev_ref=15.0, akku_monate=None):
    """Zwei Sichten auf den Verbrauch:
    - laut Ladung: geladene kWh ÷ km – enthaelt die Ladeverluste
    - laut Akku:   Akku-Abfall ÷ km aus akkuverbrauch.pro_monat() – ohne Ladeverluste
    """
    kwh_m = {}
    for l in lade_daten or []:
        if not l["menge_kwh"]:      # Grundgebuehr-Eintraege haben keine kWh
            continue
        m = l["datum"][:7]
        kwh_m[m] = kwh_m.get(m, 0) + l["menge_kwh"]
    km_m = {d["datum"]: d["km"] for d in fahrten_daten or []}
    ladung = {m: round(kwh_m[m] / km_m[m] * 100, 2)
              for m in set(kwh_m) & set(km_m) if km_m[m] > 0}
    akku = {a["monat"]: a["verbrauch"] for a in akku_monate or []}

    monate = sorted(set(ladung) | set(akku))
    if not monate:
        return _leer("Lade- und Fahrtdaten oder Akkustand erforderlich")

    serien = []
    if ladung:
        serien.append(_linie("laut Ladung", "purple", [ladung.get(m) for m in monate],
                             "fn:kwh100", flaeche=not akku))
    if akku:
        serien.append(_linie("laut Akku", "teal", [akku.get(m) for m in monate],
                             "fn:kwh100", flaeche=not ladung))
    serie = serien[0]
    serie["markLine"] = {
        "silent": True,
        "symbol": "none",
        "lineStyle": {"color": COLORS["subtext"], "type": "dashed", "width": 1},
        # Hinterlegt, damit die Beschriftung auch ueber der Kurve lesbar bleibt
        "label": {"position": "insideStartTop", "color": COLORS["subtext"],
                  "fontSize": 10, "formatter": "fn:labelRef",
                  "backgroundColor": COLORS["card"], "padding": [3, 5],
                  "borderRadius": 3},
        "data": [{"yAxis": ev_ref}],
    }
    zwei = len(serien) == 2
    # Achse immer bis ueber die Referenzlinie – sonst verschwindet sie bei niedrigen Werten
    hoechster = max([v for v in list(ladung.values()) + list(akku.values())] + [ev_ref])
    opt = _basis(
        grid={"left": 8, "right": 26, "top": 40 if zwei else 26, "bottom": 8,
              "containLabel": True},
        xAxis=_achse_kategorie(monate, boundaryGap=False),
        yAxis=_achse_wert(min=0, max=math.ceil(hoechster * 1.08 / 5) * 5),
        series=serien,
    )
    opt["legend"]["show"] = zwei
    return _bedienung(opt, len(monate))


MONATSKUERZEL = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                  "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]

# Kennzahlen des Verlaufsvergleichs: schluessel -> (Beschriftung, Formatierer, Balken?)
VERGLEICH_METRIKEN = {
    "km":             ("Kilometer", "fn:km0", True),
    "verbrauch":      ("Verbrauch laut Ladung", "fn:kwh100", False),
    "verbrauch_akku": ("Verbrauch laut Akku", "fn:kwh100", False),
    "kwh":            ("Geladene kWh", "fn:kwh1", True),
    "strom_kosten":   ("Stromkosten", "fn:euro2", True),
    "ersparnis":      ("Kraftstoff-Ersparnis", "fn:euro2", True),
}


def chart_vergleich(werte_a, werte_b, titel_a, titel_b, metrik):
    """Zwei Zeitraeume Monat fuer Monat uebereinander (1. Monat neben 1. Monat …).
    Bei gleichen Kalendermonaten (z.B. 2025 gegen 2024) steht nur der Monatsname,
    sonst beide (z.B. Sommer gegen Winter: 'Apr · Okt')."""
    beschriftung, formatierer, balken = VERGLEICH_METRIKEN[metrik]
    laenge = max(len(werte_a), len(werte_b))
    if laenge == 0:
        return _leer("Keine Monate in den gewählten Zeiträumen")

    def kuerzel(werte, i):
        return MONATSKUERZEL[int(werte[i]["monat"][5:7]) - 1] if i < len(werte) else None

    achse = []
    for i in range(laenge):
        a, b = kuerzel(werte_a, i), kuerzel(werte_b, i)
        achse.append(a if a == b or b is None else (b if a is None else f"{a} · {b}"))

    def reihe(werte):
        return [werte[i].get(metrik) if i < len(werte) else None for i in range(laenge)]

    serien = []
    for titel, werte, farbe in ((titel_a, werte_a, "blue"), (titel_b, werte_b, "orange")):
        if balken:
            serien.append(_balken(titel, farbe, reihe(werte), formatierer))
        else:
            s = _linie(titel, farbe, reihe(werte), formatierer)
            s["connectNulls"] = False
            serien.append(s)

    opt = _basis(
        xAxis=_achse_kategorie(achse, formatter=None, boundaryGap=balken),
        yAxis=_achse_wert(),
        series=serien,
    )
    opt["legend"]["show"] = True
    opt["grid"]["right"] = 34          # Platz fuer lange Doppel-Beschriftungen am Rand
    if balken:
        opt["tooltip"]["axisPointer"] = {"type": "shadow",
                                         "shadowStyle": {"color": "rgba(255,255,255,0.03)"}}
    return opt


def chart_strommix(lade_daten):
    """Anteil der geladenen kWh nach Quelle: PV, Netzbezug zuhause, oeffentlich."""
    from berechnung import stromquelle
    summen = {"PV-Strom": 0.0, "Netzbezug": 0.0, "Öffentlich": 0.0}
    for l in lade_daten or []:
        summen[stromquelle(l["anbieter"])] += l["menge_kwh"] or 0
    if sum(summen.values()) <= 0:
        return _leer("Keine Ladedaten")

    farben = {"PV-Strom": "#c4963a", "Netzbezug": COLORS["blue"],
              "Öffentlich": COLORS["purple"]}
    daten = [{"name": q, "value": round(kwh, 1), "itemStyle": {"color": farben[q]}}
             for q, kwh in summen.items() if kwh > 0]
    opt = _basis(
        tooltip={
            "trigger": "item",
            "backgroundColor": COLORS["bg"],
            "borderColor": COLORS["border"],
            "textStyle": {"color": COLORS["text"], "fontSize": 12},
            "formatter": "fn:tooltipAnteilKwh",
        },
        series=[{
            "type": "pie",
            "radius": ["48%", "74%"],
            "center": ["50%", "56%"],
            "data": daten,
            "itemStyle": {"borderColor": COLORS["card"], "borderWidth": 3,
                          "borderRadius": 5},
            "label": {"color": COLORS["text"], "fontSize": 11,
                      "formatter": "fn:labelAnteil"},
            "labelLine": {"lineStyle": {"color": COLORS["border"]}},
        }],
    )
    opt["legend"]["show"] = True
    return opt


def chart_benzinpreise(daten):
    if not daten:
        return _leer(f"Keine {_kf()['name']}preisdaten")
    serie = _linie(f"{_kf()['name']}preis", "orange", [d["preis_liter"] for d in daten],
                   "fn:euroLiter", flaeche=True)
    # Flaeche bis zum unteren Achsenende statt bis 0 – sonst wirken Schwankungen platt
    serie["areaStyle"]["origin"] = "start"
    opt = _basis(
        grid={"left": 8, "right": 26, "top": 26, "bottom": 8, "containLabel": True},
        xAxis=_achse_kategorie([d["monat"] for d in daten], boundaryGap=False),
        yAxis=_achse_wert(scale=True, axisLabel={"color": COLORS["subtext"],
                                                 "fontSize": 10, "formatter": "fn:zahl2"}),
        series=[serie],
    )
    return _bedienung(opt, len(daten))


def chart_stromtarif(daten, von=None, bis=None):
    """Treppenkurve der Tarife. von/bis ('YYYY-MM') schneiden auf einen Zeitraum zu:
    Der zu Beginn gueltige Tarif wird ab Zeitraumbeginn gezeigt, auch wenn er
    frueher eingetragen wurde."""
    if not daten:
        return _leer("Keine Stromtarifeinträge")
    daten_sorted = sorted(daten, key=lambda x: x["gueltig_ab"])
    heute = date.today().isoformat()
    ende = heute
    if von:
        start = f"{von}-01"
        ende = min(heute, f"{bis}-{calendar.monthrange(int(bis[:4]), int(bis[5:7]))[1]:02d}")
        davor = [d for d in daten_sorted if d["gueltig_ab"] <= start]
        drin = [d for d in daten_sorted if start < d["gueltig_ab"] <= ende]
        daten_sorted = ([{"gueltig_ab": start, "preis_kwh": davor[-1]["preis_kwh"]}]
                        if davor else []) + drin
        if not daten_sorted:
            return _leer("Im Zeitraum galt noch kein Stromtarif")
    punkte = [[d["gueltig_ab"], d["preis_kwh"]] for d in daten_sorted]
    # Der letzte Tarif gilt bis heute bzw. Zeitraumende – Linie weiterfuehren (ohne Punkt)
    if punkte[-1][0] < ende:
        punkte.append({"value": [ende, punkte[-1][1]],
                       "symbol": "none", "label": {"show": False}})

    serie = _linie("Stromtarif", "teal", punkte, "fn:ctKwh", step="end")
    serie["showSymbol"] = True
    serie["label"] = {"show": True, "position": "top", "color": COLORS["subtext"],
                      "fontSize": 10, "formatter": "fn:labelCt"}
    serie["areaStyle"] = _flaeche("teal")
    serie["areaStyle"]["origin"] = "start"
    opt = _basis(
        grid={"left": 8, "right": 24, "top": 28, "bottom": 8, "containLabel": True},
        xAxis={
            "type": "time",
            "axisLine": {"lineStyle": {"color": COLORS["border"]}},
            "axisTick": {"show": False},
            "axisLabel": {"color": COLORS["subtext"], "fontSize": 10,
                          "formatter": "fn:datumMonat", "hideOverlap": True},
            "axisPointer": {"label": {"formatter": "fn:datum:ap"}},
            "splitLine": {"show": False},
        },
        yAxis=_achse_wert(scale=True, axisLabel={"color": COLORS["subtext"],
                                                 "fontSize": 10, "formatter": "fn:zahl1"}),
        series=[serie],
    )
    # Treppenlinie: Umschalten auf Balken ergaebe keinen Sinn, nur Zeitraum-Regler
    return _bedienung(opt, len(punkte), umschalten=False, kategorie=False)


def chart_ladetarife(tarife, stromtarife=None):
    """Treppenkurve ct/kWh (AC) je eigenem Ladetarif; der Heimstrompreis als
    gestrichelte Vergleichslinie."""
    if not tarife:
        return _leer("Noch keine Ladetarife erfasst")
    heute = date.today().isoformat()
    gruppen = {}
    for t in sorted(tarife, key=lambda t: t["gueltig_ab"]):
        name = t["anbieter"] + (f" {t['tarif_name']}" if t["tarif_name"] else "")
        gruppen.setdefault(name, []).append(t)

    farben = ["blue", "orange", "purple", "green", "red"]
    serien = []
    for i, (name, liste) in enumerate(gruppen.items()):
        punkte = [[t["gueltig_ab"], t["preis_ac"]] for t in liste]
        ende = liste[-1]["gueltig_bis"] or heute
        if punkte[-1][0] < ende:
            punkte.append({"value": [ende, punkte[-1][1]],
                           "symbol": "none", "label": {"show": False}})
        serie = _linie(name, farben[i % len(farben)], punkte, "fn:ctKwh", step="end")
        serie["showSymbol"] = True
        serie["label"] = {"show": True, "position": "top", "color": COLORS["subtext"],
                          "fontSize": 10, "formatter": "fn:labelCt"}
        serien.append(serie)

    if stromtarife:
        start = min(t["gueltig_ab"] for t in tarife)
        heim = sorted(stromtarife, key=lambda x: x["gueltig_ab"])
        davor = [d for d in heim if d["gueltig_ab"] <= start]
        heim = ([{"gueltig_ab": start, "preis_kwh": davor[-1]["preis_kwh"]}] if davor else []) \
            + [d for d in heim if d["gueltig_ab"] > start]
        if heim:
            punkte = [[d["gueltig_ab"], d["preis_kwh"]] for d in heim]
            if punkte[-1][0] < heute:
                punkte.append([heute, punkte[-1][1]])
            serie = _linie("Heimstrom", "teal", punkte, "fn:ctKwh", step="end")
            serie["lineStyle"]["type"] = "dashed"
            serie["lineStyle"]["width"] = 1.5
            serie["showSymbol"] = False
            serien.append(serie)

    opt = _basis(
        grid={"left": 8, "right": 24, "top": 40, "bottom": 8, "containLabel": True},
        xAxis={
            "type": "time",
            "axisLine": {"lineStyle": {"color": COLORS["border"]}},
            "axisTick": {"show": False},
            "axisLabel": {"color": COLORS["subtext"], "fontSize": 10,
                          "formatter": "fn:datumMonat", "hideOverlap": True},
            "axisPointer": {"label": {"formatter": "fn:datum:ap"}},
            "splitLine": {"show": False},
        },
        yAxis=_achse_wert(scale=True, axisLabel={"color": COLORS["subtext"],
                                                 "fontSize": 10, "formatter": "fn:zahl1"}),
        series=serien,
    )
    opt["legend"]["show"] = True
    return _bedienung(opt, max(len(s["data"]) for s in serien), umschalten=False, kategorie=False)


def chart_anbieter_verteilung(lade_daten):
    if not lade_daten:
        return _leer("Keine Ladedaten")
    anbieter_k = {}
    for l in lade_daten:
        a = l["anbieter"]
        anbieter_k[a] = anbieter_k.get(a, 0) + l["gesamtpreis"]
    daten = sorted(({"name": a, "value": round(k, 2)} for a, k in anbieter_k.items()),
                   key=lambda d: -d["value"])

    opt = _basis(
        color=[COLORS["blue"], COLORS["green"], COLORS["orange"],
               COLORS["purple"], COLORS["teal"], COLORS["red"]],
        tooltip={
            "trigger": "item",
            "backgroundColor": COLORS["bg"],
            "borderColor": COLORS["border"],
            "textStyle": {"color": COLORS["text"], "fontSize": 12},
            "formatter": "fn:tooltipAnteil",
        },
        series=[{
            "type": "pie",
            "radius": ["48%", "74%"],
            "center": ["50%", "56%"],
            "data": daten,
            "itemStyle": {"borderColor": COLORS["card"], "borderWidth": 3,
                          "borderRadius": 5},
            "label": {"color": COLORS["text"], "fontSize": 11,
                      "formatter": "fn:labelAnteil"},
            "labelLine": {"lineStyle": {"color": COLORS["border"]}},
        }],
    )
    opt["legend"]["show"] = True
    return opt


def chart_thg(thg_daten):
    if not thg_daten:
        return _leer("Keine THG-Einträge")
    serie = _balken("THG-Quote", "green", [d["betrag"] for d in thg_daten], "fn:euro2",
                    barMaxWidth=60)
    serie["label"] = {"show": True, "position": "top", "color": COLORS["text"],
                      "fontSize": 11, "formatter": "fn:labelEuro0"}
    opt = _basis(
        grid={"left": 8, "right": 16, "top": 28, "bottom": 8, "containLabel": True},
        xAxis=_achse_kategorie([d["datum"] for d in thg_daten], formatter="fn:datum"),
        yAxis=_achse_wert(axisLabel={"color": COLORS["subtext"], "fontSize": 10,
                                     "formatter": "fn:euro0"}),
        series=[serie],
    )
    opt["tooltip"]["axisPointer"] = {"type": "shadow",
                                     "shadowStyle": {"color": "rgba(255,255,255,0.03)"}}
    return _bedienung(opt, len(thg_daten))
