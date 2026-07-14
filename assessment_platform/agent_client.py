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

from .config import AGENT_BASE_URL, AGENT_TIMEOUT_S
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
    resp = httpx.post(f"{base_url}/assessments", json=body, timeout=AGENT_TIMEOUT_S)
    resp.raise_for_status()
    return resp.json()["job_id"]
