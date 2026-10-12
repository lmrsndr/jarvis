"""Explicitly configured outbound owner reports. Incoming mail is not executable."""

import os
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone
from control.store import now
from zoneinfo import ZoneInfo


def configured():
    return bool(
        os.getenv("JARVIS_SMTP_HOST")
        and os.getenv("JARVIS_EMAIL_TO")
        and os.getenv("JARVIS_EMAIL_FROM")
    )


def send_pending(store):
    if not configured():
        return
    start = os.getenv("JARVIS_EMAIL_QUIET_START", "")
    end = os.getenv("JARVIS_EMAIL_QUIET_END", "")
    clock = datetime.now(ZoneInfo("Europe/London")).strftime("%H:%M")
    if (
        start
        and end
        and ((start <= clock < end) if start < end else (clock >= start or clock < end))
    ):
        return
    with store.db() as c:
        pending = [
            dict(r)
            for r in c.execute(
                "SELECT * FROM control_outbox WHERE status='pending' AND due_at<=? AND attempts<3 LIMIT 5",
                (now(),),
            )
        ]
    for item in pending:
        message = EmailMessage()
        message["Subject"] = item["subject"]
        message["From"] = os.environ["JARVIS_EMAIL_FROM"]
        message["To"] = os.environ["JARVIS_EMAIL_TO"]
        message.set_content(item["body"])
        try:
            host = os.environ["JARVIS_SMTP_HOST"]
            port = int(os.getenv("JARVIS_SMTP_PORT", "587"))
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls()
                if os.getenv("JARVIS_SMTP_USER"):
                    server.login(
                        os.environ["JARVIS_SMTP_USER"],
                        os.getenv("JARVIS_SMTP_PASSWORD", ""),
                    )
                server.send_message(message)
            with store.db() as c:
                c.execute(
                    "UPDATE control_outbox SET status='sent',attempts=attempts+1 WHERE id=?",
                    (item["id"],),
                )
            store.event("email", "Owner report sent")
        except Exception:
            due = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            with store.db() as c:
                c.execute(
                    "UPDATE control_outbox SET attempts=attempts+1,due_at=?,error='Delivery failed; verify SMTP configuration.' WHERE id=?",
                    (due, item["id"]),
                )
