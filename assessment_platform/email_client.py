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
from email.utils import formataddr

from . import config
from .email_templates import Email

logger = logging.getLogger(__name__)

_NOT_CONFIGURED = "email is not configured on the server; the link was logged, not sent."
_DEADLINE_EXCEEDED = (
    "the server's email time budget (SMTP_DEADLINE_S) ran out before this address "
    "was reached; the link was not sent."
)


class SmtpCredentialsRejectedError(RuntimeError):
    """The provider refused the configured credentials. Retrying never fixes it."""


def check_login() -> str | None:
    """Prove the mailer can actually reach and authenticate to the provider.

    `config.missing_smtp_vars()` proves only that the settings are *set*. A set
    but wrong password, or a host that wants auth we never send, fails exactly
    like a working mailer until the first real send — which happens in a
    background task off a request that already answered 202, so nobody is
    watching. That is how every password reset can be refused with
    `530 Authentication Required` while the UI reports success (U02).

    Sends no mail: connect, STARTTLS, LOGIN, quit. Raises
    SmtpCredentialsRejectedError when the provider rejected the credentials — a
    permanent failure that must stop the boot while `.env` is still editable.
    Returns a message for anything else (DNS, connect, TLS, timeout), which the
    caller logs without refusing to start: a provider that is briefly down must
    not also block a restart. Returns None when the mailer is healthy or there
    is no host to check.
    """
    if config.SMTP_HOST is None:
        return None
    try:
        with smtplib.SMTP(
            config.SMTP_HOST, config.SMTP_PORT, timeout=config.SMTP_TIMEOUT_S
        ) as smtp:
            if config.SMTP_USE_TLS:
                smtp.starttls()
            if config.SMTP_USER and config.SMTP_PASSWORD:
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            elif not _is_local_host(config.SMTP_HOST):
                # `_deliver` skips login when either credential is empty, so every
                # send goes out unauthenticated. A local relay (MailHog, Mailpit)
                # is fine with that; a provider is not, and answers 530 on the
                # first RCPT — invisibly, in a background task.
                return (
                    f"SMTP_USER/SMTP_PASSWORD are not both set, so mail to "
                    f"{config.SMTP_HOST} is sent unauthenticated and will almost "
                    "certainly be refused (Gmail answers 530 Authentication "
                    "Required). SMTP_PASSWORD must be a 16-character app "
                    "password, not the account password."
                )
    except smtplib.SMTPAuthenticationError as exc:
        raise SmtpCredentialsRejectedError(
            f"{config.SMTP_HOST} rejected SMTP_USER/SMTP_PASSWORD ({exc}). For a Gmail "
            "sender this must be a 16-character app password, not the account password."
        ) from exc
    except Exception as exc:
        return f"could not reach {config.SMTP_HOST}: {exc}"
    return None


def _is_local_host(host: str) -> bool:
    return host.lower() in {"localhost", "127.0.0.1", "::1", "[::1]", "mailhog", "mailpit"}


@dataclass(frozen=True)
class Delivery:
    """The outcome of emailing one recipient. `error` is None iff `sent`."""

    recipient: str
    sent: bool
    error: str | None = None


def _message(to: str, email: Email, reply_to: str | None = None) -> EmailMessage:
    """One `multipart/alternative` message: plain text first, HTML second.

    Order matters — a client picks the LAST part it can render, so the text body
    has to be set first for the HTML to win where HTML is supported.

    `Reply-To` is what makes a no-reply sending address survivable (X07): the
    From must stay on the authenticated domain for SPF/DKIM to pass, but a
    candidate hitting reply should reach the interviewer who invited them rather
    than a mailbox nobody reads. It is also the one header a Gmail sender keeps
    intact — Gmail rewrites From to the authenticated account, never Reply-To.
    """
    msg = EmailMessage()
    msg["Subject"] = email.subject
    # formataddr, not an f-string: a display name containing a comma or a quote
    # ("Acme, Inc.") concatenates into what parses as TWO addresses, and
    # send_message then hands smtplib a MAIL FROM of <Acme> — every message
    # rejected. formataddr quotes the name so that cannot happen.
    msg["From"] = (
        formataddr((config.SMTP_FROM_NAME, config.SMTP_FROM))
        if config.SMTP_FROM_NAME
        else config.SMTP_FROM
    )
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(email.text)
    msg.add_alternative(email.html, subtype="html")
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


def send_invite_emails(
    recipients: list[str], email: Email, url: str, *, reply_to: str | None = None
) -> list[Delivery]:
    """Email the invitation to each recipient. Best-effort; never raises.

    Returns one `Delivery` per recipient, in order. `reply_to` is the inviting
    interviewer, so a candidate who replies reaches a person.
    """
    if not recipients:
        return []
    return _deliver(recipients, url, "invite", lambda to: _message(to, email, reply_to))


def send_account_email(
    to: str, email: Email, url: str, *, reply_to: str | None = None
) -> Delivery:
    """Email one account-lifecycle message (confirm address, reset password, an
    organisation invitation) to one person. Best-effort; never raises. `url` is
    the link in the body, named separately so the unconfigured-SMTP path can log
    it under LOG_PII."""
    return _deliver([to], url, "account", lambda rcpt: _message(rcpt, email, reply_to))[0]


def send_results_email(to: str, email: Email, url: str) -> Delivery:
    """Tell one interviewer a candidate's sitting has been graded (X06).

    Same shape and same best-effort contract as `send_account_email`; separate so
    the log line names the right thing and so the two can grow apart (a results
    mail is the one an organisation is most likely to want redirected first).
    No `reply_to`: the recipient is the interviewer, so there is nobody else to
    point a reply at. `url` is the submission link in the body.
    """
    return _deliver([to], url, "results", lambda rcpt: _message(rcpt, email))[0]


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
