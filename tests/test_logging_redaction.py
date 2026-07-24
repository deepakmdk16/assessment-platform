"""SEC3 — candidate PII (recipient emails, invite links) must stay out of the
logs by default; LOG_PII opts back in for local debugging."""

from __future__ import annotations

import logging

from assessment_platform import config, email_client


def test_unconfigured_smtp_does_not_log_email_or_link(caplog) -> None:
    # Under test SMTP is forced off, so this hits the "not configured" path.
    with caplog.at_level(logging.INFO, logger="assessment_platform.email_client"):
        out = email_client.send_invite_emails(
            ["jane@example.com"], "http://host/t/SECRET-TOKEN", "Two Sum"
        )
    assert all(d.sent is False for d in out)
    text = caplog.text
    assert "jane@example.com" not in text
    assert "SECRET-TOKEN" not in text
    assert "1 recipient" in text  # the redacted line reports a count, not the address


def test_smtp_failure_masks_recipients(caplog, monkeypatch) -> None:
    # Point at an unroutable host so the connect raises and we hit the failure log.
    monkeypatch.setattr(config, "SMTP_HOST", "127.0.0.1")
    monkeypatch.setattr(config, "SMTP_PORT", 1)
    with caplog.at_level(logging.INFO, logger="assessment_platform.email_client"):
        out = email_client.send_invite_emails(["mark@corp.io"], "http://host/t/T", "Q")
    assert all(d.sent is False for d in out)
    assert "mark@corp.io" not in caplog.text
    assert "m***@c***" in caplog.text


def test_log_pii_opt_in_logs_verbatim(caplog, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOG_PII", True)
    with caplog.at_level(logging.INFO, logger="assessment_platform.email_client"):
        email_client.send_invite_emails(["jane@example.com"], "http://host/t/SECRET-TOKEN", "Q")
    assert "jane@example.com" in caplog.text
    assert "SECRET-TOKEN" in caplog.text
