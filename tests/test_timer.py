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

    started = anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io", "consent": True})
    assert started.status_code == 200
    assert started.json()["deadline"] is None


def test_timed_start_returns_stable_deadline(anon_client: TestClient) -> None:
    tok = register_interviewer(anon_client, "t-timed@x.io")
    anon_client.post("/questions", json=_question("q_timed", 30), headers=_auth(tok))
    inv = _invite(anon_client, tok, "q_timed", "c@x.io")

    first = anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io", "consent": True})
    assert first.status_code == 200
    deadline = first.json()["deadline"]
    assert deadline is not None
    expected = datetime.now(timezone.utc) + timedelta(minutes=30)
    assert abs((datetime.fromisoformat(deadline) - expected).total_seconds()) < 60

    # Re-opening the link must NOT reset the clock: same deadline back.
    again = anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io", "consent": True})
    assert again.json()["deadline"] == deadline


def test_submit_within_grace_is_accepted(anon_client: TestClient, monkeypatch) -> None:
    tok = register_interviewer(anon_client, "t-grace@x.io")
    anon_client.post("/questions", json=_question("q_grace", 30), headers=_auth(tok))
    inv = _invite(anon_client, tok, "q_grace", "c@x.io")
    anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io", "consent": True})
    # 5s past a 30-minute deadline — inside the 15s grace, so an on-time auto-submit
    # that arrives slightly late still counts.
    _age_attempt_started_at(tok, 30 * 60 + 5)

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-g"))
    resp = anon_client.post(
        f"/invite/{inv['token']}/submit",
        json={"candidate_name": "C", "candidate_email": "c@x.io", "consent": True, "language": "python", "code": "print(7)"},
    )
    assert resp.status_code == 201
    # Inside grace = on-time, not flagged late.
    sub = anon_client.get(f"/submissions/{resp.json()['submission_id']}", headers=_auth(tok))
    assert sub.json()["late"] is False


def test_submit_past_deadline_is_recorded_and_flagged_late(
    anon_client: TestClient, monkeypatch
) -> None:
    """A submit past the window is no longer discarded (was a 410): the candidate's
    work is recorded and graded, but flagged `late` so the interviewer can weigh it."""
    tok = register_interviewer(anon_client, "t-late@x.io")
    anon_client.post("/questions", json=_question("q_late", 30), headers=_auth(tok))
    inv = _invite(anon_client, tok, "q_late", "c@x.io")
    anon_client.post(f"/invite/{inv['token']}/start", json={"candidate_email": "c@x.io", "consent": True})
    # 60s past the deadline — well beyond the 15s grace.
    _age_attempt_started_at(tok, 30 * 60 + 60)

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-l"))
    resp = anon_client.post(
        f"/invite/{inv['token']}/submit",
        json={"candidate_name": "C", "candidate_email": "c@x.io", "consent": True, "language": "python", "code": "print(7)"},
    )
    assert resp.status_code == 201
    sid = resp.json()["submission_id"]
    assert anon_client.get(f"/submissions/{sid}", headers=_auth(tok)).json()["late"] is True

    # The flag reaches every interviewer submission surface, not just the detail:
    # the per-question dashboard list and the CSV export both carry it.
    rows = anon_client.get("/questions/q_late/submissions", headers=_auth(tok)).json()["items"]
    assert any(r["submission_id"] == sid and r["late"] is True for r in rows)
    csv = anon_client.get("/submissions/export", headers=_auth(tok)).text
    header, *lines = csv.strip().splitlines()
    assert "late" in header.split(",")
    late_idx = header.split(",").index("late")
    row = next(line for line in lines if line.startswith(sid))
    assert row.split(",")[late_idx] == "True"


# --------------------------------------------------------------------------- #
# R2-031 — the duration a candidate was promised is frozen when the invite is    #
# minted, like `Invite.proctored`. Editing the assessment (or the quick-screen   #
# question) afterwards must not move the deadline of a sitting that is already   #
# running, and must not turn an on-time submit into a late one.                  #
# --------------------------------------------------------------------------- #


def test_editing_an_assessment_duration_does_not_move_a_live_deadline(
    anon_client: TestClient, monkeypatch
) -> None:
    tok = register_interviewer(anon_client, "t-edit@x.io")
    anon_client.post("/questions", json=_question("q_edit", None), headers=_auth(tok))
    aid = anon_client.post(
        "/assessments",
        json={"title": "Screen", "question_ids": ["q_edit"], "duration_minutes": 60},
        headers=_auth(tok),
    ).json()["id"]
    link = anon_client.post(
        f"/assessments/{aid}/invites", json={"recipients": ["c@x.io"]}, headers=_auth(tok)
    ).json()["token"]

    started = anon_client.post(
        f"/invite/{link}/start", json={"candidate_email": "c@x.io", "consent": True}
    )
    deadline = started.json()["deadline"]
    assert deadline is not None

    # The interviewer cuts the assessment to a minute while the candidate sits it.
    assert (
        anon_client.put(
            f"/assessments/{aid}",
            json={"title": "Screen", "question_ids": ["q_edit"], "duration_minutes": 1},
            headers=_auth(tok),
        ).status_code
        == 200
    )

    # The candidate's reload reads the same deadline it read before the edit.
    assert (
        anon_client.post(
            f"/invite/{link}/start", json={"candidate_email": "c@x.io", "consent": True}
        ).json()["deadline"]
        == deadline
    )

    # And the sitting is still on time 30 minutes in — under the 60 minutes they
    # were given, well past the 1 minute the assessment now says.
    _age_attempt_started_at(tok, 30 * 60)
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-e"))
    resp = anon_client.post(
        f"/invite/{link}/submit",
        json={
            "candidate_name": "C",
            "candidate_email": "c@x.io",
            "consent": True,
            "language": "python",
            "code": "print(7)",
            "question_id": "q_edit",
        },
    )
    assert resp.status_code == 201
    sub = anon_client.get(f"/submissions/{resp.json()['submission_id']}", headers=_auth(tok))
    assert sub.json()["late"] is False


