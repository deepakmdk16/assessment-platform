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
    # Workspace-level default branding (A12): pre-fills a new assessment's
    # org_name/logo_url so the interviewer sets it once instead of per assessment.
    # Both optional; a prefill only, never applied retroactively — each Assessment
    # still stores its own snapshot. logo_url is a URL reference, never base64.
    default_org_name: str | None = None
    default_logo_url: str | None = None
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
    # Membership in a variant set (per-candidate unique variants). When set, this
    # question is one interchangeable sibling of a `VariantSet`; `variant_label`
    # is its short display tag within the set (A/B/C…). Both null for an ordinary
    # standalone question. The FK does not cascade from the set side — deleting a
    # set leaves its questions (they may have submissions, the record of truth).
    variant_set_id: str | None = Field(default=None, foreign_key="variantset.id", index=True)
    variant_label: str | None = None
    # The AI-drafted reference solution (and the language it's written in), kept so
    # the answer key survives past draft time — shown to the interviewer on the
    # question and submission pages. Null for hand-authored questions.
    reference_solution: str | None = None
    reference_language: str | None = None
    # Assessment time budget in minutes. None = untimed (indefinite) — the default,
    # so questions authored before timing existed stay untimed. The candidate
    # countdown and the server-enforced submit deadline both key off this.
    duration_minutes: int | None = None
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


class VariantSet(SQLModel, table=True):
    """A group of interchangeable question variants drafted from one brief.

    Per-candidate unique variants: hand different candidates a different-but-
    equivalent sibling so a leaked question is worthless. The members are ordinary
    `Question` rows tagged with `variant_set_id` (a variant *is* a question, so it
    reuses all question infrastructure — test cases, preview, grading, invites).
    This row keeps the shared authoring inputs (brief/difficulty/…) so the set can
    be re-drafted or extended later. Deleting a set does NOT delete its questions
    (they may carry submissions); it detaches them.
    """

    id: str = Field(primary_key=True)  # short slug, like Question.id
    owner_id: int = Field(foreign_key="interviewer.id", index=True)
    title: str
    brief: str
    language: str
    difficulty: str | None = None
    target_complexity: str | None = None
    status: str = Field(default="active", index=True)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()

    variants: list["Question"] = Relationship(
        sa_relationship_kwargs={"order_by": "Question.variant_label"},
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


class Assessment(SQLModel, table=True):
    """A named, ordered set of questions handed to a candidate as one sitting.

    First-class so it can be reused across invites. Owns the **total** time budget
    (the per-assessment timer, T4): `duration_minutes` is None = untimed, else the
    whole sitting's budget, which the candidate spends across its questions.
    """

    id: str = Field(primary_key=True)  # short slug, like Question.id
    owner_id: int = Field(foreign_key="interviewer.id", index=True)
    title: str
    duration_minutes: int | None = None  # None = untimed; per-assessment total
    # Per-assessment branding (A12): shown on the candidate IDE header as
    # "{logo} {org_name} — {title}". Both optional; None = unbranded, falls back
    # to the generic "Coding assessment" header. logo_url is an asset/URL
    # reference (e.g. an externally-hosted image), never base64 in the row.
    org_name: str | None = None
    logo_url: str | None = None
    # Integrity monitoring (I1) for every sitting of this assessment: fullscreen
    # enforced, outside pastes blocked, focus/devtools signals recorded. Defaults
    # ON so the common case is protected without a decision; an interviewer can
    # turn it off for a deliberately relaxed sitting (accessibility needs, a
    # take-home). A legacy single-question ("Quick screen") invite has no
    # Assessment row to read this from and is always monitored.
    proctored: bool = True
    status: str = Field(default="active", index=True)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()

    # The ordered questions (by AssessmentQuestion.position). Deleting an
    # assessment drops its membership rows, never the shared questions themselves.
    questions: list["AssessmentQuestion"] = Relationship(
        back_populates="assessment",
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "order_by": "AssessmentQuestion.position",
        },
    )
    invites: list["Invite"] = Relationship(back_populates="assessment")


