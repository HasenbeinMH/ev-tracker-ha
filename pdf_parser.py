"""
PDF-Parser fuer Laderechnungen: EWE go, EnBW, medl
Extrahiert Einzelvorgaenge und/oder Monatsübersichten.
"""
import re
from datetime import datetime
from dataclasses import dataclass
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
    return "Unbekannt"


# ─────────────────────────────────────────────
#  EWE GO PARSER
# ─────────────────────────────────────────────

def parse_ewe_go(text: str) -> list[Ladevorgang]:
    """
    EWE go Rechnung – typisches Layout:
    Datum | Uhrzeit | Ladestation | kWh | Preis/kWh | Gesamt
    """
    vorgaenge = []

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

        # Kontext: aktuelle + nächste 3 Zeilen
        kontext = " ".join(lines[i:i+4])

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
                    notiz="EnBW Import"
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
                preis_ct = 39.0  # medl Fallback

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
                notiz="medl Import"
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

def parse_rechnung_pdf(pdf_path: str) -> tuple[str, list[Ladevorgang]]:
    """
    Liest eine PDF-Rechnung ein und gibt (anbieter, [Ladevorgang]) zurück.
    Wirft IOError wenn PDF nicht gelesen werden kann.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber nicht installiert. Bitte: pip install pdfplumber")

    text_parts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
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

    anbieter = detect_anbieter(full_text)

    if anbieter == "EWE go":
        vorgaenge = parse_ewe_go(full_text)
    elif anbieter == "EnBW":
        vorgaenge = parse_enbw(full_text)
    elif anbieter == "medl":
        vorgaenge = parse_medl(full_text)
    else:
        # Generischer Parser – versucht alle drei
        vorgaenge = (parse_ewe_go(full_text) or
                     parse_enbw(full_text) or
                     parse_medl(full_text) or
                     _parse_monatsuebersicht(full_text, "Unbekannt"))

    return anbieter, vorgaenge


def parse_rechnung_text(raw_text: str) -> tuple[str, list[Ladevorgang]]:
    """Für Mail-Text oder manuell eingefügten Text."""
    anbieter = detect_anbieter(raw_text)
    if anbieter == "EWE go":
        vorgaenge = parse_ewe_go(raw_text)
    elif anbieter == "EnBW":
        vorgaenge = parse_enbw(raw_text)
    elif anbieter == "medl":
        vorgaenge = parse_medl(raw_text)
    else:
        vorgaenge = _parse_monatsuebersicht(raw_text, "Unbekannt")
    return anbieter, vorgaenge
