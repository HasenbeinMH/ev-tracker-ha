import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Gedaempfte, professionelle Farbpalette
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

LAYOUT_DEFAULTS = dict(
    separators=",.",   # deutsches Format: 1.234,56
    paper_bgcolor=COLORS["bg"],
    plot_bgcolor=COLORS["card"],
    font=dict(color=COLORS["text"], family="Segoe UI, sans-serif", size=11),
    margin=dict(l=45, r=20, t=40, b=40),
    xaxis=dict(gridcolor=COLORS["grid"], linecolor=COLORS["border"], tickfont=dict(size=10)),
    yaxis=dict(gridcolor=COLORS["grid"], linecolor=COLORS["border"], tickfont=dict(size=10)),
    legend=dict(
        bgcolor=COLORS["card"],
        bordercolor=COLORS["border"],
        borderwidth=1,
        font=dict(size=10)
    )
)


def _fig_to_html(fig, height=200):
    fig.update_layout(height=height)
    return fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": False, "responsive": True}
    )


def _fig_to_html_large(fig, height=520):
    fig.update_layout(height=height, margin=dict(l=55, r=30, t=50, b=50))
    return fig.to_html(
        full_html=False,
        include_plotlyjs=False,
        config={"displayModeBar": True, "responsive": True}
    )


def chart_benzinpreise(daten, large=False):
    if not daten:
        return _empty_chart("Keine Benzinpreisdaten", large)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[d["monat"] for d in daten],
        y=[d["preis_liter"] for d in daten],
        mode="lines+markers",
        line=dict(color=COLORS["orange"], width=2),
        marker=dict(size=5),
        fill="tozeroy",
        fillcolor="rgba(196,122,58,0.12)",
        name="€/L",
        hovertemplate="%{x}: %{y:.2f} €/L<extra></extra>"
    ))
    fig.update_layout(**LAYOUT_DEFAULTS, title=dict(text="Benzinpreise €/L", font=dict(size=12)))
    fig.update_yaxes(tickformat=".2f")
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)


def chart_stromtarif(daten, large=False):
    if not daten:
        return _empty_chart("Keine Stromtarifeinträge", large)
    daten_sorted = sorted(daten, key=lambda x: x["gueltig_ab"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=[d["gueltig_ab"] for d in daten_sorted],
        y=[d["preis_kwh"] for d in daten_sorted],
        mode="lines+markers+text",
        line=dict(color=COLORS["teal"], width=2, shape="hv"),
        marker=dict(size=7),
        text=[f"{d['preis_kwh']:.1f}" for d in daten_sorted],
        textposition="top center",
        textfont=dict(size=9),
        name="ct/kWh"
    ))
    fig.update_layout(**LAYOUT_DEFAULTS, title=dict(text="Stromtarif ct/kWh", font=dict(size=12)))
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)


def chart_kosten_vergleich(benzin_kosten, strom_kosten, large=False):
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=["Benziner (hochger.)", "E-Auto (tatsächl.)"],
        y=[benzin_kosten, strom_kosten],
        marker_color=[COLORS["orange"], COLORS["blue"]],
        text=[f"{benzin_kosten:.0f} €", f"{strom_kosten:.0f} €"],
        textposition="outside",
        textfont=dict(size=10, color=COLORS["text"])
    ))
    fig.update_layout(**LAYOUT_DEFAULTS,
                      title=dict(text="Kraftstoffkosten gesamt", font=dict(size=12)),
                      showlegend=False)
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)


def chart_monatliche_ersparnis(fahrten_daten, benzinpreise_daten, lade_daten,
                               benziner_l=7.0, large=False):
    if not fahrten_daten or not benzinpreise_daten:
        return _empty_chart("Benzinpreise und Fahrten erforderlich", large)

    km_pro_monat = {d["datum"]: d["km"] for d in fahrten_daten}
    bp = {d["monat"]: d["preis_liter"] for d in benzinpreise_daten}
    strom_pro_monat = {}
    for l in lade_daten:
        m = l["datum"][:7]
        strom_pro_monat[m] = strom_pro_monat.get(m, 0) + l["gesamtpreis"]

    monate = sorted(set(km_pro_monat.keys()) & set(bp.keys()))
    if not monate:
        return _empty_chart("Keine übereinstimmenden Monate", large)

    benzin_k, strom_k, ersparnis = [], [], []
    for m in monate:
        km = km_pro_monat.get(m, 0)
        bk = round((km / 100) * benziner_l * bp[m], 2)
        sk = round(strom_pro_monat.get(m, 0), 2)
        benzin_k.append(bk)
        strom_k.append(sk)
        ersparnis.append(round(bk - sk, 2))

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=monate, y=benzin_k, name="Benziner",
                         marker_color=COLORS["orange"], opacity=0.75), secondary_y=False)
    fig.add_trace(go.Bar(x=monate, y=strom_k, name="Strom",
                         marker_color=COLORS["blue"], opacity=0.75), secondary_y=False)
    fig.add_trace(go.Scatter(x=monate, y=ersparnis, name="Ersparnis",
                             mode="lines+markers",
                             line=dict(color=COLORS["green"], width=2),
                             marker=dict(size=5)), secondary_y=True)
    fig.update_layout(**LAYOUT_DEFAULTS,
                      title=dict(text="Monatliche Kosten & Ersparnis", font=dict(size=12)),
                      barmode="group")
    fig.update_yaxes(gridcolor=COLORS["grid"], secondary_y=False)
    fig.update_yaxes(gridcolor=COLORS["grid"], secondary_y=True)
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)


