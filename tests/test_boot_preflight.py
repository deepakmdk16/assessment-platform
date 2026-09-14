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


# --------------------------------------------------------------------------- #
# Mailer login preflight (U02)                                                  #
# --------------------------------------------------------------------------- #


class _LoginSMTP:
    """A reachable server whose LOGIN outcome the test chooses."""

    auth_error: BaseException | None = None
    logged_in: list[tuple[str, str]] = []

    def __init__(self, *a: Any, **k: Any) -> None:
        type(self).logged_in = []

    def __enter__(self) -> _LoginSMTP:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        if type(self).auth_error is not None:
            raise type(self).auth_error
        type(self).logged_in.append((user, password))


def _smtp(monkeypatch: pytest.MonkeyPatch, host: str, user: str | None, password: str | None) -> None:
    monkeypatch.setattr(config, "SMTP_HOST", host)
    monkeypatch.setattr(config, "SMTP_USER", user)
    monkeypatch.setattr(config, "SMTP_PASSWORD", password)
    monkeypatch.setattr(config, "SMTP_USE_TLS", True)
    _LoginSMTP.auth_error = None
    monkeypatch.setattr(email_client.smtplib, "SMTP", _LoginSMTP)


def test_check_login_is_silent_when_the_mailer_authenticates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _smtp(monkeypatch, "smtp.gmail.com", "me@gmail.com", "app-password")
    assert email_client.check_login() is None
    assert _LoginSMTP.logged_in == [("me@gmail.com", "app-password")]


def test_rejected_credentials_stop_the_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong password passes the presence check and then refuses every send
    from a background task nobody watches. It has to fail here instead."""
    _smtp(monkeypatch, "smtp.gmail.com", "me@gmail.com", "the-account-password")
    _LoginSMTP.auth_error = email_client.smtplib.SMTPAuthenticationError(
        535, b"5.7.8 Username and Password not accepted"
    )
    with pytest.raises(email_client.SmtpCredentialsRejectedError) as excinfo:
        email_client.check_login()
    # Actionable on the box: names the setting and what a Gmail value must be.
    assert "app password" in str(excinfo.value)
    assert "SMTP_PASSWORD" in str(excinfo.value)


def test_half_configured_remote_host_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reported failure: a host is set but the password isn't, so `_deliver`
    skips LOGIN and the provider answers 530 on every send — invisibly."""
    _smtp(monkeypatch, "smtp.gmail.com", "me@gmail.com", None)
    problem = email_client.check_login()
    assert problem is not None
    assert "530" in problem and "SMTP_PASSWORD" in problem
    assert _LoginSMTP.logged_in == []


def test_local_relay_without_credentials_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    """MailHog/Mailpit take unauthenticated mail on purpose — warning about it
    would train the operator to ignore the warning that matters."""
    _smtp(monkeypatch, "127.0.0.1", None, None)
    assert email_client.check_login() is None


def test_unreachable_host_is_reported_but_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider that is briefly down must not also block a restart."""
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")

    def _boom(*a: Any, **k: Any) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(email_client.smtplib, "SMTP", _boom)
    problem = email_client.check_login()
    assert problem is not None and "connection refused" in problem


def test_check_login_is_skipped_with_no_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SMTP_HOST", None)
    assert email_client.check_login() is None


def test_boot_logs_a_transient_problem_and_carries_on(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    monkeypatch.setattr(config, "TESTING", False)
    monkeypatch.setattr(email_client, "check_login", lambda: "could not reach smtp.example.com: x")
    with caplog.at_level("ERROR"):
        assert api._check_email_deliverable() is None
    assert "could not reach" in caplog.text


def test_boot_propagates_rejected_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "TESTING", False)

    def _reject() -> str | None:
        raise email_client.SmtpCredentialsRejectedError("nope")

    monkeypatch.setattr(email_client, "check_login", _reject)
    with pytest.raises(email_client.SmtpCredentialsRejectedError):
        api._check_email_deliverable()
