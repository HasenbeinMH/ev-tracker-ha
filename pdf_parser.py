"""
PDF-Parser fuer Laderechnungen: EWE go, EnBW, medl, DCS (Charge myHyundai u.a.),
Shell Recharge, vaylens, reev
Extrahiert Einzelvorgaenge und/oder Monatsübersichten.
"""
import re
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Ladevorgang:
    datum: str          # YYYY-MM-DD
    menge_kwh: float
    preis_kwh: float    # ct/kWh
    gesamtpreis: float  # €
    anbieter: str
    ladeleistung_kw: Optional[float] = None
    ladetyp: str = "AC"
    notiz: str = ""
    quelle: str = ""    # "Einzelvorgang" oder "Monatsübersicht"
    warnungen: list[str] = field(default_factory=list)  # erscheinen in der Vorschau unter der Zeile


def _parse_float_de(text: str) -> Optional[float]:
    """Parst deutsche Zahlenformate: 1.234,56 → 1234.56 oder 12,34 → 12.34"""
    if not text:
        return None
    text = text.strip().replace(" ", "").replace("\xa0", "")
    # Deutsches Format: Tausenderpunkt, Komma als Dezimal
    if re.match(r"^\d{1,3}(\.\d{3})*(,\d+)?$", text):
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_datum_de(text: str) -> Optional[str]:
    """Konvertiert diverse Datumsformate → YYYY-MM-DD"""
    if not text:
        return None
    text = text.strip()
    # TT.MM.JJJJ
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # TT.MM.JJ
    m = re.match(r"(\d{1,2})\.(\d{1,2})\.(\d{2})$", text)
    if m:
        year = int(m.group(3)) + 2000
        return f"{year}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    # YYYY-MM-DD bereits OK
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return text[:10]
    return None


def _detect_ladetyp(leistung_kw: Optional[float], text_hint: str = "") -> str:
    """AC wenn <= 22 kW, DC wenn > 22 kW oder explizit DC erwähnt"""
    text_lower = text_hint.lower()
    if "dc" in text_lower or "gleichstrom" in text_lower or "schnelllad" in text_lower:
        return "DC"
    if leistung_kw and leistung_kw > 22:
        return "DC"
    return "AC"


# ─────────────────────────────────────────────
#  ANBIETER-ERKENNUNG
# ─────────────────────────────────────────────

def detect_anbieter(text: str) -> str:
    """Gibt den erkannten Anbieter zurück."""
    text_lower = text.lower()
    if any(kw in text_lower for kw in ["ewe go", "ewego", "ewe-go"]):
        return "EWE go"
    if any(kw in text_lower for kw in ["enbw mobility", "enbw charge", "mobility+"]):
        return "EnBW"
    if any(kw in text_lower for kw in ["medl", "mülheimer energiedienstleistungen"]):
        return "medl"
    if "digital charging solutions" in text_lower or "chargemy" in text_lower:
        m = re.search(r"Charge\s?my\s?(\w+)", text)
        return f"Charge my{m.group(1)}" if m else "DCS"
    if "shell" in text_lower and "ladevorgang" in text_lower:
        return "Shell Recharge"
    if "vaylens" in text_lower:
        return "vaylens"
    if "rehau" in text_lower and "ladesäule" in text_lower:
        return "reev"
    return "Unbekannt"


def _float_punkt(text: str) -> Optional[float]:
    """Zahl mit Punkt als Dezimaltrenner (12.597) – _parse_float_de laese 12597."""
    try:
        return float(text.replace(",", "."))
    except (ValueError, AttributeError):
        return None


def _vorgang(datum, kwh, brutto, anbieter, ladetyp="AC", notiz="") -> Ladevorgang:
    return Ladevorgang(
        datum=datum,
        menge_kwh=round(kwh, 3),
        preis_kwh=round(brutto / kwh * 100, 2),
        gesamtpreis=round(brutto, 2),
        anbieter=anbieter,
        ladetyp=ladetyp,
        quelle="Einzelvorgang",
        notiz=notiz or f"{anbieter} Import"
    )


# ─────────────────────────────────────────────
#  EINZELBELEGE: Shell Recharge, vaylens, reev
# ─────────────────────────────────────────────

