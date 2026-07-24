"""T4 slice 2 — assessment CRUD (a named, ordered set of the owner's questions,
with a per-assessment total duration). Owner-scoped; fully offline."""

from __future__ import annotations

from typing import Any

from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient
from sqlmodel import Session

from assessment_platform import agent_client
from assessment_platform import db as db_module
from assessment_platform.models import Invite


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _question(qid: str) -> dict[str, Any]:
    return {
        "id": qid,
        "title": f"Q {qid}",
        "prompt": "p",
        "constraints": "c",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        # 4 correctness + 1 performance to satisfy the authoring-time floor (A1).
        "test_cases": [
            {"name": "t1", "stdin": "1\n", "expected": "1", "category": "correctness"},
            {"name": "t2", "stdin": "2\n", "expected": "2", "category": "correctness"},
            {"name": "t3", "stdin": "3\n", "expected": "3", "category": "correctness"},
            {"name": "t4", "stdin": "4\n", "expected": "4", "category": "correctness"},
            {"name": "big", "stdin": "9\n", "expected": "9", "category": "performance"},
        ],
    }


def _make_questions(client, *ids: str) -> None:
    for qid in ids:
        assert client.post("/questions", json=_question(qid)).status_code == 201


def test_assessment_crud_roundtrip(client) -> None:
    _make_questions(client, "q1", "q2", "q3")

    # Create — ordered, with a total duration.
    resp = client.post(
        "/assessments",
        json={"id": "screen1", "title": "Backend screen", "duration_minutes": 90,
              "question_ids": ["q2", "q1"]},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["duration_minutes"] == 90
    # Order and denormalized titles come back as given.
    assert [(q["question_id"], q["position"]) for q in body["questions"]] == [("q2", 0), ("q1", 1)]
    assert body["questions"][0]["title"] == "Q q2"

    # Duplicate id -> 409.
    assert client.post(
        "/assessments", json={"id": "screen1", "title": "x", "question_ids": ["q1"]}
    ).status_code == 409

    # Get + list.
    assert client.get("/assessments/screen1").json()["title"] == "Backend screen"
    assert len(client.get("/assessments").json()["items"]) == 1

    # Update: reorder, add a question, drop the duration.
    upd = client.put(
        "/assessments/screen1",
        json={"title": "Backend screen v2", "duration_minutes": None,
              "question_ids": ["q1", "q2", "q3"]},
    )
    assert upd.status_code == 200
    b2 = upd.json()
    assert b2["duration_minutes"] is None
    assert [q["question_id"] for q in b2["questions"]] == ["q1", "q2", "q3"]

    # Archive hides from the default list; unarchive restores.
    assert client.post("/assessments/screen1/archive").json()["status"] == "archived"
    assert client.get("/assessments").json()["items"] == []
    assert len(client.get("/assessments?include_archived=true").json()["items"]) == 1
    assert client.post("/assessments/screen1/unarchive").json()["status"] == "active"

    # Delete.
    assert client.delete("/assessments/screen1").status_code == 204
    assert client.get("/assessments/screen1").status_code == 404


def test_create_rejects_unknown_question(client) -> None:
    _make_questions(client, "q1")
    resp = client.post(
        "/assessments", json={"id": "a", "title": "A", "question_ids": ["q1", "ghost"]}
    )
    assert resp.status_code == 404


def test_create_rejects_duplicate_question(client) -> None:
    _make_questions(client, "q1")
    resp = client.post(
        "/assessments", json={"id": "a", "title": "A", "question_ids": ["q1", "q1"]}
    )
    assert resp.status_code == 400
    assert "at most once" in resp.json()["detail"]


def test_empty_question_list_rejected(client) -> None:
    assert client.post(
        "/assessments", json={"id": "a", "title": "A", "question_ids": []}
    ).status_code == 422


def test_assessment_owner_scoped(anon_client: TestClient) -> None:
    tok_a = register_interviewer(anon_client, "asmt-a@x.io")
    tok_b = register_interviewer(anon_client, "asmt-b@x.io")
    anon_client.post("/questions", json=_question("q1"), headers=_auth(tok_a))
    anon_client.post(
        "/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1"]},
        headers=_auth(tok_a),
    )

    # B cannot see or use A's assessment, and can't add A's question to one of theirs.
    assert anon_client.get("/assessments/a1", headers=_auth(tok_b)).status_code == 403
    assert anon_client.get("/assessments", headers=_auth(tok_b)).json()["items"] == []
    assert anon_client.post(
        "/assessments", json={"id": "b1", "title": "B", "question_ids": ["q1"]},
        headers=_auth(tok_b),
    ).status_code == 403


