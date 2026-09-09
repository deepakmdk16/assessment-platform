"""Email rendering and headers (X07).

Nothing here sends: `_message` is called directly and the resulting
`EmailMessage` is inspected. That is the point — the parts, the headers and the
escaping are what a receiver judges the mail on, and they are cheap to assert
without a mail server anywhere near the test.
"""

from __future__ import annotations

from email.message import EmailMessage

import pytest

from assessment_platform import config, email_client, email_templates


def _rendered(email: email_templates.Email, reply_to: str | None = None) -> EmailMessage:
    return email_client._message("cand@x.io", email, reply_to)


def _part(msg: EmailMessage, subtype: str) -> str:
    body = msg.get_body(preferencelist=(subtype,))
    assert body is not None, f"no {subtype} part"
    return str(body.get_content())


# --------------------------------------------------------------------------- #
# Both alternatives, always                                                     #
# --------------------------------------------------------------------------- #


def test_every_message_carries_a_text_and_an_html_part() -> None:
    """A text-only send reads as bulk mail; an HTML-only send is unreadable in
    the clients that refuse HTML. Every template owes both."""
    templates = [
        email_templates.invite(url="https://x/t/abc", title="Sum of N"),
        email_templates.results_ready(
            candidate="Jane", title="Screen", results_url="https://x/s/1",
            questions=[("Sum of N", "PASS", 100.0)],
        ),
        email_templates.org_invitation(inviter_name="Ann", org_name="Acme", url="https://x/j/1"),
        email_templates.confirm_address(name="Jane", url="https://x/v/1"),
        email_templates.reset_password(name="Jane", url="https://x/r/1"),
    ]
    for email in templates:
        msg = _rendered(email)
        assert msg.get_content_type() == "multipart/alternative"
        assert email.subject and _part(msg, "plain") and _part(msg, "html")


def test_the_text_part_spells_out_the_url() -> None:
    """A text client that renders "click here" with no link gives the reader
    nothing to act on, so the bare URL has to be in the plain body."""
    msg = _rendered(email_templates.invite(url="https://x/t/abc123", title="Sum of N"))
    assert "https://x/t/abc123" in _part(msg, "plain")


def test_html_is_the_last_part_so_it_wins_where_supported() -> None:
    """A client picks the LAST alternative it can render."""
    msg = _rendered(email_templates.confirm_address(name="Jane", url="https://x/v/1"))
    assert [p.get_content_type() for p in msg.iter_parts()] == [  # type: ignore[union-attr]
        "text/plain",
        "text/html",
    ]


# --------------------------------------------------------------------------- #
# Escaping — every interpolated value is user-supplied                          #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "email",
    [
        email_templates.invite(url="https://x/t/a", title="<script>alert(1)</script>"),
        email_templates.invite(url="https://x/t/a", title="Q", org_name="<b>Acme</b>"),
        email_templates.results_ready(
            candidate="<img src=x onerror=alert(1)>", title="S", results_url="https://x/s/1",
            questions=[("<i>Q</i>", "PASS", 100.0)],
        ),
        email_templates.confirm_address(name="<script>x</script>", url="https://x/v/1"),
        email_templates.org_invitation(
            inviter_name="<script>x</script>", org_name="Acme", url="https://x/j/1"
        ),
    ],
)
def test_user_supplied_values_are_escaped_in_the_html(email: email_templates.Email) -> None:
    """Candidate names, question titles and organisation names are all typed by
    someone else. An unescaped `<` breaks the markup at best."""
    html = _part(_rendered(email), "html")
    assert "<script>" not in html
    assert "<img src=x" not in html
    assert "<b>Acme</b>" not in html and "<i>Q</i>" not in html


def test_escaping_does_not_mangle_ordinary_punctuation() -> None:
    """The escape must not turn a normal title into entities the reader sees."""
    html = _part(_rendered(email_templates.invite(url="https://x/t/a", title="Fizz & Buzz")), "html")
    assert "Fizz &amp; Buzz" in html  # escaped in the source…
    assert "Fizz & Buzz" in _part(_rendered(email_templates.invite(url="https://x/t/a", title="Fizz & Buzz")), "plain")


# --------------------------------------------------------------------------- #
# Headers                                                                       #
# --------------------------------------------------------------------------- #


def test_reply_to_is_set_when_given_and_absent_otherwise() -> None:
    """X07: the From stays on the authenticated domain for SPF/DKIM, so Reply-To
    is the only thing that can point a candidate's reply at a human."""
    email = email_templates.invite(url="https://x/t/a", title="Q")
    assert _rendered(email, "interviewer@acme.io")["Reply-To"] == "interviewer@acme.io"
    assert _rendered(email)["Reply-To"] is None


def test_from_name_is_used_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    email = email_templates.confirm_address(name="Jane", url="https://x/v/1")
    monkeypatch.setattr(config, "SMTP_FROM", "no-reply@acme.io")

    monkeypatch.setattr(config, "SMTP_FROM_NAME", None)
    assert _rendered(email)["From"] == "no-reply@acme.io"

    monkeypatch.setattr(config, "SMTP_FROM_NAME", "Acme Assessments")
    assert _rendered(email)["From"] == "Acme Assessments <no-reply@acme.io>"


def test_a_comma_in_the_from_name_does_not_split_it_into_two_addresses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concatenated, 'Acme, Inc.' parses as TWO addresses and smtplib then sends
    MAIL FROM:<Acme> — every message rejected. formataddr quotes it."""
    monkeypatch.setattr(config, "SMTP_FROM", "no-reply@acme.io")
    monkeypatch.setattr(config, "SMTP_FROM_NAME", "Acme, Inc.")
    msg = _rendered(email_templates.confirm_address(name="Jane", url="https://x/v/1"))

    assert msg["From"] == '"Acme, Inc." <no-reply@acme.io>'
    # The header must resolve to exactly one address, and the right one.
    from email.utils import getaddresses

    assert [a for _n, a in getaddresses([msg["From"]])] == ["no-reply@acme.io"]


def test_results_email_lists_every_question_in_both_parts() -> None:
    email = email_templates.results_ready(
        candidate="Jane",
        title="Backend Screen",
        results_url="https://x/s/1",
        questions=[("Sum of N", "PASS", 100.0), ("Two Sum", "FAIL", 40.0)],
    )
    msg = _rendered(email)
    for part in ("plain", "html"):
        body = _part(msg, part)
        assert "Sum of N" in body and "Two Sum" in body
        assert "PASS" in body and "FAIL" in body