def parse_shell(text: str) -> list[Ladevorgang]:
    """Shell Recharge Transaktionsbeleg: ein Ladevorgang, Betrag brutto."""
    datum_m = re.search(r"Beginn:\s*(\d{2})/(\d{2})/(\d{4})", text)
    kwh_m = re.search(r"Menge:\s*([\d.,]+)\s*kWh", text, re.I)
    brutto_m = (re.search(r"Gezahlter Gesamtbetrag\s+([\d.,]+)\s*EUR", text)
                or re.search(r"^Gesamt\s+([\d.,]+)\s*EUR", text, re.M))
    if not (datum_m and kwh_m and brutto_m):
        return []
    kwh = _float_punkt(kwh_m.group(1))
    brutto = _parse_float_de(brutto_m.group(1))
    if not kwh or brutto is None:
        return []
    datum = f"{datum_m.group(3)}-{datum_m.group(2)}-{datum_m.group(1)}"
    return [_vorgang(datum, kwh, brutto, "Shell Recharge")]


def parse_vaylens(text: str) -> list[Ladevorgang]:
    """vaylens Zahlungsbeleg (Ad-hoc-Laden): Zahlen mit Punkt als Dezimaltrenner."""
    datum_m = re.search(r"Datum\s+(\d{1,2}\.\d{1,2}\.\d{4})", text)
    kwh_m = re.search(r"Geladene Energie\s+([\d.]+)\s*\*?\s*kWh", text)
    brutto_m = re.search(r"^Summe\s+[\d.]+\s+[\d.]+\s+([\d.]+)\s*$", text, re.M) \
        or re.search(r"^Summe\s+([\d.]+)\s*EUR", text, re.M)
    if not (datum_m and kwh_m and brutto_m):
        return []
    kwh = _float_punkt(kwh_m.group(1))
    brutto = _float_punkt(brutto_m.group(1))
    if not kwh or brutto is None:
        return []
    betreiber = re.search(r"Ladepunktbetreiber -+\s*\n\s*(.+)", text)
    notiz = f"vaylens Import ({betreiber.group(1).strip()})" if betreiber else ""
    return [_vorgang(_parse_datum_de(datum_m.group(1)), kwh, brutto, "vaylens", notiz=notiz)]


_MONATE = {m: i for i, m in enumerate(
    ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
     "september", "oktober", "november", "dezember"], 1)}


def parse_reev(text: str) -> list[Ladevorgang]:
    """
    reev (REHAU) Rechnung: "62,30900 kWh à 0,35000 €", Endbetrag brutto.
    Das Ladedatum steht im Text mit "Beschreibung" verschraenkt
    ("B0e3s.c0h8r.e2ib0u2n6g") – ohne die Buchstaben bleibt "03.08.2026".
    """
    kwh_m = re.search(r"([\d.,]+)\s*kWh\s*à", text)
    brutto_m = (re.search(r"F.lliger Betrag\s+([\d.,]+)\s*€", text)
                or re.search(r"([\d.,]+)\s*€\s*f.llig am", text))
    if not (kwh_m and brutto_m):
        return []
    kwh = _parse_float_de(kwh_m.group(1))
    brutto = _parse_float_de(brutto_m.group(1))
    if not kwh or brutto is None:
        return []

    datum = None
    zeile = next((z for z in text.split("\n") if kwh_m.group(0) in z), "")
    for wort in zeile.split():
        datum = _parse_datum_de(re.sub(r"[^\d.]", "", wort))
        if datum:
            break
    if not datum:
        m = re.search(r"Ausstellungsdatum\s+(\d{1,2})\.\s*(\w+)\s+(\d{4})", text)
        if m and m.group(2).lower() in _MONATE:
            datum = f"{m.group(3)}-{_MONATE[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    if not datum:
        return []
    return [_vorgang(datum, kwh, brutto, "reev")]


# ─────────────────────────────────────────────
#  DCS PARSER (Charge myHyundai, Kia Charge, …)
# ─────────────────────────────────────────────

