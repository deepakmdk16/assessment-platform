"""Regression tests for the 2026-09-07 launch-blocker batch (STATUS §E: P02, P04,
P09, P19). Each reproduces a defect found live against Postgres in the
2026-09-06 audit, so it stays fixed."""

from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from test_assessments import _make_questions
from test_slice_vs2 import _make_variant_set, _start

from assessment_platform import api, config

BIG_CODE = "x" * 200_001
BIG_STDIN = "y" * 1_000_001


# --- P02: settings-only edit on a started variant-set assessment ------------


def test_settings_only_edit_survives_a_started_variant_set_sitting(client: TestClient) -> None:
    # Once a candidate has started, CandidateSlotVariant rows FK the
    # AssessmentQuestion rows. A settings-only PUT used to clear + reinsert them
    # and 500 on the constraint; the frozen assignment must survive untouched.
    _make_questions(client, "q1")
    sid, variants = _make_variant_set(client, "s1", "A", "B")
    slots = [{"variant_set_id": sid}, {"question_id": "q1"}]
    client.post("/assessments", json={"id": "a1", "title": "A", "slots": slots})
    tok = client.post("/assessments/a1/invites", json={"recipients": ["c@x.io"]}).json()["token"]
    before = _start(client, tok, "c@x.io")
    assert before[0] in variants

    resp = client.put(
        "/assessments/a1",
        json={"title": "Renamed", "duration_minutes": 45, "proctored": False, "slots": slots},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["title"] == "Renamed"
    assert resp.json()["duration_minutes"] == 45
    # The candidate reloads into exactly the same variant.
    assert _start(client, tok, "c@x.io") == before


# --- P04: deleting a referenced question is a 409, not a 500 ---------------


def test_delete_question_in_a_fixed_slot_409s(client: TestClient) -> None:
    _make_questions(client, "q1")
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1"]})
    resp = client.delete("/questions/q1")
    assert resp.status_code == 409
    assert "a1" in resp.json()["detail"]
    # Still there.
    assert client.get("/questions/q1").status_code == 200


def test_delete_assigned_variant_409s(client: TestClient) -> None:
    sid, _variants = _make_variant_set(client, "s1", "A", "B")
    client.post("/assessments", json={"id": "a1", "title": "A", "slots": [{"variant_set_id": sid}]})
    tok = client.post("/assessments/a1/invites", json={"recipients": ["c@x.io"]}).json()["token"]
    assigned = _start(client, tok, "c@x.io")[0]
    resp = client.delete(f"/questions/{assigned}")
    assert resp.status_code == 409
    assert "assigned" in resp.json()["detail"]


# --- P09: candidate-supplied text is bounded ---------------------------------


def _quick_screen_token(client: TestClient) -> str:
    _make_questions(client, "q1")
    return client.post("/questions/q1/invites", json={"recipients": ["c@x.io"]}).json()["token"]


def test_candidate_submit_rejects_oversize_code(client: TestClient) -> None:
    tok = _quick_screen_token(client)
    body = {"candidate_name": "C", "candidate_email": "c@x.io", "language": "python", "code": BIG_CODE}
    assert client.post(f"/invite/{tok}/submit", json=body).status_code == 422


def test_candidate_run_rejects_oversize_stdin_and_code(client: TestClient) -> None:
    tok = _quick_screen_token(client)
    base = {"candidate_email": "c@x.io", "language": "python"}
    assert (
        client.post(f"/invite/{tok}/run", json={**base, "code": "print(1)", "stdin": BIG_STDIN}).status_code
        == 422
    )
    assert client.post(f"/invite/{tok}/run", json={**base, "code": BIG_CODE}).status_code == 422
    assert client.post(f"/invite/{tok}/run-tests", json={**base, "code": BIG_CODE}).status_code == 422


def test_interviewer_submission_rejects_oversize_code(client: TestClient) -> None:
    _make_questions(client, "q1")
    body = {"question_id": "q1", "candidate": "C", "language": "python", "code": BIG_CODE}
    assert client.post("/submissions", json=body).status_code == 422


def test_oversize_body_is_refused_before_parsing(client: TestClient, monkeypatch) -> None:
    # Content-Length above the ceiling → 413 from the middleware, no JSON parse,
    # even on an unauthenticated route with a bogus token.
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 1_000)
    resp = client.post("/invite/nope/submit", content=b"{" + b" " * 2_000 + b"}",
                       headers={"content-type": "application/json"})
    assert resp.status_code == 413
    assert "exceeds" in resp.json()["detail"]
    # Under the ceiling the request reaches the route (404: unknown invite).
    small = client.post("/invite/nope/submit", json={"candidate_name": "C", "candidate_email": "c@x.io",
                                                     "language": "python", "code": "x"})
    assert small.status_code == 404


# --- P19: the server process actually configures logging --------------------


def test_configure_logging_sets_the_root_level(monkeypatch) -> None:
    monkeypatch.setattr(config, "LOG_LEVEL", "DEBUG")
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    try:
        # basicConfig is a no-op while pytest's capture handlers are installed.
        root.handlers.clear()
        api.configure_logging()
        assert root.level == logging.DEBUG
        assert root.handlers, "configure_logging must install a handler"
    finally:
        root.handlers[:] = saved_handlers
        root.setLevel(saved_level)
