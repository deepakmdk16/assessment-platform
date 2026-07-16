"""Slice 9 tests: invite email binding, the /start gate, and invite-email
delivery reporting. Fully offline (agent + SMTP mocked).

The rules under test:
  - an invite must name at least one recipient;
  - only a named recipient can start or submit (case-insensitive);
  - a candidate who already submitted is turned away at *start*, not after
    they've written a solution;
  - the bare link reveals no question data;
  - a send failure is reported per recipient, never fails invite creation.
"""

from __future__ import annotations

import smtplib
from typing import Any

import pytest
from conftest import register_interviewer  # pytest adds tests/ to sys.path
from fastapi.testclient import TestClient
from test_slice1 import _auth, _make_invite, _sample_question

from assessment_platform import agent_client, config, email_client


def _start(client: TestClient, token: str, email: str) -> Any:
    return client.post(f"/invite/{token}/start", json={"candidate_email": email})


def _submit(client: TestClient, token: str, email: str) -> Any:
    return client.post(
        f"/invite/{token}/submit",
        json={"candidate_name": "Cand", "candidate_email": email, "language": "python", "code": "x"},
    )


# --------------------------------------------------------------------------- #
# Recipients are mandatory                                                      #
# --------------------------------------------------------------------------- #


def test_create_invite_requires_a_recipient(anon_client: TestClient) -> None:
    """An invite with no recipients would be a link nobody could use -> 422."""
    tok = register_interviewer(anon_client, "s9-empty@x.io")
    anon_client.post("/questions", json=_sample_question(), headers=_auth(tok))
    resp = anon_client.post(
        "/questions/sum_of_n/invites", json={"recipients": []}, headers=_auth(tok)
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# /start — email binding                                                        #
# --------------------------------------------------------------------------- #


def test_start_returns_question_to_invited_email(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "s9-ok@x.io")
    inv = _make_invite(anon_client, tok, recipients=["cand@x.io"])

    resp = _start(anon_client, inv["token"], "cand@x.io")
    assert resp.status_code == 200
    assert resp.json()["question"]["title"] == "Sum of N"


def test_start_rejects_uninvited_email(anon_client: TestClient) -> None:
    """The forwarded-link case: someone else holding the link can't get in."""
    tok = register_interviewer(anon_client, "s9-403@x.io")
    inv = _make_invite(anon_client, tok, recipients=["cand@x.io"])

    resp = _start(anon_client, inv["token"], "someone-else@x.io")
    assert resp.status_code == 403
    # And crucially, no question data came back with the refusal.
    assert "question" not in resp.json()


def test_start_email_check_is_case_and_space_insensitive(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "s9-case@x.io")
    inv = _make_invite(anon_client, tok, recipients=["Cand@X.io"])
    assert _start(anon_client, inv["token"], "  cand@x.io  ").status_code == 200


def test_start_allows_any_of_several_recipients(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "s9-multi@x.io")
    inv = _make_invite(anon_client, tok, recipients=["a@x.io", "b@x.io"])
    assert _start(anon_client, inv["token"], "a@x.io").status_code == 200
    assert _start(anon_client, inv["token"], "b@x.io").status_code == 200


# --------------------------------------------------------------------------- #
# /start — already-submitted gate (the point: turned away BEFORE coding)        #
# --------------------------------------------------------------------------- #


def test_start_blocks_a_candidate_who_already_submitted(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    tok = register_interviewer(anon_client, "s9-done@x.io")
    inv = _make_invite(anon_client, tok, recipients=["cand@x.io"])

    assert _start(anon_client, inv["token"], "cand@x.io").status_code == 200
    assert _submit(anon_client, inv["token"], "cand@x.io").status_code == 201

    # Second visit: refused at the gate, with no question handed out.
    resp = _start(anon_client, inv["token"], "cand@x.io")
    assert resp.status_code == 409
    assert "already been recorded" in resp.json()["detail"]
    assert "question" not in resp.json()


def test_start_gate_is_per_email_not_per_invite(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One candidate finishing must not lock the other invitee out."""
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    tok = register_interviewer(anon_client, "s9-per@x.io")
    inv = _make_invite(anon_client, tok, recipients=["a@x.io", "b@x.io"])

    assert _submit(anon_client, inv["token"], "a@x.io").status_code == 201
    assert _start(anon_client, inv["token"], "a@x.io").status_code == 409
    assert _start(anon_client, inv["token"], "b@x.io").status_code == 200


def test_start_on_revoked_and_unknown_invite(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "s9-rv@x.io")
    inv = _make_invite(anon_client, tok, recipients=["cand@x.io"])
    anon_client.post(f"/questions/sum_of_n/invites/{inv['token']}/revoke", headers=_auth(tok))

    assert _start(anon_client, inv["token"], "cand@x.io").status_code == 410
    assert _start(anon_client, "no-such-token", "cand@x.io").status_code == 404


# --------------------------------------------------------------------------- #
# Submit re-checks the gates (the start screen is only UI)                       #
# --------------------------------------------------------------------------- #


def test_submit_rejects_uninvited_email_even_without_start(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POSTing straight to /submit must not bypass the binding."""
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    tok = register_interviewer(anon_client, "s9-bypass@x.io")
    inv = _make_invite(anon_client, tok, recipients=["cand@x.io"])

    assert _submit(anon_client, inv["token"], "gatecrasher@x.io").status_code == 403


# --------------------------------------------------------------------------- #
# Invite email delivery reporting                                               #
# --------------------------------------------------------------------------- #


def test_create_invite_reports_unconfigured_smtp(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dev default: no SMTP host -> invite still created, but says it didn't send."""
    monkeypatch.setattr(config, "SMTP_HOST", None)
    tok = register_interviewer(anon_client, "s9-nosmtp@x.io")
    inv = _make_invite(anon_client, tok, recipients=["cand@x.io"])

    assert inv["status"] == "active"  # creation is unaffected
    assert inv["deliveries"] == [
        {"recipient": "cand@x.io", "sent": False, "error": email_client._NOT_CONFIGURED}
    ]


def test_create_invite_survives_send_failure(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken mail server must not cost the interviewer the invite."""

    def _boom(*a: Any, **k: Any) -> Any:
        raise smtplib.SMTPException("mail server on fire")

    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(smtplib, "SMTP", _boom)
    tok = register_interviewer(anon_client, "s9-boom@x.io")
    inv = _make_invite(anon_client, tok, recipients=["cand@x.io"])

    assert inv["status"] == "active"
    assert inv["deliveries"][0]["sent"] is False
    assert "mail server on fire" in inv["deliveries"][0]["error"]
    # The link still works for the candidate — they just need it another way.
    assert _start(anon_client, inv["token"], "cand@x.io").status_code == 200


def test_invite_reads_do_not_report_stale_deliveries(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "s9-stale@x.io")
    _make_invite(anon_client, tok, recipients=["cand@x.io"])
    listed = anon_client.get("/questions/sum_of_n/invites", headers=_auth(tok)).json()
    assert listed[0]["deliveries"] == []


# --------------------------------------------------------------------------- #
# email_client unit — one bad address must not block the rest                   #
# --------------------------------------------------------------------------- #


class _FakeSMTP:
    """Minimal stand-in: refuses one address, accepts the others."""

    def __init__(self, *a: Any, **k: Any) -> None:
        self.sent: list[str] = []

    def __enter__(self) -> _FakeSMTP:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def starttls(self) -> None:
        return None

    def login(self, *a: Any) -> None:
        return None

    def send_message(self, msg: Any) -> None:
        if msg["To"] == "bad@x.io":
            raise smtplib.SMTPRecipientsRefused({"bad@x.io": (550, b"no such user")})
        self.sent.append(msg["To"])


def test_one_bad_recipient_does_not_block_the_others(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    out = email_client.send_invite_emails(
        ["good@x.io", "bad@x.io", "also-good@x.io"], "http://x/t/abc", "Sum of N"
    )
    assert [(d.recipient, d.sent) for d in out] == [
        ("good@x.io", True),
        ("bad@x.io", False),
        ("also-good@x.io", True),
    ]
    assert out[1].error is not None