def parse_dcs(text: str, anbieter: str, hinweise: Optional[list] = None) -> list[Ladevorgang]:
    """
    Digital Charging Solutions – eine Rechnung je Land, jeweils mit Seite
    "Übersicht der Ladevorgänge". Die Beträge dort sind netto; die MwSt.
    steht auf der Rechnungsseite davor ("Gesamtbetrag (19% MwSt. DE)").
    Datum und kWh-Zeile landen im Text versetzt, gehören aber in derselben
    Reihenfolge zusammen. Eine "Kostenübernahme durch Dritte" wird anteilig
    auf die Ladevorgänge derselben Länderrechnung verteilt. Was vom
    Rechnungsbetrag uebrig bleibt (z.B. Grundgebuehr), meldet `hinweise`.
    """
    hinweise = hinweise if hinweise is not None else []
    vorgaenge = []
    marker = re.compile(r"bersicht der Ladevorg")
    ende = re.compile(r"Ihre Rechnung f|Seite 1 /")
    for m in marker.finditer(text):
        anfaenge = [a.start() for a in re.finditer(r"Ihre Rechnung f", text[:m.start()])]
        rechnung = text[anfaenge[-1] if anfaenge else 0:m.start()]
        vorher = re.findall(r"\((\d+)\s*%\s*MwSt", rechnung)
        mwst = int(vorher[-1]) / 100 if vorher else 0.19
        uebernahme = sum(abs(_parse_float_de(b) or 0) for b in
                         re.findall(r"Kosten.bernahme durch\s+(-?[\d.,]+)\s*EUR", rechnung))
        rest = text[m.end():]
        e = ende.search(rest)
        abschnitt = rest[:e.start()] if e else rest

        daten = re.findall(r"(\d{2}\.\d{2}\.\d{4})\s+\d{1,2}:\d{2}h", abschnitt)
        mengen = re.findall(
            r"([\d.,]+)\s*kWh\s+(AC|DC|HPC)\b[^\n]*?([\d.,]+)\s*EUR\s+([\d.,]+)\s*EUR\s+([\d.,]+)\s*EUR",
            abschnitt)
        land_m = re.search(r"Ihre Rechnung f.r (\S+)", rechnung)
        land = f"Rechnung {land_m.group(1)}" if land_m else "Eine Teilrechnung"
        if len(daten) != len(mengen):
            hinweise.append(f"{land}: {len(daten)} Datumsangaben, aber {len(mengen)} Ladevorgänge gefunden – "
                            f"diese Rechnung wurde übersprungen, bitte die Vorgänge von Hand eintragen.")
            continue
        neue = []
        for datum_txt, (kwh_txt, produkt, _, _, netto_txt) in zip(daten, mengen):
            kwh = _parse_float_de(kwh_txt)
            netto = _parse_float_de(netto_txt)
            if not kwh or kwh < 0.5 or netto is None:
                continue
            neue.append(Ladevorgang(
                datum=_parse_datum_de(datum_txt),
                menge_kwh=round(kwh, 3),
                preis_kwh=0.0,
                gesamtpreis=round(netto * (1 + mwst), 2),
                anbieter=anbieter,
                ladetyp="AC" if produkt == "AC" else "DC",
                quelle="Einzelvorgang",
                notiz=f"{anbieter} Import"
            ))

        # Kostenuebernahme anteilig nach Betrag; Rundungsrest auf den letzten Vorgang
        summe = sum(v.gesamtpreis for v in neue)
        rest_abzug = round(uebernahme, 2)
        for i, v in enumerate(neue):
            if rest_abzug and summe > 0:
                abzug = rest_abzug if i == len(neue) - 1 else round(uebernahme * v.gesamtpreis / summe, 2)
                rest_abzug = round(rest_abzug - abzug, 2)
                v.gesamtpreis = round(v.gesamtpreis - abzug, 2)
                v.notiz += f" (Kostenübernahme -{abzug:.2f} €".replace(".", ",") + ")"
            v.preis_kwh = round(v.gesamtpreis / v.menge_kwh * 100, 2)
        vorgaenge += neue

        # Abgleich mit dem Endbetrag dieser Laenderrechnung
        offen = re.findall(r"Offener Zahlbetrag\s+([\d.,]+)\s*EUR", rechnung)
        gesamt = re.findall(r"^Gesamtbetrag\s+([\d.,]+)\s*EUR", rechnung, re.M)
        endbetrag = _parse_float_de((offen or gesamt or [""])[-1])
        if endbetrag is not None:
            diff = round(endbetrag - sum(v.gesamtpreis for v in neue), 2)
            if diff > 0.05:
                posten = [p for p in re.findall(r"^(.+?) vom \d{2}\.\d{2}\.\d{4} - ", rechnung, re.M)
                          if not p.startswith("Summe") and "Zeitraum" not in p]
                was = f"„{posten[0].strip()}“" if posten else "z. B. eine Grundgebühr"
                hinweise.append(f"{land}: {_eur(diff)} gehören zu keinem Ladevorgang ({was}) "
                                f"und werden nicht importiert.")
            elif diff < -0.05:
                hinweise.append(f"{land}: Die erkannten Vorgänge ergeben {_eur(-diff)} mehr als der "
                                f"Rechnungsbetrag {_eur(endbetrag)} – bitte prüfen.")
    return vorgaenge


