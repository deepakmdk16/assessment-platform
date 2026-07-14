"""API tests. Fully offline: the outbound agent call is mocked, so no real agent,
LLM, or network is required."""

from __future__ import annotations

from typing import Any

from assessment_platform import agent_client


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
    assert client.get("/health").json() == {"status": "ok"}


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
    assert len(client.get("/questions").json()) == 1

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


def test_create_submission_mocks_agent(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())

    captured: dict[str, Any] = {}

    def fake_trigger(question, submission, callback_url, base_url=None):  # noqa: ANN001
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


def test_submission_unknown_question_404(client, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "x")
    resp = client.post(
        "/submissions",
        json={"question_id": "ghost", "candidate": "X", "language": "python", "code": "x"},
    )
    assert resp.status_code == 404


def test_agent_call_failure_marks_error(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())

    def boom(*a, **k):  # noqa: ANN002, ANN003
        raise RuntimeError("agent down")

    monkeypatch.setattr(agent_client, "trigger_assessment", boom)
    resp = client.post(
        "/submissions",
        json={"question_id": "sum_of_n", "candidate": "X", "language": "python", "code": "x"},
    )
    assert resp.status_code == 502
    # The submission row still exists, flipped to error.
    subs = client.get("/submissions").json()
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
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: job_id)
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


def test_callback_unknown_job_ignored(client) -> None:
    resp = client.post("/assessments/callback", json={"job_id": "nobody", "verdict": "PASS"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_callback_missing_job_id_400(client) -> None:
    assert client.post("/assessments/callback", json={"verdict": "PASS"}).status_code == 400
