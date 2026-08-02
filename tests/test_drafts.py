"""CX2 — server-side draft autosave: the candidate's in-progress code survives
a cleared cache / incognito / device switch. Fully offline. A draft is neither
an attempt nor a submission: saving must never start a clock, and only the
candidate's own sitting can read it back."""

from __future__ import annotations

from typing import Any

from conftest import async_return
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from assessment_platform import agent_client
from assessment_platform import db as db_module
from assessment_platform.models import CandidateAttempt, CandidateDraft


def _question(qid: str) -> dict[str, Any]:
    return {
        "id": qid,
        "title": f"Q {qid}",
        "prompt": "p",
        "constraints": "c",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "test_cases": [
            {"name": "t1", "stdin": "1\n", "expected": "1", "category": "correctness"},
            {"name": "t2", "stdin": "2\n", "expected": "2", "category": "correctness"},
            {"name": "t3", "stdin": "3\n", "expected": "3", "category": "correctness"},
            {"name": "t4", "stdin": "4\n", "expected": "4", "category": "correctness"},
            {"name": "big", "stdin": "9\n", "expected": "9", "category": "performance"},
        ],
    }


def _single_invite(client: TestClient, qid: str = "q1", email: str = "cand@x.io") -> str:
    assert client.post("/questions", json=_question(qid)).status_code == 201
    resp = client.post(f"/questions/{qid}/invites", json={"recipients": [email]})
    assert resp.status_code == 201
    return resp.json()["token"]


def _save(client: TestClient, token: str, **over: Any) -> Any:
    body = {"candidate_email": "cand@x.io", "code": "print(1)", "language": "python"}
    body.update(over)
    return client.put(f"/invite/{token}/draft", json=body)


def test_draft_round_trips_and_upserts(client) -> None:
    token = _single_invite(client)
    assert _save(client, token).status_code == 204
    assert _save(client, token, code="print(2)", language="javascript").status_code == 204

    body = client.get(f"/invite/{token}/draft", params={"candidate_email": "cand@x.io"}).json()
    assert len(body["drafts"]) == 1  # upserted, not appended
    assert body["drafts"][0]["code"] == "print(2)"
    assert body["drafts"][0]["language"] == "javascript"
    assert body["drafts"][0]["question_id"] == "q1"


def test_saving_a_draft_never_starts_the_clock(client) -> None:
    token = _single_invite(client)
    assert _save(client, token).status_code == 204
    with Session(db_module.engine) as s:
        assert s.exec(select(CandidateAttempt)).all() == []
        assert s.exec(select(CandidateDraft)).one().code == "print(1)"


def test_draft_gates_match_the_candidate_surface(client) -> None:
    token = _single_invite(client)
    # Not an invited recipient.
    assert _save(client, token, candidate_email="stranger@x.io").status_code == 403
    assert (
        client.get(f"/invite/{token}/draft", params={"candidate_email": "stranger@x.io"})
    ).status_code == 403
    # Not a question of this invite.
    assert _save(client, token, question_id="other-q").status_code == 404
    # Dead link.
    revoked = client.post(f"/questions/q1/invites/{token}/revoke")
    assert revoked.status_code == 200
    assert _save(client, token).status_code == 410


def test_each_question_of_a_sitting_keeps_its_own_draft(client) -> None:
    for qid in ("q1", "q2"):
        assert client.post("/questions", json=_question(qid)).status_code == 201
    aid = client.post(
        "/assessments", json={"title": "A", "question_ids": ["q1", "q2"]}
    ).json()["id"]
    token = client.post(
        f"/assessments/{aid}/invites", json={"recipients": ["cand@x.io"]}
    ).json()["token"]

    assert _save(client, token, question_id="q1", code="one").status_code == 204
    assert _save(client, token, question_id="q2", code="two").status_code == 204
    # A multi-question save must name its question.
    assert _save(client, token).status_code == 400

    drafts = client.get(
        f"/invite/{token}/draft", params={"candidate_email": "cand@x.io"}
    ).json()["drafts"]
    assert {d["question_id"]: d["code"] for d in drafts} == {"q1": "one", "q2": "two"}


def test_a_save_racing_the_submit_is_still_accepted(client, monkeypatch) -> None:
    # Like /events: the last autosave can land a moment after the submit; failing
    # it would be noise. The submission is already the durable record by then.
    token = _single_invite(client)
    client.post(
        f"/invite/{token}/start", json={"candidate_name": "C", "candidate_email": "cand@x.io"}
    )
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    assert (
        client.post(
            f"/invite/{token}/submit",
            json={
                "candidate_name": "C",
                "candidate_email": "cand@x.io",
                "language": "python",
                "code": "print(1)",
            },
        ).status_code
        == 201
    )
    assert _save(client, token, code="late autosave").status_code == 204


def test_a_cold_start_reads_an_empty_list_not_an_error(client) -> None:
    token = _single_invite(client)
    body = client.get(f"/invite/{token}/draft", params={"candidate_email": "cand@x.io"}).json()
    assert body == {"drafts": []}
