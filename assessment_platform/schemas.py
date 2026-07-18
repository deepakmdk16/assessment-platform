"""Request/response models for the API boundary (input validation + shaping).

These are the external contract. The SQLModel tables in `models.py` are the
storage layer; keeping the two separate means the API can accept nested test
cases and return a submission-plus-result view without leaking ORM internals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from .models import as_utc

Category = Literal["correctness", "performance"]
Difficulty = Literal["easy", "medium", "hard"]
QuestionStatus = Literal["active", "archived"]


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
    # Stored as a 0..1 fraction (the agent rejects anything outside (0, 1]). The
    # wizard works in whole-number percent and converts at the API boundary.
    pass_threshold: float = Field(default=0.9, gt=0, le=1)
    required_complexity: str | None = None
    example_input: str | None = None
    example_output: str | None = None
    difficulty: Difficulty | None = None
    test_cases: list[TestCaseIn] = Field(default_factory=list)


class QuestionUpdate(BaseModel):
    """Full replace of a question's mutable fields (PUT semantics)."""

    title: str
    prompt: str
    constraints: str = ""
    time_limit_s: float = 2.0
    # Stored as a 0..1 fraction (the agent rejects anything outside (0, 1]). The
    # wizard works in whole-number percent and converts at the API boundary.
    pass_threshold: float = Field(default=0.9, gt=0, le=1)
    required_complexity: str | None = None
    example_input: str | None = None
    example_output: str | None = None
    difficulty: Difficulty | None = None
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
    difficulty: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    test_cases: list[TestCaseOut]


class QuestionDraftIn(BaseModel):
    """An interviewer's brief for the AI question-authoring assistant."""

    brief: str = Field(min_length=1)
    language: str
    difficulty: str | None = None
    target_complexity: str | None = None


class QuestionDraftOut(BaseModel):
    """A drafted question, reshaped to feed the create form directly. Nothing is
    stored here — the interviewer reviews/edits, then submits via POST /questions."""

    question: QuestionCreate
    warnings: list[str] = Field(default_factory=list)
    reference_solution: str | None = None
    reference_language: str | None = None
    engine: str
    cost_usd: float | None = None


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
    email: EmailStr
    password: str = Field(min_length=1)
    name: str
    # Required only when the server sets REGISTRATION_CODE (gated sign-up).
    registration_code: str | None = None


class InterviewerOut(BaseModel):
    id: int
    email: str
    name: str


class LoginIn(BaseModel):
    # Plain str on purpose: login is a credential lookup, not a data-entry point.
    # Validating the format here would only turn a non-match (401) into a 422 and
    # could lock out any account created before EmailStr was enforced on register.
    email: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --------------------------------------------------------------------------- #
# Invites                                                                       #
# --------------------------------------------------------------------------- #


class InviteCreate(BaseModel):
    # At least one recipient is required: the link is bound to the emails listed
    # here (a candidate must identify as one of them to start), so an invite with
    # no recipients would be a link nobody could ever use.
    recipients: list[EmailStr] = Field(min_length=1)
    expires_at: datetime | None = None

    @field_validator("expires_at")
    @classmethod
    def _expiry_in_future(cls, v: datetime | None) -> datetime | None:
        # A past expiry produces an invite that 410s the instant it's opened —
        # silently, and only after every recipient has already been emailed the
        # link. Reject it at the boundary, using the same naive->UTC rule as the
        # runtime expiry check (models.as_utc) so the two never disagree.
        if v is None:
            return v
        if as_utc(v) <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return v


class InviteDeliveryOut(BaseModel):
    """Per-recipient outcome of the invite email send."""

    recipient: str
    sent: bool
    error: str | None = None


class InviteOut(BaseModel):
    token: str
    url: str
    question_id: str
    recipients: list[str]
    expires_at: datetime | None
    status: str
    # Populated only on the create response — delivery outcomes aren't stored, so
    # reads (list/revoke) return an empty list rather than a stale one.
    deliveries: list[InviteDeliveryOut] = Field(default_factory=list)


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


class InviteStatusOut(BaseModel):
    """The unauthenticated probe for `GET /invite/{token}`: says only whether the
    link is live. Deliberately carries no question data — the candidate must
    identify as an invited recipient via `POST /invite/{token}/start` first, so
    holding the link alone never reveals the problem."""

    status: str


class CandidateStartIn(BaseModel):
    candidate_email: EmailStr


class InvitePublicOut(BaseModel):
    question: CandidateQuestionView
    languages: list[str]


class CandidateSubmitIn(BaseModel):
    candidate_name: str
    candidate_email: EmailStr
    language: str
    code: str = Field(min_length=1)


class CandidateSubmitOut(BaseModel):
    submission_id: str
    status: str


class CandidateRunIn(BaseModel):
    """Run the candidate's code against input they typed themselves."""

    candidate_email: EmailStr
    language: str
    code: str = Field(min_length=1)
    stdin: str = ""


class CandidateRunOut(BaseModel):
    """What the program did. Safe to show: it's the candidate's own code fed
    their own input, so nothing here derives from the question's test cases."""

    stdout: str
    stderr: str | None = None
    duration_s: float
    timed_out: bool
    compile_error: str | None = None


class CandidateRunTestsIn(BaseModel):
    candidate_email: EmailStr
    language: str
    code: str = Field(min_length=1)


class CandidateTestOutcomeOut(BaseModel):
    """One test case as the CANDIDATE is allowed to see it.

    Pass/fail and timing — nothing else. No stdin, no expected, no actual, and
    no case *name*: a name like "handles_duplicates" is itself a hint about the
    answer key. Cases are identified positionally ("Test 1"), like HackerRank.
    """

    index: int
    category: Category
    status: str  # "PASS" | "FAIL" | "TLE"
    duration_s: float


class CandidateRunTestsOut(BaseModel):
    total: int
    passed: int
    compile_error: str | None = None
    test_cases: list[CandidateTestOutcomeOut] = Field(default_factory=list)


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
