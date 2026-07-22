"""SQLModel tables — the platform's durable state (system of record).

The platform stores questions (with their expected answers / test cases),
candidate submissions, and the assessment results the agent returns. It never
computes or overrides a verdict/score itself: `AssessmentResult` is a faithful
record of what the agent (the deterministic grader) decided, with the agent's
entire callback payload kept verbatim in `full_result`.

Every table carries timezone-aware UTC `created_at` and `updated_at`; the latter
auto-bumps on any UPDATE via SQLAlchemy `onupdate` (see `_updated_at`).
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime) -> datetime:
    """Interpret a naive datetime as UTC; leave aware ones unchanged.

    Datetimes stored in SQLite come back naive, and clients may post naive ISO
    strings; both the invite-expiry validator and the runtime expiry check need
    the same rule so they never disagree about whether an invite has expired.
    """
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _created_at() -> Any:
    return Field(default_factory=_utcnow)


def _updated_at() -> Any:
    # Auto-bumps to now on every UPDATE, so no write path can forget it.
    return Field(default_factory=_utcnow, sa_column_kwargs={"onupdate": _utcnow})


class Interviewer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    name: str
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()


class Question(SQLModel, table=True):
    id: str = Field(primary_key=True)
    owner_id: int = Field(foreign_key="interviewer.id", index=True)
    title: str
    prompt: str
    constraints: str
    time_limit_s: float = 2.0
    pass_threshold: float = 0.9
    required_complexity: str | None = None
    example_input: str | None = None
    example_output: str | None = None
    # Interviewer-facing metadata. difficulty is an optional label (easy/medium/
    # hard); status retires a question without deleting it — "archived" hides it
    # from the dashboard while keeping its submissions (which are the record).
    difficulty: str | None = None
    # The AI-drafted reference solution (and the language it's written in), kept so
    # the answer key survives past draft time — shown to the interviewer on the
    # question and submission pages. Null for hand-authored questions.
    reference_solution: str | None = None
    reference_language: str | None = None
    status: str = Field(default="active", index=True)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()

    test_cases: list["QuestionTestCase"] = Relationship(
        back_populates="question",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    # An invite is just a link to this question — it is meaningless once the
    # question is gone, so it goes with it. Submissions are deliberately NOT
    # cascaded: they are the system of record, so a question that has any is
    # refused deletion instead (see `delete_question`).
    invites: list["Invite"] = Relationship(
        back_populates="question",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class QuestionTestCase(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    question_id: str = Field(foreign_key="question.id", index=True)
    name: str
    stdin: str
    expected: str
    category: str = "correctness"  # "correctness" | "performance"
    weight: float = 1.0
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()

    question: Question | None = Relationship(back_populates="test_cases")


class Invite(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)  # url-safe random, shared with candidate
    question_id: str = Field(foreign_key="question.id", index=True)
    created_by: int = Field(foreign_key="interviewer.id", index=True)
    recipients: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Per-recipient send outcome captured at creation, so who-was-emailed is an
    # audit trail rather than a value that vanishes with the create response. Each
    # entry is {recipient, sent, error}. See schemas.InviteDeliveryOut.
    deliveries: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
    expires_at: datetime | None = None
    status: str = "active"
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()

    question: Question | None = Relationship(back_populates="invites")


class Submission(SQLModel, table=True):
    # One attempt per candidate per invite, enforced by the DATABASE. The
    # pre-insert check in `candidate_submit` is a SELECT followed by an INSERT, so
    # two concurrent submits both pass it and both write — the "one attempt" rule
    # was advisory until this constraint existed. NULLs compare as distinct in SQL
    # (both SQLite and Postgres), so the interviewer's direct POST /submissions
    # path — which has no invite_id or candidate_email — stays unconstrained, which
    # is the intent: it is not a candidate attempt.
    __table_args__ = (
        UniqueConstraint("invite_id", "candidate_email", name="uq_submission_invite_candidate"),
    )

    id: str = Field(primary_key=True)  # uuid hex, assigned in the route
    question_id: str = Field(foreign_key="question.id", index=True)
    # Set when the submission came in through a candidate invite link (nullable so
    # the direct POST /submissions path still works without an invite).
    invite_id: int | None = Field(default=None, foreign_key="invite.id", index=True)
    candidate: str  # candidate display name
    candidate_email: str | None = None
    language: str
    code: str
    status: str = "pending"  # "pending" | "running" | "done" | "error"
    agent_job_id: str | None = Field(default=None, index=True)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()


class AssessmentResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    submission_id: str = Field(foreign_key="submission.id", unique=True, index=True)
    verdict: str  # "PASS" | "FAIL" | "ERROR"
    score_pct: float
    reason: str
    # The agent's entire callback payload, stored verbatim (test cases, quality, etc.).
    full_result: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # `received_at` is the domain event (when the agent's callback arrived);
    # created_at/updated_at are the uniform row-metadata timestamps.
    received_at: datetime = Field(default_factory=_utcnow)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()
