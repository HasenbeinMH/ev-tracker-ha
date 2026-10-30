# -*- coding: utf-8 -*-
"""
Monats- und Jahresberichte: Kennzahlen sammeln und als HTML-Mail aufbereiten.
Wird von der Webapp genutzt (Vorschau, Versand, Zeitplan).
"""
import calendar
import html
from datetime import date

import database as db
from i18n import _, N_
import berechnung

MONATE = [N_("Januar"), N_("Februar"), N_("März"), N_("April"), N_("Mai"), N_("Juni"),
          N_("Juli"), N_("August"), N_("September"), N_("Oktober"), N_("November"), N_("Dezember")]


def monatsname(monat: int) -> str:
    """Monatsname (1–12) in der eingestellten Sprache."""
    return _(MONATE[monat - 1])


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
        return _("→ unverändert")
    pfeil = "▲" if diff > 0 else "▼"
    prozent = diff / abs(vorher) * 100
    text = f"{pfeil} {fmt(abs(diff), nachkommastellen, einheit)} ({prozent:+.0f} %)"
    if besser:
        klasse = "gruen" if (diff > 0) == (besser == "hoch") else "orange"
        text = f'<span class="{klasse}">{text}</span>'
    return text


# ── Datensammlung ────────────────────────────────────────────────────────────

def _zeitraum_kennzahlen(von: str, bis: str, monate: list) -> dict:
    """Kennzahlen für einen Zeitraum. `monate` sind die enthaltenen 'YYYY-MM'.
    Mehrere Fahrzeuge in der Gesamtsicht: je Fahrzeug gerechnet und zusammengefasst,
    die Einzelwerte stehen unter "je_fahrzeug"."""
    if db.aktuelles_fahrzeug() is None:
        je = []
        for fz in db.fahrzeuge():
            with db.fahrzeug_kontext(fz["id"]):
                je.append((fz, _zeitraum_kennzahlen(von, bis, monate)))
        return _summe([k for _f, k in je], je)
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

    # Plus, was der Akku in den Monaten netto hergab (wie zeitraum.kennzahlen)
    kwh_v = kwh
    if kwh and not cfg["simulation"]:
        import akkuverbrauch
        entnahme = akkuverbrauch.entnahme_je_monat()
        kwh_v += sum(entnahme.get(m, 0.0) for m in monate)

    return {
        "km": km,
        "kwh": kwh,
        "ladevorgaenge": berechnung.anzahl_ladungen(lade),
        "strom_kosten": strom_kosten,
        "benzin_kosten": benzin_kosten,
        "ersparnis": benzin_kosten - strom_kosten,
        "thg": thg_summe,
        "avg_benzin": avg_benzin,
        "liter": liter,
        "co2": berechnung.co2_kg(liter, cfg["co2_faktor_benzin"]),
        "_kwh_v": kwh_v,
        "verbrauch": (kwh_v / km * 100) if km > 0 and kwh_v > 0 else None,
        "kosten_pro_100km": (strom_kosten / km * 100) if km > 0 else None,
        "nach_anbieter": nach_anbieter,
    }


def _summe(liste: list, je: list) -> dict:
    """Berichtswerte mehrerer Fahrzeuge: Summen addiert, Verhaeltnisse neu gebildet."""
    s = {k: sum(x[k] for x in liste) for k in
         ("km", "kwh", "ladevorgaenge", "strom_kosten", "benzin_kosten", "ersparnis",
          "thg", "liter", "co2", "_kwh_v")}
    nach_anbieter = {}
    for x in liste:
        for name, a in x["nach_anbieter"].items():
            z = nach_anbieter.setdefault(name, {"kwh": 0.0, "kosten": 0.0, "anzahl": 0})
            for k in z:
                z[k] += a[k]
    preise = [x["avg_benzin"] for x in liste if x["avg_benzin"]]
    return {
        **s,
        "avg_benzin": s["benzin_kosten"] / s["liter"] if s["liter"] else (preise[0] if preise else None),
        "verbrauch": (s["_kwh_v"] / s["km"] * 100) if s["km"] > 0 and s["_kwh_v"] > 0 else None,
        "kosten_pro_100km": (s["strom_kosten"] / s["km"] * 100) if s["km"] > 0 else None,
        "nach_anbieter": nach_anbieter,
        "je_fahrzeug": [{"name": fz["name"], **k} for fz, k in je],
    }


