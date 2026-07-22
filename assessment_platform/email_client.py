"""Outbound email for invite links.

Deliberately thin: one `send_invite_emails` entry point that the API calls after
creating an invite. With no SMTP host configured it logs the link instead of
sending, so dev/tests run offline; tests mock this function.

Sending stays best-effort — a failure is reported, never raised, so it can't fail
invite creation (the link is stored regardless). But the outcome is *returned*
per recipient rather than only logged, so the interviewer can see that a specific
address didn't get the mail instead of assuming it did. Each recipient is sent
individually, so one bad address doesn't cost the rest their invite.
"""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from . import config

logger = logging.getLogger(__name__)

_NOT_CONFIGURED = "email is not configured on the server; the link was logged, not sent."


@dataclass(frozen=True)
class Delivery:
    """The outcome of emailing one recipient. `error` is None iff `sent`."""

    recipient: str
    sent: bool
    error: str | None = None


def _build_message(to: str, url: str, question_title: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Coding assessment invite: {question_title}"
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg.set_content(
        f"You've been invited to complete a coding assessment ({question_title}).\n\n"
        f"Open your assessment here:\n{url}\n\n"
        "This link is personal to you — you'll be asked to confirm this email\n"
        "address to begin, and it won't work for anyone else."
    )
    return msg


def _mask_email(addr: str) -> str:
    """A recognizable but non-identifying form for logs: first char of the local
    part and of the domain, the rest starred (jane@example.com -> j***@e***)."""
    local, _, domain = addr.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain[:1]}***"


def _who(recipients: list[str]) -> str:
    """Recipients rendered for a log line — verbatim only when LOG_PII is on."""
    return ", ".join(r if config.LOG_PII else _mask_email(r) for r in recipients)


def send_invite_emails(recipients: list[str], url: str, question_title: str) -> list[Delivery]:
    """Email the invite `url` to each recipient. Best-effort; never raises.

    Returns one `Delivery` per recipient, in order.
    """
    if not recipients:
        return []
    if config.SMTP_HOST is None:
        # Dev affordance: with LOG_PII on, log the copy-pasteable link. Otherwise
        # keep emails + link out of the logs — the link is still in the create
        # response and the interviewer's invite table.
        if config.LOG_PII:
            logger.info("SMTP not configured; invite link for %s: %s", recipients, url)
        else:
            logger.info(
                "SMTP not configured; invite link for %d recipient(s) not emailed "
                "(retrieve it from the create response / invite table).",
                len(recipients),
            )
        return [Delivery(r, sent=False, error=_NOT_CONFIGURED) for r in recipients]

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as smtp:
            if config.SMTP_USE_TLS:
                smtp.starttls()
            if config.SMTP_USER and config.SMTP_PASSWORD:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            return [_send_one(smtp, to, url, question_title) for to in recipients]
    except Exception as exc:
        # Connect/TLS/login failed — nobody was mailed. Report it against every
        # recipient rather than failing invite creation.
        logger.exception("invite email: SMTP connection failed for %s", _who(recipients))
        return [Delivery(r, sent=False, error=str(exc)) for r in recipients]


def _send_one(smtp: smtplib.SMTP, to: str, url: str, question_title: str) -> Delivery:
    try:
        smtp.send_message(_build_message(to, url, question_title))
        return Delivery(to, sent=True)
    except Exception as exc:  # one bad address must not block the others
        logger.exception(
            "invite email: failed to send to %s", to if config.LOG_PII else _mask_email(to)
        )
        return Delivery(to, sent=False, error=str(exc))
