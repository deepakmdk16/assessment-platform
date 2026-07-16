"""Outbound integration with the (stateless) Assessment Agent.

The only place that talks to the agent; tests mock these functions to run
offline. Four calls, of which exactly one grades:

- `trigger_assessment` — the grading job (async: the agent 202s, then calls back).
- `draft_question`     — the authoring assistant (synchronous, LLM-backed).
- `run_code`           — execute once against the candidate's own stdin.
- `run_tests`          — run the question's suite; pass/fail per case only.

The last two are the candidate's editor buttons: synchronous, non-grading, and
they store nothing on either side.

Request shapes match the agent's pydantic models exactly (the question dict
carries a nested `example: {input, output}`).
"""

from __future__ import annotations

import httpx

from . import config
from .config import AGENT_BASE_URL, AGENT_DRAFT_TIMEOUT_S, AGENT_RUN_TIMEOUT_S, AGENT_TIMEOUT_S
from .models import Question, Submission


def _auth_headers() -> dict[str, str]:
    """Our shared secret, sent only when configured (dev/tests run without)."""
    if config.ASSESS_API_TOKEN:
        return {config.AUTH_HEADER: config.ASSESS_API_TOKEN}
    return {}


def build_question_payload(question: Question) -> dict:
    """Shape a stored Question into the inline `question` dict the agent expects."""
    example = None
    if question.example_input is not None or question.example_output is not None:
        example = {
            "input": question.example_input or "",
            "output": question.example_output or "",
        }
    return {
        "id": question.id,
        "title": question.title,
        "prompt": question.prompt,
        "constraints": question.constraints,
        "test_cases": [
            {
                "name": tc.name,
                "stdin": tc.stdin,
                "expected": tc.expected,
                "category": tc.category,
                "weight": tc.weight,
            }
            for tc in question.test_cases
        ],
        "time_limit_s": question.time_limit_s,
        "pass_threshold": question.pass_threshold,
        "example": example,
        "required_complexity": question.required_complexity,
    }


def draft_question(
    brief: str,
    language: str,
    difficulty: str | None = None,
    target_complexity: str | None = None,
    base_url: str = AGENT_BASE_URL,
) -> dict:
    """Ask the agent to draft a validated question from a brief; return its payload.

    Stateless on both sides: the agent stores nothing and we don't persist here —
    the caller shows the draft for human approval, then stores via the normal
    create path. Raises on transport/HTTP error (the route maps the agent's
    503/422/400 back to the interviewer). This is the only place that talks to the
    agent's draft endpoint; tests mock it here to run offline.
    """
    body = {
        "brief": brief,
        "language": language,
        "difficulty": difficulty,
        "target_complexity": target_complexity,
    }
    resp = httpx.post(
        f"{base_url}/questions/draft",
        json=body,
        headers=_auth_headers(),
        timeout=AGENT_DRAFT_TIMEOUT_S,
    )
    resp.raise_for_status()
    result: dict = resp.json()
    return result


def run_code(
    code: str,
    language: str,
    stdin: str,
    base_url: str = AGENT_BASE_URL,
) -> dict:
    """Execute `code` once against `stdin` on the agent; return what it printed.

    The candidate's "Run" button. Synchronous and non-grading: no verdict, no
    LLM, nothing stored on either side. Raises on transport/HTTP error.
    """
    body = {"code": code, "language": language, "stdin": stdin}
    resp = httpx.post(
        f"{base_url}/run", json=body, headers=_auth_headers(), timeout=AGENT_RUN_TIMEOUT_S
    )
    resp.raise_for_status()
    result: dict = resp.json()
    return result


def run_tests(
    question: Question,
    code: str,
    language: str,
    base_url: str = AGENT_BASE_URL,
) -> dict:
    """Run `code` against the question's tests; return pass/fail per case.

    The candidate's "Run against test cases" rehearsal. The agent returns no
    input/expected/actual on this path, and the caller redacts further before
    it reaches the candidate. Raises on transport/HTTP error.
    """
    body = {
        "question": build_question_payload(question),
        "code": code,
        "language": language,
    }
    resp = httpx.post(
        f"{base_url}/run/tests", json=body, headers=_auth_headers(), timeout=AGENT_RUN_TIMEOUT_S
    )
    resp.raise_for_status()
    result: dict = resp.json()
    return result


def trigger_assessment(
    question: Question,
    submission: Submission,
    callback_url: str,
    base_url: str = AGENT_BASE_URL,
) -> str:
    """POST the job to the agent and return its job_id. Raises on transport/HTTP error."""
    body = {
        "question": build_question_payload(question),
        "code": submission.code,
        "language": submission.language,
        "candidate": submission.candidate,
        "callback_url": callback_url,
        "email_to": None,
    }
    resp = httpx.post(
        f"{base_url}/assessments", json=body, headers=_auth_headers(), timeout=AGENT_TIMEOUT_S
    )
    resp.raise_for_status()
    return resp.json()["job_id"]