class AssessmentQuestion(SQLModel, table=True):
    """One slot in an assessment, with its display order. A slot is EITHER a fixed
    question (`question_id`) OR a variant-set pool (`variant_set_id`, VS2) — exactly
    one is set. A set-slot resolves to a concrete variant per candidate at start
    time (see `CandidateSlotVariant`); a fixed slot is the same question for
    everyone. A question/set may belong to many assessments (they are shared), so
    neither FK cascades.

    `question_id` is nullable because a set-slot carries no fixed question. The
    unique key stays on `(assessment_id, question_id)` — NULLs compare distinct, so
    it still forbids the same question twice while allowing many set-slots; a
    duplicate variant set is caught in `_membership_rows` instead."""

    __table_args__ = (
        UniqueConstraint("assessment_id", "question_id", name="uq_assessment_question"),
    )

    id: int | None = Field(default=None, primary_key=True)
    assessment_id: str = Field(foreign_key="assessment.id", index=True)
    question_id: str | None = Field(default=None, foreign_key="question.id", index=True)
    variant_set_id: str | None = Field(default=None, foreign_key="variantset.id", index=True)
    position: int = 0
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()

    assessment: Assessment | None = Relationship(back_populates="questions")
    question: Question | None = Relationship()


class Invite(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    token: str = Field(unique=True, index=True)  # url-safe random, shared with candidate
    # An invite points at EITHER a single legacy question or (T4) an assessment.
    # question_id is nullable now so an assessment-backed invite needs no question;
    # exactly one of the two is set. Legacy single-question invites keep question_id.
    question_id: str | None = Field(default=None, foreign_key="question.id", index=True)
    assessment_id: str | None = Field(default=None, foreign_key="assessment.id", index=True)
    # When the invite handed the candidate a variant from a set, this records which
    # set it came from; `question_id` still holds the *assigned* variant, so the
    # whole candidate flow resolves it exactly like a single-question invite. Only
    # the interviewer-side assignment UI (which variant went to whom, round-robin)
    # needs this provenance. Null for ordinary question/assessment invites.
    variant_set_id: str | None = Field(default=None, foreign_key="variantset.id", index=True)
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
    assessment: Assessment | None = Relationship(back_populates="invites")


class CandidateAttempt(SQLModel, table=True):
    """When a candidate first opened a given invite — the server-authoritative
    clock start for a timed assessment.

    Stamped once on the first `/start` for an (invite, candidate_email) pair and
    never moved, so the deadline (started_at + question.duration_minutes) survives
    a reload or a device switch and can't be reset by re-opening the link. Only
    the timer needs this; the attempt of record is still the `Submission`.

    `candidate_name` (A10) is anchored the same way: stamped once here at first
    `/start`, then used for every `Submission.candidate` across the sitting,
    instead of trusting the display name resent on each individual `/submit` —
    a name typo re-entered after a reload used to fork one candidate's sitting
    into inconsistently-labeled rows. Nullable so a pre-existing attempt row
    (created before this column existed) degrades gracefully rather than
    breaking; `candidate_submit` falls back to the current request's name only
    in that case.
    """

    __table_args__ = (
        UniqueConstraint("invite_id", "candidate_email", name="uq_attempt_invite_candidate"),
    )

    id: int | None = Field(default=None, primary_key=True)
    invite_id: int = Field(foreign_key="invite.id", index=True)
    candidate_email: str = Field(index=True)
    candidate_name: str | None = None
    started_at: datetime = Field(default_factory=_utcnow)
    created_at: datetime = _created_at()
    updated_at: datetime = _updated_at()


class CandidateSlotVariant(SQLModel, table=True):
    """The concrete variant a candidate was assigned for a variant-set slot of an
    assessment (VS2), frozen on first resolution and stable thereafter.

    A set-slot resolves per candidate — round-robin across the assessment's
    candidates so the pool stays evenly used — and this row records the choice so
    it can't drift across reloads, resubmissions, or the interviewer's results
    view. Keyed by `(invite_id, candidate_email, assessment_question_id)`, NOT by
    `CandidateAttempt`: resolving a variant must never stamp the timer, and the
    interviewer results path reads these without ever creating an attempt. The
    unique key makes the get-or-create race-safe, exactly like `CandidateAttempt`.
    `question_id` holds the assigned variant, so the whole candidate flow (view /
    run / submit / results) treats a set-slot exactly like a fixed question."""

    __table_args__ = (
        UniqueConstraint(
            "invite_id",
            "candidate_email",
            "assessment_question_id",
            name="uq_candidate_slot_variant",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    invite_id: int = Field(foreign_key="invite.id", index=True)
    candidate_email: str = Field(index=True)
    assessment_question_id: int = Field(foreign_key="assessmentquestion.id", index=True)
    question_id: str = Field(foreign_key="question.id", index=True)
    created_at: datetime = _created_at()


class IntegrityEvent(SQLModel, table=True):
    """One recorded integrity signal from a candidate's browser (I1 stage 1).

    Keyed like `CandidateAttempt` — by `(invite_id, candidate_email)` — because a
    signal belongs to the *sitting*, not to one submission: a tab switch happens
    between questions as easily as during one. `question_id` records which
    question was open when it fired (null for signals raised before/outside a
    question), so the interviewer's timeline can say where it happened without
    the events being owned per question.

    **Client-reported and therefore untrusted.** A candidate who disables JS or
    edits the page simply produces no events, so absence of signals is not
    evidence of a clean sitting — this is corroboration for a human reading a
    submission, never an input to the grade (the agent owns the verdict).
    `offset_ms` is the client's own ms-since-start; the write path clamps it to
    the server-observed elapsed window so a forged value can't place an event
    outside the sitting. `created_at` is the server's own receive time and is the
    only timestamp here that isn't the client's word.
    """

    id: int | None = Field(default=None, primary_key=True)
    invite_id: int = Field(foreign_key="invite.id", index=True)
    candidate_email: str = Field(index=True)
    question_id: str | None = Field(default=None, foreign_key="question.id", index=True)
    # See schemas.IntegrityEventKind for the allowed values + what each means.
    kind: str = Field(index=True)
    # Ms from this candidate's attempt start (clamped server-side).
    offset_ms: int = 0
    # How long the candidate was away / out of fullscreen, when the signal has a
    # duration; null for instantaneous ones (a paste, devtools opening).
    duration_ms: int | None = None
    # Characters pasted, for the paste signals; null otherwise.
    size: int | None = None
    # Whether the client actually prevented the action (an outside paste) rather
    # than only recording it. Recorded because the enforcement is best-effort:
    # a signal that fired without blocking still matters to the reader.
    blocked: bool = False
    created_at: datetime = _created_at()


class Submission(SQLModel, table=True):
    # One attempt per candidate per invite PER QUESTION, enforced by the DATABASE.
    # (T4: an assessment invite carries several questions, so the candidate gets one
    # attempt at each — the constraint gained `question_id`.) The pre-insert check in
    # `candidate_submit` is a SELECT followed by an INSERT, so two concurrent submits
    # both pass it and both write — the "one attempt" rule was advisory until this
    # constraint existed. NULLs compare as distinct in SQL (both SQLite and Postgres),
    # so the interviewer's direct POST /submissions path — which has no invite_id or
    # candidate_email — stays unconstrained, which is the intent: not a candidate
    # attempt. For a legacy single-question invite the extra column is constant, so
    # per-(invite,candidate,question) collapses back to the old per-(invite,candidate).
    __table_args__ = (
        UniqueConstraint(
            "invite_id",
            "candidate_email",
            "question_id",
            name="uq_submission_invite_candidate_question",
        ),
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
    # True when this submission arrived after the timed sitting's window closed
    # (past deadline + grace). A candidate's work is recorded and graded either
    # way — the timer no longer discards it — but a late submit is flagged so the
    # interviewer can see it came in after time and weigh it accordingly. Always
    # False for an untimed sitting or a submit within the window.
    late: bool = False
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
