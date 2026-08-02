"""Request/response models for the API boundary (input validation + shaping).

These are the external contract. The SQLModel tables in `models.py` are the
storage layer; keeping the two separate means the API can accept nested test
cases and return a submission-plus-result view without leaking ORM internals.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from .models import as_utc

Category = Literal["correctness", "performance"]
Difficulty = Literal["easy", "medium", "hard"]
QuestionStatus = Literal["active", "archived"]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """A paginated slice of a collection. `total` is the full count matching the
    query (before limit/offset), so a client can render "showing X-Y of Z" and a
    pager without a second request. Envelope over a bare array so the metadata
    travels with the data — no custom headers to expose through CORS."""

    items: list[T]
    total: int
    limit: int
    offset: int


class TestCaseIn(BaseModel):
    name: str
    stdin: str
    expected: str
    category: Category = "correctness"
    weight: float = 1.0


class TestCaseOut(TestCaseIn):
    id: int


class QuestionCreate(BaseModel):
    # Optional: the UI omits it and the server generates slug(title)+suffix. The
    # agent/CLI authoring path may still supply an explicit id, which is honored.
    id: str | None = None
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
    # The AI-drafted reference solution, carried through from a draft so it can be
    # persisted. Null (and absent from the payload) for hand-authored questions.
    reference_solution: str | None = None
    reference_language: str | None = None
    # Assessment time budget in minutes; None = untimed. Positive when set.
    duration_minutes: int | None = Field(default=None, gt=0)
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
    reference_solution: str | None = None
    reference_language: str | None = None
    duration_minutes: int | None = Field(default=None, gt=0)
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
    reference_solution: str | None
    reference_language: str | None
    duration_minutes: int | None
    status: str
    created_at: datetime
    updated_at: datetime
    test_cases: list[TestCaseOut]


class AssessmentSlotIn(BaseModel):
    """One slot of an assessment: EITHER a fixed question OR a variant-set pool
    (VS2), exactly one set. A set-slot hands each candidate a different variant
    at start time; a question-slot is the same question for everyone."""

    question_id: str | None = None
    variant_set_id: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> AssessmentSlotIn:
        if bool(self.question_id) == bool(self.variant_set_id):
            raise ValueError(
                "each slot must set exactly one of question_id / variant_set_id"
            )
        return self


class _AssessmentSlots(BaseModel):
    """Shared slot-input handling for create/update. A caller supplies EITHER the
    legacy flat `question_ids` (all fixed slots — the pre-VS2 shape, still accepted
    so existing clients need no change) OR the ordered `slots` list (mixed fixed
    questions + variant sets). Exactly one, at least one slot."""

    question_ids: list[str] | None = None
    slots: list[AssessmentSlotIn] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> _AssessmentSlots:
        if self.question_ids is not None and self.slots is not None:
            raise ValueError("provide either question_ids or slots, not both")
        if not self.ordered_slots():
            raise ValueError("an assessment needs at least one question or variant-set slot")
        return self

    def ordered_slots(self) -> list[AssessmentSlotIn]:
        if self.slots is not None:
            return self.slots
        return [AssessmentSlotIn(question_id=qid) for qid in (self.question_ids or [])]


class AssessmentCreate(_AssessmentSlots):
    """An interviewer's assessment: a named, ordered set of question / variant-set
    slots with an optional total time budget (T4, VS2)."""

    # Optional: the UI omits it and the server generates slug(title)+suffix.
    id: str | None = None
    title: str
    duration_minutes: int | None = Field(default=None, gt=0)  # None = untimed total
    # Per-assessment branding (A12): shown on the candidate IDE header. Both
    # optional; logo_url is a URL reference, never base64.
    org_name: str | None = None
    logo_url: str | None = None
    # Integrity monitoring (I1). Defaults on; a caller that omits it gets a
    # monitored sitting, which is what the pre-I1 clients should now do.
    proctored: bool = True


class AssessmentUpdate(_AssessmentSlots):
    """Full replace of an assessment's mutable fields (PUT semantics)."""

    title: str
    duration_minutes: int | None = Field(default=None, gt=0)
    org_name: str | None = None
    logo_url: str | None = None
    proctored: bool = True