def test_an_invite_minted_after_the_edit_carries_the_new_duration(
    anon_client: TestClient,
) -> None:
    """Freezing is per invite, not per assessment: the next candidate invited gets
    what the assessment says today."""
    tok = register_interviewer(anon_client, "t-edit2@x.io")
    anon_client.post("/questions", json=_question("q_edit2", None), headers=_auth(tok))
    aid = anon_client.post(
        "/assessments",
        json={"title": "Screen", "question_ids": ["q_edit2"], "duration_minutes": 60},
        headers=_auth(tok),
    ).json()["id"]
    anon_client.put(
        f"/assessments/{aid}",
        json={"title": "Screen", "question_ids": ["q_edit2"], "duration_minutes": 90},
        headers=_auth(tok),
    )
    link = anon_client.post(
        f"/assessments/{aid}/invites", json={"recipients": ["c2@x.io"]}, headers=_auth(tok)
    ).json()["token"]

    assert anon_client.get(f"/invite/{link}").json()["duration_minutes"] == 90
    started = anon_client.post(
        f"/invite/{link}/start", json={"candidate_email": "c2@x.io", "consent": True}
    )
    expected = datetime.now(timezone.utc) + timedelta(minutes=90)
    got = datetime.fromisoformat(started.json()["deadline"])
    assert abs((got - expected).total_seconds()) < 60


def test_editing_a_quick_screen_question_duration_does_not_move_a_live_deadline(
    anon_client: TestClient,
) -> None:
    """The legacy single-question invite reads the question's own duration, and
    freezes it the same way."""
    tok = register_interviewer(anon_client, "t-edit3@x.io")
    anon_client.post("/questions", json=_question("q_quick", 60), headers=_auth(tok))
    inv = _invite(anon_client, tok, "q_quick", "c3@x.io")

    deadline = anon_client.post(
        f"/invite/{inv['token']}/start", json={"candidate_email": "c3@x.io", "consent": True}
    ).json()["deadline"]

    edited = dict(_question("q_quick", 5))
    edited.pop("id")
    assert (
        anon_client.put("/questions/q_quick", json=edited, headers=_auth(tok)).status_code == 200
    )

    assert (
        anon_client.post(
            f"/invite/{inv['token']}/start", json={"candidate_email": "c3@x.io", "consent": True}
        ).json()["deadline"]
        == deadline
    )
    # The probe the candidate's start screen reads says the same thing.
    assert anon_client.get(f"/invite/{inv['token']}").json()["duration_minutes"] == 60


def test_an_untimed_sitting_cannot_be_given_a_clock_mid_flight(
    anon_client: TestClient, monkeypatch
) -> None:
    """The snapshot has to record "no limit" as a value, not as an absent one.

    Storing NULL for an untimed invite and reading NULL as "nothing recorded"
    conflates the two: the invite fell back to the live assessment, so turning a
    30-minute limit on mid-sitting gave a candidate who was promised no limit a
    deadline — and then recorded their submit `late`.
    """
    tok = register_interviewer(anon_client, "t-untimed-edit@x.io")
    anon_client.post("/questions", json=_question("q_ue", None), headers=_auth(tok))
    aid = anon_client.post(
        "/assessments",
        json={"title": "Screen", "question_ids": ["q_ue"], "duration_minutes": None},
        headers=_auth(tok),
    ).json()["id"]
    link = anon_client.post(
        f"/assessments/{aid}/invites", json={"recipients": ["c@x.io"]}, headers=_auth(tok)
    ).json()["token"]

    assert (
        anon_client.post(
            f"/invite/{link}/start", json={"candidate_email": "c@x.io", "consent": True}
        ).json()["deadline"]
        is None
    )

    anon_client.put(
        f"/assessments/{aid}",
        json={"title": "Screen", "question_ids": ["q_ue"], "duration_minutes": 30},
        headers=_auth(tok),
    )

    assert (
        anon_client.post(
            f"/invite/{link}/start", json={"candidate_email": "c@x.io", "consent": True}
        ).json()["deadline"]
        is None
    )
    assert anon_client.get(f"/invite/{link}").json()["duration_minutes"] is None

    # An hour in, with no limit to be past: recorded, and not flagged late.
    _age_attempt_started_at(tok, 60 * 60)
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-ue"))
    resp = anon_client.post(
        f"/invite/{link}/submit",
        json={
            "candidate_name": "C",
            "candidate_email": "c@x.io",
            "consent": True,
            "language": "python",
            "code": "print(7)",
            "question_id": "q_ue",
        },
    )
    assert resp.status_code == 201
    sub = anon_client.get(f"/submissions/{resp.json()['submission_id']}", headers=_auth(tok))
    assert sub.json()["late"] is False
