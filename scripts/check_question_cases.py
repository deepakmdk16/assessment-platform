#!/usr/bin/env python3
"""Offline audit: flag stored questions that would fail the agent's grade-time floor.

Tightening a shared invariant (the F4 correctness-case floor, 3 -> 4) silently
invalidated questions already in the DB: a candidate submitting one now eats a
502 because the agent refuses to grade it, and the candidate can't fix the
interviewer's question (STATUS A1/A2). This is the "flag early" half — run it at
deploy time to see which stored questions violate the floor *before* a candidate
hits it.

Runs fully OFFLINE — it only reads the database (no agent, no network, no LLM).
It targets whatever `DATABASE_URL` points at (defaults to the dev DB), so:

    DATABASE_URL=sqlite:///./dev.db uv run python scripts/check_question_cases.py

Exit 0 = every question satisfies the floor; exit 1 = offenders were listed.
"""

from __future__ import annotations

import sys

from sqlmodel import Session, select

from assessment_platform.db import engine
from assessment_platform.models import Question
from assessment_platform.question_rules import case_floor_violations


def find_offenders(session: Session) -> list[tuple[str, list[str]]]:
    """Return (question_id, [reasons]) for every question that fails the floor."""
    offenders: list[tuple[str, list[str]]] = []
    for q in session.exec(select(Question)).all():
        problems = case_floor_violations([tc.category for tc in q.test_cases])
        if problems:
            offenders.append((q.id, problems))
    return offenders


def main() -> int:
    with Session(engine) as session:
        offenders = find_offenders(session)
    if not offenders:
        print("OK: every stored question satisfies the case floor.")
        return 0
    print(f"FAIL: {len(offenders)} question(s) would fail grading:")
    for qid, problems in offenders:
        print(f"  - {qid}: {'; '.join(problems)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
