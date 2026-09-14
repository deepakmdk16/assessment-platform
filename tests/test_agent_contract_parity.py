"""Cross-repo contract parity (gate G1): the platform must never store a question
the agent will refuse to grade, and never build a callback body the platform
itself will refuse to read.

Why this is a test and not a comment: `question_rules.py` used to carry a "keep
identical" comment against the agent's constant, and `_limit_body_size`'s
docstring claims the schema caps bound what is stored. Neither is checked by
anything, and both drifted — the 2026-09-14 audit's two P0s are exactly that
drift (R2-001, R2-002). A comment cannot fail a push; this can.

The agent is a separate deployable and is NOT a dependency of the platform, so
this imports it from a sibling checkout and **skips with a notice** when there
isn't one — the same cross-repo pattern `scripts/checkpoints.sh` already uses for
`signing.py` and `callback_contract.py`. CI checks the agent out so the gate is
not silently absent there (see `.github/workflows/checks.yml`).

**Known divergences are `xfail(strict=True)`**, each naming its finding and the
session that closes it. Strict means the suite fails if one starts *passing*, so
a fixed divergence cannot be left rotting in this list — delete the mark when the
session lands. Anything not on the list fails immediately, which is the point:
this gate is installed before the fixes, so no *new* drift can be added while
S01/S02 are still outstanding.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from assessment_platform import config
from assessment_platform.agent_client import build_question_payload
from assessment_platform.models import Question, QuestionTestCase
from assessment_platform.question_rules import MIN_CORRECTNESS_CASES, case_floor_violations
from assessment_platform.schemas import QuestionCreate, TestCaseIn

# --- locating the companion repo ---------------------------------------------
# Local dev keeps the two repos side by side (`../AssesmentAgent`); CI cannot
# check out above the workspace, so it puts it inside (`./AssesmentAgent`).
_TESTS_DIR = Path(__file__).resolve().parent
_AGENT_CANDIDATES = (
    _TESTS_DIR.parents[1] / "AssesmentAgent",
    _TESTS_DIR.parents[0] / "AssesmentAgent",
)
AGENT_ROOT: Path | None = next(
    (p for p in _AGENT_CANDIDATES if (p / "assessment_agent" / "questions.py").is_file()), None
)

pytestmark = pytest.mark.skipif(
    AGENT_ROOT is None,
    reason="companion agent repo not checked out beside this one — parity gate skipped",
)


def _agent() -> Any:
    """Import the agent's question intake, adding its root to `sys.path` once.

    Appended, never inserted: both repos carry a top-level `contract` package and
    the platform's must keep winning.
    """
    assert AGENT_ROOT is not None
    if str(AGENT_ROOT) not in sys.path:
        sys.path.append(str(AGENT_ROOT))
    import assessment_agent.loader as agent_loader
    import assessment_agent.questions as agent_questions

    return agent_loader, agent_questions


# --- the shared fixture -------------------------------------------------------


def _valid_payload() -> dict[str, Any]:
    """A question both sides accept — the baseline every case below mutates."""
    cases: list[dict[str, Any]] = [
        {
            "name": f"correct_{i}",
            "stdin": f"{i}\n",
            "expected": str(i),
            "category": "correctness",
            "weight": 1.0,
        }
        for i in range(MIN_CORRECTNESS_CASES)
    ]
    cases.append(
        {
            "name": "performance_large",
            "stdin": "10\n",
            "expected": "10",
            "category": "performance",
            "weight": 6.0,
        }
    )
    return {
        "id": "parity_probe",
        "title": "Parity probe",
        "prompt": "Read an integer N from standard input and print it.",
        "constraints": "1 <= N <= 10",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "test_cases": cases,
    }


def _platform_stores(payload: dict[str, Any]) -> Question | None:
    """Run the platform's authoring acceptance exactly as `create_question` does:
    the `QuestionCreate` schema, then the case floor. Returns the row it would
    store, or None if the platform refuses it."""
    try:
        body = QuestionCreate.model_validate(payload)
    except ValidationError:
        return None
    if case_floor_violations([tc.category for tc in body.test_cases]):
        return None
    return Question(
        id=body.id or "parity_probe",
        org_id=1,
        title=body.title,
        prompt=body.prompt,
        constraints=body.constraints,
        time_limit_s=body.time_limit_s,
        pass_threshold=body.pass_threshold,
        required_complexity=body.required_complexity,
        example_input=body.example_input,
        example_output=body.example_output,
        test_cases=[
            QuestionTestCase(
                name=tc.name,
                stdin=tc.stdin,
                expected=tc.expected,
                category=tc.category,
                weight=tc.weight,
            )
            for tc in body.test_cases
        ],
    )


def _agent_refuses(stored: Question) -> str | None:
    """Put the stored question through the real wire path — `build_question_payload`
    into the agent's `question_from_dict` — on the **grade** path, and return the
    refusal message, or None if the agent would grade it.

    `degrade_authoring=True` is what the agent's intake uses when grading a
    candidate's submission, so the two authoring-shape invariants (the case floor
    and the required performance case) come back as warnings rather than raising.
    Only a refusal here strands a candidate, which is what this gate is about.
    """
    agent_loader, _ = _agent()
    try:
        agent_loader.question_from_dict(build_question_payload(stored), degrade_authoring=True)
    except Exception as exc:  # ValidationError (shape) or ValueError (invariants)
        return f"{type(exc).__name__}: {exc}"
    return None


# --- 1. nothing the platform stores may be refused by the agent ---------------

Mutation = Callable[[dict[str, Any]], None]


def _blank_constraints(p: dict[str, Any]) -> None:
    p["constraints"] = ""


def _blank_title(p: dict[str, Any]) -> None:
    p["title"] = "   "


def _blank_prompt(p: dict[str, Any]) -> None:
    p["prompt"] = ""


def _zero_time_limit(p: dict[str, Any]) -> None:
    p["time_limit_s"] = 0.0


def _zero_weight(p: dict[str, Any]) -> None:
    p["test_cases"][0]["weight"] = 0.0


def _negative_weight(p: dict[str, Any]) -> None:
    p["test_cases"][0]["weight"] = -1.0


def _empty_expected(p: dict[str, Any]) -> None:
    p["test_cases"][0]["expected"] = ""


def _duplicate_case_names(p: dict[str, Any]) -> None:
    p["test_cases"][1]["name"] = p["test_cases"][0]["name"]


def _blank_case_name(p: dict[str, Any]) -> None:
    p["test_cases"][0]["name"] = " "


def _bad_category(p: dict[str, Any]) -> None:
    # Appended rather than applied to an existing case: changing one would drop the
    # correctness count below the floor, and the floor would mask the divergence.
    p["test_cases"].append({**p["test_cases"][0], "name": "odd_one", "category": "smoke"})


def _blank_id(p: dict[str, Any]) -> None:
    p["id"] = "   "


def _xfail(finding: str, session: str) -> pytest.MarkDecorator:
    return pytest.mark.xfail(
        strict=True,
        reason=f"{finding} — known divergence, closed by {session}; delete this mark with the fix",
    )


# Each entry: the mutation, and either no marks (the platform already refuses it)
# or an xfail naming the finding. R2-002 names blank constraints, weight <= 0,
# empty expected, duplicate case names and time limit 0 explicitly; the blank
# title/prompt/id cases are the same class of missing `min_length` and ride with
# it into S02.
DIVERGENCE_CASES = [
    pytest.param(_blank_constraints, id="blank_constraints", marks=_xfail("R2-002", "S02")),
    pytest.param(_blank_title, id="blank_title", marks=_xfail("R2-002", "S02")),
    pytest.param(_blank_prompt, id="blank_prompt", marks=_xfail("R2-002", "S02")),
    pytest.param(_zero_time_limit, id="zero_time_limit", marks=_xfail("R2-002", "S02")),
    pytest.param(_zero_weight, id="zero_weight", marks=_xfail("R2-002", "S02")),
    pytest.param(_negative_weight, id="negative_weight", marks=_xfail("R2-002", "S02")),
    pytest.param(_empty_expected, id="empty_expected", marks=_xfail("R2-002", "S02")),
    pytest.param(_duplicate_case_names, id="duplicate_case_names", marks=_xfail("R2-002", "S02")),
    pytest.param(_blank_case_name, id="blank_case_name", marks=_xfail("R2-002", "S02")),
    pytest.param(_blank_id, id="blank_id", marks=_xfail("R2-002", "S02")),
    # Already in parity: the platform's `Category` literal and the agent's agree.
    pytest.param(_bad_category, id="invalid_category"),
]


@pytest.mark.parametrize("mutate", DIVERGENCE_CASES)
def test_platform_refuses_what_the_agent_refuses(mutate: Mutation) -> None:
    """The core cross-repo invariant: a question the platform accepts must grade.

    The candidate is the one who pays for a violation — they cannot edit the
    question, so every submission against it ends as "error" with no reason
    (R2-002). The assertion is one-directional on purpose: the platform may be
    *stricter* than the agent (that only costs the interviewer a 422 at authoring
    time, which they can act on).
    """
    payload = _valid_payload()
    mutate(payload)

    stored = _platform_stores(payload)
    if stored is None:
        return  # the platform refused it first — parity holds

    refusal = _agent_refuses(stored)
    assert refusal is None, (
        "the platform would STORE this question but the agent refuses to grade it, "
        f"stranding every candidate who submits against it:\n  {refusal}\n"
        "Fix the platform's QuestionCreate/TestCaseIn schema to refuse it at authoring time."
    )


def test_the_baseline_question_is_accepted_by_both() -> None:
    """Guards the cases above: if the baseline itself stopped being valid, every
    parametrised case would pass for the wrong reason."""
    stored = _platform_stores(_valid_payload())
    assert stored is not None, "the platform refuses its own baseline question"
    assert _agent_refuses(stored) is None


def test_case_floor_constant_matches_the_agent() -> None:
    """`question_rules.MIN_CORRECTNESS_CASES` is a hand-kept mirror of the agent's.

    The platform cannot import the agent at runtime — separate deployable, not a
    dependency — so the mirror stays, but this is what keeps it honest instead of
    the old "keep identical" comment.
    """
    _, agent_questions = _agent()
    assert MIN_CORRECTNESS_CASES == agent_questions.MIN_CORRECTNESS_CASES, (
        f"platform floor {MIN_CORRECTNESS_CASES} != agent floor "
        f"{agent_questions.MIN_CORRECTNESS_CASES} — a question passing authoring would "
        "fail the agent's own floor (or vice versa)."
    )


# --- 2. the result callback must fit the body cap the platform enforces -------

# The agent echoes each case's `input`, `expected` and `actual` verbatim into the
# result payload (`assessment_agent/agent.py::result_to_dict`), which it POSTs to
# `POST /assessments/callback` — where the platform's own
# `api.py::_limit_body_size` 413s anything over MAX_BODY_BYTES. The agent does not
# retry a 4xx, so the grade is lost. For the callback to be deliverable for every
# question the platform will store, the platform must BOUND what it stores.
_CANDIDATE_OUTPUT_CAP_ENV = "ASSESS_OUTPUT_LIMIT_MB"


def _stored_case_char_caps() -> tuple[int | None, int | None]:
    """The platform's own `max_length` on a stored test case's stdin and expected
    (None = unbounded)."""

    def cap(name: str) -> int | None:
        meta = TestCaseIn.model_fields[name].metadata
        return next((m.max_length for m in meta if hasattr(m, "max_length")), None)

    return cap("stdin"), cap("expected")


@_xfail("R2-001", "S01")
def test_the_largest_storable_question_fits_the_callback_body_cap() -> None:
    """A stored question must not be able to produce an undeliverable result.

    Two things have to hold, and neither does today:
      1. the platform bounds each stored case's `stdin`/`expected`;
      2. that bound, times the number of cases, plus the agent's per-case output
         cap, fits under MAX_BODY_BYTES.
    """
    stdin_cap, expected_cap = _stored_case_char_caps()
    assert stdin_cap is not None and expected_cap is not None, (
        "TestCaseIn.stdin / .expected carry no max_length, so a stored question has no "
        "size bound at all — a 9.6 MB performance input is storable today and its grade "
        "is silently lost at the callback (R2-001). `_limit_body_size`'s docstring already "
        "claims the schema caps bound what is stored; make that true."
    )

    # `actual` is the candidate program's stdout for the case, capped by the agent's
    # ASSESS_OUTPUT_LIMIT_MB (64 MB by default) — it rides in the same body.
    output_cap = 64 * 1024 * 1024
    n_cases = 50  # the platform does not cap the case count either (R2-073)
    worst_case = n_cases * (stdin_cap + expected_cap + output_cap)
    assert worst_case < config.MAX_BODY_BYTES, (
        f"the largest storable question renders a ~{worst_case:,}-byte callback body, over "
        f"the {config.MAX_BODY_BYTES:,}-byte cap `_limit_body_size` enforces. Bound the stored "
        f"input, the case count, and the echoed output ({_CANDIDATE_OUTPUT_CAP_ENV}) together."
    )


def test_a_baseline_result_callback_is_well_under_the_cap() -> None:
    """The ordinary case, so the size gate above is not the only thing measuring
    the body — this one must stay green on its own."""
    stored = _platform_stores(_valid_payload())
    assert stored is not None
    payload = build_question_payload(stored)
    body = {
        "job_id": "parity-probe",
        "verdict": "PASS",
        "score_pct": 100.0,
        "reason": "all cases passed",
        "test_cases": [
            {**c, "input": c["stdin"], "actual": c["expected"], "status": "PASS"}
            for c in payload["test_cases"]
        ],
    }
    size = len(json.dumps(body).encode())
    assert size < config.MAX_BODY_BYTES, f"baseline callback is {size:,} bytes"
