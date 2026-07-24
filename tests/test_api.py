"""API tests. Fully offline: the outbound agent call is mocked, so no real agent,
LLM, or network is required."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from conftest import async_raise, async_return, patch_async_post
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session

from assessment_platform import agent_client, config, signing
from assessment_platform import db as db_module
from assessment_platform.models import Submission


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
            {
                "name": "t1",
                "stdin": "2\n3 4\n",
                "expected": "7",
                "category": "correctness",
                "weight": 1.0,
            },
            {
                "name": "big",
                "stdin": "100000\n...",
                "expected": "12345",
                "category": "performance",
                "weight": 3.0,
            },
        ],
    }


def test_health(client) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_503_when_db_unreachable(anon_client) -> None:
    # A load balancer routes on /health, so it must fail when the DB is gone
    # rather than report ok. Simulate a session whose query raises.
    from assessment_platform.api import app
    from assessment_platform.db import get_session

    def _broken_session():
        session = MagicMock()
        session.execute.side_effect = OperationalError("select 1", {}, Exception("db down"))
        yield session

    app.dependency_overrides[get_session] = _broken_session
    try:
        assert anon_client.get("/health").status_code == 503
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_smtp_forced_off_under_test() -> None:
    # conftest sets PLATFORM_TESTING=1 before config loads, so a developer's real
    # .env can never make the offline suite open a live Gmail connection.
    assert config.TESTING is True
    assert config.SMTP_HOST is None


def test_question_crud_roundtrip(client) -> None:
    # Create
    resp = client.post("/questions", json=_sample_question())
    assert resp.status_code == 201
    created = resp.json()
    assert created["id"] == "sum_of_n"
    assert len(created["test_cases"]) == 2
    assert created["test_cases"][0]["id"] is not None

    # Duplicate id -> 409
    assert client.post("/questions", json=_sample_question()).status_code == 409

    # Get one
    got = client.get("/questions/sum_of_n")
    assert got.status_code == 200
    assert got.json()["title"] == "Sum of N"

    # List
    assert len(client.get("/questions").json()["items"]) == 1

    # Update (full replace, fewer test cases)
    upd = {
        "title": "Sum of N (v2)",
        "prompt": "updated",
        "constraints": "",
        "time_limit_s": 3.0,
        "pass_threshold": 0.8,
        "required_complexity": "O(N)",
        "example_input": None,
        "example_output": None,
        "test_cases": [
            {"name": "only", "stdin": "1\n5\n", "expected": "5", "category": "correctness", "weight": 1.0}
        ],
    }
    resp = client.put("/questions/sum_of_n", json=upd)
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Sum of N (v2)"
    assert body["required_complexity"] == "O(N)"
    assert len(body["test_cases"]) == 1

    # Delete
    assert client.delete("/questions/sum_of_n").status_code == 204
    assert client.get("/questions/sum_of_n").status_code == 404


def test_get_missing_question_404(client) -> None:
    assert client.get("/questions/nope").status_code == 404


def test_delete_question_with_submissions_409(client, monkeypatch) -> None:
    """A question someone has submitted against is not deletable.

    Submissions are the system of record. Cascading them away with the question
    would destroy the very thing the platform exists to keep — and every result
    attached to it — so the delete is refused instead.
    """
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-del"))
    sub_id = client.post(
        "/submissions",
        json={
            "question_id": "sum_of_n",
            "candidate": "Jane Doe",
            "language": "python",
            "code": "print(1)",
        },
    ).json()["id"]

    resp = client.delete("/questions/sum_of_n")
    assert resp.status_code == 409
    assert "submission" in resp.json()["detail"]

    # Refused, not half-done: both the question and the submission survive intact.
    assert client.get("/questions/sum_of_n").status_code == 200
    assert client.get(f"/submissions/{sub_id}").status_code == 200


# --------------------------------------------------------------------------- #
# Question difficulty + status (archive / unarchive)                            #
# --------------------------------------------------------------------------- #


def test_create_question_with_difficulty_defaults_active(client) -> None:
    q = _sample_question()
    q["difficulty"] = "medium"
    body = client.post("/questions", json=q).json()
    assert body["difficulty"] == "medium"
    assert body["status"] == "active"


def test_create_question_without_difficulty(client) -> None:
    body = client.post("/questions", json=_sample_question()).json()
    assert body["difficulty"] is None
    assert body["status"] == "active"


def test_invalid_difficulty_rejected(client) -> None:
    q = _sample_question()
    q["difficulty"] = "impossible"
    assert client.post("/questions", json=q).status_code == 422


def test_reference_solution_persists_on_create_and_get(client) -> None:
    # A drafted question carries its AI reference solution + language; both must
    # survive the create and come back on the question (F1 — the answer key was
    # dropped after draft time before this).
    q = _sample_question()
    q["reference_solution"] = "def solve():\n    return 42\n"
    q["reference_language"] = "python"
    created = client.post("/questions", json=q).json()
    assert created["reference_solution"] == "def solve():\n    return 42\n"
    assert created["reference_language"] == "python"
    got = client.get("/questions/sum_of_n").json()
    assert got["reference_solution"] == "def solve():\n    return 42\n"
    assert got["reference_language"] == "python"


def test_reference_solution_absent_for_hand_authored(client) -> None:
    body = client.post("/questions", json=_sample_question()).json()
    assert body["reference_solution"] is None
    assert body["reference_language"] is None


def test_update_sets_difficulty(client) -> None:
    client.post("/questions", json=_sample_question())
    upd = {k: v for k, v in _sample_question().items() if k != "id"}
    upd["difficulty"] = "hard"
    assert client.put("/questions/sum_of_n", json=upd).json()["difficulty"] == "hard"


def test_archive_hides_from_list_but_keeps_reachable(client) -> None:
    client.post("/questions", json=_sample_question())
    assert client.post("/questions/sum_of_n/archive").json()["status"] == "archived"

    # Hidden from the default dashboard list...
    assert [q["id"] for q in client.get("/questions").json()["items"]] == []
    # ...but still returned with ?include_archived=true, and directly reachable.
    assert [q["id"] for q in client.get("/questions?include_archived=true").json()["items"]] == ["sum_of_n"]
    assert client.get("/questions/sum_of_n").json()["status"] == "archived"


def test_unarchive_restores_to_list(client) -> None:
    client.post("/questions", json=_sample_question())
    client.post("/questions/sum_of_n/archive")
    assert client.post("/questions/sum_of_n/unarchive").json()["status"] == "active"
    assert [q["id"] for q in client.get("/questions").json()["items"]] == ["sum_of_n"]


def test_archive_retires_a_question_with_submissions(client, monkeypatch) -> None:
    # DELETE 409s once a question has submissions; archive is the retire path.
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-arch"))
    client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "J", "language": "python", "code": "x"},
    )
    assert client.delete("/questions/sum_of_n").status_code == 409
    assert client.post("/questions/sum_of_n/archive").json()["status"] == "archived"
    # The submission is untouched.
    assert len(client.get("/questions/sum_of_n/submissions").json()["items"]) == 1


def test_delete_question_cascades_invites(client) -> None:
    """Invites go with their question rather than lingering as orphans.

    An invite is only a link to a question, so it carries no record worth keeping
    once the question is gone — but left behind it would point at a row that no
    longer exists.
    """
    client.post("/questions", json=_sample_question())
    token = client.post(
        "/questions/sum_of_n/invites", json={"recipients": ["candidate@test.io"]}
    ).json()["token"]
    assert client.get(f"/invite/{token}").status_code == 200

    assert client.delete("/questions/sum_of_n").status_code == 204
    assert client.get(f"/invite/{token}").status_code == 404


def test_sqlite_foreign_keys_are_enforced(anon_client) -> None:
    """SQLite must reject a row pointing at a question that doesn't exist.

    SQLite ignores foreign keys unless the pragma is on, while Postgres — the
    production target — always enforces them. Without this, a write that orphans
    rows passes every local test and then fails in prod. `anon_client` is here to
    point `db_module.engine` at the test DB.
    """
    with Session(db_module.engine) as session:
        session.add(
            Submission(
                id="orphan",
                question_id="no_such_question",
                candidate="Nobody",
                language="python",
                code="print(1)",
                status="pending",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_pass_threshold_must_be_a_fraction(client) -> None:
    # The agent rejects pass_threshold outside (0, 1] with a 400 at grade time, so
    # the platform must reject a wizard-style percent (e.g. 90) at creation (422).
    q = _sample_question()
    q["pass_threshold"] = 90.0  # a percent, not the required 0..1 fraction
    assert client.post("/questions", json=q).status_code == 422
    q["pass_threshold"] = 0.0  # boundary: must be > 0
    assert client.post("/questions", json=q).status_code == 422
    q["pass_threshold"] = 0.9  # valid
    assert client.post("/questions", json=q).status_code == 201


def test_create_submission_mocks_agent(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())

    captured: dict[str, Any] = {}

    async def fake_trigger(question, submission, callback_url, base_url=None):  # noqa: ANN001
        captured["question_id"] = question.id
        captured["code"] = submission.code
        captured["callback_url"] = callback_url
        return "job-123"

    monkeypatch.setattr(agent_client, "trigger_assessment", fake_trigger)

    resp = client.post(
        "/submissions",
        json={
            "question_id": "sum_of_n",
            "candidate": "Jane Doe",
            "language": "python",
            "code": "print(sum(...))",
        },
    )
    assert resp.status_code == 201
    sub = resp.json()
    assert sub["status"] == "running"
    assert sub["agent_job_id"] == "job-123"
    assert sub["result"] is None
    assert captured["question_id"] == "sum_of_n"
    assert captured["callback_url"].endswith("/assessments/callback")


def test_direct_submissions_are_not_constrained_by_the_invite_unique(client, monkeypatch) -> None:
    """`uq_submission_invite_candidate` must not touch the interviewer's own path.

    POST /submissions carries no invite_id and no candidate_email, and NULLs
    compare as distinct in SQL, so any number of direct submissions coexist — they
    are not candidate attempts. Asserted rather than assumed: if NULLs ever stopped
    being distinct, the second insert here would 409 instead.
    """
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    body = {"question_id": "sum_of_n", "candidate": "Jane Doe", "language": "python", "code": "x"}

    assert client.post("/submissions", json=body).status_code == 201
    assert client.post("/submissions", json=body).status_code == 201
    assert len(client.get("/submissions").json()["items"]) == 2


def test_submission_unknown_question_404(client, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("x"))
    resp = client.post(
        "/submissions",
        json={"question_id": "ghost", "candidate": "X", "language": "python", "code": "x"},
    )
    assert resp.status_code == 404


def test_agent_call_failure_marks_error(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())

    monkeypatch.setattr(
        agent_client, "trigger_assessment", async_raise(RuntimeError("agent down"))
    )
    resp = client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "X", "language": "python", "code": "x"},
    )
    assert resp.status_code == 502
    # The submission row still exists, flipped to error.
    subs = client.get("/submissions").json()["items"]
    assert len(subs) == 1 and subs[0]["status"] == "error"


def _callback_payload(job_id: str, verdict: str = "PASS") -> dict[str, Any]:
    return {
        "question_id": "sum_of_n",
        "question_title": "Sum of N",
        "language": "python",
        "verdict": verdict,
        "reason": "all tests passed",
        "score_pct": 100.0,
        "points_earned": 10,
        "points_total": 10,
        "pass_threshold_pct": 90.0,
        "compile_error": None,
        "infra_error": None,
        "test_cases": [
            {"name": "t1", "category": "correctness", "weight": 1.0, "status": "PASS",
             "input": "2\n3 4\n", "expected": "7", "actual": "7", "duration_s": 0.01,
             "timed_out": False, "error": None}
        ],
        "quality": {"engine": "offline", "time_complexity": "O(n)", "overall_score": 4.5},
        "judge_cost_usd": 0.0094,
        "candidate": "Jane Doe",
        "job_id": job_id,
    }


def _create_running_submission(client, monkeypatch, job_id: str = "job-abc") -> str:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return(job_id))
    resp = client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "Jane Doe", "language": "python", "code": "x"},
    )
    return resp.json()["id"]


def test_callback_persists_result_and_marks_done(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-abc")

    resp = client.post("/assessments/callback", json=_callback_payload("job-abc"))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "done"
    assert sub["result"] is not None
    assert sub["result"]["verdict"] == "PASS"
    assert sub["result"]["score_pct"] == 100.0
    # Stored verbatim.
    assert sub["result"]["full_result"]["judge_cost_usd"] == 0.0094
    assert sub["result"]["full_result"]["test_cases"][0]["name"] == "t1"


def test_callback_error_verdict_marks_error(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-err")
    payload = _callback_payload("job-err", verdict="ERROR")
    payload["infra_error"] = "python toolchain missing"
    resp = client.post("/assessments/callback", json=payload)
    assert resp.status_code == 200
    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "error"
    assert sub["result"]["verdict"] == "ERROR"


def test_callback_agent_error_payload(client, monkeypatch) -> None:
    # The agent's failure path sends {job_id, status: error, error: ...} with no verdict.
    sub_id = _create_running_submission(client, monkeypatch, "job-boom")
    resp = client.post(
        "/assessments/callback",
        json={"job_id": "job-boom", "status": "error", "error": "kaboom"},
    )
    assert resp.status_code == 200
    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "error"
    assert sub["result"]["verdict"] == "ERROR"
    assert sub["result"]["reason"] == "kaboom"


# --------------------------------------------------------------------------- #
# Reaper: submissions stranded in "running" (callback never arrived)            #
# --------------------------------------------------------------------------- #


def _age_submission(sub_id: str, seconds: float) -> None:
    """Backdate a submission's updated_at so the reaper sees it as stale.

    Set explicitly, so SQLAlchemy's onupdate default does not overwrite it.
    """
    with Session(db_module.engine) as s:
        row = s.get(Submission, sub_id)
        assert row is not None
        row.updated_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        s.add(row)
        s.commit()


def test_reaper_flips_stale_running_to_error(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-stale")
    _age_submission(sub_id, config.REAP_RUNNING_AFTER_S + 60)

    # Viewing the submission reaps it.
    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "error"
    # agent_job_id is preserved so a late callback can still match and land.
    assert sub["agent_job_id"] == "job-stale"


def test_reaper_leaves_fresh_running_alone(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-fresh")
    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "running"


def test_reaped_submission_becomes_retryable(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-old")
    _age_submission(sub_id, config.REAP_RUNNING_AFTER_S + 60)
    client.get("/submissions")  # reap on the dashboard read

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-new"))
    resp = client.post(f"/submissions/{sub_id}/retry")
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"
    assert resp.json()["agent_job_id"] == "job-new"


def test_reaper_disabled_when_grace_non_positive(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-keep")
    _age_submission(sub_id, 100_000)
    monkeypatch.setattr(config, "REAP_RUNNING_AFTER_S", 0)
    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "running"


def test_late_callback_lands_even_after_reap(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-late")
    _age_submission(sub_id, config.REAP_RUNNING_AFTER_S + 60)
    client.get("/submissions")  # reap -> error

    # The job wasn't dead, just slow: its callback still matches on agent_job_id.
    resp = client.post("/assessments/callback", json=_callback_payload("job-late"))
    assert resp.status_code == 200
    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "done"
    assert sub["result"]["verdict"] == "PASS"


def test_callback_unknown_job_ignored(client) -> None:
    resp = client.post("/assessments/callback", json={"job_id": "nobody", "verdict": "PASS"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_callback_missing_job_id_400(client) -> None:
    assert client.post("/assessments/callback", json={"verdict": "PASS"}).status_code == 400


def test_retry_from_error_reruns(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())

    # First trigger fails -> submission lands in "error".
    monkeypatch.setattr(
        agent_client, "trigger_assessment", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down"))
    )
    resp = client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "Jane", "language": "python", "code": "x"},
    )
    assert resp.status_code == 502
    sub_id = client.get("/submissions").json()["items"][0]["id"]

    # Agent recovers; retry succeeds with a fresh job_id.
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-retry-1"))
    resp = client.post(f"/submissions/{sub_id}/retry")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["agent_job_id"] == "job-retry-1"


def test_retry_non_error_returns_409(client, monkeypatch) -> None:
    # A "running" submission may not be retried.
    sub_id = _create_running_submission(client, monkeypatch, "job-live")
    resp = client.post(f"/submissions/{sub_id}/retry")
    assert resp.status_code == 409


def test_retry_unknown_submission_404(client) -> None:
    assert client.post("/submissions/nope/retry").status_code == 404


# --------------------------------------------------------------------------- #
# Shared-secret auth                                                            #
# --------------------------------------------------------------------------- #


def test_callback_requires_token_when_set(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-auth")
    monkeypatch.setattr(config, "CALLBACK_TOKEN", "s3cret")

    # Missing header -> 401.
    resp = client.post("/assessments/callback", json=_callback_payload("job-auth"))
    assert resp.status_code == 401

    # Wrong header -> 401.
    resp = client.post(
        "/assessments/callback",
        json=_callback_payload("job-auth"),
        headers={"X-Assess-Token": "nope"},
    )
    assert resp.status_code == 401

    # Correct header -> 200 and persists as before.
    resp = client.post(
        "/assessments/callback",
        json=_callback_payload("job-auth"),
        headers={"X-Assess-Token": "s3cret"},
    )
    assert resp.status_code == 200
    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "done"
    assert sub["result"]["verdict"] == "PASS"


def test_outbound_call_includes_token_when_set(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(config, "ASSESS_API_TOKEN", "outbound-secret")

    captured: dict[str, Any] = {}

    def fake_post(url, timeout, **kw):  # ANN001
        captured["headers"] = kw["headers"]
        return httpx.Response(
            200,
            json={"job_id": "job-hdr", "status": "accepted"},
            request=httpx.Request("POST", url),
        )

    patch_async_post(monkeypatch, fake_post)

    resp = client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "Jane", "language": "python", "code": "x"},
    )
    assert resp.status_code == 201
    assert captured["headers"]["X-Assess-Token"] == "outbound-secret"


def test_outbound_request_is_signed_when_configured(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(config, "ASSESS_SIGNING_SECRET", "out-sign")

    captured: dict[str, Any] = {}

    def fake_post(url, timeout, **kw):  # ANN001
        captured.update(kw)
        return httpx.Response(
            200,
            json={"job_id": "j", "status": "accepted"},
            request=httpx.Request("POST", url),
        )

    patch_async_post(monkeypatch, fake_post)
    client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "J", "language": "python", "code": "x"},
    )
    # The outbound body carries a signature the agent can verify over those bytes.
    sig = captured["headers"].get(signing.SIGNATURE_HEADER)
    assert sig is not None
    assert signing.verify("out-sign", captured["content"], sig)


def test_callback_signature_required_when_configured(client, monkeypatch) -> None:
    monkeypatch.setattr(config, "CALLBACK_SIGNING_SECRET", "cb-verify")
    raw = json.dumps({"job_id": "nope", "verdict": "PASS", "score_pct": 100.0}).encode()
    ct = {"Content-Type": "application/json"}

    # No signature -> 401, before any job lookup.
    assert client.post("/assessments/callback", content=raw, headers=ct).status_code == 401

    # A valid signature over the exact bytes -> 200 (an unknown job is still acked).
    ok = client.post(
        "/assessments/callback",
        content=raw,
        headers={**ct, signing.SIGNATURE_HEADER: signing.sign("cb-verify", raw)},
    )
    assert ok.status_code == 200

    # Wrong secret -> 401.
    bad = client.post(
        "/assessments/callback",
        content=raw,
        headers={**ct, signing.SIGNATURE_HEADER: signing.sign("wrong", raw)},
    )
    assert bad.status_code == 401


# --------------------------------------------------------------------------- #
# Question authoring assistant (POST /questions/draft)                          #
# --------------------------------------------------------------------------- #


def _draft_payload() -> dict[str, Any]:
    """The agent's draft response shape (example nested, pass_threshold a fraction)."""
    return {
        "engine": "claude-sonnet-4-6",
        "question": {
            "id": "longest_run",
            "title": "Longest increasing run",
            "prompt": "Read N then N integers; print the longest strictly increasing run.",
            "constraints": "1 <= N <= 1e5",
            "time_limit_s": 2.0,
            "pass_threshold": 0.9,
            "required_complexity": "O(n)",
            "example": {"input": "4\n1 2 1 3\n", "output": "2"},
            "test_cases": [
                {"name": "t1", "stdin": "4\n1 2 1 3\n", "expected": "2",
                 "category": "correctness", "weight": 1.0},
            ],
        },
        "warnings": ["Dropped case 'edge': reference timed out."],
        "reference_solution": "print('ref')",
        "reference_language": "python",
        "cost_usd": 0.021,
    }


