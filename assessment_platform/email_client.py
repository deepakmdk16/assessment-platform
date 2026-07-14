"""Outbound email for invite links.

Deliberately thin: one `send_invite_emails` entry point that the API calls after
creating an invite. With no SMTP host configured it logs the link instead of
sending, so dev/tests run offline; tests mock this function. Sending is
best-effort — a failure is logged, never raised, so it can't fail invite
creation (the link is stored regardless).
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from . import config

logger = logging.getLogger(__name__)


def _build_message(to: str, url: str, question_title: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Coding assessment invite: {question_title}"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg.set_content(
        f"You've been invited to complete a coding assessment ({question_title}).\n\n"
        f"Open your assessment here:\n{url}\n\n"
        "This link is personal to you; please don't share it."
    )
    return msg


def send_invite_emails(recipients: list[str], url: str, question_title: str) -> None:
    """Email the invite `url` to each recipient. Best-effort; never raises."""
    if not recipients:
        return
    if config.SMTP_HOST is None:
        logger.info("SMTP not configured; invite link for %s: %s", recipients, url)
        return
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            if config.SMTP_USE_TLS:
                smtp.starttls()
            if config.SMTP_USER and config.SMTP_PASSWORD:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            for to in recipients:
                smtp.send_message(_build_message(to, url, question_title))
    except Exception:  # delivery failure must not fail invite creation
        logger.exception("failed to send invite email to %s", recipients)
