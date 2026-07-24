"""A1 — the authoring-time question case floor.

Creating/updating a question with fewer than MIN_CORRECTNESS_CASES correctness
cases, or with no performance case, is rejected (so we never store a question the
agent would refuse to grade). The offline `scripts/check_question_cases.py` audit
flags such rows that already exist. Fully offline — no agent, no network."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sqlmodel import Session

from assessment_platform import db as db_module
from assessment_platform.models import Interviewer, Question, QuestionTestCase

# The audit's core lives in the deploy-time script; import it for a direct test.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from check_question_cases import find_offenders  # noqa: E402


def _correctness(n: int) -> list[dict[str, Any]]:
    return [
        {"name": f"c{i}", "stdin": f"{i}\n", "expected": str(i), "category": "correctness", "weight": 1.0}
        for i in range(1, n + 1)
    ]


_PERF = {"name": "big", "stdin": "9\n", "expected": "9", "category": "performance", "weight": 3.0}


def _question(qid: str, test_cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": qid,
        "title": "Q",
        "prompt": "p",
        "constraints": "c",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "test_cases": test_cases,
    }


def test_create_rejects_too_few_correctness_cases(client) -> None:
    q = _question("q_few", _correctness(3) + [_PERF])  # 3 < 4
    resp = client.post("/questions", json=q)
    assert resp.status_code == 422
    assert "correctness" in resp.json()["detail"]
    assert client.get("/questions/q_few").status_code == 404  # nothing stored


def test_create_rejects_missing_performance_case(client) -> None:
    q = _question("q_noperf", _correctness(4))  # 4 correctness, 0 performance
    resp = client.post("/questions", json=q)
    assert resp.status_code == 422
    assert "performance" in resp.json()["detail"]


def test_create_accepts_a_valid_question(client) -> None:
    q = _question("q_ok", _correctness(4) + [_PERF])
    resp = client.post("/questions", json=q)
    assert resp.status_code == 201
    assert len(resp.json()["test_cases"]) == 5


def test_update_enforces_case_floor(client) -> None:
    assert client.post("/questions", json=_question("q_u", _correctness(4) + [_PERF])).status_code == 201
    # PUT that drops below the floor is rejected; the stored question is untouched.
    bad = {k: v for k, v in _question("q_u", _correctness(2) + [_PERF]).items() if k != "id"}
    assert client.put("/questions/q_u", json=bad).status_code == 422
    assert len(client.get("/questions/q_u").json()["test_cases"]) == 5


def test_check_question_cases_flags_offenders(anon_client) -> None:
    # The API now refuses to create a below-floor question, so seed one directly to
    # simulate a row stored under the old floor, then assert the audit catches it.
    with Session(db_module.engine) as s:
        owner = Interviewer(email="owner@floor.io", password_hash="x", name="O")
        s.add(owner)
        s.commit()
        s.refresh(owner)
        assert owner.id is not None
        bad = Question(
            id="bad_legacy",
            owner_id=owner.id,
            title="Bad",
            prompt="p",
            constraints="c",
            test_cases=[
                QuestionTestCase(name="c1", stdin="1", expected="1", category="correctness"),
                QuestionTestCase(name="c2", stdin="2", expected="2", category="correctness"),
                QuestionTestCase(name="c3", stdin="3", expected="3", category="correctness"),
                QuestionTestCase(name="big", stdin="9", expected="9", category="performance"),
            ],
        )
        good = Question(
            id="good_ok",
            owner_id=owner.id,
            title="Good",
            prompt="p",
            constraints="c",
            test_cases=[
                QuestionTestCase(name=f"c{i}", stdin=str(i), expected=str(i), category="correctness")
                for i in range(4)
            ]
            + [QuestionTestCase(name="big", stdin="9", expected="9", category="performance")],
        )
        s.add(bad)
        s.add(good)
        s.commit()

    with Session(db_module.engine) as s:
        offenders = dict(find_offenders(s))

    assert "bad_legacy" in offenders
    assert any("correctness" in r for r in offenders["bad_legacy"])
    assert "good_ok" not in offenders