def _eur(betrag: float) -> str:
    return f"{betrag:.2f} €".replace(".", ",")


# ─────────────────────────────────────────────
#  EWE GO PARSER
# ─────────────────────────────────────────────

def parse_ewe_go(text: str) -> list[Ladevorgang]:
    """
    EWE go Rechnung – typisches Layout:
    Datum | Uhrzeit | Ladestation | kWh | Preis/kWh | Gesamt
    """
    vorgaenge = _parse_ewe_go_uebersicht(text)
    if vorgaenge:
        return vorgaenge

    # Einzelvorgänge: Zeilen mit Datum und kWh
    # Format: "12.03.2025 14:32  Ladestation XY  32,50 kWh  0,4200 €/kWh  13,65 €"
    pattern = re.compile(
        r"(\d{1,2}\.\d{1,2}\.\d{4})"           # Datum
        r".*?"
        r"([\d.,]+)\s*[kK][wW][hH]"             # kWh
        r".*?"
        r"([\d.,]+)\s*€/[kK][wW][hH]"           # €/kWh
        r".*?"
        r"([\d.,]+)\s*€",                        # Gesamt €
        re.MULTILINE
    )

    for m in pattern.finditer(text):
        datum = _parse_datum_de(m.group(1))
        kwh = _parse_float_de(m.group(2))
        preis_euro = _parse_float_de(m.group(3))  # €/kWh → umrechnen in ct
        gesamt = _parse_float_de(m.group(4))

        if datum and kwh and preis_euro and gesamt and kwh > 0:
            preis_ct = preis_euro * 100
            vorgaenge.append(Ladevorgang(
                datum=datum,
                menge_kwh=round(kwh, 3),
                preis_kwh=round(preis_ct, 2),
                gesamtpreis=round(gesamt, 2),
                anbieter="EWE go",
                ladetyp=_detect_ladetyp(None, text),
                quelle="Einzelvorgang",
                notiz="EWE go Import"
            ))

    # Fallback: Monatsübersicht falls keine Einzelvorgänge
    if not vorgaenge:
        vorgaenge += _parse_monatsuebersicht(text, "EWE go")

    return vorgaenge


def _parse_ewe_go_uebersicht(text: str) -> list[Ladevorgang]:
    """
    EWE Go Rechnung ab 2026: Seite "Ladevorgangsübersicht" mit Blöcken
    "Ladevorgang Nr. 1 … Start: 16.08.2026 … Ladeart: DC … Gesamtkosten 6,55 €".
    Die Beträge dort sind netto; der Rundungsrest zum Bruttobetrag der
    Rechnung geht auf den letzten Vorgang.
    """
    bloecke = re.split(r"Ladevorgang Nr\.\s*\d+", text)[1:]
    mwst_m = re.search(r"MwSt\.?\s*(\d+)\s*%", text)
    mwst = int(mwst_m.group(1)) / 100 if mwst_m else 0.19
    vorgaenge = []
    for block in bloecke:
        datum_m = re.search(r"Start:\s*(\d{1,2}\.\d{1,2}\.\d{4})", block)
        kwh_m = re.search(r"([\d.,]+)\s*kWh\s+[\d.,]+\s*€\s*/\s*kWh", block)
        netto_m = re.search(r"Gesamtkosten\s+([\d.,]+)\s*€", block)
        art_m = re.search(r"Ladeart:\s*(AC|DC)", block)
        if not (datum_m and kwh_m and netto_m):
            continue
        kwh = _parse_float_de(kwh_m.group(1))
        netto = _parse_float_de(netto_m.group(1))
        if not kwh or kwh < 0.5 or netto is None:
            continue
        vorgaenge.append(_vorgang(_parse_datum_de(datum_m.group(1)), kwh,
                                  netto * (1 + mwst), "EWE go",
                                  art_m.group(1) if art_m else "AC", "EWE go Import"))

    brutto_m = re.search(r"Gesamtbetrag Brutto\s+([\d.,]+)\s*€", text)
    if vorgaenge and brutto_m and len(vorgaenge) == len(bloecke):
        diff = round(_parse_float_de(brutto_m.group(1)) - sum(v.gesamtpreis for v in vorgaenge), 2)
        if diff and abs(diff) <= 0.05 * len(vorgaenge):
            v = vorgaenge[-1]
            v.gesamtpreis = round(v.gesamtpreis + diff, 2)
            v.preis_kwh = round(v.gesamtpreis / v.menge_kwh * 100, 2)
    return vorgaenge