def chart_verbrauch_100km(lade_daten, fahrten_daten, ev_ref=15.0, large=False):
    if not lade_daten or not fahrten_daten:
        return _empty_chart("Lade- und Fahrtdaten erforderlich", large)

    kwh_m = {}
    for l in lade_daten:
        m = l["datum"][:7]
        kwh_m[m] = kwh_m.get(m, 0) + l["menge_kwh"]

    km_m = {d["datum"]: d["km"] for d in fahrten_daten}
    monate = sorted(set(kwh_m) & set(km_m))
    if not monate:
        return _empty_chart("Keine übereinstimmenden Monate", large)

    verbrauch = [round(kwh_m[m] / km_m[m] * 100, 2) if km_m[m] > 0 else 0 for m in monate]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=monate, y=verbrauch,
        mode="lines+markers",
        line=dict(color=COLORS["purple"], width=2),
        marker=dict(size=5),
        fill="tozeroy",
        fillcolor="rgba(122,106,170,0.12)",
        name="kWh/100km"
    ))
    fig.add_hline(y=ev_ref, line_dash="dot", line_color=COLORS["subtext"], line_width=1,
                  annotation_text=f"{ev_ref} kWh Ref.", annotation_font_size=9,
                  annotation_position="top right")
    fig.update_layout(**LAYOUT_DEFAULTS,
                      title=dict(text="Verbrauch kWh/100km", font=dict(size=12)))
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)


def chart_anbieter_verteilung(lade_daten, large=False):
    if not lade_daten:
        return _empty_chart("Keine Ladedaten", large)
    anbieter_k = {}
    for l in lade_daten:
        a = l["anbieter"]
        anbieter_k[a] = anbieter_k.get(a, 0) + l["gesamtpreis"]

    fig = go.Figure(go.Pie(
        labels=list(anbieter_k.keys()),
        values=list(anbieter_k.values()),
        hole=0.45,
        marker=dict(colors=[COLORS["blue"], COLORS["green"], COLORS["orange"],
                             COLORS["purple"], COLORS["teal"], COLORS["red"]]),
        textfont=dict(size=10, color=COLORS["text"]),
        insidetextorientation="radial"
    ))
    fig.update_layout(**LAYOUT_DEFAULTS,
                      title=dict(text="Ladekosten nach Anbieter", font=dict(size=12)))
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)


def chart_thg(thg_daten, large=False):
    if not thg_daten:
        return _empty_chart("Keine THG-Einträge", large)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[d["datum"] for d in thg_daten],
        y=[d["betrag"] for d in thg_daten],
        marker_color=COLORS["green"],
        text=[f"{d['betrag']:.0f}€" for d in thg_daten],
        textposition="outside",
        textfont=dict(size=10)
    ))
    fig.update_layout(**LAYOUT_DEFAULTS,
                      title=dict(text="THG-Quote Erträge €", font=dict(size=12)),
                      showlegend=False)
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)


def chart_co2_ersparnis(fahrten_daten, benziner_l=7.0, co2_faktor=2.37, large=False):
    if not fahrten_daten:
        return _empty_chart("Keine Fahrtdaten", large)
    monate = [d["datum"] for d in fahrten_daten]
    co2_werte = [(d["km"] / 100) * benziner_l * co2_faktor for d in fahrten_daten]
    kumulativ, total = [], 0
    for v in co2_werte:
        total += v
        kumulativ.append(round(total, 1))

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=monate, y=[round(v, 1) for v in co2_werte],
                         name="CO2/Monat kg",
                         marker_color=COLORS["green"], opacity=0.75), secondary_y=False)
    fig.add_trace(go.Scatter(x=monate, y=kumulativ, name="Kumuliert kg",
                             mode="lines+markers",
                             line=dict(color=COLORS["teal"], width=2),
                             marker=dict(size=5)), secondary_y=True)
    fig.update_layout(**LAYOUT_DEFAULTS,
                      title=dict(text="CO2-Ersparnis vs. Benziner (kg)", font=dict(size=12)))
    fig.update_yaxes(gridcolor=COLORS["grid"], secondary_y=False)
    fig.update_yaxes(gridcolor=COLORS["grid"], secondary_y=True)
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)


def _empty_chart(msg, large=False):
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper",
                       x=0.5, y=0.5, showarrow=False,
                       font=dict(size=13, color=COLORS["subtext"]))
    fig.update_layout(**LAYOUT_DEFAULTS)
    return _fig_to_html_large(fig) if large else _fig_to_html(fig)
