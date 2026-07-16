"""Slice 11 tests: the candidate's in-editor Run / Run-against-tests routes.

These are non-grading rehearsals: nothing is stored, and they must not consume
the candidate's one attempt. The agent is mocked (these run offline) — the real
execution is covered by the agent's own suite.

The load-bearing rule here is redaction: a candidate may learn how many cases
pass, never what the cases are.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from conftest import register_interviewer  # pytest adds tests/ to sys.path
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from test_slice1 import _auth, _make_invite

from assessment_platform import agent_client, config
from assessment_platform import db as db_module
from assessment_platform.models import Submission

RUN_OK = {
    "stdout": "7",
    "stderr": None,
    "duration_s": 0.01,
    "timed_out": False,
    "compile_error": None,
    "infra_error": None,
}

TESTS_OK = {
    "compile_error": None,
    "infra_error": None,
    "test_cases": [
        {"name": "secret_edge_case", "category": "correctness", "status": "PASS", "duration_s": 0.01},
        {"name": "big_input", "category": "performance", "status": "TLE", "duration_s": 2.0},
    ],
}


def _run(client: TestClient, token: str, email: str = "cand@x.io", **extra: Any) -> Any:
    body = {"candidate_email": email, "language": "python", "code": "print(7)", **extra}
    return client.post(f"/invite/{token}/run", json=body)


def _run_tests(client: TestClient, token: str, email: str = "cand@x.io") -> Any:
    body = {"candidate_email": email, "language": "python", "code": "print(7)"}
    return client.post(f"/invite/{token}/run-tests", json=body)


@pytest.fixture
def invite(anon_client: TestClient) -> dict:
    tok = register_interviewer(anon_client, "s11@x.io")
    return _make_invite(anon_client, tok, recipients=["cand@x.io"])


# --------------------------------------------------------------------------- #
# POST /invite/{token}/run — the candidate's own input                          #
# --------------------------------------------------------------------------- #


def test_run_returns_program_output(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def _fake(code: str, language: str, stdin: str, **k: Any) -> dict:
        seen["code"], seen["language"], seen["stdin"] = code, language, stdin
        return RUN_OK

    monkeypatch.setattr(agent_client, "run_code", _fake)
    resp = _run(anon_client, invite["token"], stdin="3\n1 2 4\n")

    assert resp.status_code == 200
    assert resp.json()["stdout"] == "7"
    # The candidate's stdin reaches the agent verbatim.
    assert seen["stdin"] == "3\n1 2 4\n"


def test_run_does_not_create_a_submission(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running is a rehearsal — it must not spend the candidate's one attempt."""
    monkeypatch.setattr(agent_client, "run_code", lambda *a, **k: RUN_OK)
    assert _run(anon_client, invite["token"]).status_code == 200

    with Session(db_module.engine) as s:
        assert s.exec(select(Submission)).all() == []
    # And they can still start + submit afterwards.
    assert anon_client.post(
        f"/invite/{invite['token']}/start", json={"candidate_email": "cand@x.io"}
    ).status_code == 200