def _http_error(status: int, detail: Any) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "http://agent/questions/draft")
    response = httpx.Response(status, json={"detail": detail}, request=request)
    return httpx.HTTPStatusError("err", request=request, response=response)


def test_draft_question_happy_path(client, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "draft_question", async_return(_draft_payload()))

    resp = client.post(
        "/questions/draft",
        json={"brief": "Longest increasing run", "language": "python"},
    )
    assert resp.status_code == 200
    body = resp.json()
    q = body["question"]
    assert q["id"] == "longest_run"
    # example flattened; pass_threshold kept as the agent's 0..1 fraction.
    assert q["example_input"] == "4\n1 2 1 3\n"
    assert q["example_output"] == "2"
    assert q["pass_threshold"] == 0.9
    assert len(q["test_cases"]) == 1
    assert body["warnings"] == ["Dropped case 'edge': reference timed out."]
    assert body["reference_solution"] == "print('ref')"

    # Stateless: nothing was persisted.
    assert client.get("/questions").json()["items"] == []


def test_draft_question_offline_503(client, monkeypatch) -> None:
    monkeypatch.setattr(
        agent_client,
        "draft_question",
        async_raise(_http_error(503, "drafting requires a live model.")),
    )
    resp = client.post("/questions/draft", json={"brief": "x", "language": "python"})
    assert resp.status_code == 503
    assert "live model" in resp.json()["detail"]