def _sim_zusatz() -> str:
    """Im Simulationsmodus steht das im Titel – auch im Betreff der Mail. Bei mehreren
    Fahrzeugen der Name des gewaehlten bzw. "alle Fahrzeuge"."""
    zusatz = _(" (Simulation)") if db.get_config()["simulation"] else ""
    if db.mehrere_fahrzeuge() and len(db.sichtbare_ids()) > 1:
        fid = db.aktuelles_fahrzeug()
        name = (_("alle Fahrzeuge") if fid is None
                else next((f["name"] for f in db.fahrzeuge() if f["id"] == fid), ""))
        zusatz += f" – {name}"
    return zusatz


def _leasing() -> list:
    """Stand der Leasingvertraege fuer den Bericht: [(fahrzeugname, leasing.auswertung)] –
    das gewaehlte Fahrzeug bzw. alle sichtbaren."""
    import leasing
    import module
    if not module.an("leasing"):
        return []
    fid = db.aktuelles_fahrzeug()
    erg = []
    for fz in db.fahrzeuge():
        if fid is not None and fz["id"] != fid:
            continue
        with db.fahrzeug_kontext(fz["id"]):
            l = leasing.auswertung()
        if l:
            erg.append((fz["name"], l))
    return erg


def _energie(monat: str) -> list:
    """Energie-Aufteilung des Monats je Fahrzeug: [(fahrzeugname, energie.summe)] – nur mit
    Modul Energie und nur Fahrzeuge mit Tagen im Monat."""
    import energie
    import module
    if not module.an("energie"):
        return []
    fid = db.aktuelles_fahrzeug()
    erg = []
    for fz in db.fahrzeuge():
        if fid is not None and fz["id"] != fid:
            continue
        tage = [t for t in db.get_energie_tage(fz["id"]) if t["datum"][:7] == monat]
        if tage:
            erg.append((fz["name"], energie.summe(tage)))
    return erg


def energie_text(name: str, s: dict) -> str:
    """Eine Zeile zur Energie-Aufteilung (Mail und Text)."""
    teile = [f"{_(text)} {fmt(s['anteile'][k], 0)} %" for k, text in
             (("antrieb_wh", "Antrieb"), ("klima_wh", "Klima"), ("elektronik_wh", "Bordelektronik"))
             if s["anteile"][k] is not None]
    text = _("Laut Bordcomputer {0} kWh/100 km", fmt(s["bordcomputer"], 1)) + " · " + ", ".join(teile)
    if s["rekuperation_wh"]:
        text += " · " + _("Rekuperation {0} kWh", fmt(s["rekuperation_wh"] / 1000, 1))
    return (f"{name}: " if name else "") + text