# ─────────────────────────────────────────────
#  ENBW PARSER
# ─────────────────────────────────────────────

def parse_enbw(text: str) -> list[Ladevorgang]:
    """
    EnBW mobility+ Rechnung – typisches Layout:
    Datum | Standort | Energie | Leistung | Tarif | Betrag
    """
    vorgaenge = []

    # Einzelvorgänge zeilenweise erkennen, z.B.
    # "15.03.2025  Schnellader Berlin  45,20 kWh  50 kW  0,49 €/kWh  22,15 €"
    lines = text.split("\n")
    for i, line in enumerate(lines):
        # Suche Zeilen mit Datum
        datum_m = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", line)
        if not datum_m:
            continue

        # Kontext: aktuelle + nächste 3 Zeilen, aber nur bis zum nächsten Datum –
        # sonst landet der Betrag des folgenden Vorgangs hier
        kontext_zeilen = [line]
        for folge in lines[i+1:i+4]:
            if re.search(r"\d{1,2}\.\d{1,2}\.\d{4}", folge):
                break
            kontext_zeilen.append(folge)
        kontext = " ".join(kontext_zeilen)

        kwh_m = re.search(r"([\d.,]+)\s*[kK][wW][hH]", kontext)
        kw_m = re.search(r"([\d]+(?:[.,]\d+)?)\s*[kK][wW](?![hH])", kontext)
        preis_m = re.search(r"([\d.,]+)\s*€\s*/\s*[kK][wW][hH]", kontext)
        gesamt_m = re.findall(r"([\d.,]+)\s*€", kontext)

        if kwh_m:
            datum = _parse_datum_de(datum_m.group(1))
            kwh = _parse_float_de(kwh_m.group(1))
            leistung = _parse_float_de(kw_m.group(1)) if kw_m else None
            preis_euro = _parse_float_de(preis_m.group(1)) if preis_m else None
            # Letzter €-Betrag in der Zeile ist meist Gesamtpreis
            gesamt = _parse_float_de(gesamt_m[-1]) if gesamt_m else None

            if datum and kwh and kwh > 0.5:
                if preis_euro is None and gesamt and kwh:
                    preis_euro = gesamt / kwh
                preis_ct = (preis_euro * 100) if preis_euro else 49.0  # EnBW Fallback

                vorgaenge.append(Ladevorgang(
                    datum=datum,
                    menge_kwh=round(kwh, 3),
                    preis_kwh=round(preis_ct, 2),
                    gesamtpreis=round(gesamt, 2) if gesamt else round(kwh * preis_ct / 100, 2),
                    anbieter="EnBW",
                    ladeleistung_kw=leistung,
                    ladetyp=_detect_ladetyp(leistung, kontext),
                    quelle="Einzelvorgang",
                    notiz="EnBW Import",
                    warnungen=[] if preis_euro else
                    ["Weder Preis noch Betrag gefunden – 49 ct/kWh angenommen, bitte Betrag eintragen"]
                ))

    # Deduplizierung (selbes Datum + kWh)
    seen = set()
    unique = []
    for v in vorgaenge:
        key = (v.datum, v.menge_kwh)
        if key not in seen:
            seen.add(key)
            unique.append(v)
    vorgaenge = unique

    if not vorgaenge:
        vorgaenge += _parse_monatsuebersicht(text, "EnBW")

    return vorgaenge