def test_assessment_invite_creation(client) -> None:
    _make_questions(client, "q1", "q2")
    client.post(
        "/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1", "q2"]}
    )
    resp = client.post("/assessments/a1/invites", json={"recipients": ["cand@x.io"]})
    assert resp.status_code == 201
    inv = resp.json()
    # An assessment invite carries assessment_id and no single question_id.
    assert inv["assessment_id"] == "a1"
    assert inv["question_id"] is None
    assert inv["url"].endswith(f"/t/{inv['token']}")

    listed = client.get("/assessments/a1/invites").json()
    assert len(listed) == 1 and listed[0]["token"] == inv["token"]


def _sub(tok: str, email: str, qid: str | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "candidate_name": "C", "candidate_email": email, "language": "python", "code": "print(1)",
    }
    if qid is not None:
        body["question_id"] = qid
    return body


def test_candidate_multi_question_flow(client, monkeypatch) -> None:
    _make_questions(client, "q1", "q2")
    client.post(
        "/assessments",
        json={"id": "a1", "title": "A", "duration_minutes": 60, "question_ids": ["q1", "q2"]},
    )
    tok = client.post("/assessments/a1/invites", json={"recipients": ["cand@x.io"]}).json()["token"]

    # /start hands back BOTH questions (ordered), a shared deadline, and no key.
    data = client.post(f"/invite/{tok}/start", json={"candidate_email": "cand@x.io"}).json()
    assert [q["id"] for q in data["questions"]] == ["q1", "q2"]
    assert all(q["submitted"] is False for q in data["questions"])
    assert data["deadline"] is not None
    assert "test_cases" not in str(data["questions"])  # answer key never leaks

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    # Submit q1; re-entering shows it done and q2 still open (no all-or-nothing block).
    assert client.post(f"/invite/{tok}/submit", json=_sub(tok, "cand@x.io", "q1")).status_code == 201
    again = client.post(f"/invite/{tok}/start", json={"candidate_email": "cand@x.io"}).json()
    assert {q["id"]: q["submitted"] for q in again["questions"]} == {"q1": True, "q2": False}

    # One attempt PER QUESTION: re-submitting q1 is 409, submitting q2 is fine.
    assert client.post(f"/invite/{tok}/submit", json=_sub(tok, "cand@x.io", "q1")).status_code == 409
    assert client.post(f"/invite/{tok}/submit", json=_sub(tok, "cand@x.io", "q2")).status_code == 201

    # A multi-question invite requires naming the question.
    assert client.post(f"/invite/{tok}/submit", json=_sub(tok, "cand@x.io", None)).status_code == 400


def test_delete_blocked_by_invite(client) -> None:
    _make_questions(client, "q1")
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1"]})
    # An invite pointing at the assessment (slice 3 builds the endpoint; insert
    # directly for now) blocks deletion — it's a live link.
    with Session(db_module.engine) as s:
        s.add(Invite(token="tok-asmt-1", assessment_id="a1", created_by=1))
        s.commit()
    resp = client.delete("/assessments/a1")
    assert resp.status_code == 409
    assert "invite" in resp.json()["detail"]