def leasing_text(name: str, l: dict) -> str:
    """Eine Zeile zum Leasingstand (Mail und Text)."""
    text = _("{0} von {1} km gefahren (Soll heute {2} km), Prognose bis Vertragsende {3} km",
             fmt(l["ist"]), fmt(l["vertrag_km"]), fmt(l["soll"]), fmt(l["prognose"]))
    if l["mehr_km"] > 0:
        text += " · " + _("≈ {0} Mehr-km", fmt(l["mehr_km"]))
        if l["mehr_ct"]:
            text += " · " + _("≈ {0} € Nachzahlung", fmt(l["mehr_eur"]))
    elif l["minder_km"] > 0:
        text += " · " + _("≈ {0} Minder-km", fmt(l["minder_km"]))
    return (f"{name}: " if name else "") + text


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

    return {"typ": "monat", "titel": f"{monatsname(monat)} {jahr}" + _sim_zusatz(),
            "jahr": jahr, "monat": monat,
            "daten": daten, "vergleich": vormonat,
            "vergleich_titel": f"{monatsname(v_monat)} {v_jahr}", "leasing": _leasing(),
            "energie": _energie(schluessel)}


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
            monatsliste.append(dict(name=monatsname(m), **werte))

    return {"typ": "jahr", "titel": _("Jahresbericht {0}", jahr) + _sim_zusatz(), "jahr": jahr,
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
        _kachel(fmt(d["km"], 0, "km"), _("Gefahrene Strecke"))
        + _kachel(fmt(d["kwh"], 1, "kWh"), _("Geladene Energie"))
        + _kachel(fmt(d["strom_kosten"], 2, "&euro;"), _("Stromkosten"))
        + _kachel(fmt(d["ersparnis"], 2, "&euro;"), _("Ersparnis vs. {0}", kf['fahrzeug']),
                  "#2f7d4f" if d["ersparnis"] >= 0 else "#aa3333")
    )

    verbrauch = fmt(d["verbrauch"], 1, "kWh/100km") if d["verbrauch"] else "–"
    pro100 = fmt(d["kosten_pro_100km"], 2, "&euro;") if d["kosten_pro_100km"] else "–"
    zeilen = [
        (_("Gefahrene Strecke"), fmt(d["km"], 0, "km"),
         _delta_text(d["km"], v["km"], 0, "km")),
        (_("Geladene Energie"), fmt(d["kwh"], 1, "kWh"),
         _delta_text(d["kwh"], v["kwh"], 1, "kWh")),
        (_("Ladevorgänge"), str(d["ladevorgaenge"]), ""),
        (_("Verbrauch laut Wallbox/Ladesäule"), verbrauch, ""),
        (_("Stromkosten"), fmt(d["strom_kosten"], 2, "&euro;"),
         _delta_text(d["strom_kosten"], v["strom_kosten"], 2, "&euro;", "niedrig")),
        (_("Kosten je 100 km"), pro100, ""),
        (_("{0} hätte gekostet", kf['fahrzeug']), fmt(d["benzin_kosten"], 2, "&euro;"),
         _("bei &Oslash; {0}", fmt(d["avg_benzin"], 3, "&euro;/L"))),
        (_("Ersparnis"), fmt(d["ersparnis"], 2, "&euro;"),
         _delta_text(d["ersparnis"], v["ersparnis"], 2, "&euro;", "hoch")),
        (_("THG-Ertrag"), fmt(d["thg"], 2, "&euro;"), ""),
        (_("CO&#8322; gespart"), fmt(d["co2"], 1, "kg"),
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
        anbieter_html = (f'<h2>{_("Ladevorgänge nach Anbieter")}</h2><table>'
                         f'<tr><th>{_("Anbieter")}</th><th class="z">{_("Anzahl")}</th>'
                         f'<th class="z">{_("Energie")}</th><th class="z">{_("Kosten")}</th></tr>'
                         + reihen + '</table>')

    fahrzeug_html = ""
    if len(d.get("je_fahrzeug") or []) > 1:
        reihen = "".join(
            f'<tr><td>{x["name"]}</td><td class="z">{fmt(x["km"], 0)}</td>'
            f'<td class="z">{fmt(x["kwh"], 1)}</td>'
            f'<td class="z">{fmt(x["strom_kosten"], 2)}</td>'
            f'<td class="z {"gruen" if x["ersparnis"] >= 0 else "rot"}">'
            f'{fmt(x["ersparnis"], 2)}</td></tr>'
            for x in d["je_fahrzeug"])
        fahrzeug_html = (f'<h2>{_("Je Fahrzeug")}</h2><table>'
                         f'<tr><th>{_("Fahrzeug")}</th><th class="z">km</th><th class="z">kWh</th>'
                         f'<th class="z">{_("Kosten &euro;")}</th>'
                         f'<th class="z">{_("Ersparnis &euro;")}</th></tr>'
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
        monats_html = (f'<h2>{_("Monatsverlauf")}</h2><table>'
                       f'<tr><th>{_("Monat")}</th><th class="z">km</th><th class="z">kWh</th>'
                       f'<th class="z">{_("Kosten &euro;")}</th>'
                       f'<th class="z">{_("Ersparnis &euro;")}</th></tr>'
                       + reihen + '</table>')

    energie_html = ""
    if bericht.get("energie"):
        viele = len(bericht["energie"]) > 1
        energie_html = (f'<h2>{_("Energie nach Verbraucher")}</h2>'
                        + "".join(f'<p style="font-size:13px">'
                                  f'{html.escape(energie_text(name if viele else "", s))}</p>'
                                  for name, s in bericht["energie"]))
    mehrere_namen = len(bericht.get("leasing") or []) > 1
    leasing_html = ""
    if bericht.get("leasing"):
        leasing_html = (f'<h2>{_("Leasing-Kilometer")}</h2>'
                        + "".join(f'<p style="font-size:13px">'
                                  f'{html.escape(leasing_text(name if mehrere_namen else "", l))}</p>'
                                  for name, l in bericht["leasing"]))

    return (
        f'<!DOCTYPE html><html lang="{db.sprache()}"><head><meta charset="utf-8">'
        f'<style>{_STIL}</style></head><body><div class="rahmen">'
        f'<div class="kopf"><h1>&#9889; EV Tracker – {bericht["titel"]}</h1>'
        f'<div>{_("Vergleich mit {0}", bericht["vergleich_titel"])}</div></div>'
        '<div class="inhalt">'
        + (f'<div style="background:#fff8e1;border:1px solid #e6d9a8;'
           f'border-radius:6px;padding:10px 12px;font-size:12px;margin-bottom:14px">'
           f'&#9888; {bericht["hinweis"]}</div>' if bericht.get("hinweis") else '')
        + f'<div style="margin:0 -1%">{kacheln}</div>'
        f'<h2>{_("Kennzahlen")}</h2><table>{tabelle}</table>'
        f'<p class="grau" style="font-size:12px">{_("Stromkosten, Verbrauch und Ersparnis rechnen mit den kWh, die an Wallbox oder Ladesäule gemessen und bezahlt wurden – die Ladeverluste sind darin enthalten.")}</p>'
        f'{fahrzeug_html}{anbieter_html}{monats_html}{energie_html}{leasing_html}</div>'
        f'<div class="fuss">{_("Automatisch erstellt vom EV Tracker am {0}.", date.today().strftime("%d.%m.%Y"))}</div>'
        '</div></body></html>')


def als_text(bericht: dict) -> str:
    """Textfassung als Rückfallebene für Mailprogramme ohne HTML."""
    d = bericht["daten"]
    kf = berechnung.kraftstoff()
    return "\n".join([
        f"EV Tracker – {bericht['titel']}",
        "=" * 40,
        f"{_('Gefahrene Strecke:'):<19} {fmt(d['km'], 0, 'km')}",
        f"{_('Geladene Energie:'):<19} {fmt(d['kwh'], 1, 'kWh')} "
        + _("in {0} Vorgaengen", d['ladevorgaenge']),
        f"{_('Stromkosten:'):<19} {fmt(d['strom_kosten'], 2, 'EUR')}",
        f"{_('{0}-Vergleich:', kf['name']):<19} {fmt(d['benzin_kosten'], 2, 'EUR')}",
        f"{_('Ersparnis:'):<19} {fmt(d['ersparnis'], 2, 'EUR')}",
        f"{_('THG-Ertrag:'):<19} {fmt(d['thg'], 2, 'EUR')}",
        f"{_('CO2 gespart:'):<19} {fmt(d['co2'], 1, 'kg')}",
        "",
        _("Stromkosten, Verbrauch und Ersparnis rechnen mit den kWh, die an Wallbox oder Ladesäule gemessen und bezahlt wurden – die Ladeverluste sind darin enthalten."),
    ] + [_("Energie: {0}", energie_text(name if len(bericht.get("energie") or []) > 1 else "", s))
         for name, s in bericht.get("energie") or []] + [_("Leasing: {0}", leasing_text(name if len(bericht.get("leasing") or []) > 1 else "", l))
         for name, l in bericht.get("leasing") or []])
