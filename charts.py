"""
Chart-Definitionen fuer das Dashboard (Apache ECharts).

Jede Funktion liefert ein ECharts-Option-Dict, das als JSON an den Browser geht
und dort von static/charts.js gezeichnet wird. Zahlen- und Datumsformatierung
laeuft im Browser: Strings der Form "fn:<name>" werden in charts.js durch die
gleichnamige Formatierfunktion ersetzt (JSON kann keine Funktionen transportieren).

Kurven werden bewusst nicht geglaettet – bei Monatswerten wuerden Zwischenwerte
vorgetaeuscht, die es nicht gibt.
"""
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


def _leer(msg):
    return {"leer": msg}


# ─────────────────────────────────────────────────────────────
#  Charts
# ─────────────────────────────────────────────────────────────

def chart_monatliche_ersparnis(fahrten_daten, benzinpreise_daten, lade_daten,
                               benziner_l=7.0):
    if not fahrten_daten or not benzinpreise_daten:
        return _leer("Benzinpreise und Fahrten erforderlich")

    km_pro_monat = {d["datum"]: d["km"] for d in fahrten_daten}
    bp = {d["monat"]: d["preis_liter"] for d in benzinpreise_daten}
    strom_pro_monat = {}
    for l in lade_daten:
        m = l["datum"][:7]
        strom_pro_monat[m] = strom_pro_monat.get(m, 0) + l["gesamtpreis"]

    monate = sorted(set(km_pro_monat.keys()) & set(bp.keys()))
    if not monate:
        return _leer("Keine übereinstimmenden Monate")

    benzin_k, strom_k, ersparnis = [], [], []
    for m in monate:
        km = km_pro_monat.get(m, 0)
        bk = round((km / 100) * benziner_l * bp[m], 2)
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
            _balken("Benziner", "orange", benzin_k, "fn:euro2"),
            _balken("Strom", "blue", strom_k, "fn:euro2"),
            _linie("Ersparnis", "green", ersparnis, "fn:euro2", yAxisIndex=1, z=3),
        ],
    )
    opt["legend"]["show"] = True
    opt["tooltip"]["axisPointer"] = {"type": "shadow",
                                     "shadowStyle": {"color": "rgba(255,255,255,0.03)"}}
    opt["yAxis"][0]["alignTicks"] = True
    opt["yAxis"][1]["alignTicks"] = True
    return opt


def chart_kosten_vergleich(benzin_kosten, strom_kosten):
    # Liegende Balken: bei nur zwei Werten besser lesbar als stehende
    opt = _basis(
        grid={"left": 8, "right": 70, "top": 16, "bottom": 8, "containLabel": True},
        xAxis=_achse_wert(axisLabel={"color": COLORS["subtext"], "fontSize": 10,
                                     "formatter": "fn:euro0"}),
        yAxis=_achse_kategorie(["E-Auto (tatsächlich)", "Benziner (hochgerechnet)"],
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
    return opt


def chart_verbrauch_100km(lade_daten, fahrten_daten, ev_ref=15.0):
    if not lade_daten or not fahrten_daten:
        return _leer("Lade- und Fahrtdaten erforderlich")

    kwh_m = {}
    for l in lade_daten:
        m = l["datum"][:7]
        kwh_m[m] = kwh_m.get(m, 0) + l["menge_kwh"]

    km_m = {d["datum"]: d["km"] for d in fahrten_daten}
    monate = sorted(set(kwh_m) & set(km_m))
    if not monate:
        return _leer("Keine übereinstimmenden Monate")

    verbrauch = [round(kwh_m[m] / km_m[m] * 100, 2) if km_m[m] > 0 else 0 for m in monate]

    serie = _linie("Verbrauch", "purple", verbrauch, "fn:kwh100", flaeche=True)
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
    return _basis(
        grid={"left": 8, "right": 16, "top": 20, "bottom": 8, "containLabel": True},
        xAxis=_achse_kategorie(monate, boundaryGap=False),
        yAxis=_achse_wert(min=0),
        series=[serie],
    )


def chart_benzinpreise(daten):
    if not daten:
        return _leer("Keine Benzinpreisdaten")
    serie = _linie("Benzinpreis", "orange", [d["preis_liter"] for d in daten],
                   "fn:euroLiter", flaeche=True)
    # Flaeche bis zum unteren Achsenende statt bis 0 – sonst wirken Schwankungen platt
    serie["areaStyle"]["origin"] = "start"
    return _basis(
        grid={"left": 8, "right": 16, "top": 20, "bottom": 8, "containLabel": True},
        xAxis=_achse_kategorie([d["monat"] for d in daten], boundaryGap=False),
        yAxis=_achse_wert(scale=True, axisLabel={"color": COLORS["subtext"],
                                                 "fontSize": 10, "formatter": "fn:zahl2"}),
        series=[serie],
    )


def chart_stromtarif(daten):
    if not daten:
        return _leer("Keine Stromtarifeinträge")
    daten_sorted = sorted(daten, key=lambda x: x["gueltig_ab"])
    punkte = [[d["gueltig_ab"], d["preis_kwh"]] for d in daten_sorted]
    # Der letzte Tarif gilt bis heute – Linie bis heute weiterfuehren (ohne Punkt)
    heute = date.today().isoformat()
    if punkte[-1][0] < heute:
        punkte.append({"value": [heute, punkte[-1][1]],
                       "symbol": "none", "label": {"show": False}})

    serie = _linie("Stromtarif", "teal", punkte, "fn:ctKwh", step="end")
    serie["showSymbol"] = True
    serie["label"] = {"show": True, "position": "top", "color": COLORS["subtext"],
                      "fontSize": 10, "formatter": "fn:labelCt"}
    serie["areaStyle"] = _flaeche("teal")
    serie["areaStyle"]["origin"] = "start"
    return _basis(
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
    return opt
