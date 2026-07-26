"""T4 slice 2 — assessment CRUD (a named, ordered set of the owner's questions,
with a per-assessment total duration). Owner-scoped; fully offline."""

from __future__ import annotations

import re
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


def test_create_assessment_without_id_generates_slug(client) -> None:
    # A6: the UI no longer sends an id — the server derives slug(title)+suffix.
    _make_questions(client, "q1")
    resp = client.post(
        "/assessments", json={"title": "Backend Screen", "question_ids": ["q1"]}
    )
    assert resp.status_code == 201
    aid = resp.json()["id"]
    assert re.fullmatch(r"backend-screen-[0-9a-f]{6}", aid), aid
    assert client.get(f"/assessments/{aid}").status_code == 200


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


def test_update_locks_question_set_once_invited(client) -> None:
    """A9: the question set can't change once an invite has gone out, but
    title/duration/branding stay freely editable, and re-submitting the SAME
    set (no real change) is not blocked."""
    _make_questions(client, "q1", "q2", "q3")
    client.post(
        "/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1", "q2"]}
    )

    # Before any invite: reordering/changing the set is fine.
    assert client.put(
        "/assessments/a1", json={"title": "A", "question_ids": ["q2", "q1"]}
    ).status_code == 200

    client.post("/assessments/a1/invites", json={"recipients": ["cand@x.io"]})

    # Now locked: adding/removing/reordering questions 409s.
    resp = client.put(
        "/assessments/a1", json={"title": "A", "question_ids": ["q1", "q2", "q3"]}
    )
    assert resp.status_code == 409
    assert "question set can't change" in resp.json()["detail"]

    # Re-sending the SAME (already-current) set is not a real change — allowed.
    same_order = client.get("/assessments/a1").json()
    current_ids = [q["question_id"] for q in same_order["questions"]]
    assert client.put(
        "/assessments/a1",
        json={"title": "A", "question_ids": current_ids, "duration_minutes": 45},
    ).status_code == 200

    # Title/duration/branding remain editable even though questions are locked.
    resp = client.put(
        "/assessments/a1",
        json={
            "title": "A v2", "question_ids": current_ids, "duration_minutes": 30,
            "org_name": "Acme", "logo_url": "https://cdn.example.com/a.png",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "A v2"
    assert body["duration_minutes"] == 30
    assert body["org_name"] == "Acme"


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


def test_candidate_name_anchored_at_start_not_reforked_per_submit(client, monkeypatch) -> None:
    """A10: the name given at /start wins for every submission in the sitting,
    even if a later /submit (e.g. after a reload re-typed it) sends a different
    one — the whole sitting stays one consistently-labeled candidate."""
    _make_questions(client, "q1", "q2")
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1", "q2"]})
    tok = client.post("/assessments/a1/invites", json={"recipients": ["cand@x.io"]}).json()["token"]

    client.post(
        f"/invite/{tok}/start", json={"candidate_email": "cand@x.io", "candidate_name": "Jane Doe"}
    )
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    assert client.post(
        f"/invite/{tok}/submit",
        json={
            "candidate_name": "jane d",  # differs from the /start name
            "candidate_email": "cand@x.io", "language": "python", "code": "print(1)",
            "question_id": "q1",
        },
    ).status_code == 201
    assert client.post(
        f"/invite/{tok}/submit",
        json={
            "candidate_name": "Janee Doee",  # a different typo again
            "candidate_email": "cand@x.io", "language": "python", "code": "print(2)",
            "question_id": "q2",
        },
    ).status_code == 201

    names = {s["question_id"]: s["candidate"] for s in client.get("/submissions").json()["items"]}
    assert names == {"q1": "Jane Doe", "q2": "Jane Doe"}


def test_candidate_name_anchored_at_first_submit_when_start_had_none(client, monkeypatch) -> None:
    """A10 fallback: an old client that never sends candidate_name to /start
    still gets one consistent name, anchored from the first /submit that
    actually created the attempt."""
    _make_questions(client, "q1", "q2")
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1", "q2"]})
    tok = client.post("/assessments/a1/invites", json={"recipients": ["cand@x.io"]}).json()["token"]

    client.post(f"/invite/{tok}/start", json={"candidate_email": "cand@x.io"})  # no name
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    assert client.post(
        f"/invite/{tok}/submit",
        json={
            "candidate_name": "Jane Doe",
            "candidate_email": "cand@x.io", "language": "python", "code": "print(1)",
            "question_id": "q1",
        },
    ).status_code == 201
    assert client.post(
        f"/invite/{tok}/submit",
        json={
            "candidate_name": "Someone Else",  # must not override the anchored name
            "candidate_email": "cand@x.io", "language": "python", "code": "print(2)",
            "question_id": "q2",
        },
    ).status_code == 201

    names = {s["question_id"]: s["candidate"] for s in client.get("/submissions").json()["items"]}
    assert names == {"q1": "Jane Doe", "q2": "Jane Doe"}


def _callback(job_id: str, verdict: str, score: float) -> dict[str, Any]:
    return {"job_id": job_id, "verdict": verdict, "score_pct": score, "reason": "r"}


def test_assessment_attempts_composite(client, monkeypatch) -> None:
    """A3/A11: one row per candidate who started, with every question's result
    plus a composite — pass count always well-defined, avg score over graded
    questions only (None until at least one is graded)."""
    _make_questions(client, "q1", "q2")
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1", "q2"]})
    tok = client.post(
        "/assessments/a1/invites", json={"recipients": ["cand1@x.io", "cand2@x.io"]}
    ).json()["token"]

    def submit(email: str, name: str, qid: str, job_id: str) -> None:
        monkeypatch.setattr(agent_client, "trigger_assessment", async_return(job_id))
        resp = client.post(
            f"/invite/{tok}/submit",
            json={
                "candidate_name": name, "candidate_email": email,
                "language": "python", "code": "x", "question_id": qid,
            },
        )
        assert resp.status_code == 201

    # cand1 starts and submits both questions; cand2 starts but only submits q1.
    client.post(f"/invite/{tok}/start", json={"candidate_email": "cand1@x.io", "candidate_name": "Cand One"})
    submit("cand1@x.io", "Cand One", "q1", "job-1a")
    submit("cand1@x.io", "Cand One", "q2", "job-1b")
    client.post(f"/invite/{tok}/start", json={"candidate_email": "cand2@x.io", "candidate_name": "Cand Two"})
    submit("cand2@x.io", "Cand Two", "q1", "job-2a")

    client.post("/assessments/callback", json=_callback("job-1a", "PASS", 100.0))
    client.post("/assessments/callback", json=_callback("job-1b", "FAIL", 40.0))
    client.post("/assessments/callback", json=_callback("job-2a", "PASS", 80.0))

    rows = {r["candidate_email"]: r for r in client.get("/assessments/a1/attempts").json()}
    assert set(rows) == {"cand1@x.io", "cand2@x.io"}

    c1 = rows["cand1@x.io"]
    assert c1["candidate_name"] == "Cand One"
    assert (c1["passed_count"], c1["total_count"]) == (1, 2)
    assert c1["avg_score_pct"] == 70.0  # (100 + 40) / 2
    assert {q["question_id"]: q["verdict"] for q in c1["questions"]} == {"q1": "PASS", "q2": "FAIL"}

    c2 = rows["cand2@x.io"]
    assert (c2["passed_count"], c2["total_count"]) == (1, 2)
    assert c2["avg_score_pct"] == 80.0  # only q1 is graded
    q_by_id = {q["question_id"]: q for q in c2["questions"]}
    assert q_by_id["q1"]["submitted"] is True
    assert q_by_id["q1"]["submission_id"] is not None  # links to the full submission
    assert q_by_id["q2"]["submitted"] is False
    assert q_by_id["q2"]["submission_id"] is None
    assert q_by_id["q2"]["verdict"] is None


def test_assessment_attempts_owner_scoped_and_empty(client) -> None:
    _make_questions(client, "q1")
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1"]})

    # No invites yet: empty, not an error.
    assert client.get("/assessments/a1/attempts").json() == []

    # Another interviewer can't see this assessment's attempts at all.
    tok_b = register_interviewer(client, "other@x.io")
    assert client.get("/assessments/a1/attempts", headers=_auth(tok_b)).status_code == 403


def test_submissions_list_surfaces_assessment_link(client, monkeypatch) -> None:
    """A3: a submission via an assessment invite is tagged with the assessment's
    id/title in the summary list; a standalone direct submission is not."""
    _make_questions(client, "q1", "q2")
    client.post(
        "/assessments", json={"id": "a1", "title": "Backend Screen", "question_ids": ["q1", "q2"]}
    )
    tok = client.post("/assessments/a1/invites", json={"recipients": ["cand@x.io"]}).json()["token"]

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    assert client.post(f"/invite/{tok}/submit", json=_sub(tok, "cand@x.io", "q1")).status_code == 201
    # A direct, non-invite submission against the same owner's question.
    assert client.post(
        "/submissions",
        json={"question_id": "q2", "candidate": "Direct", "language": "python", "code": "print(1)"},
    ).status_code == 201

    by_candidate = {s["candidate"]: s for s in client.get("/submissions").json()["items"]}
    assert by_candidate["C"]["assessment_id"] == "a1"
    assert by_candidate["C"]["assessment_title"] == "Backend Screen"
    assert by_candidate["Direct"]["assessment_id"] is None
    assert by_candidate["Direct"]["assessment_title"] is None


def test_assessment_branding_roundtrip(client) -> None:
    """A12: org_name/logo_url are stored and echoed back, and PUT can change them."""
    _make_questions(client, "q1")
    created = client.post(
        "/assessments",
        json={
            "id": "a1", "title": "A", "question_ids": ["q1"],
            "org_name": "Acme Corp", "logo_url": "https://cdn.example.com/acme.png",
        },
    ).json()
    assert created["org_name"] == "Acme Corp"
    assert created["logo_url"] == "https://cdn.example.com/acme.png"

    updated = client.put(
        "/assessments/a1",
        json={
            "title": "A", "question_ids": ["q1"],
            "org_name": "New Name", "logo_url": None,
        },
    ).json()
    assert updated["org_name"] == "New Name"
    assert updated["logo_url"] is None


def test_candidate_view_carries_assessment_branding(client, monkeypatch) -> None:
    """A12: the candidate-facing /start response carries the assessment's
    branding; a legacy single-question invite carries none."""
    _make_questions(client, "q1")
    client.post(
        "/assessments",
        json={
            "id": "a1", "title": "Backend Screen", "question_ids": ["q1"],
            "org_name": "Acme Corp", "logo_url": "https://cdn.example.com/acme.png",
        },
    )
    tok = client.post("/assessments/a1/invites", json={"recipients": ["cand@x.io"]}).json()["token"]
    data = client.post(f"/invite/{tok}/start", json={"candidate_email": "cand@x.io"}).json()
    assert data["assessment_title"] == "Backend Screen"
    assert data["org_name"] == "Acme Corp"
    assert data["logo_url"] == "https://cdn.example.com/acme.png"

    # A legacy single-question invite has no Assessment to brand from.
    legacy_tok = client.post(
        "/questions/q1/invites", json={"recipients": ["legacy@x.io"]}
    ).json()["token"]
    legacy_data = client.post(
        f"/invite/{legacy_tok}/start", json={"candidate_email": "legacy@x.io"}
    ).json()
    assert legacy_data["assessment_title"] is None
    assert legacy_data["org_name"] is None
    assert legacy_data["logo_url"] is None


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