class AssessmentQuestionOut(BaseModel):
    """One slot of an assessment. A fixed slot carries `question_id`; a variant-set
    slot (VS2) carries `variant_set_id` and `variant_count` instead. `title` is the
    question title or the set title, denormalized so the builder needs no 2nd fetch."""

    question_id: str | None = None
    variant_set_id: str | None = None
    variant_count: int | None = None
    position: int
    title: str


class AssessmentOut(BaseModel):
    id: str
    title: str
    duration_minutes: int | None
    org_name: str | None
    logo_url: str | None
    proctored: bool = True
    status: str
    created_at: datetime
    updated_at: datetime
    questions: list[AssessmentQuestionOut]


class AssessmentAttemptQuestionOut(BaseModel):
    """One question's result within a candidate's sitting (A3/A11). For a
    variant-set slot (VS2), `question_id` is the variant this candidate was
    assigned and `variant_label` names it (different candidates get different
    variants of the same slot); null when they never started the slot."""

    question_id: str | None = None
    variant_set_id: str | None = None
    variant_label: str | None = None
    title: str
    submitted: bool
    late: bool = False  # this candidate's submission arrived after the window closed
    submission_id: str | None = None
    verdict: str | None = None
    score_pct: float | None = None


class AssessmentAttemptOut(BaseModel):
    """One candidate's whole sitting of an assessment: every question's result
    plus a composite (A11) — pass count is the headline (always well-defined,
    even with an ungraded question), average score across GRADED questions is
    the secondary detail (None until at least one is graded)."""

    candidate_name: str
    candidate_email: str
    questions: list[AssessmentAttemptQuestionOut]
    passed_count: int
    total_count: int
    avg_score_pct: float | None = None
    # Integrity signals recorded during this candidate's sitting (I1). Counted
    # here, not just on the submission, so the grid answers "who is worth a look"
    # WITHOUT opening each submission — and so a candidate who triggered signals
    # and never submitted is visible at all (they have an attempt row but no
    # submission to hang a report off). Null for an unmonitored sitting, which
    # is not the same as zero.
    integrity_signals: int | None = None
    integrity_blocked: int = 0  # of those, pastes actually blocked (the severe kind)
    # The sitting's risk level from integrity.py (none|low|elevated|high) — the
    # triage column. Null exactly when integrity_signals is (unmonitored).
    integrity_risk: str | None = None


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


# --- Variant sets (per-candidate unique variants) ---------------------------


class VariantSetDraftIn(BaseModel):
    """A brief to draft a SET of sibling variants from (the authoring inputs are
    pinned across the set so the variants stay in one difficulty band)."""

    brief: str = Field(min_length=1)
    language: str
    count: int = Field(ge=2, le=8, description="How many variants to draft.")
    difficulty: str | None = None
    target_complexity: str | None = None


class VariantDraftOut(BaseModel):
    """One drafted variant, reshaped to feed the create form (nothing stored)."""

    label: str | None = None  # short tag within the set (A/B/C…)
    question: QuestionCreate
    reference_solution: str | None = None
    reference_language: str | None = None
    warnings: list[str] = Field(default_factory=list)