def test_draft_question_unusable_422(client, monkeypatch) -> None:
    warnings_detail = {"warnings": ["The draft produced no correctness inputs."]}

    monkeypatch.setattr(
        agent_client, "draft_question", async_raise(_http_error(422, warnings_detail))
    )
    resp = client.post("/questions/draft", json={"brief": "x", "language": "python"})
    assert resp.status_code == 422
    # The dict detail (with `warnings`) is flattened to a readable string for the UI.
    assert resp.json()["detail"] == "The draft produced no correctness inputs."


def test_draft_question_requires_auth(anon_client) -> None:
    resp = anon_client.post("/questions/draft", json={"brief": "x", "language": "python"})
    assert resp.status_code == 401


def test_draft_uses_the_longer_draft_timeout(client, monkeypatch) -> None:
    # Drafting is synchronous (LLM + reference execution), so it must use the long
    # AGENT_DRAFT_TIMEOUT_S, not the short trigger timeout — else complex drafts 502.
    captured: dict[str, Any] = {}

    def fake_post(url, timeout, **kw):  # ANN001
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={"engine": "x", "question": _draft_payload()["question"], "warnings": []},
            request=httpx.Request("POST", url),
        )

    patch_async_post(monkeypatch, fake_post)
    resp = client.post("/questions/draft", json={"brief": "x", "language": "python"})
    assert resp.status_code == 200
    assert captured["timeout"] == config.AGENT_DRAFT_TIMEOUT_S
    assert config.AGENT_DRAFT_TIMEOUT_S > config.AGENT_TIMEOUT_S


