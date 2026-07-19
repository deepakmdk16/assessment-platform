"""Slice 1 tests: interviewer auth, question ownership, invites, the public
candidate flow, and the owner-scoped dashboard. Fully offline (agent mocked)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from conftest import async_return, register_interviewer  # pytest adds tests/ to sys.path
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from assessment_platform import agent_client
from assessment_platform import db as db_module
from assessment_platform.config import SUPPORTED_LANGUAGES
from assessment_platform.models import Invite, Submission


def _sample_question(qid: str = "sum_of_n") -> dict[str, Any]:
    return {
        "id": qid,
        "title": "Sum of N",
        "prompt": "Read N then N integers; print their sum.",
        "constraints": "1 <= N <= 1e5",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "required_complexity": None,
        "example_input": "2\n3 4\n",
        "example_output": "7",
        "test_cases": [
            {"name": "t1", "stdin": "2\n3 4\n", "expected": "7", "category": "correctness", "weight": 1.0},
            {"name": "big", "stdin": "9\n...", "expected": "42", "category": "performance", "weight": 3.0},
        ],
    }


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Auth                                                                          #
# --------------------------------------------------------------------------- #


def test_register_login_me(anon_client: TestClient) -> None:
    resp = anon_client.post(
        "/auth/register", json={"email": "a@x.io", "password": "pw", "name": "Ann"}
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == "a@x.io" and body["name"] == "Ann" and "id" in body
    assert "password" not in body and "password_hash" not in body

    resp = anon_client.post("/auth/login", json={"email": "a@x.io", "password": "pw"})
    assert resp.status_code == 200
    tok = resp.json()
    assert tok["token_type"] == "bearer" and tok["access_token"]

    resp = anon_client.get("/auth/me", headers=_auth(tok["access_token"]))
    assert resp.status_code == 200
    assert resp.json()["email"] == "a@x.io"


def test_register_duplicate_email_409(anon_client: TestClient) -> None:
    anon_client.post("/auth/register", json={"email": "d@x.io", "password": "pw", "name": "D"})
    resp = anon_client.post(
        "/auth/register", json={"email": "d@x.io", "password": "pw2", "name": "D2"}
    )
    assert resp.status_code == 409


def test_login_bad_credentials_401(anon_client: TestClient) -> None:
    anon_client.post("/auth/register", json={"email": "b@x.io", "password": "pw", "name": "B"})
    assert anon_client.post("/auth/login", json={"email": "b@x.io", "password": "nope"}).status_code == 401


def test_register_rejects_invalid_email_422(anon_client: TestClient) -> None:
    resp = anon_client.post(
        "/auth/register", json={"email": "not-an-email", "password": "pw", "name": "X"}
    )
    assert resp.status_code == 422
    assert anon_client.post("/auth/login", json={"email": "ghost@x.io", "password": "pw"}).status_code == 401


def test_me_requires_auth_401(anon_client: TestClient) -> None:
    assert anon_client.get("/auth/me").status_code == 401
    assert anon_client.get("/auth/me", headers=_auth("garbage.token")).status_code == 401


def test_questions_require_auth_401(anon_client: TestClient) -> None:
    assert anon_client.get("/questions").status_code == 401
    assert anon_client.post("/questions", json=_sample_question()).status_code == 401


# --------------------------------------------------------------------------- #
# Question ownership                                                            #
# --------------------------------------------------------------------------- #


def test_question_ownership_isolation(anon_client: TestClient) -> None:
    tok_a = register_interviewer(anon_client, "owner-a@x.io")
    tok_b = register_interviewer(anon_client, "owner-b@x.io")

    resp = anon_client.post("/questions", json=_sample_question(), headers=_auth(tok_a))
    assert resp.status_code == 201

    # B sees an empty list and cannot GET/PUT/DELETE A's question.
    assert anon_client.get("/questions", headers=_auth(tok_b)).json()["items"] == []
    assert anon_client.get("/questions/sum_of_n", headers=_auth(tok_b)).status_code == 403

    upd = {
        "title": "hijack", "prompt": "x", "constraints": "", "time_limit_s": 2.0,
        "pass_threshold": 0.9, "required_complexity": None,
        "example_input": None, "example_output": None, "test_cases": [],
    }
    assert anon_client.put("/questions/sum_of_n", json=upd, headers=_auth(tok_b)).status_code == 403
    assert anon_client.delete("/questions/sum_of_n", headers=_auth(tok_b)).status_code == 403

    # A still sees and owns it.
    assert len(anon_client.get("/questions", headers=_auth(tok_a)).json()["items"]) == 1
    assert anon_client.get("/questions/sum_of_n", headers=_auth(tok_a)).status_code == 200


# --------------------------------------------------------------------------- #
# Invites + candidate view (must NOT leak test cases / expected outputs)        #
# --------------------------------------------------------------------------- #


def _make_invite_resp(
    client: TestClient,
    token: str,
    expires_at: str | None = None,
    recipients: list[str] | None = None,
):
    client.post("/questions", json=_sample_question(), headers=_auth(token))
    body: dict[str, Any] = {"recipients": recipients or ["cand@x.io"]}
    if expires_at is not None:
        body["expires_at"] = expires_at
    return client.post("/questions/sum_of_n/invites", json=body, headers=_auth(token))


def _make_invite(
    client: TestClient,
    token: str,
    expires_at: str | None = None,
    recipients: list[str] | None = None,
) -> dict:
    resp = _make_invite_resp(client, token, expires_at, recipients)
    assert resp.status_code == 201
    return resp.json()


def test_create_invite_returns_link(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "iv@x.io")
    inv = _make_invite(anon_client, tok)
    assert inv["question_id"] == "sum_of_n"
    assert inv["status"] == "active"
    assert inv["recipients"] == ["cand@x.io"]
    assert inv["url"].endswith(f"/t/{inv['token']}")

    listed = anon_client.get("/questions/sum_of_n/invites", headers=_auth(tok)).json()
    assert len(listed) == 1 and listed[0]["token"] == inv["token"]


def test_invite_deliveries_persist_and_surface_on_read(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "iv-deliv@x.io")
    inv = _make_invite(anon_client, tok, recipients=["a@x.io", "b@x.io"])
    # Create response carries a per-recipient outcome for every recipient.
    assert {d["recipient"] for d in inv["deliveries"]} == {"a@x.io", "b@x.io"}

    # The audit trail persists: listing invites returns the same outcomes rather
    # than the empty list reads used to give (deliveries weren't stored before).
    listed = anon_client.get("/questions/sum_of_n/invites", headers=_auth(tok)).json()
    assert len(listed) == 1
    assert {d["recipient"] for d in listed[0]["deliveries"]} == {"a@x.io", "b@x.io"}
    # Under test SMTP is off, so every recipient records a not-sent outcome.
    assert all(d["sent"] is False for d in listed[0]["deliveries"])


def test_create_invite_rejects_invalid_recipient_422(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "iv-bad@x.io")
    anon_client.post("/questions", json=_sample_question(), headers=_auth(tok))
    resp = anon_client.post(
        "/questions/sum_of_n/invites", json={"recipients": ["nope"]}, headers=_auth(tok)
    )
    assert resp.status_code == 422


def test_invite_probe_reveals_no_question(anon_client: TestClient) -> None:
    """The bare link says only that it's live — the question is behind /start."""
    tok = register_interviewer(anon_client, "iv-probe@x.io")
    inv = _make_invite(anon_client, tok)

    resp = anon_client.get(f"/invite/{inv['token']}")
    assert resp.status_code == 200
    assert resp.json() == {"status": "active"}


