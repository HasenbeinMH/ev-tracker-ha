# -*- coding: utf-8 -*-
"""
Monats- und Jahresberichte: Kennzahlen sammeln und als HTML-Mail aufbereiten.
Wird von der Webapp genutzt (Vorschau, Versand, Zeitplan).
"""
import calendar
from datetime import date

import database as db
import berechnung

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
          "Juli", "August", "September", "Oktober", "November", "Dezember"]


# ── Formatierung ─────────────────────────────────────────────────────────────

def fmt(wert, nachkommastellen=0, einheit=""):
    """Deutsche Zahlformatierung: 12345.6 -> '12.345,6'."""
    if wert is None:
        return "–"
    s = f"{wert:,.{nachkommastellen}f}"
    s = s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{s} {einheit}".strip()


def _delta_text(aktuell, vorher, nachkommastellen=0, einheit="", besser=None):
    """Veränderung gegenüber der Vorperiode als Text mit Pfeil.

    besser: "hoch", "niedrig" oder None – färbt die Veränderung grün (besser)
    oder orange (schlechter) wie auf der Statistikseite; None bleibt grau.
    """
    if not vorher or aktuell is None:
        return ""
    diff = aktuell - vorher
    if abs(diff) < 10 ** -nachkommastellen / 2:
        return "→ unverändert"
    pfeil = "▲" if diff > 0 else "▼"
    prozent = diff / abs(vorher) * 100
    text = f"{pfeil} {fmt(abs(diff), nachkommastellen, einheit)} ({prozent:+.0f} %)"
    if besser:
        klasse = "gruen" if (diff > 0) == (besser == "hoch") else "orange"
        text = f'<span class="{klasse}">{text}</span>'
    return text


# ── Datensammlung ────────────────────────────────────────────────────────────

def _zeitraum_kennzahlen(von: str, bis: str, monate: list) -> dict:
    """Kennzahlen für einen Zeitraum. `monate` sind die enthaltenen 'YYYY-MM'."""
    cfg = db.get_config()
    lade = berechnung.ladevorgaenge(von, bis)
    thg = db.get_thg_zeitraum(von, bis)

    fahrten = {f["monat"]: f["km"] for f in db.get_fahrten_monate()}
    preise = {b["monat"]: b["preis_liter"] for b in db.get_benzinpreise()}

    km = sum(fahrten.get(m, 0.0) for m in monate)
    kwh = sum(l["menge_kwh"] for l in lade)
    strom_kosten = sum(l["gesamtpreis"] for l in lade)
    thg_summe = sum(t["betrag"] for t in thg)

    # Monat fuer Monat mit dem Preis des Monats – die Monatszeilen des Jahresberichts
    # summieren sich so genau auf den Jahreswert
    ersatz = berechnung.durchschnitt_benzinpreis(db.get_benzinpreise())
    liter = berechnung.benzin_liter(km, cfg["benziner_verbrauch"])
    benzin_kosten = berechnung.benzin_kosten({m: fahrten.get(m, 0.0) for m in monate}, preise,
                                             cfg["benziner_verbrauch"], ersatz)
    monatspreise = [preise[m] for m in monate if m in preise]
    if liter:
        avg_benzin = benzin_kosten / liter          # km-gewichteter Ø
    elif monatspreise:
        avg_benzin = sum(monatspreise) / len(monatspreise)
    else:
        avg_benzin = ersatz

    nach_anbieter = {}
    for l in lade:
        a = nach_anbieter.setdefault(l["anbieter"],
                                     {"kwh": 0.0, "kosten": 0.0, "anzahl": 0})
        a["kwh"] += l["menge_kwh"]
        a["kosten"] += l["gesamtpreis"]
        a["anzahl"] += 1

    return {
        "km": km,
        "kwh": kwh,
        "ladevorgaenge": len(berechnung.nur_ladungen(lade)),
        "strom_kosten": strom_kosten,
        "benzin_kosten": benzin_kosten,
        "ersparnis": benzin_kosten - strom_kosten,
        "thg": thg_summe,
        "avg_benzin": avg_benzin,
        "liter": liter,
        "co2": berechnung.co2_kg(liter, cfg["co2_faktor_benzin"]),
        "verbrauch": (kwh / km * 100) if km > 0 else None,
        "kosten_pro_100km": (strom_kosten / km * 100) if km > 0 else None,
        "nach_anbieter": nach_anbieter,
    }


def _sim_zusatz() -> str:
    """Im Simulationsmodus steht das im Titel – auch im Betreff der Mail."""
    return " (Simulation)" if db.get_config()["simulation"] else ""


