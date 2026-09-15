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
import os
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
from assessment_platform.schemas import (
    MAX_QUESTION_CASES_BYTES,
    QuestionCreate,
    TestCaseIn,
    TestCaseOut,
)

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

# CI is responsible for making the companion present (checks.yml checks it out),
# so there a missing companion is a failure, not a skip — otherwise the gate
# degrades to a silent pass, which is the failure mode it was written to end.
_REQUIRED = os.getenv("REQUIRE_COMPANION_REPO") == "1"
if _REQUIRED and AGENT_ROOT is None:
    raise RuntimeError(
        "REQUIRE_COMPANION_REPO=1 but the agent repo is not checked out at "
        f"{' or '.join(str(p) for p in _AGENT_CANDIDATES)} — the cross-repo parity "
        "gate would silently skip."
    )

# Only the tests that actually import the agent. The body-cap tests below read
# nothing but this repo, and must keep running on a lone checkout — a skip would
# beat their strict xfail and quietly retire the R2-001 gate.
needs_agent = pytest.mark.skipif(
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
    # `create_question` strips an explicit id and generates a slug when nothing is
    # left, so a blank id can never reach storage. Mirror that here rather than
    # storing the blank — otherwise this probe invents a divergence the API cannot
    # produce, and "fix" it by 422-ing the supported send-an-empty-id path.
    explicit_id = (body.id or "").strip()
    return Question(
        id=explicit_id or "generated-slug-1",
        org_id=1,
        title=body.title,
        prompt=body.prompt,
        constraints=body.constraints,
        time_limit_s=body.time_limit_s,
        pass_threshold=body.pass_threshold,
        required_complexity=body.required_complexity,
        example_input=body.example_input,
        example_output=body.example_output,
        difficulty=body.difficulty,
        reference_solution=body.reference_solution,
        reference_language=body.reference_language,
        duration_minutes=body.duration_minutes,
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


# Each entry is a mutation the platform must not store. S02 closed the nine that
# were `xfail`ed here when the gate was installed (R2-002): the platform now
# refuses blank prose, a zero time limit, weight <= 0, empty expected output, a
# blank case name and duplicate case names at authoring time, and the agent no
# longer refuses to GRADE over prose the candidate has already read. Nothing is
# marked any more — a new divergence fails this list on sight, which is the point.
DIVERGENCE_CASES = [
    pytest.param(_blank_constraints, id="blank_constraints"),
    pytest.param(_blank_title, id="blank_title"),
    pytest.param(_blank_prompt, id="blank_prompt"),
    pytest.param(_zero_time_limit, id="zero_time_limit"),
    pytest.param(_zero_weight, id="zero_weight"),
    pytest.param(_negative_weight, id="negative_weight"),
    pytest.param(_empty_expected, id="empty_expected"),
    pytest.param(_duplicate_case_names, id="duplicate_case_names"),
    pytest.param(_blank_case_name, id="blank_case_name"),
    # Already in parity: the platform's `Category` literal and the agent's agree.
    pytest.param(_bad_category, id="invalid_category"),
]


@needs_agent
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


@needs_agent
def test_the_baseline_question_is_accepted_by_both() -> None:
    """Guards the cases above: if the baseline itself stopped being valid, every
    parametrised case would pass for the wrong reason."""
    stored = _platform_stores(_valid_payload())
    assert stored is not None, "the platform refuses its own baseline question"
    assert _agent_refuses(stored) is None


@needs_agent
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

# The agent builds its result payload from each case's `input`, `expected` and
# `actual` (`assessment_agent/agent.py::result_to_dict`) and POSTs it to
# `POST /assessments/callback` — where the platform's own `api.py::_limit_body_size`
# 413s anything over MAX_BODY_BYTES. The agent does not retry a 4xx, so an
# oversized body loses the grade outright (R2-001). Two bounds keep that from
# happening, and both are measured below: the platform bounds what it STORES, and
# the agent excerpts what it ECHOES — needed separately, because a candidate's
# stdout is bounded only by the agent's 64 MB output cap, which no choice of
# MAX_BODY_BYTES could absorb.
def _stored_case_char_caps() -> tuple[int | None, int | None]:
    """The platform's own `max_length` on a stored test case's stdin and expected
    (None = unbounded)."""

    def cap(name: str) -> int | None:
        meta = TestCaseIn.model_fields[name].metadata
        return next((m.max_length for m in meta if hasattr(m, "max_length")), None)

    return cap("stdin"), cap("expected")


def _stored_case_count_cap() -> int | None:
    """The platform's own cap on how many cases one question may carry."""
    meta = QuestionCreate.model_fields["test_cases"].metadata
    return next((m.max_length for m in meta if hasattr(m, "max_length")), None)


def test_a_stored_question_is_size_bounded() -> None:
    """Step one, and the half that needs no agent: what the platform stores has to
    have a maximum size at all.

    Until it did, no arithmetic about the callback was even possible — a question
    could carry a 9.6 MB performance input (three dev questions did), and the
    result for it was 413'd at `api.py::_limit_body_size` and lost.
    """
    stdin_cap, expected_cap = _stored_case_char_caps()
    missing = [
        name
        for name, cap in (
            ("TestCaseIn.stdin", stdin_cap),
            ("TestCaseIn.expected", expected_cap),
            ("QuestionCreate.test_cases", _stored_case_count_cap()),
        )
        if cap is None
    ]
    assert not missing, (
        f"unbounded: {', '.join(missing)}. A stored question therefore has no size bound, "
        "so no cap on the result callback can be guaranteed (R2-001). "
        "`_limit_body_size`'s docstring already claims the schema caps bound what is "
        "stored; make that true."
    )


def test_the_largest_storable_question_fits_one_request_body() -> None:
    """R2-012: a PUT re-sends every test case, so a question that does not fit in
    one body cannot be EDITED — at the old 4 MiB cap a title change on a question
    with a large performance input was 413'd. The per-field caps and
    MAX_BODY_BYTES are therefore one decision, and this is where they meet.
    """
    assert MAX_QUESTION_CASES_BYTES < config.MAX_BODY_BYTES, (
        f"the {MAX_QUESTION_CASES_BYTES:,}-byte budget for a question's test cases is over the "
        f"{config.MAX_BODY_BYTES:,}-byte cap `_limit_body_size` enforces — so a question could "
        "be created one case at a time but never edited (R2-012)."
    )

    # The budget has to be counted in the units the body cap is counted in. The
    # per-field caps cannot do it: they count characters, and JSON spends two
    # bytes on a newline and six on a control character, so newline-separated
    # performance input encodes to far more than its length.
    escaping = [
        {"name": f"c{i}", "stdin": "1\n" * 300_000, "expected": "x",
         "category": "correctness", "weight": 1.0}
        for i in range(_stored_case_count_cap() or 25)
    ]
    assert _platform_stores({**_valid_payload(), "test_cases": escaping}) is None, (
        "a question whose cases are under every per-field cap but over the body cap in "
        "encoded bytes was accepted — it can be created and never edited (R2-012)."
    )


@needs_agent
def test_the_largest_storable_question_fits_the_callback_body_cap() -> None:
    """Step two: the worst body the agent can build for a storable question must
    fit under the cap the platform itself enforces.

    The agent's per-field excerpt cap is read from the agent, not mirrored here —
    mirroring a cross-repo constant by hand is the failure this whole file exists
    to replace. This arithmetic used to multiply by the agent's *output* cap
    (`runner._OUTPUT_LIMIT_BYTES`, 64 MB) because the payload echoed every value
    whole; S01 made it send an excerpt, so that cap no longer reaches the wire.
    """
    case_cap = _stored_case_count_cap()
    if case_cap is None:
        pytest.fail("unbounded stored question — see test_a_stored_question_is_size_bounded")

    _agent()  # puts the agent repo on sys.path
    import assessment_agent.agent as agent_module

    excerpt_cap = getattr(agent_module, "PAYLOAD_EXCERPT_BYTES", None)
    assert excerpt_cap is not None, (
        "the agent's per-field excerpt cap (agent.PAYLOAD_EXCERPT_BYTES, "
        "ASSESS_PAYLOAD_EXCERPT_KB) could not be read — it moved, and this gate can no "
        "longer measure the real body. If the agent went back to echoing whole values, "
        "multiply by runner._OUTPUT_LIMIT_BYTES instead and watch this fail."
    )

    # Per case the callback carries `input`, `expected`, `actual` and `error`
    # (`assessment_agent/agent.py::result_to_dict`), plus the execution-level
    # `compile_error` and `infra_error` — raw compiler/runtime stderr, which no
    # bound on the QUESTION reaches. Every one of them is excerpted to that cap,
    # and every one of them is counted here; a new unexcerpted free-text field is
    # the way this gate goes stale, so add it on both sides at once.
    worst_case = (case_cap * 4 + 2) * excerpt_cap
    assert worst_case < config.MAX_BODY_BYTES, (
        f"the largest storable question renders a ~{worst_case:,}-byte callback body, over "
        f"the {config.MAX_BODY_BYTES:,}-byte cap `_limit_body_size` enforces (R2-001)."
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


# --- 3. the regression the two bounds exist to prevent -------------------------


def test_a_question_with_a_full_size_performance_input_can_be_created_and_edited(
    client: Any,
) -> None:
    """R2-012, through the real routes and the real `_limit_body_size`.

    A PUT re-sends every test case, so before the caps and the body cap were
    chosen together, a question carrying a large performance input could be
    created a case at a time but a title change on it was 413'd — the interviewer
    could not correct their own question. Uses the largest input the schema now
    accepts, so raising a cap without raising the body cap fails here.
    """
    stdin_cap, expected_cap = _stored_case_char_caps()
    assert stdin_cap is not None and expected_cap is not None
    payload = _valid_payload()
    payload["id"] = "big-perf"
    payload["test_cases"][-1]["stdin"] = "9" * stdin_cap
    payload["test_cases"][-1]["expected"] = "9" * expected_cap

    assert client.post("/questions", json=payload).status_code == 201

    payload["title"] = "Renamed"
    resp = client.put("/questions/big-perf", json=payload)
    assert resp.status_code != 413, "a large question still cannot be edited (R2-012)"
    assert resp.status_code == 200, resp.text
    assert client.get("/questions/big-perf").json()["title"] == "Renamed"


@needs_agent
def test_the_worst_callback_the_agent_can_send_is_accepted(client: Any) -> None:
    """R2-001, through the real route: the biggest body the contract now permits —
    every case at the schema's limit, every echoed field at the agent's excerpt cap.

    The P0 was a 413 here. The agent does not retry a 4xx, so the reaper
    re-triggered three times and the submission ended as "error" with no stored
    reason: the grade was simply gone. The job id is unknown on purpose — this
    measures the size gate the body has to clear first, and 413 is the one status
    that must never come back.
    """
    case_cap = _stored_case_count_cap()
    if case_cap is None:
        pytest.fail("unbounded case count — see test_a_stored_question_is_size_bounded")

    _agent()  # puts the agent repo on sys.path
    import assessment_agent.agent as agent_module

    field = "9" * agent_module.PAYLOAD_EXCERPT_BYTES
    body = {
        "job_id": "no-such-job",
        "verdict": "PASS",
        "score_pct": 100.0,
        "reason": "all cases passed",
        "test_cases": [
            {
                "name": f"case_{i}",
                "category": "performance",
                "weight": 1.0,
                "status": "PASS",
                "input": field,
                "expected": field,
                "actual": field,
                "duration_s": 0.1,
                "timed_out": False,
                "error": None,
            }
            for i in range(case_cap)
        ],
    }
    assert client.post("/assessments/callback", json=body).status_code != 413, (
        f"a {len(json.dumps(body).encode()):,}-byte callback — the worst the contract allows — "
        f"is refused by the {config.MAX_BODY_BYTES:,}-byte body cap, so that grade is lost "
        "(R2-001)."
    )


def test_the_intake_caps_do_not_reach_the_response_model() -> None:
    """`TestCaseOut` inherits `TestCaseIn`, so the intake rules would be enforced on
    the way OUT too — and FastAPI validates a response model, so every question
    stored before them (nine dev cases over S01's size caps; 198 cases with empty
    expected output and every legacy zero weight, from S02's) would 500 on read
    instead of being editable back into shape. The re-declaration in `TestCaseOut`
    is what prevents that; this fails if someone tidies it away.
    """
    stdin_cap, expected_cap = _stored_case_char_caps()
    assert stdin_cap is not None and expected_cap is not None
    TestCaseOut(
        id=1,
        name="  ",  # blank (S02)
        stdin="9" * (stdin_cap + 1),
        expected="",  # empty (S02)
        weight=0.0,  # zero (S02)
    )
    TestCaseOut(id=2, name="legacy", stdin="9", expected="9" * (expected_cap + 1))


def test_refusing_an_oversized_question_does_not_echo_it_back(client: Any) -> None:
    """The size caps exist to stop a large body costing more than it should; a
    422 that serializes pydantic's `input` back turned a 13 MB rejected question
    into a 13 MB response, so the refusal cost as much as accepting it would.
    """
    cases = [
        {"name": f"c{i}", "stdin": "1\n" * 173_000, "expected": "x",
         "category": "correctness", "weight": 1.0}
        for i in range(_stored_case_count_cap() or 25)
    ]
    resp = client.post("/questions", json={**_valid_payload(), "test_cases": cases})
    assert resp.status_code == 422, resp.status_code
    assert len(resp.content) < 4096, f"{len(resp.content):,}-byte response to a rejected question"
    assert "over the" in resp.json()["detail"][0]["msg"]
