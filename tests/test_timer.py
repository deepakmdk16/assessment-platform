"""T1 — the assessment timer: question.duration_minutes, the server-authoritative
start stamped on /start, and the deadline enforced on /submit. Fully offline."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from assessment_platform import agent_client
from assessment_platform import db as db_module
from assessment_platform.models import CandidateAttempt


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _question(qid: str, duration_minutes: int | None) -> dict[str, Any]:
    return {
        "id": qid,
        "title": "Timed problem",
        "prompt": "Read N then N integers; print their sum.",
        "constraints": "1 <= N <= 1e5",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "example_input": "2\n3 4\n",
        "example_output": "7",
        "duration_minutes": duration_minutes,
        # 4 correctness + 1 performance to satisfy the authoring-time floor (A1).
        "test_cases": [
            {"name": "t1", "stdin": "2\n3 4\n", "expected": "7", "category": "correctness", "weight": 1.0},
            {"name": "t2", "stdin": "1\n5\n", "expected": "5", "category": "correctness", "weight": 1.0},
            {"name": "t3", "stdin": "3\n1 2 3\n", "expected": "6", "category": "correctness", "weight": 1.0},
            {"name": "t4", "stdin": "1\n0\n", "expected": "0", "category": "correctness", "weight": 1.0},
            {"name": "big", "stdin": "9\n...", "expected": "42", "category": "performance", "weight": 3.0},
        ],
    }


def _invite(client: TestClient, tok: str, qid: str, email: str) -> dict:
    resp = client.post(f"/questions/{qid}/invites", json={"recipients": [email]}, headers=_auth(tok))
    assert resp.status_code == 201
    return resp.json()


def _age_attempt_started_at(token: str, seconds_ago: int) -> None:
    """Push the (single) attempt's clock start into the past, to model a candidate
    who opened the assessment `seconds_ago` seconds ago."""
    with Session(db_module.engine) as s:
        attempt = s.exec(select(CandidateAttempt)).one()
        attempt.started_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
        s.add(attempt)
        s.commit()


def test_duration_roundtrips_and_rejects_nonpositive(client) -> None:
    body = client.post("/questions", json=_question("timed", 45)).json()
    assert body["duration_minutes"] == 45
    got = client.get("/questions/timed").json()
    assert got["duration_minutes"] == 45

    # Untimed is the default and comes back as None.
    untimed = client.post("/questions", json=_question("untimed", None)).json()
    assert untimed["duration_minutes"] is None

    # A non-positive duration is a bad request, not a 0-minute assessment.
    assert client.post("/questions", json=_question("zero", 0)).status_code == 422


def test_untimed_question_has_no_deadline(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "t-untimed@x.io")
    anon_client.post("/questions", json=_question("q_untimed", None), headers=_auth(tok))
    inv = _invite(anon_client, tok, "q_untimed", "c@x.io")

    started = anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io"})
    assert started.status_code == 200
    assert started.json()["deadline"] is None


def test_timed_start_returns_stable_deadline(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "t-timed@x.io")
    anon_client.post("/questions", json=_question("q_timed", 30), headers=_auth(tok))
    inv = _invite(anon_client, tok, "q_timed", "c@x.io")

    first = anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io"})
    assert first.status_code == 200
    deadline = first.json()["deadline"]
    assert deadline is not None
    expected = datetime.now(timezone.utc) + timedelta(minutes=30)
    assert abs((datetime.fromisoformat(deadline) - expected).total_seconds()) < 60

    # Re-opening the link must NOT reset the clock: same deadline back.
    again = anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io"})
    assert again.json()["deadline"] == deadline


def test_submit_within_grace_is_accepted(anon_client: TestClient, monkeypatch) -> None:
    tok = register_interviewer(anon_client, "t-grace@x.io")
    anon_client.post("/questions", json=_question("q_grace", 30), headers=_auth(tok))
    inv = _invite(anon_client, tok, "q_grace", "c@x.io")
    anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io"})
    # 5s past a 30-minute deadline — inside the 15s grace, so an on-time auto-submit
    # that arrives slightly late still counts.
    _age_attempt_started_at(tok, 30 * 60 + 5)

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-g"))
    resp = anon_client.post(
        f"/invite/{inv['token']}/submit",
        json={"candidate_name": "C", "candidate_email": "c@x.io", "language": "python", "code": "print(7)"},
    )
    assert resp.status_code == 201


def test_submit_past_deadline_and_grace_410(anon_client: TestClient, monkeypatch) -> None:
    tok = register_interviewer(anon_client, "t-late@x.io")
    anon_client.post("/questions", json=_question("q_late", 30), headers=_auth(tok))
    inv = _invite(anon_client, tok, "q_late", "c@x.io")
    anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io"})
    # 60s past the deadline — well beyond the 15s grace.
    _age_attempt_started_at(tok, 30 * 60 + 60)

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-l"))
    resp = anon_client.post(
        f"/invite/{inv['token']}/submit",
        json={"candidate_name": "C", "candidate_email": "c@x.io", "language": "python", "code": "print(7)"},
    )
    assert resp.status_code == 410
    assert "time" in resp.json()["detail"].lower()