def monatsbericht(jahr: int, monat: int) -> dict:
    """Kennzahlen eines Monats inklusive Vergleich zum Vormonat."""
    letzter = calendar.monthrange(jahr, monat)[1]
    schluessel = f"{jahr}-{monat:02d}"
    daten = _zeitraum_kennzahlen(f"{schluessel}-01",
                                 f"{schluessel}-{letzter:02d}", [schluessel])

    v_jahr, v_monat = (jahr, monat - 1) if monat > 1 else (jahr - 1, 12)
    v_letzter = calendar.monthrange(v_jahr, v_monat)[1]
    v_schluessel = f"{v_jahr}-{v_monat:02d}"
    vormonat = _zeitraum_kennzahlen(f"{v_schluessel}-01",
                                    f"{v_schluessel}-{v_letzter:02d}", [v_schluessel])

    return {"typ": "monat", "titel": f"{MONATE[monat-1]} {jahr}" + _sim_zusatz(),
            "jahr": jahr, "monat": monat,
            "daten": daten, "vergleich": vormonat,
            "vergleich_titel": f"{MONATE[v_monat-1]} {v_jahr}"}


def jahresbericht(jahr: int) -> dict:
    """Kennzahlen eines Jahres mit Monatsaufstellung und Vorjahresvergleich."""
    monate = [f"{jahr}-{m:02d}" for m in range(1, 13)]
    daten = _zeitraum_kennzahlen(f"{jahr}-01-01", f"{jahr}-12-31", monate)
    vorjahr = _zeitraum_kennzahlen(f"{jahr-1}-01-01", f"{jahr-1}-12-31",
                                   [f"{jahr-1}-{m:02d}" for m in range(1, 13)])

    monatsliste = []
    for m in range(1, 13):
        schluessel = f"{jahr}-{m:02d}"
        letzter = calendar.monthrange(jahr, m)[1]
        werte = _zeitraum_kennzahlen(f"{schluessel}-01",
                                     f"{schluessel}-{letzter:02d}", [schluessel])
        if werte["km"] or werte["kwh"]:
            monatsliste.append(dict(name=MONATE[m-1], **werte))

    return {"typ": "jahr", "titel": f"Jahresbericht {jahr}" + _sim_zusatz(), "jahr": jahr,
            "daten": daten, "vergleich": vorjahr,
            "vergleich_titel": str(jahr - 1), "monate": monatsliste}


# ── HTML-Aufbereitung ────────────────────────────────────────────────────────

_STIL = """
body{margin:0;padding:0;background:#f4f5f7;font-family:'Segoe UI',Arial,sans-serif;color:#1f2430}
.rahmen{max-width:640px;margin:0 auto;background:#ffffff}
.kopf{background:#2d6a9f;color:#ffffff;padding:20px 24px}
.kopf h1{margin:0;font-size:20px}
.kopf div{opacity:.85;font-size:13px;margin-top:4px}
.inhalt{padding:20px 24px}
h2{font-size:15px;color:#2d6a9f;margin:24px 0 10px;border-bottom:1px solid #e3e6ea;padding-bottom:6px}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:8px 10px;border-bottom:1px solid #eceef1;text-align:left}
th{font-size:12px;color:#6b7280;font-weight:600}
td.z{text-align:right;white-space:nowrap}
.kachel{display:inline-block;box-sizing:border-box;width:46%;margin:0 1% 10px;padding:12px 14px;
        vertical-align:top;
        background:#f7f9fb;border:1px solid #e3e6ea;border-radius:6px}
.kachel .w{font-size:20px;font-weight:700}
.kachel .l{font-size:11px;color:#6b7280;margin-top:2px}
.gruen{color:#2f7d4f}
.rot{color:#aa3333}
.orange{color:#b86a2a}
.grau{color:#6b7280;font-size:12px}
.fuss{padding:14px 24px;background:#f7f9fb;color:#6b7280;font-size:11px;border-top:1px solid #e3e6ea}
"""


def _kachel(wert, label, farbe="#2d6a9f"):
    return (f'<div class="kachel"><div class="w" style="color:{farbe}">{wert}</div>'
            f'<div class="l">{label}</div></div>')


