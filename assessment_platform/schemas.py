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


# --------------------------------------------------------------------------- #
# Auth                                                                          #
# --------------------------------------------------------------------------- #


class RegisterIn(BaseModel):
    email: str
    password: str = Field(min_length=1)
    name: str
    # Required only when the server sets REGISTRATION_CODE (gated sign-up).
    registration_code: str | None = None


class InterviewerOut(BaseModel):
    id: int
    email: str
    name: str


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --------------------------------------------------------------------------- #
# Invites                                                                       #
# --------------------------------------------------------------------------- #


class InviteCreate(BaseModel):
    recipients: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class InviteOut(BaseModel):
    token: str
    url: str
    question_id: str
    recipients: list[str]
    expires_at: datetime | None
    status: str


# --------------------------------------------------------------------------- #
# Candidate (public, token-gated) — MUST NOT expose test cases / expected output #
# --------------------------------------------------------------------------- #


class CandidateQuestionView(BaseModel):
    """The candidate-facing question: prompt/constraints/public example only.
    Deliberately omits test_cases and any expected outputs."""

    title: str
    prompt: str
    constraints: str
    example_input: str | None
    example_output: str | None
    time_limit_s: float


class InvitePublicOut(BaseModel):
    question: CandidateQuestionView
    languages: list[str]


class CandidateSubmitIn(BaseModel):
    candidate_name: str
    candidate_email: str
    language: str
    code: str = Field(min_length=1)


class CandidateSubmitOut(BaseModel):
    submission_id: str
    status: str


# --------------------------------------------------------------------------- #
# Dashboard                                                                     #
# --------------------------------------------------------------------------- #


class DashboardSubmissionOut(BaseModel):
    submission_id: str
    candidate_name: str
    candidate_email: str | None
    language: str
    status: str
    verdict: str | None = None
    score_pct: float | None = None
    created_at: datetime
