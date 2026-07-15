"""Outbound integration with the (stateless) Assessment Agent.

Builds the agent's `POST /assessments` request from a stored question + a
submission, triggers the job, and returns the agent's `job_id`. This is the only
place that talks to the agent; tests mock `httpx.post` here to run offline.

The request shape matches the agent's `AssessmentRequest` exactly (question dict
with a nested `example: {input, output}`, plus code/language/candidate/
callback_url/email_to).
"""

from __future__ import annotations

import httpx

from . import config
from .config import AGENT_BASE_URL, AGENT_DRAFT_TIMEOUT_S, AGENT_TIMEOUT_S
from .models import Question, Submission


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
    headers = {}
    if config.ASSESS_API_TOKEN:
        headers[config.AUTH_HEADER] = config.ASSESS_API_TOKEN
    resp = httpx.post(
        f"{base_url}/questions/draft", json=body, headers=headers, timeout=AGENT_DRAFT_TIMEOUT_S
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
    # Send our shared secret only when configured (backward-compatible with dev/tests).
    headers = {}
    if config.ASSESS_API_TOKEN:
        headers[config.AUTH_HEADER] = config.ASSESS_API_TOKEN
    resp = httpx.post(f"{base_url}/assessments", json=body, headers=headers, timeout=AGENT_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()["job_id"]
