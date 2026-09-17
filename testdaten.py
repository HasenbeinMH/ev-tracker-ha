"""
Testdaten fuer EV Tracker - einmalig ausfuehren
Legt realistische Daten fuer 6 Monate an (Nov 2024 - Apr 2025)
"""
import database as db


def main():
    db.init_db()

    print("Lege Testdaten an...")

    # Monats-km
    fahrten = [
        ("2024-11", 1180),
        ("2024-12", 980),
        ("2025-01", 1350),
        ("2025-02", 1120),
        ("2025-03", 1480),
        ("2025-04", 1250),
    ]
    for monat, km in fahrten:
        db.set_fahrt_monat(monat, km)
    print(f"  {len(fahrten)} Monate Fahrtdaten")

    # Benzinpreise
    benzin = [
        ("2024-11", 1.789),
        ("2024-12", 1.759),
        ("2025-01", 1.812),
        ("2025-02", 1.798),
        ("2025-03", 1.771),
        ("2025-04", 1.749),
    ]
    for monat, preis in benzin:
        db.set_benzinpreis(monat, preis)
    print(f"  {len(benzin)} Benzinpreise")

    # Stromtarif (nur anlegen wenn noch keiner existiert – idempotent)
    if not db.get_stromtarife():
        db.add_stromtarif("2024-01-01", 31.5, "medl Grünstrom 24")
        db.add_stromtarif("2025-01-01", 29.8, "medl Grünstrom 25")
        print("  2 Stromtarife")
    else:
        print("  Stromtarife bereits vorhanden – übersprungen")

    # Ladevorgaenge
    ladevorgaenge = [
        # Nov 2024
        ("2024-11-03", 28.5, 29.8, "Privat – Netzbezug", 11, "AC"),
        ("2024-11-12", 31.2, 29.8, "Privat – Netzbezug", 11, "AC"),
        ("2024-11-20", 18.4, None, "medl", 22, "AC"),
        ("2024-11-28", 22.1, 29.8, "Privat – Netzbezug", 11, "AC"),
        # Dez 2024
        ("2024-12-04", 25.0, 29.8, "Privat – Netzbezug", 11, "AC"),
        ("2024-12-14", 15.3, None, "EnBW", 50, "DC"),
        ("2024-12-22", 29.8, 29.8, "Privat – Netzbezug", 11, "AC"),
        # Jan 2025
        ("2025-01-06", 32.1, 29.8, "Privat – Netzbezug", 11, "AC"),
        ("2025-01-15", 20.5, 13.0, "Privat – PV", 11, "AC"),
        ("2025-01-23", 27.3, 29.8, "Privat – Netzbezug", 11, "AC"),
        ("2025-01-30", 18.9, None, "medl", 22, "AC"),
        # Feb 2025
        ("2025-02-08", 30.2, 29.8, "Privat – Netzbezug", 11, "AC"),
        ("2025-02-18", 22.7, 13.0, "Privat – PV", 11, "AC"),
        ("2025-02-25", 16.4, None, "EnBW", 150, "DC"),
        # Mär 2025
        ("2025-03-03", 28.9, 29.8, "Privat – Netzbezug", 11, "AC"),
        ("2025-03-11", 24.1, 13.0, "Privat – PV", 11, "AC"),
        ("2025-03-19", 19.8, None, "medl", 22, "AC"),
        ("2025-03-27", 31.5, 29.8, "Privat – Netzbezug", 11, "AC"),
        # Apr 2025
        ("2025-04-05", 26.3, 29.8, "Privat – Netzbezug", 11, "AC"),
        ("2025-04-13", 28.8, 13.0, "Privat – PV", 11, "AC"),
        ("2025-04-21", 17.2, None, "ARAL Pulse", 50, "DC"),
    ]

    # Pauschale Preise fuer oeffentliche Anbieter ohne ct-Angabe
    pauschale = {"medl": 0.39, "EnBW": 0.49, "ARAL Pulse": 0.45, "Ionity": 0.52}

    neu, uebersprungen = 0, 0
    for datum, kwh, ct, anbieter, leistung, ladetyp in ladevorgaenge:
        if db.ladevorgang_exists(datum, kwh, anbieter):
            uebersprungen += 1
            continue
        if ct:
            gesamt = round(kwh * ct / 100, 2)
            preis_kwh = ct
        else:
            p = pauschale.get(anbieter, 0.45)
            gesamt = round(kwh * p, 2)
            preis_kwh = p * 100
        db.add_ladevorgang(datum, kwh, preis_kwh, gesamt, anbieter, leistung, ladetyp)
        neu += 1

    print(f"  {neu} Ladevorgaenge angelegt, {uebersprungen} bereits vorhanden")

    # KFZ-Steuer
    db.set_einstellung("kfz_steuer_benziner", 168.0)
    print("  KFZ-Steuer: 168 EUR/Jahr")

    # THG-Quote (nur anlegen wenn noch keiner existiert – idempotent)
    if not db.get_thg_eintraege():
        db.add_thg("2025-01-15", 75.00, "ADAC", "THG 2024")
        print("  1 THG-Eintrag")
    else:
        print("  THG-Eintraege bereits vorhanden – übersprungen")

    print()
    print("Testdaten erfolgreich angelegt!")
    print("Web-App starten bzw. Container neu starten, dann im Browser oeffnen.")


if __name__ == "__main__":
    main()
