# -*- coding: utf-8 -*-
"""
E-Mail-Versand über SMTP (STARTTLS oder SSL, je nach Port).
Zugangsdaten kommen aus den Einstellungen der Datenbank.
"""
import smtplib
import ssl
from email.message import EmailMessage

import database as db


def sende_mail(betreff: str, html: str, text: str = "",
               empfaenger: str = "", cfg: dict | None = None) -> tuple[bool, str]:
    """Verschickt eine HTML-Mail. Rückgabe: (erfolg, meldung)."""
    cfg = cfg or db.get_mail_settings()

    server = (cfg.get("mail_smtp_server") or "").strip()
    benutzer = (cfg.get("mail_benutzer") or "").strip()
    passwort = cfg.get("mail_passwort") or ""
    absender = (cfg.get("mail_absender") or "").strip() or benutzer
    ziel = (empfaenger or cfg.get("mail_empfaenger") or "").strip()

    if not server:
        return False, "Kein SMTP-Server hinterlegt."
    if not ziel:
        return False, "Kein Empfänger hinterlegt."
    if not absender:
        return False, "Kein Absender hinterlegt."

    try:
        port = int(cfg.get("mail_smtp_port") or 587)
    except ValueError:
        return False, "Port ist keine Zahl."

    nachricht = EmailMessage()
    nachricht["Subject"] = betreff
    nachricht["From"] = absender
    nachricht["To"] = ziel
    nachricht.set_content(text or "Dieser Bericht benötigt einen HTML-fähigen Mailclient.")
    nachricht.add_alternative(html, subtype="html")

    kontext = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(server, port, timeout=30, context=kontext) as s:
                if benutzer:
                    s.login(benutzer, passwort)
                s.send_message(nachricht)
        else:
            with smtplib.SMTP(server, port, timeout=30) as s:
                s.ehlo()
                s.starttls(context=kontext)
                s.ehlo()
                if benutzer:
                    s.login(benutzer, passwort)
                s.send_message(nachricht)
    except smtplib.SMTPAuthenticationError:
        return False, ("Anmeldung abgelehnt. Bei web.de/GMX muss der SMTP-Zugang "
                       "im Postfach freigeschaltet sein; ggf. wird ein separates "
                       "App-Passwort benötigt.")
    except smtplib.SMTPException as e:
        return False, f"SMTP-Fehler: {e}"
    except OSError as e:
        return False, f"Verbindungsfehler: {e}"

    return True, f"Mail an {ziel} verschickt."
