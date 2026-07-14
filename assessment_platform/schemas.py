"""Request/response models for the API boundary (input validation + shaping).

These are the external contract. The SQLModel tables in `models.py` are the
storage layer; keeping the two separate means the API can accept nested test
cases and return a submission-plus-result view without leaking ORM internals.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Category = Literal["correctness", "performance"]


class TestCaseIn(BaseModel):
    name: str
    stdin: str
    expected: str
    category: Category = "correctness"
    weight: float = 1.0


class TestCaseOut(TestCaseIn):
    id: int


class QuestionCreate(BaseModel):
    id: str
    title: str
    prompt: str
    constraints: str = ""
    time_limit_s: float = 2.0
    pass_threshold: float = 0.9
    required_complexity: str | None = None
    example_input: str | None = None
    example_output: str | None = None
    test_cases: list[TestCaseIn] = Field(default_factory=list)


class QuestionUpdate(BaseModel):
    """Full replace of a question's mutable fields (PUT semantics)."""

    title: str
    prompt: str
    constraints: str = ""
    time_limit_s: float = 2.0
    pass_threshold: float = 0.9
    required_complexity: str | None = None
    example_input: str | None = None
    example_output: str | None = None
    test_cases: list[TestCaseIn] = Field(default_factory=list)


class QuestionOut(BaseModel):
    id: str
    title: str
    prompt: str
    constraints: str
    time_limit_s: float
    pass_threshold: float
    required_complexity: str | None
    example_input: str | None
    example_output: str | None
    created_at: datetime
    updated_at: datetime
    test_cases: list[TestCaseOut]


class SubmissionCreate(BaseModel):
    question_id: str
    candidate: str
    language: str
    code: str = Field(min_length=1)


class ResultOut(BaseModel):
    verdict: str
    score_pct: float
    reason: str
    full_result: dict[str, Any]
    received_at: datetime


class SubmissionOut(BaseModel):
    id: str
    question_id: str
    candidate: str
    language: str
    code: str
    status: str
    agent_job_id: str | None
    created_at: datetime
    result: ResultOut | None = None