def test_questions_pagination_bounds_and_cover(client) -> None:
    for i in range(3):
        assert client.post("/questions", json=_sample_question(f"q{i}")).status_code == 201

    all_ids = [q["id"] for q in client.get("/questions").json()["items"]]
    assert sorted(all_ids) == ["q0", "q1", "q2"]

    # The envelope reports the FULL count and the slice params, so a client can
    # render "showing 1-2 of 3" and a pager without a second request.
    first = client.get("/questions?limit=2&offset=0").json()
    assert first["total"] == 3 and first["limit"] == 2 and first["offset"] == 0
    assert len(first["items"]) == 2

    # limit + offset partition the full set with no overlap and no gaps.
    page1 = [q["id"] for q in first["items"]]
    page2 = [q["id"] for q in client.get("/questions?limit=2&offset=2").json()["items"]]
    assert len(page1) == 2 and len(page2) == 1
    assert set(page1).isdisjoint(page2)
    assert set(page1) | set(page2) == {"q0", "q1", "q2"}

    # Ordering is deterministic: the same request returns the same order twice,
    # so paging over it never repeats or skips a row.
    assert [q["id"] for q in client.get("/questions").json()["items"]] == all_ids

    # Bounds are enforced (limit 1..200, offset >= 0).
    assert client.get("/questions?limit=0").status_code == 422
    assert client.get("/questions?limit=201").status_code == 422
    assert client.get("/questions?offset=-1").status_code == 422