class VariantSetDraftOut(BaseModel):
    """A drafted variant set: the variants plus the SET-level warnings (a variant
    shortfall and any parity drift the agent flagged). Reviewed, then saved via
    POST /variant-sets — the platform never stores an unvalidated question."""

    variants: list[VariantDraftOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    engine: str = ""
    cost_usd: float | None = None


class VariantCreate(QuestionCreate):
    """A reviewed variant to persist: a full question plus its label in the set."""

    label: str | None = None


class VariantSetCreate(BaseModel):
    id: str | None = None
    title: str
    brief: str
    language: str
    difficulty: str | None = None
    target_complexity: str | None = None
    variants: list[VariantCreate] = Field(min_length=2)


class VariantOut(QuestionOut):
    variant_label: str | None = None


class VariantSetOut(BaseModel):
    id: str
    title: str
    brief: str
    language: str
    difficulty: str | None
    target_complexity: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    variants: list[VariantOut]


class VariantSetSummaryOut(BaseModel):
    """Lean list row — the set plus how many variants it holds, no question bodies."""

    id: str
    title: str
    language: str
    difficulty: str | None
    variant_count: int
    status: str
    created_at: datetime
    updated_at: datetime


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
    # True when this submission arrived after the timed window closed (recorded
    # and graded, but flagged so the interviewer can weigh it).
    late: bool = False
    result: ResultOut | None = None


class SubmissionSummaryOut(BaseModel):
    """Lean list row: everything the summary needs, minus the two heavy fields
    (`code` and the agent's `full_result` payload). A page of these stays small
    even at hundreds of rows; fetch the full `SubmissionOut` per-id for detail."""

    id: str
    question_id: str
    candidate: str
    candidate_email: str | None = None
    language: str
    status: str
    agent_job_id: str | None
    created_at: datetime
    verdict: str | None = None
    score_pct: float | None = None
    late: bool = False  # arrived after the timed window closed (recorded + flagged)
    # Integrity signals recorded during the sitting this submission came from (I1).
    # None = the sitting wasn't monitored (or there was no sitting at all — an
    # interviewer's direct submission), which must not read as a clean zero.
    integrity_signals: int | None = None
    integrity_blocked: int = 0  # of those, pastes actually blocked (the severe kind)
    # Set when this submission came in through an assessment invite (A3): lets the
    # list tell an assessment sitting apart from a standalone single-question
    # attempt without a second fetch per row.
    assessment_id: str | None = None
    assessment_title: str | None = None


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
    # Workspace-level default branding (A12) — prefills a new assessment's org/logo.
    default_org_name: str | None = None
    default_logo_url: str | None = None


class InterviewerUpdate(BaseModel):
    # Partial update of the caller's own workspace settings (PATCH /auth/me).
    # Only the fields sent are changed; sending an explicit null clears one.
    default_org_name: str | None = None
    default_logo_url: str | None = None


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


class VariantSetInviteCreate(InviteCreate):
    """Invite candidates to a variant set. One invite is minted per recipient, each
    handed a variant round-robin; `overrides` pins specific recipients to a chosen
    variant (email → variant question id) instead of the rotation."""

    overrides: dict[str, str] = Field(default_factory=dict)


class InviteOut(BaseModel):
    token: str
    url: str
    # Exactly one is set: a legacy single-question invite has question_id; a T4
    # assessment invite has assessment_id.
    question_id: str | None = None
    assessment_id: str | None = None
    # Set when the invite drew its question from a variant set (question_id is the
    # assigned variant); variant_label is that variant's tag, for the assignment UI.
    variant_set_id: str | None = None
    variant_label: str | None = None
    recipients: list[str]
    expires_at: datetime | None
    status: str
    # Per-recipient send outcome, persisted at creation, so every read (create,
    # list, revoke) reports who was actually emailed.
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


class CandidateQuestionPublic(CandidateQuestionView):
    """A candidate-facing question inside the multi-question flow (T4): the same
    safe view plus the id the run/submit calls target, and whether this candidate
    has already submitted it (so the UI can mark it done). Still never carries the
    answer key."""

    id: str
    submitted: bool = False


class InviteStatusOut(BaseModel):
    """The unauthenticated probe for `GET /invite/{token}`: says only whether the
    link is live. Deliberately carries no question data — the candidate must
    identify as an invited recipient via `POST /invite/{token}/start` first, so
    holding the link alone never reveals the problem. `proctored` is the one
    exception and is not question data: the start screen has to disclose that the
    sitting is monitored BEFORE the candidate identifies themselves."""

    status: str
    proctored: bool = True


class CandidateStartIn(BaseModel):
    candidate_email: EmailStr
    # Anchored on the CandidateAttempt at first /start (A10) and reused for
    # every submission in the sitting. Optional so an old client that only
    # ever sent it at /submit keeps working; a fresh attempt just starts
    # nameless until the first submit's body backfills it.
    candidate_name: str | None = None


class InvitePublicOut(BaseModel):
    # `question` is the FIRST question, kept so the pre-T4 single-question UI keeps
    # working; the multi-question UI reads the ordered `questions` list.
    question: CandidateQuestionView
    questions: list[CandidateQuestionPublic] = Field(default_factory=list)
    languages: list[str]
    # Server-authoritative moment the sitting must be submitted by (started_at +
    # the assessment's total duration, or the single question's, for a legacy
    # invite). None when untimed. The candidate UI counts down to this off the
    # server clock, not the browser's.
    deadline: datetime | None = None
    # Per-assessment branding (A12): set only for an assessment invite whose
    # Assessment carries them; None for a legacy single-question invite or an
    # unbranded assessment (candidate UI falls back to a generic header).
    assessment_title: str | None = None
    org_name: str | None = None
    logo_url: str | None = None
    # Whether this sitting is monitored (I1): the candidate UI enforces fullscreen
    # and blocks outside pastes only when true. An assessment invite reads its
    # Assessment.proctored; a legacy single-question ("Quick screen") invite has no
    # Assessment and is always monitored.
    proctored: bool = True


class CandidateSubmitIn(BaseModel):
    candidate_name: str
    candidate_email: EmailStr
    language: str
    code: str = Field(min_length=1)
    # Which question this submits. None (or omitted) targets the invite's single
    # question; required for a multi-question assessment invite.
    question_id: str | None = None


class CandidateSubmitOut(BaseModel):
    submission_id: str
    status: str


class CandidateRunIn(BaseModel):
    """Run the candidate's code against input they typed themselves."""

    candidate_email: EmailStr
    language: str
    code: str = Field(min_length=1)
    stdin: str = ""
    # The question being worked on (None = the invite's single question); used only
    # for the live/invited/not-already-submitted gate — run itself is generic.
    question_id: str | None = None


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
    # Which question's tests to run. None = the invite's single question; required
    # for a multi-question assessment invite.
    question_id: str | None = None


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
    late: bool = False  # arrived after the timed window closed (recorded + flagged)
    # Integrity signals for the sitting (I1); None = unmonitored, not zero.
    integrity_signals: int | None = None
    integrity_blocked: int = 0
    created_at: datetime


# --------------------------------------------------------------------------- #
# Analytics (AR1)                                                              #
# --------------------------------------------------------------------------- #
# All rates are fractions in [0, 1] (None = undefined, e.g. no graded rows);
# scores are on the 0..100 scale, matching AssessmentResult.score_pct. Counts
# are always well-defined even before anything is graded.


class TrendPointOut(BaseModel):
    """One day of the workspace submission trend."""

    date: date  # the UTC calendar day (serializes as YYYY-MM-DD)
    submissions: int
    graded: int
    passed: int
    pass_rate: float | None = None  # passed / graded that day


class ScoreBucketOut(BaseModel):
    """One bar of a score histogram: [low, high) (top bucket is inclusive)."""

    low: float
    high: float
    count: int


class OverviewAnalyticsOut(BaseModel):
    """Workspace-level rollup across all of the interviewer's questions."""

    questions: int  # active (non-archived, non-variant) questions
    submissions: int
    graded: int
    candidates: int  # distinct candidate emails seen across submissions
    passed: int
    pass_rate: float | None = None  # passed / graded overall
    avg_score_pct: float | None = None
    trend: list[TrendPointOut]
    score_distribution: list[ScoreBucketOut]


class QuestionAnalyticsOut(BaseModel):
    """Per-question aggregate stats — the metrics the plain question list lacked."""

    question_id: str
    title: str
    difficulty: str | None = None
    submissions: int
    graded: int
    passed: int
    pass_rate: float | None = None
    avg_score_pct: float | None = None
    median_score_pct: float | None = None
    late: int  # count of submissions flagged late
    avg_time_to_solve_s: float | None = None  # over submissions with a known start
    median_time_to_solve_s: float | None = None


class AssessmentCandidateAnalyticsOut(BaseModel):
    """One candidate's standing within a single assessment."""

    candidate_name: str
    candidate_email: str
    passed_count: int
    submitted_count: int  # slots this candidate has submitted (for completion status)
    total_count: int
    avg_score_pct: float | None = None
    rank: int | None = None  # competition rank among graded candidates (1 = top)
    percentile: float | None = None  # share of graded candidates at or below
    time_to_solve_s: float | None = None  # first open -> last submission (whole sitting)


class AssessmentAnalyticsOut(BaseModel):
    """Cross-candidate rollup for one assessment (extends the attempts view with
    ranking, time-to-solve, and workspace-style aggregates)."""

    assessment_id: str
    title: str
    slot_count: int
    candidates_started: int
    candidates_completed: int  # submitted every slot
    avg_score_pct: float | None = None  # mean of per-candidate averages
    pass_rate: float | None = None  # graded question-attempts that passed
    score_distribution: list[ScoreBucketOut]
    candidates: list[AssessmentCandidateAnalyticsOut]


# --- Integrity signals (I1 browser telemetry) -------------------------------

IntegrityEventKind = Literal[
    "focus_loss",  # the assessment tab/window lost focus (duration_ms = time away)
    "fullscreen_exit",  # left fullscreen (duration_ms = time until they returned)
    "fullscreen_denied",  # the browser refused fullscreen — context, not misconduct
    "paste_external",  # pasted text that wasn't copied from this page (blocked)
    "paste_internal",  # pasted text copied within this page (allowed; context)
    "devtools",  # developer tools appear to have been opened
]


class IntegrityEventIn(BaseModel):
    """One signal the candidate's browser reports. Every field is the client's own
    word — see models.IntegrityEvent for why that is acceptable and what the write
    path clamps."""

    kind: IntegrityEventKind
    offset_ms: int = Field(ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    size: int | None = Field(default=None, ge=0)
    blocked: bool = False


class IntegrityEventsIn(BaseModel):
    """A batch of signals for one candidate, flushed periodically by the candidate
    UI. Batched because these fire in bursts (a tab switch is two events) and one
    request per event would burn the rate limit on a normal sitting."""

    candidate_email: EmailStr
    # The question open when the batch was collected; null before one is chosen.
    question_id: str | None = None
    events: list[IntegrityEventIn] = Field(min_length=1, max_length=50)


class IntegrityEventOut(BaseModel):
    kind: str
    offset_ms: int
    duration_ms: int | None
    size: int | None
    blocked: bool
    question_id: str | None
    # The question's title, denormalized so a multi-question sitting's timeline can
    # say where a signal fired without a second fetch. Null when question_id is.
    question_title: str | None = None


class IntegritySummaryOut(BaseModel):
    """Counts the interviewer reads first, before the timeline itself."""

    total: int
    focus_losses: int
    away_ms: int  # total time spent off the assessment tab
    fullscreen_exits: int
    pastes_blocked: int
    devtools_opens: int


class IntegrityRiskReasonOut(BaseModel):
    """One factor that contributed to the risk score, e.g. '2 outside pastes
    blocked' worth 60 — so the interviewer sees what drove the level, not a
    bare number."""

    label: str
    points: int


class IntegrityRiskOut(BaseModel):
    """The sitting's triage hint (integrity.py): a deterrent-grade signal to
    look closer, never proof and never part of the verdict."""

    score: int  # 0-100
    level: str  # none | low | elevated | high
    reasons: list[IntegrityRiskReasonOut]


class IntegrityReportOut(BaseModel):
    """A sitting's integrity signals, as read from one submission. Signals belong
    to the whole sitting (invite + candidate), not to a single question, so a
    multi-question assessment shows the same timeline on each of its submissions
    — each event naming its own question."""

    monitored: bool  # false = this sitting ran unmonitored, so "no signals" means nothing
    summary: IntegritySummaryOut
    # Null only when there is nothing to score AND the sitting was unmonitored —
    # recorded events are always scored, whatever the flag says (suppressing real
    # evidence is never the safer default).
    risk: IntegrityRiskOut | None = None
    events: list[IntegrityEventOut]
