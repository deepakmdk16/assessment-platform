"""The copy and markup of every outbound email, in one place (X07).

Until this existed every message was a plain-text f-string built at its call
site, which had three costs: an invite looked like a machine wrote it (the
single biggest reason a candidate treats it as junk), the wording of the same
idea drifted between call sites, and there was no HTML alternative at all —
which most receivers read as a signal of bulk or automated mail.

**Both alternatives, always.** Each builder returns an `Email` carrying a
subject, a plain-text body and an HTML body, and `email_client` sends them as
one `multipart/alternative`. The text part is never an afterthought: it spells
out the full URL, because a text-only client that shows a bare "click here"
gives the reader nothing to act on.

**No template engine.** Five messages do not justify a dependency (CONVENTIONS:
keep deps lean), and the security rule that matters is simply applied everywhere
instead: every interpolated value is `escape()`d on the HTML side. Candidate
names, question titles and organisation names are all user-supplied, and an
unescaped `<` in a question title would otherwise break the markup at best.

**Inline styles only, and a light palette.** Email clients strip or ignore
`<head>` CSS with no consistency worth reasoning about, so every rule is on the
element. The frontend's token/no-hex convention is a `web/` rule about
re-themeable UI; it does not reach here, and could not — there is no cascade to
theme with.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

# One neutral palette. Deliberately light-only: `prefers-color-scheme` support
# across mail clients is inconsistent enough that a dark variant reliably
# produces unreadable pairings somewhere, and an email is read once.
_INK = "#1a1a1a"
_MUTED = "#6b7280"
_LINE = "#e5e7eb"
_PAGE = "#f6f7f9"
_CARD = "#ffffff"
_ACTION = "#1f6feb"
_VERDICT = {"PASS": "#0f7b3f", "FAIL": "#b42318", "ERROR": "#8a5a00"}

_FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
)


@dataclass(frozen=True)
class Email:
    """One rendered message: the subject line and both body alternatives."""

    subject: str
    text: str
    html: str


def _button(label: str, url: str) -> str:
    return (
        f'<a href="{escape(url, quote=True)}" '
        f'style="display:inline-block;padding:11px 20px;border-radius:6px;'
        f'background:{_ACTION};color:#ffffff;font-weight:600;font-size:15px;'
        f'text-decoration:none">{escape(label)}</a>'
    )


def _layout(*, heading: str, blocks: list[str], footer: str) -> str:
    """Wrap pre-rendered HTML `blocks` in the shared shell.

    Callers pass HTML, so everything they interpolate must already be escaped —
    the one place in this module where that is the caller's job.
    """
    body = "".join(blocks)
    return (
        f'<div style="margin:0;padding:24px 12px;background:{_PAGE};font-family:{_FONT}">'
        f'<div style="max-width:560px;margin:0 auto;background:{_CARD};'
        f'border:1px solid {_LINE};border-radius:10px;padding:32px">'
        f'<h1 style="margin:0 0 18px;font-size:20px;line-height:1.3;color:{_INK}">'
        f"{escape(heading)}</h1>"
        f"{body}"
        f'<p style="margin:28px 0 0;padding-top:18px;border-top:1px solid {_LINE};'
        f'font-size:12px;line-height:1.6;color:{_MUTED}">{escape(footer)}</p>'
        "</div></div>"
    )


def _p(text: str) -> str:
    return (
        f'<p style="margin:0 0 14px;font-size:15px;line-height:1.6;color:{_INK}">'
        f"{escape(text)}</p>"
    )


def _fallback(url: str) -> str:
    """The link as copyable text under the button — for the clients that strip
    the button, and for anyone who wants to see where it goes before clicking."""
    return (
        f'<p style="margin:22px 0 0;font-size:12px;line-height:1.6;color:{_MUTED}">'
        f'Or paste this into your browser:<br><span style="color:{_INK}">'
        f"{escape(url)}</span></p>"
    )


# --------------------------------------------------------------------------- #
# Candidate-facing                                                              #
# --------------------------------------------------------------------------- #


def invite(*, url: str, title: str, org_name: str | None = None) -> Email:
    """The invitation a candidate receives. The one email a stranger reads."""
    sender = org_name or "A hiring team"
    subject = f"Coding assessment: {title}"
    if org_name:
        subject = f"{org_name} — coding assessment: {title}"

    text = (
        f"{sender} has invited you to complete a coding assessment ({title}).\n\n"
        f"Open your assessment here:\n{url}\n\n"
        "This link is personal to you — you'll be asked to confirm this email\n"
        "address to begin, and it won't work for anyone else.\n\n"
        "If you weren't expecting this, you can ignore this email."
    )
    html = _layout(
        heading="You've been invited to a coding assessment",
        blocks=[
            _p(f"{sender} has invited you to complete {title}."),
            _p("The link below is personal to you: you'll confirm this email address to begin, and it won't work for anyone else."),
            f'<p style="margin:24px 0 0">{_button("Start the assessment", url)}</p>',
            _fallback(url),
        ],
        footer="If you weren't expecting this, you can ignore this email.",
    )
    return Email(subject=subject, text=text, html=html)


# --------------------------------------------------------------------------- #
# Interviewer-facing                                                            #
# --------------------------------------------------------------------------- #


def results_ready(
    *,
    candidate: str,
    title: str,
    results_url: str,
    questions: list[tuple[str, str, float]],
) -> Email:
    """A finished sitting (X06). `questions` is (title, verdict, score_pct)."""
    text_rows = "\n".join(
        f"  {verdict:<5} {score:5.1f}%  {qtitle}" for qtitle, verdict, score in questions
    )
    text = (
        f"{candidate} has completed {title}.\n\n"
        f"{text_rows}\n\n"
        f"Full result, code and per-test-case detail:\n{results_url}"
    )

    rows = []
    for qtitle, verdict, score in questions:
        colour = _VERDICT.get(verdict, _MUTED)
        rows.append(
            f'<tr><td style="padding:8px 0;border-bottom:1px solid {_LINE};'
            f'font-size:14px;color:{_INK}">{escape(qtitle)}</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid {_LINE};'
            f'text-align:right;font-size:14px;font-weight:600;color:{colour};'
            f'white-space:nowrap">{escape(verdict)} · {score:.0f}%</td></tr>'
        )
    table = (
        f'<table style="width:100%;border-collapse:collapse;margin:4px 0 0">'
        f"{''.join(rows)}</table>"
    )

    html = _layout(
        heading=f"{candidate} finished {title}",
        blocks=[
            _p("Here's how the sitting went:"),
            table,
            f'<p style="margin:24px 0 0">{_button("Open the full result", results_url)}</p>',
            _fallback(results_url),
        ],
        footer="You're receiving this because you sent this candidate's invitation.",
    )
    return Email(subject=f"Assessment complete: {candidate} — {title}", text=text, html=html)


def org_invitation(*, inviter_name: str, org_name: str, url: str) -> Email:
    text = (
        f"{inviter_name} invited you to join {org_name} on the coding-assessment "
        "platform.\n\n"
        f"Accept the invitation:\n{url}\n\n"
        "The link is valid for 7 days. If you weren't expecting this, ignore it."
    )
    html = _layout(
        heading=f"Join {org_name}",
        blocks=[
            _p(f"{inviter_name} invited you to join {org_name} on the coding-assessment platform."),
            f'<p style="margin:24px 0 0">{_button("Accept the invitation", url)}</p>',
            _fallback(url),
        ],
        footer="The link is valid for 7 days. If you weren't expecting this, ignore it.",
    )
    return Email(subject=f"You've been invited to {org_name}", text=text, html=html)


# --------------------------------------------------------------------------- #
# Account lifecycle                                                             #
# --------------------------------------------------------------------------- #


def confirm_address(*, name: str, url: str) -> Email:
    text = (
        f"Hi {name},\n\n"
        "Confirm this address for your coding-assessment account by opening:\n"
        f"{url}\n\n"
        "The link is valid for 3 days. If you didn't create an account, ignore this email."
    )
    html = _layout(
        heading="Confirm your email address",
        blocks=[
            _p(f"Hi {name},"),
            _p("Confirm this address for your coding-assessment account."),
            f'<p style="margin:24px 0 0">{_button("Confirm my address", url)}</p>',
            _fallback(url),
        ],
        footer="The link is valid for 3 days. If you didn't create an account, ignore this email.",
    )
    return Email(subject="Confirm your email address", text=text, html=html)


def reset_password(*, name: str, url: str) -> Email:
    text = (
        f"Hi {name},\n\n"
        "Someone asked to reset the password for this coding-assessment account. "
        "If that was you, open:\n"
        f"{url}\n\n"
        "The link works once and expires in 1 hour. If you didn't ask for it, "
        "ignore this email — your password is unchanged."
    )
    html = _layout(
        heading="Reset your password",
        blocks=[
            _p(f"Hi {name},"),
            _p("Someone asked to reset the password for this coding-assessment account."),
            f'<p style="margin:24px 0 0">{_button("Choose a new password", url)}</p>',
            _fallback(url),
        ],
        footer=(
            "The link works once and expires in 1 hour. If you didn't ask for it, "
            "ignore this email — your password is unchanged."
        ),
    )
    return Email(subject="Reset your password", text=text, html=html)