# ─────────────────────────────────────────────
#  MEDL PARSER
# ─────────────────────────────────────────────

def parse_medl(text: str) -> list[Ladevorgang]:
    """
    medl Rechnung – kommunales Stadtwerk Mülheim.
    Oft einfachere Layouts, AC-Lader.
    """
    vorgaenge = []
    lines = text.split("\n")

    for i, line in enumerate(lines):
        datum_m = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", line)
        if not datum_m:
            continue

        kontext = " ".join(lines[i:i+3])

        kwh_m = re.search(r"([\d.,]+)\s*[kK][wW][hH]", kontext)
        preis_m = re.search(r"([\d.,]+)\s*(?:€/[kK][wW][hH]|ct/[kK][wW][hH])", kontext)
        gesamt_m = re.findall(r"([\d.,]+)\s*€", kontext)

        if kwh_m:
            datum = _parse_datum_de(datum_m.group(1))
            kwh = _parse_float_de(kwh_m.group(1))
            gesamt = _parse_float_de(gesamt_m[-1]) if gesamt_m else None

            if not datum or not kwh or kwh < 0.5:
                continue

            # Preis ermitteln
            raw = _parse_float_de(preis_m.group(1)) if preis_m else None
            if raw is not None:
                # ct oder €?
                if "ct" in preis_m.group(0).lower():
                    preis_ct = raw
                else:
                    preis_ct = raw * 100 if raw < 5 else raw
            elif gesamt and kwh:
                preis_ct = round(gesamt / kwh * 100, 2)
            else:
                preis_ct = None

            warnungen = []
            if preis_ct is None:
                preis_ct = 39.0  # medl Fallback
                warnungen.append("Weder Preis noch Betrag gefunden – 39 ct/kWh angenommen, bitte Betrag eintragen")

            if not gesamt and kwh and preis_ct:
                gesamt = round(kwh * preis_ct / 100, 2)

            vorgaenge.append(Ladevorgang(
                datum=datum,
                menge_kwh=round(kwh, 3),
                preis_kwh=round(preis_ct, 2),
                gesamtpreis=round(gesamt, 2) if gesamt else 0.0,
                anbieter="medl",
                ladetyp="AC",
                quelle="Einzelvorgang",
                notiz="medl Import",
                warnungen=warnungen
            ))

    if not vorgaenge:
        vorgaenge += _parse_monatsuebersicht(text, "medl")

    return vorgaenge


# ─────────────────────────────────────────────
#  GENERISCHER FALLBACK
# ─────────────────────────────────────────────

def _parse_monatsuebersicht(text: str, anbieter: str) -> list[Ladevorgang]:
    """
    Fallback: Sucht nach Gesamtsummen wenn keine Einzelvorgänge erkannt wurden.
    Erstellt einen Sammel-Eintrag.
    """
    vorgaenge = []

    # Gesamtenergie
    kwh_patterns = [
        r"[Gg]esamt(?:energie|verbrauch|menge)?[:\s]+([\d.,]+)\s*[kK][wW][hH]",
        r"[Ss]umme[:\s]+([\d.,]+)\s*[kK][wW][hH]",
        r"[Ee]nergie[:\s]+([\d.,]+)\s*[kK][wW][hH]",
        r"([\d.,]+)\s*[kK][wW][hH]\s+(?:gesamt|total|summe)",
    ]
    # Gesamtbetrag
    euro_patterns = [
        r"[Gg]esamt(?:betrag|summe|preis)?[:\s]+([\d.,]+)\s*€",
        r"[Rr]echnungsbetrag[:\s]+([\d.,]+)\s*€",
        r"[Zz]u\s+[Zz]ahlen[:\s]+([\d.,]+)\s*€",
        r"[Ss]umme[:\s]+([\d.,]+)\s*€",
    ]
    # Abrechnungsdatum / Monat
    datum_patterns = [
        r"[Aa]brechnungszeitraum[:\s]+.*?(\d{1,2}\.\d{1,2}\.\d{4})",
        r"[Rr]echnungsdatum[:\s]+(\d{1,2}\.\d{1,2}\.\d{4})",
        r"[Ll]eisungszeitraum[:\s]+.*?(\d{1,2}\.\d{1,2}\.\d{4})",
    ]

    kwh_total = None
    for pat in kwh_patterns:
        m = re.search(pat, text)
        if m:
            kwh_total = _parse_float_de(m.group(1))
            break

    euro_total = None
    for pat in euro_patterns:
        m = re.search(pat, text)
        if m:
            euro_total = _parse_float_de(m.group(1))
            break

    datum = None
    for pat in datum_patterns:
        m = re.search(pat, text)
        if m:
            datum = _parse_datum_de(m.group(1))
            break

    if not datum:
        # Erstes Datum im Text
        m = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", text)
        if m:
            datum = _parse_datum_de(m.group(1))

    if not datum:
        datum = datetime.now().strftime("%Y-%m-%d")

    if kwh_total and kwh_total > 0:
        if not euro_total:
            euro_total = 0.0
        preis_ct = round(euro_total / kwh_total * 100, 2) if euro_total > 0 else 0.0
        vorgaenge.append(Ladevorgang(
            datum=datum,
            menge_kwh=round(kwh_total, 3),
            preis_kwh=preis_ct,
            gesamtpreis=round(euro_total, 2),
            anbieter=anbieter,
            ladetyp="AC",
            quelle="Monatsübersicht",
            notiz=f"{anbieter} Monatsübersicht Import"
        ))

    return vorgaenge