def test_submissions_list_is_lean(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    body = {"question_id": "sum_of_n", "candidate": "Jane", "language": "python", "code": "print(1)"}
    assert client.post("/submissions", json=body).status_code == 201

    rows = client.get("/submissions").json()["items"]
    assert len(rows) == 1
    row = rows[0]
    # The list is a summary: the heavy per-row blobs must not ship.
    assert "code" not in row
    assert "full_result" not in row
    assert "result" not in row
    assert {"id", "question_id", "candidate", "language", "status", "verdict", "score_pct"} <= row.keys()
    # candidate_email rides on the lean row (light field, used to disambiguate in
    # the global Submissions list); the direct POST /submissions path has none.
    assert "candidate_email" in row
    assert row["candidate_email"] is None

    # The full payload is still available per-id.
    detail = client.get(f"/submissions/{row['id']}").json()
    assert detail["code"] == "print(1)"

    # Pagination bounds apply here too.
    assert client.get("/submissions?limit=0").status_code == 422


def test_submissions_csv_export(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "Jane", "language": "python", "code": "print(1)"},
    )

    resp = client.get("/submissions/export")
    assert resp.status_code == 200  # not swallowed by /submissions/{id}
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("submission_id,question_id,question_title,candidate")
    assert "Jane" in resp.text
    assert "Sum of N" in resp.text  # the question title is joined in, not just the id
