"""SQLModel tables — the platform's durable state (system of record).

The platform stores questions (with their expected answers / test cases),
candidate submissions, and the assessment results the agent returns. It never
computes or overrides a verdict/score itself: `AssessmentResult` is a faithful
record of what the agent (the deterministic grader) decided, with the agent's
entire callback payload kept verbatim in `full_result`.
"""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Interviewer(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(unique=True, index=True)
    password_hash: str
    name: str
    created_at: datetime = Field(default_factory=_utcnow)


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
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    test_cases: list["QuestionTestCase"] = Relationship(
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

    question: Question | None = Relationship(back_populates="test_cases")


class Invite(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)  # url-safe random, shared with candidate
    question_id: str = Field(foreign_key="question.id", index=True)
    created_by: int = Field(foreign_key="interviewer.id", index=True)
    recipients: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    expires_at: datetime | None = None
    status: str = "active"
    created_at: datetime = Field(default_factory=_utcnow)


class Submission(SQLModel, table=True):
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
    created_at: datetime = Field(default_factory=_utcnow)


class AssessmentResult(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    submission_id: str = Field(foreign_key="submission.id", unique=True, index=True)
    verdict: str  # "PASS" | "FAIL" | "ERROR"
    score_pct: float
    reason: str
    # The agent's entire callback payload, stored verbatim (test cases, quality, etc.).
    full_result: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    received_at: datetime = Field(default_factory=_utcnow)
