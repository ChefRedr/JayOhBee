"""Email notifications over SMTP. No-op when SMTP env vars are unset."""
from __future__ import annotations

import logging
import os
import smtplib
from email.message import EmailMessage

log = logging.getLogger("jobbot.notify")


def _configured() -> bool:
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "NOTIFY_EMAIL_TO"))


def send_email(subject: str, body: str) -> bool:
    if not _configured():
        log.debug("notifications not configured; skipping: %s", subject)
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[jobbot] {subject}"
    msg["From"] = os.environ.get("NOTIFY_EMAIL_FROM", os.environ["SMTP_USER"])
    msg["To"] = os.environ["NOTIFY_EMAIL_TO"]
    msg.set_content(body)
    try:
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as smtp:
            smtp.starttls()
            smtp.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            smtp.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 — notification failure must not break the run
        log.error("email send failed: %s", exc)
        return False


def notify_applied(company: str, title: str, location: str | None, url: str) -> None:
    send_email(
        f"Applied: {title} @ {company}",
        f"Applied automatically:\n\nCompany: {company}\nRole: {title}\n"
        f"Location: {location or 'n/a'}\nURL: {url}\n",
    )


def notify_needs_review(company: str, title: str, reason: str, url: str) -> None:
    send_email(
        f"Needs review: {title} @ {company}",
        f"Application needs review:\n\nCompany: {company}\nRole: {title}\n"
        f"Reason: {reason}\nURL: {url}\n",
    )


def notify_summary(metrics: dict) -> None:
    lines = "\n".join(f"{k}: {v}" for k, v in metrics.items())
    send_email("Run summary", f"Job bot run summary:\n\n{lines}\n")
