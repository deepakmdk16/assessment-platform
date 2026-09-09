"""Boot-time mail preflight, and the SMTP time budget.

The platform refuses to start with a half-configured mailer, because a server
that cannot send is a server that accepts invites it silently never delivers.
These tests pin the three things that make that safe to ship: the check names
every missing variable, the placeholder sender counts as missing, and both test
harnesses plus the documented escape hatch still boot.
"""

from __future__ import annotations

from typing import Any

import pytest

from assessment_platform import api, config, email_client, email_templates


def _clear_smtp(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing configured, and not in test mode — a bare production boot."""
    monkeypatch.setattr(config, "TESTING", False)
    monkeypatch.setattr(config, "ALLOW_UNCONFIGURED_EMAIL", False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setattr(config, "SMTP_USER", None)
    monkeypatch.setattr(config, "SMTP_PASSWORD", None)
    monkeypatch.setattr(config, "SMTP_FROM", config.SMTP_FROM_PLACEHOLDER)


def test_missing_smtp_vars_names_every_unset_var(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp(monkeypatch)
    assert config.missing_smtp_vars() == [
        "SMTP_HOST",
        "SMTP_USER",
        "SMTP_PASSWORD",
        "SMTP_FROM",
    ]


def test_placeholder_from_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.local` has no MX, so the placeholder sender bounces everywhere. A
    presence-only check would wave it through — this is the whole 'no original
    email exists' failure, so it must read as unset."""
    _clear_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setattr(config, "SMTP_USER", "me@gmail.com")
    monkeypatch.setattr(config, "SMTP_PASSWORD", "app-password")
    assert config.missing_smtp_vars() == ["SMTP_FROM"]

    monkeypatch.setattr(config, "SMTP_FROM", "me@gmail.com")
    assert config.missing_smtp_vars() == []


def test_preflight_raises_and_names_the_missing_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp(monkeypatch)
    with pytest.raises(RuntimeError) as excinfo:
        api._require_email_configured()
    message = str(excinfo.value)
    for name in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM"):
        assert name in message
    # The error has to be actionable on the box, so it points at the file to edit
    # and names the escape hatch rather than just refusing.
    assert ".env.example" in message
    assert "ALLOW_UNCONFIGURED_EMAIL" in message


def test_escape_hatch_allows_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_smtp(monkeypatch)
    monkeypatch.setattr(config, "ALLOW_UNCONFIGURED_EMAIL", True)
    assert api._require_email_configured() is None


def test_testing_flag_allows_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keeps pytest and the Playwright webServer green. If someone re-keys the
    test flag, this fails loudly instead of the whole suite failing at fixture
    setup with an unrelated-looking error."""
    _clear_smtp(monkeypatch)
    monkeypatch.setattr(config, "TESTING", True)
    assert api._require_email_configured() is None


def test_client_fixture_boots_under_the_preflight(anon_client: Any) -> None:
    """conftest enters `with TestClient(app)`, which runs the lifespan — so the
    preflight executes on every client test. Proves it doesn't."""
    assert anon_client.get("/health").status_code == 200


# --------------------------------------------------------------------------- #
# SMTP time budget                                                              #
# --------------------------------------------------------------------------- #


class _CountingSMTP:
    """Accepts everything and records it; stands in for a reachable server."""

    sent: list[str] = []

    def __init__(self, *a: Any, **k: Any) -> None:
        type(self).sent = []

    def __enter__(self) -> _CountingSMTP:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, *a: Any) -> None:
        return None

    def send_message(self, msg: Any) -> None:
        type(self).sent.append(msg["To"])


def test_deadline_stops_the_recipient_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero budget means nobody is reached, and each recipient is told why
    rather than being reported as sent."""
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(config, "SMTP_DEADLINE_S", 0.0)
    monkeypatch.setattr(email_client.smtplib, "SMTP", _CountingSMTP)

    out = email_client.send_invite_emails(
        ["a@x.io", "b@x.io", "c@x.io"], email_templates.invite(url="http://u", title="Q"), "http://u"
    )

    assert [d.sent for d in out] == [False, False, False]
    assert all(d.error == email_client._DEADLINE_EXCEEDED for d in out)
    assert _CountingSMTP.sent == []


def test_deadline_is_inert_on_the_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """The budget must not cost anyone their invite when the server is healthy."""
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(email_client.smtplib, "SMTP", _CountingSMTP)

    out = email_client.send_invite_emails(
        ["a@x.io", "b@x.io", "c@x.io"], email_templates.invite(url="http://u", title="Q"), "http://u"
    )

    assert [d.sent for d in out] == [True, True, True]
    assert _CountingSMTP.sent == ["a@x.io", "b@x.io", "c@x.io"]
