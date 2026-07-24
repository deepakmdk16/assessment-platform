"""The question test-case invariants, enforced at authoring time.

The agent (the grader) enforces a hard floor on every question it grades: at
least `MIN_CORRECTNESS_CASES` correctness cases and at least one performance
case (`../AssesmentAgent/assessment_agent/questions.py::validate_question`).
The platform must not let an interviewer *save* a question that would later
fail that floor — otherwise the candidate, who can't fix the question, eats a
502 at submit time (STATUS A1).

`MIN_CORRECTNESS_CASES` mirrors the agent's constant of the same name; keep the
two in step. This one function is the single source of truth for both the
create/update routes and the offline `scripts/check_question_cases.py` audit.
"""

from __future__ import annotations

from collections.abc import Sequence

# Mirror of the agent's `MIN_CORRECTNESS_CASES` (F4 floor). Keep identical.
MIN_CORRECTNESS_CASES = 4


def case_floor_violations(categories: Sequence[str]) -> list[str]:
    """Return human-readable reasons the case set fails the floor (empty = ok).

    Takes just the categories so it works off either API `TestCaseIn`s or stored
    `QuestionTestCase` rows.
    """
    problems: list[str] = []
    if not any(c == "performance" for c in categories):
        problems.append("needs at least one 'performance' test case")
    n_correctness = sum(1 for c in categories if c == "correctness")
    if n_correctness < MIN_CORRECTNESS_CASES:
        problems.append(
            f"needs at least {MIN_CORRECTNESS_CASES} 'correctness' test cases "
            f"(has {n_correctness})"
        )
    return problems