def test_run_rejects_an_uninvited_email(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otherwise the link would be free compute for anyone holding it."""
    monkeypatch.setattr(agent_client, "run_code", lambda *a, **k: RUN_OK)
    assert _run(anon_client, invite["token"], email="mallory@x.io").status_code == 403


def test_run_rejects_a_candidate_who_already_submitted(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_client, "trigger_assessment", lambda *a, **k: "job")
    monkeypatch.setattr(agent_client, "run_code", lambda *a, **k: RUN_OK)
    anon_client.post(
        f"/invite/{invite['token']}/submit",
        json={
            "candidate_name": "C",
            "candidate_email": "cand@x.io",
            "language": "python",
            "code": "x",
        },
    )
    assert _run(anon_client, invite["token"]).status_code == 409


def test_run_on_unknown_or_revoked_invite(
    anon_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_client, "run_code", lambda *a, **k: RUN_OK)
    assert _run(anon_client, "no-such-token").status_code == 404

    tok = register_interviewer(anon_client, "s11-rv@x.io")
    inv = _make_invite(anon_client, tok, recipients=["cand@x.io"])
    anon_client.post(f"/questions/sum_of_n/invites/{inv['token']}/revoke", headers=_auth(tok))
    assert _run(anon_client, inv["token"]).status_code == 410


def test_run_surfaces_a_compile_error_as_a_normal_response(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Broken code is an expected outcome of Run, not a server error."""
    monkeypatch.setattr(
        agent_client, "run_code", lambda *a, **k: {**RUN_OK, "compile_error": "syntax error"}
    )
    resp = _run(anon_client, invite["token"])
    assert resp.status_code == 200
    assert resp.json()["compile_error"] == "syntax error"


def test_run_maps_agent_infra_error_to_502(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing toolchain is our problem, not the candidate's."""
    monkeypatch.setattr(
        agent_client, "run_code", lambda *a, **k: {**RUN_OK, "infra_error": "no python3"}
    )
    assert _run(anon_client, invite["token"]).status_code == 502


def test_run_maps_agent_unreachable_to_502(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(*a: Any, **k: Any) -> dict:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(agent_client, "run_code", _boom)
    assert _run(anon_client, invite["token"]).status_code == 502


def test_run_is_rate_limited(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "RUN_RATE_LIMIT_MAX", 2)
    monkeypatch.setattr(agent_client, "run_code", lambda *a, **k: RUN_OK)
    assert _run(anon_client, invite["token"]).status_code == 200
    assert _run(anon_client, invite["token"]).status_code == 200
    assert _run(anon_client, invite["token"]).status_code == 429


# --------------------------------------------------------------------------- #
# POST /invite/{token}/run-tests — pass/fail only                               #
# --------------------------------------------------------------------------- #


def test_run_tests_summarises_pass_fail(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_client, "run_tests", lambda *a, **k: TESTS_OK)
    resp = _run_tests(anon_client, invite["token"])

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["passed"] == 1
    assert [c["status"] for c in body["test_cases"]] == ["PASS", "TLE"]
    assert [c["index"] for c in body["test_cases"]] == [1, 2]


def test_run_tests_never_leaks_the_answer_key(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of the whole endpoint: counts, not contents."""
    monkeypatch.setattr(agent_client, "run_tests", lambda *a, **k: TESTS_OK)
    body = _run_tests(anon_client, invite["token"]).json()

    for case in body["test_cases"]:
        assert set(case.keys()) == {"index", "category", "status", "duration_s"}
    # Case names are a hint in themselves ("secret_edge_case") — they're dropped.
    assert "secret_edge_case" not in str(body)
    assert "big_input" not in str(body)


def test_run_tests_does_not_create_a_submission(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_client, "run_tests", lambda *a, **k: TESTS_OK)
    assert _run_tests(anon_client, invite["token"]).status_code == 200
    with Session(db_module.engine) as s:
        assert s.exec(select(Submission)).all() == []


def test_run_tests_rejects_an_uninvited_email(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent_client, "run_tests", lambda *a, **k: TESTS_OK)
    assert _run_tests(anon_client, invite["token"], email="mallory@x.io").status_code == 403


def test_run_tests_reports_a_compile_error_with_no_cases(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        agent_client,
        "run_tests",
        lambda *a, **k: {"compile_error": "boom", "infra_error": None, "test_cases": []},
    )
    resp = _run_tests(anon_client, invite["token"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["compile_error"] == "boom"
    assert body["total"] == 0 and body["passed"] == 0


def test_run_tests_passes_the_stored_question_to_the_agent(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def _fake(question: Any, code: str, language: str, **k: Any) -> dict:
        seen["question_id"] = question.id
        return TESTS_OK

    monkeypatch.setattr(agent_client, "run_tests", _fake)
    _run_tests(anon_client, invite["token"])
    assert seen["question_id"] == "sum_of_n"


def test_run_tests_is_rate_limited(
    anon_client: TestClient, invite: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unlimited, this is a pass/fail oracle for reverse-engineering the suite."""
    monkeypatch.setattr(config, "RUN_RATE_LIMIT_MAX", 1)
    monkeypatch.setattr(agent_client, "run_tests", lambda *a, **k: TESTS_OK)
    assert _run_tests(anon_client, invite["token"]).status_code == 200
    assert _run_tests(anon_client, invite["token"]).status_code == 429
