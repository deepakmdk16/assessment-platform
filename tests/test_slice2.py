"""Slice 2 tests: CORS, gated registration, rate limiting, invite lifecycle
(revoke + one-submission-per-email), and auth/ownership on the /submissions*
routes. Fully offline (agent mocked)."""

from __future__ import annotations

from conftest import register_interviewer  # pytest adds tests/ to sys.path
from fastapi.testclient import TestClient
from test_slice1 import _auth, _make_invite, _sample_question

from assessment_platform import agent_client, api, config, email_client


def _submit(client: TestClient, token: str, email: str, name: str = "Cand") -> object:
    return client.post(
        f"/invite/{token}/submit",
        json={"candidate_name": name, "candidate_email": email, "language": "python", "code": "x"},
    )


# --------------------------------------------------------------------------- #
# CORS                                                                          #
# --------------------------------------------------------------------------- #


def test_cors_allows_frontend_origin(anon_client: TestClient) -> None:
    origin = config.CORS_ORIGINS[0]
    resp = anon_client.get("/health", headers={"Origin": origin})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin


# --------------------------------------------------------------------------- #
# Gated registration (decision B)                                               #
# --------------------------------------------------------------------------- #


def test_register_gate_requires_code_when_set(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(config, "REGISTRATION_CODE", "s3cret")

    # Missing / wrong code -> 403.
    assert anon_client.post(
        "/auth/register", json={"email": "g@x.io", "password": "pw", "name": "G"}
    ).status_code == 403
    assert anon_client.post(
        "/auth/register",
        json={"email": "g@x.io", "password": "pw", "name": "G", "registration_code": "nope"},
    ).status_code == 403

    # Correct code -> 201.
    assert anon_client.post(
        "/auth/register",
        json={"email": "g@x.io", "password": "pw", "name": "G", "registration_code": "s3cret"},
    ).status_code == 201


# --------------------------------------------------------------------------- #
# Rate limiting                                                                 #
# --------------------------------------------------------------------------- #


def test_login_rate_limited(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(config, "LOGIN_RATE_LIMIT_MAX", 2)
    anon_client.post("/auth/register", json={"email": "rl@x.io", "password": "pw", "name": "RL"})
    body = {"email": "rl@x.io", "password": "pw"}
    assert anon_client.post("/auth/login", json=body).status_code == 200
    assert anon_client.post("/auth/login", json=body).status_code == 200
    assert anon_client.post("/auth/login", json=body).status_code == 429


def test_candidate_submit_rate_limited(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(config, "SUBMIT_RATE_LIMIT_MAX", 1)
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    tok = register_interviewer(anon_client, "rl2@x.io")
    inv = _make_invite(anon_client, tok, recipients=["a@x.io", "b@x.io"])

    assert _submit(anon_client, inv["token"], "a@x.io").status_code == 201
    # Different email, but over the per-window submit cap -> 429 (checked first).
    assert _submit(anon_client, inv["token"], "b@x.io").status_code == 429


# --------------------------------------------------------------------------- #
# Invite lifecycle                                                              #
# --------------------------------------------------------------------------- #


def test_revoke_invite_blocks_candidate(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    tok = register_interviewer(anon_client, "rv@x.io")
    inv = _make_invite(anon_client, tok, recipients=["c@x.io"])

    resp = anon_client.post(
        f"/questions/sum_of_n/invites/{inv['token']}/revoke", headers=_auth(tok)
    )
    assert resp.status_code == 200 and resp.json()["status"] == "revoked"

    # Candidate view + submit both 410 once revoked.
    assert anon_client.get(f"/invite/{inv['token']}").status_code == 410
    assert _submit(anon_client, inv["token"], "c@x.io").status_code == 410


def test_revoke_invite_owner_scoped(anon_client: TestClient) -> None:
    tok_a = register_interviewer(anon_client, "rv-a@x.io")
    tok_b = register_interviewer(anon_client, "rv-b@x.io")
    inv = _make_invite(anon_client, tok_a)
    resp = anon_client.post(
        f"/questions/sum_of_n/invites/{inv['token']}/revoke", headers=_auth(tok_b)
    )
    assert resp.status_code == 403


def test_one_submission_per_email(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    tok = register_interviewer(anon_client, "1p@x.io")
    inv = _make_invite(anon_client, tok, recipients=["jane@x.io", "john@x.io"])

    assert _submit(anon_client, inv["token"], "jane@x.io").status_code == 201
    # Same email (case-insensitive) -> 409.
    assert _submit(anon_client, inv["token"], "JANE@x.io").status_code == 409
    # A different email is still allowed.
    assert _submit(anon_client, inv["token"], "john@x.io").status_code == 201


def test_duplicate_submit_race_is_refused_by_the_db(
    anon_client: TestClient, monkeypatch
) -> None:
    """The DATABASE enforces one attempt — the pre-insert check cannot.

    `_check_not_already_submitted` is a SELECT followed by an INSERT, so two
    concurrent submits both pass it and both write. Neutralising the check
    reproduces exactly the state a race produces — both requests arriving at the
    insert — and the unique constraint must still refuse the second. Without the
    constraint this test stores two attempts and triggers two paid agent jobs.
    """
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    monkeypatch.setattr(api, "_check_not_already_submitted", lambda *a, **k: None)
    tok = register_interviewer(anon_client, "race@x.io")
    inv = _make_invite(anon_client, tok, recipients=["jane@x.io"])

    assert _submit(anon_client, inv["token"], "jane@x.io").status_code == 201
    resp = _submit(anon_client, inv["token"], "jane@x.io")
    assert resp.status_code == 409
    # Indistinguishable from the check's own 409 — the candidate learns nothing
    # about which guard caught them.
    assert "already been recorded" in resp.json()["detail"]

    # Refused, not duplicated: exactly one attempt is on record.
    subs = anon_client.get("/questions/sum_of_n/submissions", headers=_auth(tok)).json()
    assert len(subs) == 1


# --------------------------------------------------------------------------- #
# Invite email                                                                  #
# --------------------------------------------------------------------------- #


def test_create_invite_emails_recipients(anon_client: TestClient, monkeypatch) -> None:
    sent: dict[str, object] = {}

    def _fake_send(recipients: list[str], url: str, title: str) -> list[email_client.Delivery]:
        sent["recipients"], sent["url"], sent["title"] = recipients, url, title
        return [email_client.Delivery(r, sent=True) for r in recipients]

    monkeypatch.setattr(email_client, "send_invite_emails", _fake_send)
    tok = register_interviewer(anon_client, "mail@x.io")
    inv = _make_invite(anon_client, tok)  # recipients=["cand@x.io"]

    assert sent["recipients"] == ["cand@x.io"]
    assert sent["url"] == inv["url"]
    assert sent["title"] == "Sum of N"


# --------------------------------------------------------------------------- #
# /submissions* auth + ownership                                               #
# --------------------------------------------------------------------------- #


def test_submissions_routes_require_auth(anon_client: TestClient) -> None:
    assert anon_client.get("/submissions").status_code == 401
    assert anon_client.get("/submissions/whatever").status_code == 401
    assert anon_client.post(
        "/submissions",
        json={"question_id": "x", "candidate": "c", "language": "python", "code": "x"},
    ).status_code == 401
    assert anon_client.post("/submissions/whatever/retry").status_code == 401


def test_submissions_owner_scoped(anon_client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    tok_a = register_interviewer(anon_client, "sub-a@x.io")
    tok_b = register_interviewer(anon_client, "sub-b@x.io")
    anon_client.post("/questions", json=_sample_question(), headers=_auth(tok_a))

    created = anon_client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "c", "language": "python", "code": "x"},
        headers=_auth(tok_a),
    )
    assert created.status_code == 201
    sub_id = created.json()["id"]

    # B cannot read A's submission, and B's list is empty.
    assert anon_client.get(f"/submissions/{sub_id}", headers=_auth(tok_b)).status_code == 403
    assert anon_client.get("/submissions", headers=_auth(tok_b)).json() == []
    # A sees exactly its own.
    assert len(anon_client.get("/submissions", headers=_auth(tok_a)).json()) == 1
