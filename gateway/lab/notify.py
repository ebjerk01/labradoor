"""Mail to the owner when an admin asks for an approval (optional; in-app notification always happens)."""
import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage

from . import config

log = logging.getLogger("lab.notify")


def configured():
    return bool(config.SMTP_HOST and config.SMTP_FROM and config.OWNER_EMAIL)


def send(subject, text):
    if not configured():
        return

    def go():
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, config.OWNER_EMAIL, subject
        msg.set_content(text)
        try:
            ctx = ssl.create_default_context()
            if config.SMTP_PORT == 465:
                conn = smtplib.SMTP_SSL(config.SMTP_HOST, 465, timeout=20, context=ctx)
            else:
                conn = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20)
                conn.starttls(context=ctx)
            with conn as s:
                if config.SMTP_USER:
                    s.login(config.SMTP_USER, config.SMTP_PASSWORD)
                s.send_message(msg)
        except (OSError, smtplib.SMTPException) as e:
            log.warning("approval mail failed: %s", e)

    threading.Thread(target=go, daemon=True).start()