# ─────────────────────────────────────────────
#  HAUPT-ENTRY-POINT
# ─────────────────────────────────────────────

def lies_pdf_text(pdf_path: str) -> tuple[str, str]:
    """
    Gibt (Text mit Tabellen, reiner Seitentext) zurück.
    Wirft IOError wenn PDF nicht gelesen werden kann.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber nicht installiert. Bitte: pip install pdfplumber")

    text_parts, seiten = [], []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
                    seiten.append(t)
                # Tabellen als Text extrahieren
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        if row:
                            text_parts.append("  ".join(str(c or "") for c in row))
    except Exception as e:
        raise IOError(f"PDF konnte nicht gelesen werden: {e}")

    full_text = "\n".join(text_parts)
    if not full_text.strip():
        raise IOError("PDF enthält keinen lesbaren Text (ggf. gescannt/Bild-PDF)")
    return full_text, "\n".join(seiten)


def auswerten_pdf(pdf_path: str) -> tuple[str, list[Ladevorgang], list[str]]:
    """(anbieter, [Ladevorgang], [Hinweis]) – Hinweise betreffen die ganze Rechnung."""
    full_text, seitentext = lies_pdf_text(pdf_path)
    # Seitentext ohne die zusaetzlich extrahierten Tabellen – die wuerden Vorgaenge doppeln
    return _auswerten(full_text, seitentext, fallback=True)


def auswerten_text(raw_text: str) -> tuple[str, list[Ladevorgang], list[str]]:
    """Für Mail-Text oder manuell eingefügten Text."""
    return _auswerten(raw_text, raw_text, fallback=False)


def parse_rechnung_pdf(pdf_path: str) -> tuple[str, list[Ladevorgang]]:
    return auswerten_pdf(pdf_path)[:2]


def parse_rechnung_text(raw_text: str) -> tuple[str, list[Ladevorgang]]:
    return auswerten_text(raw_text)[:2]


def _auswerten(text: str, seitentext: str, fallback: bool):
    anbieter = detect_anbieter(text)
    hinweise: list[str] = []
    vorgaenge = _parse_nach_anbieter(anbieter, text, seitentext, fallback, hinweise)
    hinweise += pruefe(anbieter, vorgaenge, text)
    return anbieter, vorgaenge, hinweise


def _parse_nach_anbieter(anbieter: str, text: str, seitentext: str,
                         fallback: bool, hinweise: list) -> list[Ladevorgang]:
    if anbieter == "EWE go":
        return _parse_ewe_go_uebersicht(seitentext) or parse_ewe_go(text)
    if anbieter == "EnBW":
        return parse_enbw(text)
    if anbieter == "medl":
        return parse_medl(text)
    if anbieter.startswith("Charge my") or anbieter == "DCS":
        return parse_dcs(seitentext, anbieter, hinweise)
    if anbieter == "Shell Recharge":
        return parse_shell(seitentext)
    if anbieter == "vaylens":
        return parse_vaylens(seitentext)
    if anbieter == "reev":
        return parse_reev(seitentext)
    if not fallback:
        return _parse_monatsuebersicht(text, "Unbekannt")
    # Generischer Versuch – die Parser setzen ihren eigenen Anbieternamen,
    # der hier nicht stimmt; der Nutzer traegt ihn in der Vorschau ein
    vorgaenge = (parse_ewe_go(text) or parse_enbw(text) or parse_medl(text)
                 or _parse_monatsuebersicht(text, "Unbekannt"))
    for v in vorgaenge:
        v.anbieter = "Unbekannt"
        v.notiz = "Rechnungsimport (Anbieter unbekannt)"
    return vorgaenge


# ─────────────────────────────────────────────
#  PLAUSIBILITAETSPRUEFUNG
# ─────────────────────────────────────────────

PREIS_MIN_CT, PREIS_MAX_CT = 15, 120   # ausserhalb davon eher ein Lesefehler
KWH_MAX = 150                          # mehr passt in kaum einen Akku


def pruefe(anbieter: str, vorgaenge: list[Ladevorgang], text: str) -> list[str]:
    """
    Haengt Warnungen an auffaellige Vorgaenge und gibt Hinweise zur ganzen
    Rechnung zurueck. Nichts wird verworfen – der Nutzer entscheidet in der Vorschau.
    """
    hinweise = []
    if not vorgaenge:
        hinweise.append("In dieser Rechnung wurde kein Ladevorgang erkannt. Das Layout ist vermutlich "
                        "unbekannt – bitte die Werte unten von Hand eintragen.")
        return hinweise
    if anbieter == "Unbekannt":
        hinweise.append("Anbieter nicht erkannt. Die Werte wurden mit einem allgemeinen Muster gelesen "
                        "und sind unsicher – bitte jede Zeile prüfen und den Anbieter eintragen.")
    if any(v.quelle == "Monatsübersicht" for v in vorgaenge):
        hinweise.append("Nur eine Monatssumme erkannt, keine einzelnen Ladevorgänge. "
                        "Datum und Betrag bitte prüfen.")

    heute = datetime.now().strftime("%Y-%m-%d")
    for v in vorgaenge:
        if not v.datum:
            v.warnungen.append("Datum nicht erkannt")
        elif v.datum > heute:
            v.warnungen.append("Datum liegt in der Zukunft")
        if v.menge_kwh > KWH_MAX:
            v.warnungen.append(f"Ungewöhnlich große Lademenge ({v.menge_kwh:g} kWh)".replace(".", ","))
        if v.gesamtpreis <= 0:
            v.warnungen.append("Betrag ist 0 €")
        elif not PREIS_MIN_CT <= v.preis_kwh <= PREIS_MAX_CT:
            v.warnungen.append(f"Ungewöhnlicher Preis ({v.preis_kwh:.2f} ct/kWh)".replace(".", ","))

    # Summe der Vorgaenge gegen den Endbetrag – DCS prueft je Laenderrechnung selbst
    if not (anbieter.startswith("Charge my") or anbieter == "DCS"):
        endbetrag = _endbetrag(text)
        summe = round(sum(v.gesamtpreis for v in vorgaenge), 2)
        if endbetrag is not None and abs(endbetrag - summe) > 0.05:
            hinweise.append(f"Die erkannten Vorgänge ergeben {_eur(summe)}, die Rechnung aber {_eur(endbetrag)} "
                            f"– vermutlich fehlt ein Vorgang oder es gibt Gebühren. Bitte prüfen.")
    return hinweise


def _endbetrag(text: str) -> Optional[float]:
    for muster in (r"Gezahlter Gesamtbetrag\s+([\d.,]+)\s*(?:€|EUR)",
                   r"Gesamtbetrag Brutto\s+([\d.,]+)\s*(?:€|EUR)",
                   r"F.lliger Betrag\s+([\d.,]+)\s*(?:€|EUR)",
                   r"Rechnungsbetrag:?\s+([\d.,]+)\s*(?:€|EUR)"):
        m = re.search(muster, text)
        if m:
            return _parse_float_de(m.group(1))
    return None
