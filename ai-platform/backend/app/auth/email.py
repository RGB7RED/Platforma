from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
from functools import lru_cache
import logging
import os
import smtplib

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmailSettings:
    smtp_host: str
    smtp_port: int
    smtp_user: str | None
    smtp_pass: str | None
    smtp_from: str
    public_base_url: str


@lru_cache
def get_email_settings() -> EmailSettings:
    smtp_host = os.getenv("SMTP_HOST", "")
    smtp_port = int(os.getenv("SMTP_PORT", "25"))
    smtp_user = os.getenv("SMTP_USER") or None
    smtp_pass = os.getenv("SMTP_PASS") or None
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@localhost")
    public_base_url = os.getenv("PUBLIC_BASE_URL", "http://localhost").rstrip("/")

    return EmailSettings(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        smtp_from=smtp_from,
        public_base_url=public_base_url,
    )


def build_public_link(path: str) -> str:
    settings = get_email_settings()
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{settings.public_base_url}{path}"


def send_email(*, to_email: str, subject: str, body: str) -> None:
    settings = get_email_settings()
    if not settings.smtp_host:
        logger.warning(
            "SMTP not configured; skipping email delivery. to=%s subject=%s body=%s",
            to_email,
            subject,
            body,
        )
        return

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_user and settings.smtp_pass:
                smtp.login(settings.smtp_user, settings.smtp_pass)
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_user and settings.smtp_pass:
            smtp.starttls()
            smtp.login(settings.smtp_user, settings.smtp_pass)
        smtp.send_message(message)