def test_candidate_view_hides_test_cases(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "iv2@x.io")
    inv = _make_invite(anon_client, tok)

    # PUBLIC — no bearer, but must identify as an invited recipient.
    resp = anon_client.post(
        f"/invite/{inv['token']}/start", json={"candidate_email": "cand@x.io"}
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["languages"] == SUPPORTED_LANGUAGES
    q = data["question"]
    # Explicitly assert the answer key is NOT leaked.
    assert "test_cases" not in q
    assert "expected" not in q
    assert "pass_threshold" not in q
    assert set(q.keys()) == {
        "title", "prompt", "constraints", "example_input", "example_output", "time_limit_s",
    }
    # The public example is fine to show.
    assert q["example_output"] == "7"


def test_candidate_view_unknown_token_404(anon_client: TestClient) -> None:
    assert anon_client.get("/invite/does-not-exist").status_code == 404


# --------------------------------------------------------------------------- #
# Candidate submit                                                              #
# --------------------------------------------------------------------------- #


def test_candidate_submit_triggers_agent(anon_client: TestClient, monkeypatch) -> None:
    tok = register_interviewer(anon_client, "iv3@x.io")
    inv = _make_invite(anon_client, tok, recipients=["jane@x.io"])

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-cand"))

    resp = anon_client.post(
        f"/invite/{inv['token']}/submit",
        json={
            "candidate_name": "Jane Doe",
            "candidate_email": "jane@x.io",
            "language": "python",
            "code": "print(7)",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "running"
    sub_id = body["submission_id"]

    # Persisted with invite_id + candidate_email tied to the invite.
    with Session(db_module.engine) as s:
        sub = s.exec(select(Submission).where(Submission.id == sub_id)).first()
        assert sub is not None
        assert sub.candidate == "Jane Doe"
        assert sub.candidate_email == "jane@x.io"
        assert sub.invite_id is not None
        assert sub.agent_job_id == "job-cand"


def test_expired_invite_410(anon_client: TestClient, monkeypatch) -> None:
    tok = register_interviewer(anon_client, "iv4@x.io")
    inv = _make_invite(anon_client, tok, recipients=["x@x.io"])
    # Model an invite whose once-future expiry has since elapsed: the API rejects a
    # past expires_at at creation, so age the stored row directly instead.
    with Session(db_module.engine) as s:
        row = s.exec(select(Invite).where(Invite.token == inv["token"])).one()
        row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        s.add(row)
        s.commit()

    assert anon_client.get(f"/invite/{inv['token']}").status_code == 410

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-x"))
    resp = anon_client.post(
        f"/invite/{inv['token']}/submit",
        json={"candidate_name": "X", "candidate_email": "x@x.io", "language": "python", "code": "x"},
    )
    assert resp.status_code == 410


def test_invite_past_expiry_rejected(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "iv5@x.io")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    resp = _make_invite_resp(anon_client, tok, expires_at=past)
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Dashboard                                                                     #
# --------------------------------------------------------------------------- #


def test_dashboard_submissions_owner_scoped(anon_client: TestClient, monkeypatch) -> None:
    tok_a = register_interviewer(anon_client, "dash-a@x.io")
    tok_b = register_interviewer(anon_client, "dash-b@x.io")
    inv = _make_invite(anon_client, tok_a, recipients=["c@x.io"])

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-d"))
    anon_client.post(
        f"/invite/{inv['token']}/submit",
        json={"candidate_name": "Cand", "candidate_email": "c@x.io", "language": "python", "code": "x"},
    )

    # Owner A sees the candidate's submission.
    resp = anon_client.get("/questions/sum_of_n/submissions", headers=_auth(tok_a))
    assert resp.status_code == 200
    rows = resp.json()["items"]
    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_name"] == "Cand"
    assert row["candidate_email"] == "c@x.io"
    assert row["language"] == "python"
    assert row["status"] == "running"
    assert row["verdict"] is None  # no callback yet

    # Non-owner B is forbidden.
    assert anon_client.get("/questions/sum_of_n/submissions", headers=_auth(tok_b)).status_code == 403
