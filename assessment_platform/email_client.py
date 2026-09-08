"""Outbound email: invite links, and the account-lifecycle mails (address
confirmation, password reset).

Deliberately thin: `send_invite_emails` (called after creating an invite) and
`send_account_email` (one message to one interviewer) share one delivery path.
With no SMTP host configured it logs instead of sending, so dev/tests run
offline; tests mock these functions.

Sending stays best-effort — a failure is reported, never raised, so it can't fail
invite creation (the link is stored regardless). But the outcome is *returned*
per recipient rather than only logged, so the interviewer can see that a specific
address didn't get the mail instead of assuming it did. Each recipient is sent
individually, so one bad address doesn't cost the rest their invite.
"""

from __future__ import annotations

import logging
import smtplib
import time
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage

from . import config

logger = logging.getLogger(__name__)

_NOT_CONFIGURED = "email is not configured on the server; the link was logged, not sent."
_DEADLINE_EXCEEDED = (
    "the server's email time budget (SMTP_DEADLINE_S) ran out before this address "
    "was reached; the link was not sent."
)


@dataclass(frozen=True)
class Delivery:
    """The outcome of emailing one recipient. `error` is None iff `sent`."""

    recipient: str
    sent: bool
    error: str | None = None


def _message(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = to
    msg.set_content(body)
    return msg


def _build_message(to: str, url: str, question_title: str) -> EmailMessage:
    return _message(
        to,
        f"Coding assessment invite: {question_title}",
        f"You've been invited to complete a coding assessment ({question_title}).\n\n"
        f"Open your assessment here:\n{url}\n\n"
        "This link is personal to you — you'll be asked to confirm this email\n"
        "address to begin, and it won't work for anyone else.",
    )


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
    return _deliver(
        recipients, url, "invite", lambda to: _build_message(to, url, question_title)
    )


def send_account_email(to: str, subject: str, body: str, url: str) -> Delivery:
    """Email one account-lifecycle message (confirm address, reset password) to
    an interviewer. Best-effort; never raises. `url` is the link in the body,
    named separately so the unconfigured-SMTP path can log it under LOG_PII."""
    return _deliver([to], url, "account", lambda rcpt: _message(rcpt, subject, body))[0]


def _deliver(
    recipients: list[str], url: str, kind: str, build: Callable[[str], EmailMessage]
) -> list[Delivery]:
    if config.SMTP_HOST is None:
        # Dev affordance: with LOG_PII on, log the copy-pasteable link. Otherwise
        # keep emails + link out of the logs — an invite link is still in the
        # create response and the interviewer's invite table.
        if config.LOG_PII:
            logger.info("SMTP not configured; %s link for %s: %s", kind, recipients, url)
        else:
            hint = (
                "retrieve it from the create response / invite table"
                if kind == "invite"
                else "LOG_PII=true logs it"
            )
            logger.info(
                "SMTP not configured; %s link for %d recipient(s) not emailed (%s).",
                kind,
                len(recipients),
                hint,
            )
        return [Delivery(r, sent=False, error=_NOT_CONFIGURED) for r in recipients]

    # One wall clock for the whole delivery, started before the connect so the
    # handshake and login count against it too. smtplib's `timeout` bounds each
    # socket operation individually, and a multi-recipient send makes many — so
    # without a total ceiling the worst case grows with the recipient list, all
    # of it inline on the caller's request. Checked between recipients, so the
    # real bound is this budget plus the one send already in flight.
    deadline = time.monotonic() + config.SMTP_DEADLINE_S
    try:
        with smtplib.SMTP(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_S
        ) as smtp:
            if config.SMTP_USE_TLS:
                smtp.starttls()
            if config.SMTP_USER and config.SMTP_PASSWORD:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            out: list[Delivery] = []
            for to in recipients:
                if time.monotonic() >= deadline:
                    logger.warning(
                        "%s email: time budget exhausted with %d recipient(s) unsent",
                        kind,
                        len(recipients) - len(out),
                    )
                    out.append(Delivery(to, sent=False, error=_DEADLINE_EXCEEDED))
                    continue
                out.append(_send_one(smtp, to, kind, build))
            return out
    except Exception as exc:
        # Connect/TLS/login failed — nobody was mailed. Report it against every
        # recipient rather than failing the caller's operation.
        logger.exception("%s email: SMTP connection failed for %s", kind, _who(recipients))
        return [Delivery(r, sent=False, error=str(exc)) for r in recipients]


def _send_one(
    smtp: smtplib.SMTP, to: str, kind: str, build: Callable[[str], EmailMessage]
) -> Delivery:
    try:
        smtp.send_message(build(to))
        return Delivery(to, sent=True)
    except Exception as exc:  # one bad address must not block the others
        logger.exception(
            "%s email: failed to send to %s", kind, to if config.LOG_PII else _mask_email(to)
        )
        return Delivery(to, sent=False, error=str(exc))