def als_html(bericht: dict) -> str:
    d = bericht["daten"]
    v = bericht["vergleich"]
    kf = berechnung.kraftstoff()

    kacheln = (
        _kachel(fmt(d["km"], 0, "km"), "Gefahrene Strecke")
        + _kachel(fmt(d["kwh"], 1, "kWh"), "Geladene Energie")
        + _kachel(fmt(d["strom_kosten"], 2, "&euro;"), "Stromkosten")
        + _kachel(fmt(d["ersparnis"], 2, "&euro;"), f"Ersparnis vs. {kf['fahrzeug']}",
                  "#2f7d4f" if d["ersparnis"] >= 0 else "#aa3333")
    )

    verbrauch = fmt(d["verbrauch"], 1, "kWh/100km") if d["verbrauch"] else "–"
    pro100 = fmt(d["kosten_pro_100km"], 2, "&euro;") if d["kosten_pro_100km"] else "–"
    zeilen = [
        ("Gefahrene Strecke", fmt(d["km"], 0, "km"),
         _delta_text(d["km"], v["km"], 0, "km")),
        ("Geladene Energie", fmt(d["kwh"], 1, "kWh"),
         _delta_text(d["kwh"], v["kwh"], 1, "kWh")),
        ("Ladevorgänge", str(d["ladevorgaenge"]), ""),
        ("Verbrauch", verbrauch, ""),
        ("Stromkosten", fmt(d["strom_kosten"], 2, "&euro;"),
         _delta_text(d["strom_kosten"], v["strom_kosten"], 2, "&euro;", "niedrig")),
        ("Kosten je 100 km", pro100, ""),
        (f"{kf['fahrzeug']} hätte gekostet", fmt(d["benzin_kosten"], 2, "&euro;"),
         "bei &Oslash; " + fmt(d["avg_benzin"], 3, "&euro;/L")),
        ("Ersparnis", fmt(d["ersparnis"], 2, "&euro;"),
         _delta_text(d["ersparnis"], v["ersparnis"], 2, "&euro;", "hoch")),
        ("THG-Ertrag", fmt(d["thg"], 2, "&euro;"), ""),
        ("CO&#8322; gespart",fmt(d["co2"], 1, "kg"),
         _delta_text(d["co2"], v["co2"], 1, "kg", "hoch")),
    ]
    tabelle = "".join(
        f'<tr><td>{name}</td><td class="z"><strong>{wert}</strong></td>'
        f'<td class="z grau">{zusatz}</td></tr>'
        for name, wert, zusatz in zeilen)

    anbieter_html = ""
    if d["nach_anbieter"]:
        reihen = "".join(
            f'<tr><td>{name}</td><td class="z">{a["anzahl"]}</td>'
            f'<td class="z">{fmt(a["kwh"], 1, "kWh")}</td>'
            f'<td class="z">{fmt(a["kosten"], 2, "&euro;")}</td></tr>'
            for name, a in sorted(d["nach_anbieter"].items(),
                                  key=lambda x: -x[1]["kosten"]))
        anbieter_html = ('<h2>Ladevorgänge nach Anbieter</h2><table>'
                         '<tr><th>Anbieter</th><th class="z">Anzahl</th>'
                         '<th class="z">Energie</th><th class="z">Kosten</th></tr>'
                         + reihen + '</table>')

    monats_html = ""
    if bericht.get("monate"):
        reihen = "".join(
            f'<tr><td>{m["name"]}</td><td class="z">{fmt(m["km"], 0)}</td>'
            f'<td class="z">{fmt(m["kwh"], 1)}</td>'
            f'<td class="z">{fmt(m["strom_kosten"], 2)}</td>'
            f'<td class="z {"gruen" if m["ersparnis"] >= 0 else "rot"}">'
            f'{fmt(m["ersparnis"], 2)}</td></tr>'
            for m in bericht["monate"])
        monats_html = ('<h2>Monatsverlauf</h2><table>'
                       '<tr><th>Monat</th><th class="z">km</th><th class="z">kWh</th>'
                       '<th class="z">Kosten &euro;</th>'
                       '<th class="z">Ersparnis &euro;</th></tr>'
                       + reihen + '</table>')

    return (
        '<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">'
        f'<style>{_STIL}</style></head><body><div class="rahmen">'
        f'<div class="kopf"><h1>&#9889; EV Tracker – {bericht["titel"]}</h1>'
        f'<div>Vergleich mit {bericht["vergleich_titel"]}</div></div>'
        '<div class="inhalt">'
        + (f'<div style="background:#fff8e1;border:1px solid #e6d9a8;'
           f'border-radius:6px;padding:10px 12px;font-size:12px;margin-bottom:14px">'
           f'&#9888; {bericht["hinweis"]}</div>' if bericht.get("hinweis") else '')
        + f'<div style="margin:0 -1%">{kacheln}</div>'
        f'<h2>Kennzahlen</h2><table>{tabelle}</table>'
        f'{anbieter_html}{monats_html}</div>'
        f'<div class="fuss">Automatisch erstellt vom EV Tracker am '
        f'{date.today().strftime("%d.%m.%Y")}.</div>'
        '</div></body></html>')


def als_text(bericht: dict) -> str:
    """Textfassung als Rückfallebene für Mailprogramme ohne HTML."""
    d = bericht["daten"]
    kf = berechnung.kraftstoff()
    return "\n".join([
        f"EV Tracker – {bericht['titel']}",
        "=" * 40,
        f"Gefahrene Strecke:  {fmt(d['km'], 0, 'km')}",
        f"Geladene Energie:   {fmt(d['kwh'], 1, 'kWh')} "
        f"in {d['ladevorgaenge']} Vorgaengen",
        f"Stromkosten:        {fmt(d['strom_kosten'], 2, 'EUR')}",
        f"{(kf['name'] + '-Vergleich:'):<19} {fmt(d['benzin_kosten'], 2, 'EUR')}",
        f"Ersparnis:          {fmt(d['ersparnis'], 2, 'EUR')}",
        f"THG-Ertrag:         {fmt(d['thg'], 2, 'EUR')}",
        f"CO2 gespart:        {fmt(d['co2'], 1, 'kg')}",
    ])
