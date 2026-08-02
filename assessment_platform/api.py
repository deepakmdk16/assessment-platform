"""FastAPI app — the Assessment Platform HTTP surface.

The platform is the system of record: it stores questions, submissions, and the
results the agent returns. It never grades. `POST /submissions` triggers a job
on the agent (passing a callback_url pointing back here); the agent later POSTs
the full result to `POST /assessments/callback`, which we persist verbatim.

Interviewers authenticate with a JWT bearer (see `auth.py`) and own their
questions; candidates reach a question through a public, token-gated invite link
that never exposes the test cases / expected outputs. A shared secret guards the
platform<->agent link (see README).
"""

from __future__ import annotations

import csv
import io
import logging
import re
import secrets
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from . import agent_client, analytics, config, email_client, integrity, signing
from .auth import (
    create_access_token,
    get_current_interviewer,
    hash_password,
    verify_password,
)
from .config import PLATFORM_BASE_URL
from .db import get_session, init_db
from .models import (
    Assessment,
    AssessmentQuestion,
    AssessmentResult,
    CandidateAttempt,
    CandidateSlotVariant,
    IntegrityEvent,
    Interviewer,
    Invite,
    Question,
    QuestionTestCase,
    Submission,
    VariantSet,
    as_utc,
)
from .question_rules import case_floor_violations
from .ratelimit import client_ip, limiter
from .schemas import (
    AssessmentAnalyticsOut,
    AssessmentAttemptOut,
    AssessmentAttemptQuestionOut,
    AssessmentCandidateAnalyticsOut,
    AssessmentCreate,
    AssessmentOut,
    AssessmentQuestionOut,
    AssessmentSlotIn,
    AssessmentUpdate,
    CandidateQuestionPublic,
    CandidateQuestionView,
    CandidateRunIn,
    CandidateRunOut,
    CandidateRunTestsIn,
    CandidateRunTestsOut,
    CandidateStartIn,
    CandidateSubmitIn,
    CandidateSubmitOut,
    CandidateTestOutcomeOut,
    DashboardSubmissionOut,
    IntegrityEventOut,
    IntegrityEventsIn,
    IntegrityReportOut,
    IntegrityRiskOut,
    IntegrityRiskReasonOut,
    IntegritySummaryOut,
    InterviewerOut,
    InterviewerUpdate,
    InviteCreate,
    InviteDeliveryOut,
    InviteOut,
    InvitePublicOut,
    InviteStatusOut,
    LoginIn,
    OverviewAnalyticsOut,
    Page,
    QuestionAnalyticsOut,
    QuestionCreate,
    QuestionDraftIn,
    QuestionDraftOut,
    QuestionOut,
    QuestionUpdate,
    RegisterIn,
    ResultOut,
    ScoreBucketOut,
    SubmissionCreate,
    SubmissionOut,
    SubmissionSummaryOut,
    TestCaseIn,
    TestCaseOut,
    TokenOut,
    TrendPointOut,
    VariantDraftOut,
    VariantOut,
    VariantSetCreate,
    VariantSetDraftIn,
    VariantSetDraftOut,
    VariantSetInviteCreate,
    VariantSetOut,
    VariantSetSummaryOut,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # Production runs Alembic migrations; create_all only when explicitly opted in
    # (dev/E2E) so a missing migration surfaces instead of being papered over.
    if config.AUTO_CREATE_TABLES:
        init_db()
    yield


app = FastAPI(
    title="Assessment Platform",
    description="System of record for coding questions, submissions, and agent results.",
    version="0.1.0",
    lifespan=_lifespan,
)

# The SPA is served from a different origin than the API, so browser requests
# need CORS. Origins are env-driven (see config.CORS_ORIGINS).
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    # No credentials cross-origin: the JWT rides in the Authorization header, not
    # a cookie, so cookie/credential CORS is unnecessary (and can't combine with
    # a wildcard origin anyway).
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Serialization helpers                                                         #
# --------------------------------------------------------------------------- #


def _require_id(value: int | None) -> int:
    """Narrow a persisted row's Optional[int] id to int, guarding at runtime.

    A committed/loaded row always has an id, but the column type is Optional. A
    bare `assert` would express this — except `python -O` strips asserts, so the
    guarantee would vanish in an optimized run. Raise explicitly instead.
    """
    if value is None:
        raise RuntimeError("expected a persisted row to have an id")
    return value


def _question_out(q: Question) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        title=q.title,
        prompt=q.prompt,
        constraints=q.constraints,
        time_limit_s=q.time_limit_s,
        pass_threshold=q.pass_threshold,
        required_complexity=q.required_complexity,
        example_input=q.example_input,
        example_output=q.example_output,
        difficulty=q.difficulty,
        reference_solution=q.reference_solution,
        reference_language=q.reference_language,
        duration_minutes=q.duration_minutes,
        status=q.status,
        created_at=q.created_at,
        updated_at=q.updated_at,
        test_cases=[
            TestCaseOut(
                id=tc.id if tc.id is not None else -1,
                name=tc.name,
                stdin=tc.stdin,
                expected=tc.expected,
                category=tc.category,  # type: ignore[arg-type]  # DB stores str; values are the Category literals
                weight=tc.weight,
            )
            for tc in q.test_cases
        ],
    )


def _submission_out(sub: Submission, result: AssessmentResult | None) -> SubmissionOut:
    result_out = None
    if result is not None:
        result_out = ResultOut(
            verdict=result.verdict,
            score_pct=result.score_pct,
            reason=result.reason,
            full_result=result.full_result,
            received_at=result.received_at,
        )
    return SubmissionOut(
        id=sub.id,
        question_id=sub.question_id,
        candidate=sub.candidate,
        language=sub.language,
        code=sub.code,
        status=sub.status,
        agent_job_id=sub.agent_job_id,
        created_at=sub.created_at,
        late=sub.late,
        result=result_out,
    )


def _submission_summary(
    sub: Submission,
    result: AssessmentResult | None,
    assessment: Assessment | None = None,
    integrity: tuple[int | None, int] = (None, 0),
) -> SubmissionSummaryOut:
    return SubmissionSummaryOut(
        id=sub.id,
        question_id=sub.question_id,
        candidate=sub.candidate,
        candidate_email=sub.candidate_email,
        language=sub.language,
        status=sub.status,
        agent_job_id=sub.agent_job_id,
        created_at=sub.created_at,
        verdict=result.verdict if result else None,
        score_pct=result.score_pct if result else None,
        late=sub.late,
        integrity_signals=integrity[0],
        integrity_blocked=integrity[1],
        assessment_id=assessment.id if assessment else None,
        assessment_title=assessment.title if assessment else None,
    )


def _assessments_by_submission(
    subs: Sequence[Submission], session: Session
) -> dict[str, Assessment]:
    """Assessment (if any) each submission's invite belongs to, keyed by
    submission_id — two batched queries (invites, then assessments), no N+1.
    A submission with no invite, or a legacy single-question invite, is simply
    absent from the result (A3)."""
    invite_ids = [s.invite_id for s in subs if s.invite_id is not None]
    if not invite_ids:
        return {}
    invites = session.exec(
        select(Invite).where(col(Invite.id).in_(invite_ids), col(Invite.assessment_id).is_not(None))
    ).all()
    assessment_ids = [inv.assessment_id for inv in invites if inv.assessment_id is not None]
    if not assessment_ids:
        return {}
    assessments = {
        a.id: a
        for a in session.exec(select(Assessment).where(col(Assessment.id).in_(assessment_ids))).all()
    }
    invite_to_assessment: dict[int, Assessment] = {}
    for inv in invites:
        if inv.assessment_id is not None and inv.assessment_id in assessments:
            invite_to_assessment[_require_id(inv.id)] = assessments[inv.assessment_id]

    result: dict[str, Assessment] = {}
    for s in subs:
        if s.invite_id is not None and s.invite_id in invite_to_assessment:
            result[s.id] = invite_to_assessment[s.invite_id]
    return result


def _integrity_by_submission(
    subs: Sequence[Submission], session: Session
) -> dict[str, tuple[int | None, int]]:
    """Per-submission integrity counts `(signals, blocked)` keyed by submission_id,
    batched (invites, then events — no N+1). Signals are counted per *sitting*
    (invite + candidate), matching the attempts grid: `None` means the sitting
    wasn't monitored — or there was no sitting at all (an interviewer's direct
    submission) — which must not read as a clean zero."""
    invite_ids = {s.invite_id for s in subs if s.invite_id is not None}
    proctored: dict[int, bool] = {}
    if invite_ids:
        for inv in session.exec(
            select(Invite).where(col(Invite.id).in_(invite_ids))
        ).all():
            proctored[_require_id(inv.id)] = inv.proctored
    signals: dict[tuple[int, str], int] = {}
    blocked: dict[tuple[int, str], int] = {}
    monitored_ids = {i for i, p in proctored.items() if p}
    if monitored_ids:
        for ev in session.exec(
            select(IntegrityEvent).where(col(IntegrityEvent.invite_id).in_(monitored_ids))
        ).all():
            key = (ev.invite_id, ev.candidate_email)
            signals[key] = signals.get(key, 0) + 1
            if ev.kind == "paste_external" and ev.blocked:
                blocked[key] = blocked.get(key, 0) + 1
    out: dict[str, tuple[int | None, int]] = {}
    for s in subs:
        if (
            s.invite_id is None
            or s.candidate_email is None
            or not proctored.get(s.invite_id, False)
        ):
            out[s.id] = (None, 0)
        else:
            key = (s.invite_id, s.candidate_email)
            out[s.id] = (signals.get(key, 0), blocked.get(key, 0))
    return out


def _results_by_submission(
    subs: Sequence[Submission], session: Session
) -> dict[str, AssessmentResult]:
    """Fetch all results for `subs` in one query, keyed by submission_id (avoids N+1)."""
    ids = [s.id for s in subs]
    if not ids:
        return {}
    results = session.exec(
        select(AssessmentResult).where(AssessmentResult.submission_id.in_(ids))  # type: ignore[attr-defined]
    ).all()
    return {r.submission_id: r for r in results}


def _invite_url(token: str) -> str:
    return f"{config.FRONTEND_BASE_URL}/t/{token}"


def _invite_out(inv: Invite, variant_label: str | None = None) -> InviteOut:
    return InviteOut(
        token=inv.token,
        url=_invite_url(inv.token),
        question_id=inv.question_id,
        assessment_id=inv.assessment_id,
        variant_set_id=inv.variant_set_id,
        variant_label=variant_label,
        recipients=inv.recipients,
        expires_at=inv.expires_at,
        status=inv.status,
        # Read the persisted send outcomes, so every read (not just create) shows
        # who was actually emailed.
        deliveries=[
            InviteDeliveryOut(
                recipient=d.get("recipient", ""), sent=bool(d.get("sent")), error=d.get("error")
            )
            for d in (inv.deliveries or [])
        ],
    )


def _normalize_email(email: str) -> str:
    """Canonical form for comparing/storing candidate emails (case-insensitive)."""
    return email.strip().lower()


def _is_expired(expires_at: datetime | None) -> bool:
    """True if the invite's expiry has passed. Stored datetimes may come back
    naive from SQLite; treat those as UTC so the comparison never crashes."""
    if expires_at is None:
        return False
    return datetime.now(timezone.utc) > as_utc(expires_at)


# --------------------------------------------------------------------------- #
# Health                                                                        #
# --------------------------------------------------------------------------- #


@app.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    # A load balancer routes on this, so it must fail when the DB is gone rather
    # than report ok while every real request errors. Cheapest liveness probe.
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Auth (interviewers)                                                           #
# --------------------------------------------------------------------------- #


def _secret_matches(provided: str | None, expected: str) -> bool:
    """Constant-time comparison of a caller-supplied secret against the real one.

    `==` on secrets returns as soon as two bytes differ, so how long the reject
    takes leaks how much of the prefix was right, and a patient caller can rebuild
    the secret one byte at a time. The shared agent token and the sign-up code are
    both long-lived, so neither should be compared that way.
    """
    if provided is None:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def _interviewer_out(interviewer: Interviewer) -> InterviewerOut:
    return InterviewerOut(
        id=_require_id(interviewer.id),
        email=interviewer.email,
        name=interviewer.name,
        default_org_name=interviewer.default_org_name,
        default_logo_url=interviewer.default_logo_url,
    )


@app.post("/auth/register", response_model=InterviewerOut, status_code=201)
def register(
    body: RegisterIn, request: Request, session: Session = Depends(get_session)
) -> InterviewerOut:
    # Login was rate-limited but this wasn't, and sign-up is open unless
    # REGISTRATION_CODE is set — so this was the unmetered way to mint the accounts
    # that reach the paid draft endpoint.
    limiter.check(
        "register", client_ip(request), config.REGISTER_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S
    )
    # Gated sign-up: when a registration code is configured, require a match.
    if config.REGISTRATION_CODE and not _secret_matches(
        body.registration_code, config.REGISTRATION_CODE
    ):
        raise HTTPException(status_code=403, detail="invalid or missing registration code.")
    existing = session.exec(
        select(Interviewer).where(Interviewer.email == body.email)
    ).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail=f"email {body.email!r} already registered.")
    interviewer = Interviewer(
        email=body.email,
        password_hash=hash_password(body.password),
        name=body.name,
    )
    session.add(interviewer)
    session.commit()
    session.refresh(interviewer)
    return _interviewer_out(interviewer)


@app.post("/auth/login", response_model=TokenOut)
def login(
    body: LoginIn, request: Request, session: Session = Depends(get_session)
) -> TokenOut:
    limiter.check(
        "login", client_ip(request), config.LOGIN_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S
    )
    interviewer = session.exec(
        select(Interviewer).where(Interviewer.email == body.email)
    ).first()
    if interviewer is None or not verify_password(body.password, interviewer.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password.")
    return TokenOut(access_token=create_access_token(_require_id(interviewer.id)))


@app.get("/auth/me", response_model=InterviewerOut)
def me(current: Interviewer = Depends(get_current_interviewer)) -> InterviewerOut:
    return _interviewer_out(current)


@app.patch("/auth/me", response_model=InterviewerOut)
def update_me(
    body: InterviewerUpdate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> InterviewerOut:
    """Update the caller's own workspace settings (A12 default branding). A partial
    update: only fields present in the request are changed, so sending an explicit
    null clears a default while omitting a field leaves it untouched. Blank strings
    are normalised to null so an empty box means 'no default', not an empty brand."""
    fields = body.model_dump(exclude_unset=True)
    if "default_org_name" in fields:
        current.default_org_name = (fields["default_org_name"] or "").strip() or None
    if "default_logo_url" in fields:
        current.default_logo_url = (fields["default_logo_url"] or "").strip() or None
    current.updated_at = datetime.now(timezone.utc)
    session.add(current)
    session.commit()
    session.refresh(current)
    return _interviewer_out(current)


# --------------------------------------------------------------------------- #
# Questions CRUD                                                                #
# --------------------------------------------------------------------------- #


def _owned_question(question_id: str, current: Interviewer, session: Session) -> Question:
    """Load a question and enforce ownership: 404 if missing, 403 if not the caller's."""
    q = session.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail=f"no question with id {question_id!r}.")
    if q.owner_id != current.id:
        raise HTTPException(status_code=403, detail="not your question.")
    return q


def _owned_submission(submission_id: str, current: Interviewer, session: Session) -> Submission:
    """Load a submission and enforce ownership via its question's owner."""
    sub = session.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail=f"no submission with id {submission_id!r}.")
    _owned_question(sub.question_id, current, session)  # 403 if not the caller's question
    return sub


def _enforce_case_floor(test_cases: list[TestCaseIn]) -> None:
    """Reject a question that would later fail the agent's grade-time floor.

    Enforced at authoring time (create/update) so we never store a question that
    hard-fails every candidate submission — the candidate can't fix it (A1)."""
    problems = case_floor_violations([tc.category for tc in test_cases])
    if problems:
        raise HTTPException(status_code=422, detail="question " + "; ".join(problems) + ".")


def _slugify(text: str) -> str:
    """A URL-safe lowercase slug from free text (empty input -> "item")."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "item"


def _generate_id(title: str, exists: Callable[[str], bool]) -> str:
    """slug(title) + a short random suffix, retried until unused.

    The id is an internal PK / URL key, not a user concept — the UI no longer
    asks for it (A6). The random suffix makes a collision vanishingly unlikely;
    the loop makes it impossible.
    """
    base = _slugify(title)
    for _ in range(6):
        candidate = f"{base}-{secrets.token_hex(3)}"
        if not exists(candidate):
            return candidate
    return f"{base}-{uuid.uuid4().hex[:8]}"


@app.post("/questions", response_model=QuestionOut, status_code=201)
def create_question(
    body: QuestionCreate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> QuestionOut:
    # An explicit id (agent/CLI authoring path) is honored; the UI omits it and
    # the server generates slug(title)+suffix.
    explicit_id = (body.id or "").strip()
    if explicit_id:
        if session.get(Question, explicit_id) is not None:
            raise HTTPException(status_code=409, detail=f"question {explicit_id!r} already exists.")
        qid = explicit_id
    else:
        qid = _generate_id(body.title, lambda c: session.get(Question, c) is not None)
    _enforce_case_floor(body.test_cases)
    q = Question(
        id=qid,
        owner_id=_require_id(current.id),
        title=body.title,
        prompt=body.prompt,
        constraints=body.constraints,
        time_limit_s=body.time_limit_s,
        pass_threshold=body.pass_threshold,
        required_complexity=body.required_complexity,
        example_input=body.example_input,
        example_output=body.example_output,
        difficulty=body.difficulty,
        reference_solution=body.reference_solution,
        reference_language=body.reference_language,
        duration_minutes=body.duration_minutes,
        test_cases=[
            QuestionTestCase(
                name=tc.name,
                stdin=tc.stdin,
                expected=tc.expected,
                category=tc.category,
                weight=tc.weight,
            )
            for tc in body.test_cases
        ],
    )
    session.add(q)
    session.commit()
    session.refresh(q)
    return _question_out(q)


def _agent_detail(exc: httpx.HTTPStatusError) -> str:
    """The agent's own error reason, flattened to a readable string.

    A draft 422's detail is a dict carrying `warnings`; join them so the UI shows
    the reason rather than "[object Object]".
    """
    try:
        detail: Any = exc.response.json().get("detail", exc.response.text)
    except ValueError:
        detail = exc.response.text
    if isinstance(detail, dict):
        warnings = detail.get("warnings")
        if warnings:
            return "; ".join(str(w) for w in warnings)
    return str(detail)


def _question_create_from_agent(q: dict) -> QuestionCreate:
    """Reshape one agent-drafted question payload into the create form's shape.

    Shared by the single-draft and variant-set-draft endpoints. The agent should
    send `pass_threshold`/`time_limit_s`, but guard explicit nulls so a stray one
    is a usable draft, not a 500 (`.get(k, default)` only defaults an absent key)."""
    example = q.get("example") or {}
    pass_threshold = q.get("pass_threshold")
    time_limit_s = q.get("time_limit_s")
    return QuestionCreate(
        id=q.get("id", ""),
        title=q.get("title", ""),
        prompt=q.get("prompt", ""),
        constraints=q.get("constraints", ""),
        time_limit_s=time_limit_s if time_limit_s is not None else 2.0,
        # Keep the agent's 0..1 fraction (QuestionCreate stores a fraction); the
        # wizard scales it to percent for display and back to a fraction on save.
        pass_threshold=pass_threshold if pass_threshold is not None else 0.9,
        required_complexity=q.get("required_complexity"),
        example_input=example.get("input"),
        example_output=example.get("output"),
        test_cases=q.get("test_cases", []),
    )


@app.post("/questions/draft", response_model=QuestionDraftOut)
async def draft_question(
    body: QuestionDraftIn,
    request: Request,
    current: Interviewer = Depends(get_current_interviewer),
) -> QuestionDraftOut:
    """Draft a question from a brief via the agent. Stateless: stores NOTHING —
    the interviewer reviews/edits the returned draft and then saves it through the
    normal POST /questions path (the platform never stores an unvalidated question).

    Rate-limited because it is the one endpoint that spends real money: every call
    runs an LLM on the agent. Bearer auth alone is not a budget — sign-up is open
    unless REGISTRATION_CODE is set, so "authenticated" was free to obtain. Each
    call can also hold a worker thread for the full draft timeout, so an uncapped
    loop exhausts the pool as well as the bill.
    """
    limiter.check(
        "draft", client_ip(request), config.DRAFT_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S
    )
    try:
        payload = await agent_client.draft_question(
            brief=body.brief,
            language=body.language,
            difficulty=body.difficulty,
            target_complexity=body.target_complexity,
        )
    except httpx.HTTPStatusError as exc:
        # Surface the agent's own status/reason (503 offline, 422 unusable draft,
        # 400 bad language) so the UI can show what actually went wrong.
        raise HTTPException(
            status_code=exc.response.status_code, detail=_agent_detail(exc)
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"agent unreachable: {exc}") from exc

    question = _question_create_from_agent(payload.get("question") or {})
    return QuestionDraftOut(
        question=question,
        warnings=payload.get("warnings", []),
        reference_solution=payload.get("reference_solution"),
        reference_language=payload.get("reference_language"),
        engine=payload.get("engine", ""),
        cost_usd=payload.get("cost_usd"),
    )


# --------------------------------------------------------------------------- #
# Variant sets (per-candidate unique variants)                                  #
# --------------------------------------------------------------------------- #

# Short display tags for the variants within a set (A, B, C…). A set is capped at
# 8 on the agent side, so the alphabet never runs out.
_VARIANT_LABELS = "ABCDEFGH"


def _owned_variant_set(set_id: str, current: Interviewer, session: Session) -> VariantSet:
    """Load a variant set and enforce ownership (404 if missing/not the caller's —
    a single status so one owner can't probe another's ids)."""
    vs = session.get(VariantSet, set_id)
    if vs is None or vs.owner_id != current.id:
        raise HTTPException(status_code=404, detail=f"no variant set with id {set_id!r}.")
    return vs


def _variant_out(q: Question) -> VariantOut:
    return VariantOut(**_question_out(q).model_dump(), variant_label=q.variant_label)


def _variant_set_out(vs: VariantSet, variants: list[Question]) -> VariantSetOut:
    return VariantSetOut(
        id=vs.id,
        title=vs.title,
        brief=vs.brief,
        language=vs.language,
        difficulty=vs.difficulty,
        target_complexity=vs.target_complexity,
        status=vs.status,
        created_at=vs.created_at,
        updated_at=vs.updated_at,
        variants=[_variant_out(q) for q in variants],
    )


def _set_variants(set_id: str, session: Session) -> list[Question]:
    """A set's variant questions, ordered by their label (A, B, C…)."""
    return list(
        session.exec(
            select(Question)
            .where(Question.variant_set_id == set_id)
            .order_by(col(Question.variant_label))
        ).all()
    )


@app.post("/variant-sets/draft", response_model=VariantSetDraftOut)
async def draft_variant_set(
    body: VariantSetDraftIn,
    request: Request,
    current: Interviewer = Depends(get_current_interviewer),
) -> VariantSetDraftOut:
    """Draft a SET of sibling variants from one brief via the agent. Stateless:
    stores NOTHING — the interviewer reviews the variants (and the parity warnings)
    and then saves via POST /variant-sets. Rate-limited on the same 'draft' bucket
    as single drafting; a set costs `count` full drafts, so it is the pricier call."""
    limiter.check(
        "draft", client_ip(request), config.DRAFT_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S
    )
    try:
        payload = await agent_client.draft_set(
            brief=body.brief,
            language=body.language,
            count=body.count,
            difficulty=body.difficulty,
            target_complexity=body.target_complexity,
        )
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code, detail=_agent_detail(exc)
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"agent unreachable: {exc}") from exc

    variants: list[VariantDraftOut] = []
    total_cost = 0.0
    have_cost = False
    for v in payload.get("variants", []):
        cost = v.get("cost_usd")
        if cost is not None:
            total_cost += cost
            have_cost = True
        q = v.get("question")
        if not q:
            # A variant the agent couldn't draft carries no question; it's counted
            # in the set-level shortfall warning, not shown as an empty card.
            continue
        variants.append(
            VariantDraftOut(
                label=_VARIANT_LABELS[len(variants)] if len(variants) < len(_VARIANT_LABELS) else None,
                question=_question_create_from_agent(q),
                reference_solution=v.get("reference_solution"),
                reference_language=v.get("reference_language"),
                warnings=v.get("warnings", []),
            )
        )
    return VariantSetDraftOut(
        variants=variants,
        warnings=payload.get("warnings", []),
        engine=payload.get("engine", ""),
        cost_usd=total_cost if have_cost else None,
    )


@app.post("/variant-sets", response_model=VariantSetOut, status_code=201)
def create_variant_set(
    body: VariantSetCreate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> VariantSetOut:
    """Persist a reviewed variant set: the set row plus one Question per variant,
    each tagged with `variant_set_id`/`variant_label`. Each variant clears the same
    case-count floor a standalone question does."""
    owner = _require_id(current.id)
    set_id = (body.id or "").strip() or _generate_id(
        body.title, lambda c: session.get(VariantSet, c) is not None
    )
    if session.get(VariantSet, set_id) is not None:
        raise HTTPException(status_code=409, detail=f"variant set {set_id!r} already exists.")

    vs = VariantSet(
        id=set_id,
        owner_id=owner,
        title=body.title,
        brief=body.brief,
        language=body.language,
        difficulty=body.difficulty,
        target_complexity=body.target_complexity,
    )
    session.add(vs)

    # Siblings of one brief share the agent's drafted id (e.g. every variant of a
    # max-sum-non-adjacent brief is drafted as 'max_sum_non_adjacent'), so honoring
    # the incoming id would collide the moment there's a 2nd variant. A variant is a
    # brand-new stored question — always mint a fresh unique id. `taken` also guards
    # against two variants colliding within this same (not-yet-committed) batch.
    variants: list[Question] = []
    taken: set[str] = set()
    for i, v in enumerate(body.variants):
        _enforce_case_floor(v.test_cases)
        qid = _generate_id(
            v.title or "variant",
            lambda c: c in taken or session.get(Question, c) is not None,
        )
        taken.add(qid)
        q = Question(
            id=qid,
            owner_id=owner,
            title=v.title,
            prompt=v.prompt,
            constraints=v.constraints,
            time_limit_s=v.time_limit_s,
            pass_threshold=v.pass_threshold,
            required_complexity=v.required_complexity,
            example_input=v.example_input,
            example_output=v.example_output,
            difficulty=v.difficulty,
            reference_solution=v.reference_solution,
            reference_language=v.reference_language,
            duration_minutes=v.duration_minutes,
            variant_set_id=set_id,
            variant_label=v.label or (_VARIANT_LABELS[i] if i < len(_VARIANT_LABELS) else str(i + 1)),
            test_cases=[
                QuestionTestCase(
                    name=tc.name,
                    stdin=tc.stdin,
                    expected=tc.expected,
                    category=tc.category,
                    weight=tc.weight,
                )
                for tc in v.test_cases
            ],
        )
        session.add(q)
        variants.append(q)

    session.commit()
    session.refresh(vs)
    for q in variants:
        session.refresh(q)
    return _variant_set_out(vs, variants)


@app.get("/variant-sets", response_model=Page[VariantSetSummaryOut])
def list_variant_sets(
    include_archived: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> Page[VariantSetSummaryOut]:
    where = [VariantSet.owner_id == current.id]
    if not include_archived:
        where.append(VariantSet.status == "active")
    total = session.exec(select(func.count()).select_from(VariantSet).where(*where)).one()
    stmt = (
        select(VariantSet)
        .where(*where)
        .order_by(col(VariantSet.created_at).desc(), col(VariantSet.id))
        .offset(offset)
        .limit(limit)
    )
    items: list[VariantSetSummaryOut] = []
    for vs in session.exec(stmt).all():
        count = session.exec(
            select(func.count()).select_from(Question).where(Question.variant_set_id == vs.id)
        ).one()
        items.append(
            VariantSetSummaryOut(
                id=vs.id,
                title=vs.title,
                language=vs.language,
                difficulty=vs.difficulty,
                variant_count=count,
                status=vs.status,
                created_at=vs.created_at,
                updated_at=vs.updated_at,
            )
        )
    return Page(items=items, total=total, limit=limit, offset=offset)


@app.get("/variant-sets/{set_id}", response_model=VariantSetOut)
def get_variant_set(
    set_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> VariantSetOut:
    vs = _owned_variant_set(set_id, current, session)
    return _variant_set_out(vs, _set_variants(set_id, session))


@app.get("/questions", response_model=Page[QuestionOut])
def list_questions(
    include_archived: bool = False,
    include_variants: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> Page[QuestionOut]:
    where: list[Any] = [Question.owner_id == current.id]
    if not include_archived:
        # Archived questions are retired: hidden from the dashboard by default but
        # still reachable (and their submissions kept) via ?include_archived=true.
        where.append(Question.status == "active")
    if not include_variants:
        # A variant set is N sibling questions tagged with variant_set_id. They are
        # one thing to the interviewer (managed on the Variant sets page), so hide
        # them from the standalone library + assessment picker by default, else a
        # set of 3 shows as 3 unrelated look-alikes. Opt in with ?include_variants=true.
        where.append(col(Question.variant_set_id).is_(None))
    total = session.exec(select(func.count()).select_from(Question).where(*where)).one()
    # Newest first, id as a stable tiebreaker so paging over equal timestamps
    # (common in tests / bulk imports) is deterministic.
    stmt = (
        select(Question)
        .where(*where)
        .order_by(col(Question.created_at).desc(), col(Question.id))
        .offset(offset)
        .limit(limit)
    )
    items = [_question_out(q) for q in session.exec(stmt).all()]
    return Page(items=items, total=total, limit=limit, offset=offset)


@app.get("/questions/{question_id}", response_model=QuestionOut)
def get_question(
    question_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> QuestionOut:
    return _question_out(_owned_question(question_id, current, session))


@app.put("/questions/{question_id}", response_model=QuestionOut)
def update_question(
    question_id: str,
    body: QuestionUpdate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> QuestionOut:
    q = _owned_question(question_id, current, session)
    _enforce_case_floor(body.test_cases)
    q.title = body.title
    q.prompt = body.prompt
    q.constraints = body.constraints
    q.time_limit_s = body.time_limit_s
    q.pass_threshold = body.pass_threshold
    q.required_complexity = body.required_complexity
    q.example_input = body.example_input
    q.example_output = body.example_output
    q.difficulty = body.difficulty
    q.reference_solution = body.reference_solution
    q.reference_language = body.reference_language
    q.duration_minutes = body.duration_minutes
    q.updated_at = datetime.now(timezone.utc)
    # Replace the whole test-case set (PUT = full replace). cascade delete-orphan
    # cleans up the old rows.
    q.test_cases = [
        QuestionTestCase(
            name=tc.name,
            stdin=tc.stdin,
            expected=tc.expected,
            category=tc.category,
            weight=tc.weight,
        )
        for tc in body.test_cases
    ]
    session.add(q)
    session.commit()
    session.refresh(q)
    return _question_out(q)


@app.post("/questions/{question_id}/archive", response_model=QuestionOut)
def archive_question(
    question_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> QuestionOut:
    """Retire a question: hide it from the dashboard while keeping its submissions.

    This is the path for a question with recorded attempts — DELETE 409s on those
    because the submissions are the record. Idempotent.
    """
    q = _owned_question(question_id, current, session)
    q.status = "archived"
    q.updated_at = datetime.now(timezone.utc)
    session.add(q)
    session.commit()
    session.refresh(q)
    return _question_out(q)


@app.post("/questions/{question_id}/unarchive", response_model=QuestionOut)
def unarchive_question(
    question_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> QuestionOut:
    """Restore an archived question to the active dashboard. Idempotent."""
    q = _owned_question(question_id, current, session)
    q.status = "active"
    q.updated_at = datetime.now(timezone.utc)
    session.add(q)
    session.commit()
    session.refresh(q)
    return _question_out(q)


@app.delete("/questions/{question_id}", status_code=204)
def delete_question(
    question_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> None:
    """Delete a question and its invites/test cases. 409 if anyone has submitted.

    Submissions are the system of record — cascading them away would destroy the
    thing this service exists to keep, and every candidate's result with it. So a
    question with recorded attempts is not deletable; the invites can be revoked
    instead. Invites and test cases carry no independent record and go with it.
    """
    q = _owned_question(question_id, current, session)
    # COUNT, not a fetch: the rows carry the candidates' full code blobs and we
    # only need to know whether any exist.
    submission_count = session.exec(
        select(func.count()).select_from(Submission).where(Submission.question_id == question_id)
    ).one()
    if submission_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"cannot delete question {question_id!r}: {submission_count} submission(s) "
                "are recorded against it. Revoke its invites instead."
            ),
        )
    session.delete(q)
    session.commit()


# --------------------------------------------------------------------------- #
# Assessments (T4: a named, ordered set of the interviewer's own questions)      #
# --------------------------------------------------------------------------- #


def _owned_assessment(assessment_id: str, current: Interviewer, session: Session) -> Assessment:
    a = session.get(Assessment, assessment_id)
    if a is None:
        raise HTTPException(status_code=404, detail=f"no assessment with id {assessment_id!r}.")
    if a.owner_id != current.id:
        raise HTTPException(status_code=403, detail="not your assessment.")
    return a


def _assessment_slot_out(aq: AssessmentQuestion, session: Session) -> AssessmentQuestionOut:
    """One slot for the builder/results UI, denormalized so no 2nd fetch is needed.
    A fixed slot carries its question title; a variant-set slot (VS2) carries the
    set title + how many variants it pools."""
    if aq.variant_set_id is not None:
        vs = session.get(VariantSet, aq.variant_set_id)
        count = session.exec(
            select(func.count())
            .select_from(Question)
            .where(Question.variant_set_id == aq.variant_set_id)
        ).one()
        return AssessmentQuestionOut(
            variant_set_id=aq.variant_set_id,
            variant_count=count,
            position=aq.position,
            title=vs.title if vs else aq.variant_set_id,
        )
    return AssessmentQuestionOut(
        question_id=aq.question_id,
        position=aq.position,
        title=aq.question.title if aq.question else (aq.question_id or ""),
    )


def _assessment_out(a: Assessment, session: Session) -> AssessmentOut:
    # `a.questions` is ordered by position (relationship order_by).
    return AssessmentOut(
        id=a.id,
        title=a.title,
        duration_minutes=a.duration_minutes,
        org_name=a.org_name,
        logo_url=a.logo_url,
        proctored=a.proctored,
        status=a.status,
        created_at=a.created_at,
        updated_at=a.updated_at,
        questions=[_assessment_slot_out(aq, session) for aq in a.questions],
    )


def _membership_rows(
    slots: list[AssessmentSlotIn], current: Interviewer, session: Session
) -> list[AssessmentQuestion]:
    """Validate an ordered slot list and build the membership rows. Each slot is a
    fixed question OR a variant set (VS2), both owner-scoped (404/403 via
    `_owned_question` / `_owned_variant_set`). A question or variant set may appear
    at most once — reported as a clean 400 (the join's unique key also backs the
    question case, but not the set case, so this is the real guard)."""
    q_ids = [s.question_id for s in slots if s.question_id is not None]
    vs_ids = [s.variant_set_id for s in slots if s.variant_set_id is not None]
    if len(set(q_ids)) != len(q_ids):
        raise HTTPException(status_code=400, detail="a question may appear at most once.")
    if len(set(vs_ids)) != len(vs_ids):
        raise HTTPException(status_code=400, detail="a variant set may appear at most once.")
    rows: list[AssessmentQuestion] = []
    for i, s in enumerate(slots):
        if s.question_id is not None:
            _owned_question(s.question_id, current, session)  # 404/403
            rows.append(AssessmentQuestion(question_id=s.question_id, position=i))
        else:
            assert s.variant_set_id is not None  # slot validator guarantees exactly one
            _owned_variant_set(s.variant_set_id, current, session)  # 404/403
            rows.append(AssessmentQuestion(variant_set_id=s.variant_set_id, position=i))
    return rows


def _assessment_has_invite(assessment_id: str, session: Session) -> bool:
    """True if any invite (sent or not) references this assessment (A9). A
    submission can't exist for an assessment without one of these, so checking
    invites alone also covers "or submissions exist"."""
    return (
        session.exec(select(Invite.id).where(Invite.assessment_id == assessment_id)).first()
        is not None
    )


@app.post("/assessments", response_model=AssessmentOut, status_code=201)
def create_assessment(
    body: AssessmentCreate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> AssessmentOut:
    explicit_id = (body.id or "").strip()
    if explicit_id:
        if session.get(Assessment, explicit_id) is not None:
            raise HTTPException(
                status_code=409, detail=f"assessment {explicit_id!r} already exists."
            )
        aid = explicit_id
    else:
        aid = _generate_id(body.title, lambda c: session.get(Assessment, c) is not None)
    a = Assessment(
        id=aid,
        owner_id=_require_id(current.id),
        title=body.title,
        duration_minutes=body.duration_minutes,
        org_name=body.org_name,
        logo_url=body.logo_url,
        proctored=body.proctored,
        questions=_membership_rows(body.ordered_slots(), current, session),
    )
    session.add(a)
    session.commit()
    session.refresh(a)
    return _assessment_out(a, session)


@app.get("/assessments", response_model=Page[AssessmentOut])
def list_assessments(
    include_archived: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> Page[AssessmentOut]:
    where = [Assessment.owner_id == current.id]
    if not include_archived:
        where.append(Assessment.status == "active")
    total = session.exec(select(func.count()).select_from(Assessment).where(*where)).one()
    stmt = (
        select(Assessment)
        .where(*where)
        .order_by(col(Assessment.created_at).desc(), col(Assessment.id))
        .offset(offset)
        .limit(limit)
    )
    items = [_assessment_out(a, session) for a in session.exec(stmt).all()]
    return Page(items=items, total=total, limit=limit, offset=offset)


@app.get("/assessments/{assessment_id}", response_model=AssessmentOut)
def get_assessment(
    assessment_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> AssessmentOut:
    return _assessment_out(_owned_assessment(assessment_id, current, session), session)


@app.put("/assessments/{assessment_id}", response_model=AssessmentOut)
def update_assessment(
    assessment_id: str,
    body: AssessmentUpdate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> AssessmentOut:
    a = _owned_assessment(assessment_id, current, session)
    # A9: once an invite has gone out (or, transitively, a submission exists),
    # two candidates in the "same" assessment must sit the same slots in the same
    # order — lock the SET, not the whole record. Title/duration/branding stay
    # freely editable; only a real membership/order change 409s. The signature
    # compares each slot's identity (fixed question OR variant set, VS2).
    new_slots = body.ordered_slots()
    current_sig = [(aq.question_id, aq.variant_set_id) for aq in a.questions]
    new_sig = [(s.question_id, s.variant_set_id) for s in new_slots]
    if new_sig != current_sig and _assessment_has_invite(assessment_id, session):
        raise HTTPException(
            status_code=409,
            detail=(
                "this assessment's question set can't change: it has already been sent "
                "as an invite. Create a new assessment instead."
            ),
        )
    a.title = body.title
    a.duration_minutes = body.duration_minutes
    a.org_name = body.org_name
    a.logo_url = body.logo_url
    a.proctored = body.proctored
    a.updated_at = datetime.now(timezone.utc)
    # Full replace of the membership set (PUT). Clear via the relationship and
    # flush FIRST (delete-orphan removes the old rows), so a question kept across
    # the update doesn't collide with its own old row on the
    # (assessment_id, question_id) unique key during a single flush.
    a.questions.clear()
    session.flush()
    a.questions.extend(_membership_rows(new_slots, current, session))
    session.add(a)
    session.commit()
    session.refresh(a)
    return _assessment_out(a, session)


@app.post("/assessments/{assessment_id}/archive", response_model=AssessmentOut)
def archive_assessment(
    assessment_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> AssessmentOut:
    """Retire an assessment: hide it by default while keeping its invites. Idempotent."""
    a = _owned_assessment(assessment_id, current, session)
    a.status = "archived"
    a.updated_at = datetime.now(timezone.utc)
    session.add(a)
    session.commit()
    session.refresh(a)
    return _assessment_out(a, session)


@app.post("/assessments/{assessment_id}/unarchive", response_model=AssessmentOut)
def unarchive_assessment(
    assessment_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> AssessmentOut:
    """Restore an archived assessment. Idempotent."""
    a = _owned_assessment(assessment_id, current, session)
    a.status = "active"
    a.updated_at = datetime.now(timezone.utc)
    session.add(a)
    session.commit()
    session.refresh(a)
    return _assessment_out(a, session)


@app.delete("/assessments/{assessment_id}", status_code=204)
def delete_assessment(
    assessment_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> None:
    """Delete an assessment (and its membership rows). 409 if any invite points at
    it — those invites are live links, so archive instead. The member questions
    are shared and never touched."""
    a = _owned_assessment(assessment_id, current, session)
    invite_count = session.exec(
        select(func.count()).select_from(Invite).where(Invite.assessment_id == assessment_id)
    ).one()
    if invite_count:
        raise HTTPException(
            status_code=409,
            detail=(
                f"cannot delete assessment {assessment_id!r}: {invite_count} invite(s) point at "
                "it. Archive it instead."
            ),
        )
    session.delete(a)
    session.commit()


# --------------------------------------------------------------------------- #
# Invites (interviewer creates a candidate link)                                #
# --------------------------------------------------------------------------- #


@app.post("/questions/{question_id}/invites", response_model=InviteOut, status_code=201)
def create_invite(
    question_id: str,
    body: InviteCreate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> InviteOut:
    question = _owned_question(question_id, current, session)  # 404/403 guard
    invite = Invite(
        token=secrets.token_urlsafe(32),
        question_id=question_id,
        created_by=_require_id(current.id),
        # Normalize on the way in so the start/submit checks can compare directly.
        recipients=[_normalize_email(r) for r in body.recipients],
        expires_at=body.expires_at,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    # Emailing the link is best-effort — a send failure must not undo an invite
    # that already exists — but the per-recipient outcome rides back on the
    # response so the interviewer sees a failure instead of assuming delivery.
    deliveries = email_client.send_invite_emails(
        invite.recipients, _invite_url(invite.token), question.title
    )
    # Persist the per-recipient outcome so it's an audit trail, not just this
    # response. Store after the send so the invite exists even if the send throws.
    invite.deliveries = [
        {"recipient": d.recipient, "sent": d.sent, "error": d.error} for d in deliveries
    ]
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return _invite_out(invite)


@app.get("/questions/{question_id}/invites", response_model=list[InviteOut])
def list_invites(
    question_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> list[InviteOut]:
    _owned_question(question_id, current, session)
    invites = session.exec(
        select(Invite).where(Invite.question_id == question_id)
    ).all()
    return [_invite_out(inv) for inv in invites]


@app.post("/assessments/{assessment_id}/invites", response_model=InviteOut, status_code=201)
def create_assessment_invite(
    assessment_id: str,
    body: InviteCreate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> InviteOut:
    """Invite candidates to a whole assessment (T4). Same shape as the per-question
    invite, but the link opens the ordered multi-question flow."""
    assessment = _owned_assessment(assessment_id, current, session)
    if not assessment.questions:
        raise HTTPException(
            status_code=400, detail="cannot invite to an assessment with no questions."
        )
    invite = Invite(
        token=secrets.token_urlsafe(32),
        assessment_id=assessment_id,
        created_by=_require_id(current.id),
        recipients=[_normalize_email(r) for r in body.recipients],
        expires_at=body.expires_at,
        # Freeze the assessment's monitoring setting onto the sitting (I1); the
        # other two invite paths have no assessment and keep the default True.
        proctored=assessment.proctored,
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    deliveries = email_client.send_invite_emails(
        invite.recipients, _invite_url(invite.token), assessment.title
    )
    invite.deliveries = [
        {"recipient": d.recipient, "sent": d.sent, "error": d.error} for d in deliveries
    ]
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return _invite_out(invite)


@app.get("/assessments/{assessment_id}/invites", response_model=list[InviteOut])
def list_assessment_invites(
    assessment_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> list[InviteOut]:
    _owned_assessment(assessment_id, current, session)
    invites = session.exec(select(Invite).where(Invite.assessment_id == assessment_id)).all()
    return [_invite_out(inv) for inv in invites]


@app.post("/variant-sets/{set_id}/invites", response_model=list[InviteOut], status_code=201)
def create_variant_set_invites(
    set_id: str,
    body: VariantSetInviteCreate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> list[InviteOut]:
    """Invite candidates to a variant set: ONE invite per recipient, each handed a
    variant. Variants rotate round-robin, and the rotation continues from however
    many invites the set already produced, so repeated calls keep the whole set
    evenly used instead of always starting at A. `overrides` (email → variant
    question id) pins a recipient to a chosen variant instead of the rotation. Each
    invite carries `question_id` = its assigned variant, so the candidate flow
    resolves it exactly like a single-question invite."""
    vs = _owned_variant_set(set_id, current, session)
    variants = _set_variants(set_id, session)
    if not variants:
        raise HTTPException(status_code=400, detail="cannot invite to a variant set with no variants.")
    by_id = {q.id: q for q in variants}

    # Continue the rotation across calls (count what this set already handed out).
    cursor = session.exec(
        select(func.count()).select_from(Invite).where(Invite.variant_set_id == set_id)
    ).one()

    created: list[tuple[Invite, str | None]] = []
    for recipient in body.recipients:
        email = _normalize_email(recipient)
        override = body.overrides.get(recipient) or body.overrides.get(email)
        if override is not None:
            if override not in by_id:
                raise HTTPException(
                    status_code=422, detail=f"variant {override!r} is not part of this set."
                )
            chosen = by_id[override]  # a pin does not consume a rotation slot
        else:
            chosen = variants[cursor % len(variants)]
            cursor += 1
        invite = Invite(
            token=secrets.token_urlsafe(32),
            question_id=chosen.id,
            variant_set_id=set_id,
            created_by=_require_id(current.id),
            recipients=[email],
            expires_at=body.expires_at,
        )
        session.add(invite)
        created.append((invite, chosen.variant_label))
    session.commit()

    for invite, _label in created:
        session.refresh(invite)
        deliveries = email_client.send_invite_emails(
            invite.recipients, _invite_url(invite.token), vs.title
        )
        invite.deliveries = [
            {"recipient": d.recipient, "sent": d.sent, "error": d.error} for d in deliveries
        ]
        session.add(invite)
    session.commit()
    return [_invite_out(inv, label) for inv, label in created]


@app.get("/variant-sets/{set_id}/invites", response_model=list[InviteOut])
def list_variant_set_invites(
    set_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> list[InviteOut]:
    _owned_variant_set(set_id, current, session)
    label_of = {q.id: q.variant_label for q in _set_variants(set_id, session)}
    invites = session.exec(select(Invite).where(Invite.variant_set_id == set_id)).all()
    return [
        _invite_out(inv, label_of.get(inv.question_id) if inv.question_id else None)
        for inv in invites
    ]


@app.get("/assessments/{assessment_id}/attempts", response_model=list[AssessmentAttemptOut])
def list_assessment_attempts(
    assessment_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> list[AssessmentAttemptOut]:
    """One row per candidate who has started this assessment (A3): every
    question's result plus a composite (A11) — pass count is the headline,
    average score across graded questions is the secondary detail. An invited
    recipient who never opened the link has no row here (nothing to attempt
    yet); that's still visible via the invite list.
    """
    a = _owned_assessment(assessment_id, current, session)
    return _assessment_attempt_rows(a, session)


def _assessment_attempt_rows(a: Assessment, session: Session) -> list[AssessmentAttemptOut]:
    """The per-candidate, per-slot result assembly shared by the attempts view
    and the analytics endpoint. A variant-set slot resolves to each candidate's
    own assigned variant, so a submission matches via the variant handed to THAT
    candidate, not the slot's set id."""
    slots = list(a.questions)  # ordered by position
    invite_ids = session.exec(
        select(Invite.id).where(Invite.assessment_id == a.id)
    ).all()
    if not invite_ids:
        return []
    # Display data for variant-set slots (VS2): the set's title (stable column
    # header across candidates) and each variant's label. Plus the per-candidate
    # assignment — a set-slot's concrete variant differs by candidate, so a
    # submission matches via the variant handed to THAT candidate, not the slot.
    set_title: dict[int, str] = {}
    label_of: dict[str, str] = {}
    assigned: dict[tuple[int, str, int], str] = {}
    for aq in slots:
        if aq.variant_set_id is not None and aq.id is not None:
            vs = session.get(VariantSet, aq.variant_set_id)
            set_title[aq.id] = vs.title if vs else aq.variant_set_id
            for v in _set_variants(aq.variant_set_id, session):
                label_of[v.id] = v.variant_label or ""
    for csv_row in session.exec(
        select(CandidateSlotVariant).where(
            col(CandidateSlotVariant.invite_id).in_(invite_ids)
        )
    ).all():
        assigned[
            (csv_row.invite_id, csv_row.candidate_email, csv_row.assessment_question_id)
        ] = csv_row.question_id
    attempts = session.exec(
        select(CandidateAttempt)
        .where(col(CandidateAttempt.invite_id).in_(invite_ids))
        .order_by(col(CandidateAttempt.started_at))
    ).all()
    # candidate_email is nullable on Submission only for the interviewer's
    # direct (non-invite) path; every row here came through an invite, whose
    # /submit route always sets it — the `is not None` narrows for mypy.
    subs = [
        s
        for s in session.exec(
            select(Submission).where(col(Submission.invite_id).in_(invite_ids))
        ).all()
        if s.candidate_email is not None
    ]
    results = _results_by_submission(subs, session)
    # Integrity signals per candidate across this assessment's invites (I1), so
    # the grid can flag who is worth opening — including a candidate who tripped
    # signals and never submitted, who has no submission to read a report from.
    signals: dict[str, int] = {}
    blocked: dict[str, int] = {}
    candidate_events: dict[str, list[IntegrityEvent]] = {}
    monitored_invites = {
        i_id
        for i_id in invite_ids
        if (inv := session.get(Invite, i_id)) is not None and inv.proctored
    }
    for ev in session.exec(
        select(IntegrityEvent).where(col(IntegrityEvent.invite_id).in_(invite_ids))
    ).all():
        signals[ev.candidate_email] = signals.get(ev.candidate_email, 0) + 1
        candidate_events.setdefault(ev.candidate_email, []).append(ev)
        if ev.kind == "paste_external" and ev.blocked:
            blocked[ev.candidate_email] = blocked.get(ev.candidate_email, 0) + 1
    # (candidate_email, question_id) -> the submission's result / id / late flag.
    graded: dict[tuple[str, str], AssessmentResult] = {}
    submission_id_by_pair: dict[tuple[str, str], str] = {}
    late_by_pair: dict[tuple[str, str], bool] = {}
    for s in subs:
        assert s.candidate_email is not None  # filtered above
        submission_id_by_pair[(s.candidate_email, s.question_id)] = s.id
        late_by_pair[(s.candidate_email, s.question_id)] = s.late
        r = results.get(s.id)
        if r is not None:
            graded[(s.candidate_email, s.question_id)] = r

    out = []
    for attempt in attempts:
        q_rows = []
        graded_scores: list[float] = []
        passed = 0
        for aq in slots:
            if aq.variant_set_id is not None:
                # This candidate's assigned variant for the set-slot (may be absent
                # if they never resolved it, e.g. never started — show it unfilled).
                qid = assigned.get(
                    (attempt.invite_id, attempt.candidate_email, aq.id)
                ) if aq.id is not None else None
                title = set_title.get(aq.id or -1, aq.variant_set_id)
                variant_label = label_of.get(qid) if qid else None
                variant_set_id = aq.variant_set_id
            else:
                qid = aq.question_id
                title = aq.question.title if aq.question else (aq.question_id or "")
                variant_label = None
                variant_set_id = None
            r = graded.get((attempt.candidate_email, qid)) if qid else None
            if r is not None:
                graded_scores.append(r.score_pct)
                if r.verdict == "PASS":
                    passed += 1
            submitted = bool(qid and (attempt.candidate_email, qid) in submission_id_by_pair)
            q_rows.append(
                AssessmentAttemptQuestionOut(
                    question_id=qid,
                    variant_set_id=variant_set_id,
                    variant_label=variant_label,
                    title=title,
                    submitted=submitted,
                    late=late_by_pair.get((attempt.candidate_email, qid), False) if qid else False,
                    submission_id=submission_id_by_pair.get((attempt.candidate_email, qid))
                    if qid
                    else None,
                    verdict=r.verdict if r else None,
                    score_pct=r.score_pct if r else None,
                )
            )
        out.append(
            AssessmentAttemptOut(
                candidate_name=attempt.candidate_name or attempt.candidate_email,
                candidate_email=attempt.candidate_email,
                questions=q_rows,
                passed_count=passed,
                total_count=len(slots),
                avg_score_pct=(
                    sum(graded_scores) / len(graded_scores) if graded_scores else None
                ),
                # None (not 0) when this candidate's sitting wasn't monitored —
                # "nothing recorded" and "nothing to record" must not look alike.
                integrity_signals=(
                    signals.get(attempt.candidate_email, 0)
                    if attempt.invite_id in monitored_invites
                    else None
                ),
                integrity_blocked=blocked.get(attempt.candidate_email, 0),
                # Same null semantics as the count: a level exists only for a
                # monitored sitting (a quiet one reads "none", not null).
                integrity_risk=(
                    integrity.risk_level(
                        integrity.risk_score(
                            list(candidate_events.get(attempt.candidate_email, []))
                        )[0]
                    )
                    if attempt.invite_id in monitored_invites
                    else None
                ),
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Analytics (AR1) — aggregate stats over the caller's own questions/results.   #
# Read-only rollups; the maths lives in `analytics.py` (DB-free, unit-tested). #
# --------------------------------------------------------------------------- #


def _since_cutoff(days: int | None) -> datetime | None:
    """The lower bound for a `?days=N` analytics window (submissions created on or
    after now-N days), or None for the all-time view when the param is absent."""
    if days is None:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def _within(subs: Sequence[Submission], cutoff: datetime | None) -> list[Submission]:
    """Submissions created at or after `cutoff` (all of them when it's None)."""
    if cutoff is None:
        return list(subs)
    return [s for s in subs if as_utc(s.created_at) >= cutoff]


def _attempt_starts(
    subs: Sequence[Submission], session: Session
) -> dict[tuple[int, str], datetime]:
    """`(invite_id, candidate_email) -> CandidateAttempt.started_at` for the
    submissions that came through an invite, in one query — the clock start used
    to derive time-to-solve. Direct (non-invite) submissions have no attempt row
    and are simply absent."""
    keys = {
        (s.invite_id, s.candidate_email)
        for s in subs
        if s.invite_id is not None and s.candidate_email is not None
    }
    if not keys:
        return {}
    invite_ids = {k[0] for k in keys}
    attempts = session.exec(
        select(CandidateAttempt).where(col(CandidateAttempt.invite_id).in_(invite_ids))
    ).all()
    return {(at.invite_id, at.candidate_email): as_utc(at.started_at) for at in attempts}


@app.get("/analytics/overview", response_model=OverviewAnalyticsOut)
def analytics_overview(
    days: int | None = Query(default=None, ge=1, le=3650),
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> OverviewAnalyticsOut:
    """Workspace rollup across all of the caller's questions: headline counts,
    overall pass rate / average score, and a daily submission trend. `days`
    windows the submission-derived stats (counts/rate/score/trend) to the last N
    days; the question count is the current library size, not time-scoped."""
    _reap_stale_running(session)
    question_count = session.exec(
        select(func.count())
        .select_from(Question)
        .where(
            Question.owner_id == current.id,
            Question.status == "active",
            col(Question.variant_set_id).is_(None),
        )
    ).one()
    cutoff = _since_cutoff(days)
    subs = _within(
        session.exec(
            select(Submission).join(Question).where(Question.owner_id == current.id)
        ).all(),
        cutoff,
    )
    results = _results_by_submission(subs, session)
    graded = passed = 0
    scores: list[float] = []
    candidates: set[str] = set()
    events: list[tuple[datetime, bool, bool]] = []
    for s in subs:
        if s.candidate_email:
            candidates.add(s.candidate_email)
        r = results.get(s.id)
        is_graded = r is not None
        is_passed = bool(r and r.verdict == "PASS")
        if is_graded:
            graded += 1
            scores.append(r.score_pct)  # type: ignore[union-attr]
            if is_passed:
                passed += 1
        events.append((as_utc(s.created_at), is_graded, is_passed))
    return OverviewAnalyticsOut(
        questions=question_count,
        submissions=len(subs),
        graded=graded,
        candidates=len(candidates),
        passed=passed,
        pass_rate=analytics.rate(passed, graded),
        avg_score_pct=analytics.mean(scores),
        trend=[TrendPointOut(**p) for p in analytics.daily_series(events)],
        score_distribution=[
            ScoreBucketOut(**bucket) for bucket in analytics.score_distribution(scores)
        ],
    )


@app.get("/analytics/questions", response_model=Page[QuestionAnalyticsOut])
def analytics_questions(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    days: int | None = Query(default=None, ge=1, le=3650),
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> Page[QuestionAnalyticsOut]:
    """Per-question stats (the numbers the plain question list lacked). Scoped to
    the caller's active, standalone questions — variant-set members are excluded
    (they're hidden from the library, VS1). `days` windows the stats to the last N
    days (the question rows themselves are the whole library). Paginated like
    `/submissions`."""
    _reap_stale_running(session)
    where = (
        Question.owner_id == current.id,
        Question.status == "active",
        col(Question.variant_set_id).is_(None),
    )
    total = session.exec(select(func.count()).select_from(Question).where(*where)).one()
    questions = session.exec(
        select(Question)
        .where(*where)
        .order_by(col(Question.created_at).desc(), col(Question.id))
        .offset(offset)
        .limit(limit)
    ).all()
    qids = [q.id for q in questions]
    subs = (
        _within(
            session.exec(
                select(Submission).where(col(Submission.question_id).in_(qids))
            ).all(),
            _since_cutoff(days),
        )
        if qids
        else []
    )
    results = _results_by_submission(subs, session)
    starts = _attempt_starts(subs, session)

    # question_id -> accumulators
    agg: dict[str, dict[str, Any]] = {
        qid: {"subs": 0, "graded": 0, "passed": 0, "late": 0, "scores": [], "tts": []}
        for qid in qids
    }
    for s in subs:
        b = agg[s.question_id]
        b["subs"] += 1
        if s.late:
            b["late"] += 1
        r = results.get(s.id)
        if r is not None:
            b["graded"] += 1
            b["scores"].append(r.score_pct)
            if r.verdict == "PASS":
                b["passed"] += 1
        start = (
            starts.get((s.invite_id, s.candidate_email))
            if s.invite_id is not None and s.candidate_email is not None
            else None
        )
        tts = analytics.time_to_solve_seconds(start, as_utc(s.created_at))
        if tts is not None:
            b["tts"].append(tts)

    items = []
    for q in questions:
        b = agg[q.id]
        items.append(
            QuestionAnalyticsOut(
                question_id=q.id,
                title=q.title,
                difficulty=q.difficulty,
                submissions=b["subs"],
                graded=b["graded"],
                passed=b["passed"],
                pass_rate=analytics.rate(b["passed"], b["graded"]),
                avg_score_pct=analytics.mean(b["scores"]),
                median_score_pct=analytics.median_value(b["scores"]),
                late=b["late"],
                avg_time_to_solve_s=analytics.mean(b["tts"]),
                median_time_to_solve_s=analytics.median_value(b["tts"]),
            )
        )
    return Page(items=items, total=total, limit=limit, offset=offset)


@app.get("/analytics/assessments/{assessment_id}", response_model=AssessmentAnalyticsOut)
def analytics_assessment(
    assessment_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> AssessmentAnalyticsOut:
    """Cross-candidate rollup for one assessment: each candidate's standing
    (rank/percentile over graded candidates, whole-sitting time-to-solve) plus
    completion and a score distribution. Reuses the attempts assembly so the
    per-candidate scores stay consistent with the results view."""
    a = _owned_assessment(assessment_id, current, session)
    rows = _assessment_attempt_rows(a, session)

    invite_ids = session.exec(
        select(Invite.id).where(Invite.assessment_id == a.id)
    ).all()
    # Whole-sitting time-to-solve: earliest attempt start -> latest submission,
    # per candidate email across this assessment's invites.
    started_by_email: dict[str, datetime] = {}
    if invite_ids:
        for at in session.exec(
            select(CandidateAttempt).where(col(CandidateAttempt.invite_id).in_(invite_ids))
        ).all():
            cur = started_by_email.get(at.candidate_email)
            start = as_utc(at.started_at)
            if cur is None or start < cur:
                started_by_email[at.candidate_email] = start
    last_submit_by_email: dict[str, datetime] = {}
    if invite_ids:
        for s in session.exec(
            select(Submission).where(col(Submission.invite_id).in_(invite_ids))
        ).all():
            if s.candidate_email is None:
                continue
            end = as_utc(s.created_at)
            cur = last_submit_by_email.get(s.candidate_email)
            if cur is None or end > cur:
                last_submit_by_email[s.candidate_email] = end

    population = [r.avg_score_pct for r in rows if r.avg_score_pct is not None]
    slot_count = len(a.questions)
    completed = sum(
        1 for r in rows if r.questions and all(q.submitted for q in r.questions)
    )
    graded_qa = sum(1 for r in rows for q in r.questions if q.verdict is not None)
    passed_qa = sum(r.passed_count for r in rows)

    candidates = []
    for r in rows:
        rank = percentile = None
        if r.avg_score_pct is not None:
            rank, percentile = analytics.rank_and_percentile(r.avg_score_pct, population)
        candidates.append(
            AssessmentCandidateAnalyticsOut(
                candidate_name=r.candidate_name,
                candidate_email=r.candidate_email,
                passed_count=r.passed_count,
                submitted_count=sum(1 for q in r.questions if q.submitted),
                total_count=r.total_count,
                avg_score_pct=r.avg_score_pct,
                rank=rank,
                percentile=percentile,
                time_to_solve_s=analytics.time_to_solve_seconds(
                    started_by_email.get(r.candidate_email),
                    last_submit_by_email.get(r.candidate_email),
                ),
            )
        )
    return AssessmentAnalyticsOut(
        assessment_id=a.id,
        title=a.title,
        slot_count=slot_count,
        candidates_started=len(rows),
        candidates_completed=completed,
        avg_score_pct=analytics.mean(population),
        pass_rate=analytics.rate(passed_qa, graded_qa),
        score_distribution=[
            ScoreBucketOut(**bucket) for bucket in analytics.score_distribution(population)
        ],
        candidates=candidates,
    )


@app.post("/questions/{question_id}/invites/{token}/revoke", response_model=InviteOut)
def revoke_invite(
    question_id: str,
    token: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> InviteOut:
    """Deactivate an invite so its link stops working (candidate view/submit 410)."""
    _owned_question(question_id, current, session)  # 404/403 guard
    invite = session.exec(
        select(Invite).where(Invite.token == token, Invite.question_id == question_id)
    ).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="invalid invite token.")
    invite.status = "revoked"
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return _invite_out(invite)


# --------------------------------------------------------------------------- #
# Candidate (public, token-gated — NO bearer). MUST NOT leak test cases.        #
# --------------------------------------------------------------------------- #


def _load_invite_or_error(token: str, session: Session) -> Invite:
    """Resolve a candidate token: 404 if unknown, 410 if expired or revoked."""
    invite = session.exec(select(Invite).where(Invite.token == token)).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="invalid invite token.")
    if invite.status != "active":
        raise HTTPException(status_code=410, detail="this invite is no longer active.")
    if _is_expired(invite.expires_at):
        raise HTTPException(status_code=410, detail="this invite has expired.")
    return invite


def _check_invited(invite: Invite, email: str) -> None:
    """403 unless `email` is one of the invite's recipients (case-insensitive).

    This binds a link to the people it was sent to: forwarding it to someone else
    no longer gets them into the assessment. It is an identity *claim*, not proof
    — anyone holding the link who knows an invited address could still type it —
    so it stops accidental sharing, not deliberate impersonation. Per-recipient
    tokens or an emailed OTP would be the stronger form.
    """
    if email not in {_normalize_email(r) for r in invite.recipients}:
        raise HTTPException(
            status_code=403,
            detail="this assessment was not sent to that email address.",
        )


# Both the pre-insert check and the unique-constraint backstop answer a duplicate
# attempt identically — the candidate must not be able to tell which one caught
# them, and one message means the two cannot drift apart.
_ALREADY_SUBMITTED_DETAIL = "your assessment has already been recorded for this email address."


def _check_not_already_submitted(
    invite: Invite, email: str, question_id: str, session: Session
) -> None:
    """409 if `email` already submitted THIS question on this invite (one attempt
    per candidate per question — T4).

    The fast path only: it is a SELECT before an INSERT, so it cannot stop two
    concurrent submits from both passing. The uq_submission_invite_candidate_question
    constraint is what actually enforces the rule; this just turns the common,
    uncontended case into a clean 409 instead of a caught IntegrityError.
    """
    already = session.exec(
        select(Submission).where(
            Submission.invite_id == invite.id,
            Submission.candidate_email == email,
            Submission.question_id == question_id,
        )
    ).first()
    if already is not None:
        raise HTTPException(status_code=409, detail=_ALREADY_SUBMITTED_DETAIL)


def _resolve_slot_variant(
    invite: Invite, aq: AssessmentQuestion, email: str, session: Session
) -> Question:
    """The concrete variant this candidate gets for a variant-set slot (VS2),
    frozen on first call and stable afterwards. Round-robin across the
    assessment's candidates (count of prior assignments for this slot) so the pool
    stays evenly used. The (invite, email, slot) unique key makes the get-or-create
    race-safe, like `_get_or_start_attempt`; it never touches the clock."""
    key = (
        CandidateSlotVariant.invite_id == invite.id,
        CandidateSlotVariant.candidate_email == email,
        CandidateSlotVariant.assessment_question_id == aq.id,
    )
    existing = session.exec(select(CandidateSlotVariant).where(*key)).first()
    if existing is not None:
        q = session.get(Question, existing.question_id)
        if q is not None:
            return q  # a deleted variant falls through to a fresh assignment
    assert aq.variant_set_id is not None  # caller only passes set-slots
    variants = _set_variants(aq.variant_set_id, session)
    if not variants:
        raise HTTPException(
            status_code=404, detail="a variant set in this assessment has no variants."
        )
    cursor = session.exec(
        select(func.count())
        .select_from(CandidateSlotVariant)
        .where(CandidateSlotVariant.assessment_question_id == aq.id)
    ).one()
    chosen = variants[cursor % len(variants)]
    row = CandidateSlotVariant(
        invite_id=_require_id(invite.id),
        candidate_email=email,
        assessment_question_id=_require_id(aq.id),
        question_id=chosen.id,
    )
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = session.exec(select(CandidateSlotVariant).where(*key)).first()
        if raced is None:  # pragma: no cover — the constraint guarantees a row here
            raise
        q = session.get(Question, raced.question_id)
        assert q is not None  # just-written variant exists
        return q
    return chosen


def _invite_questions(
    invite: Invite, session: Session, email: str | None = None
) -> list[Question]:
    """The ordered questions this invite presents to `email`: an assessment's slots
    (T4) or a legacy invite's single question. A variant-set slot (VS2) resolves to
    this candidate's assigned variant — so the list is per-candidate. 404 if a
    referenced thing is gone. `email` is required to resolve a set-slot; without it
    (should not happen on a candidate path) a set-slot falls back to its first
    variant so nothing crashes."""
    if invite.assessment_id is not None:
        a = session.get(Assessment, invite.assessment_id)
        if a is None:
            raise HTTPException(status_code=404, detail="this assessment no longer exists.")
        qs: list[Question] = []
        for aq in a.questions:
            if aq.variant_set_id is not None:
                if email is not None:
                    qs.append(_resolve_slot_variant(invite, aq, email, session))
                else:
                    pool = _set_variants(aq.variant_set_id, session)
                    if pool:
                        qs.append(pool[0])
            elif aq.question is not None:
                qs.append(aq.question)
        if not qs:
            raise HTTPException(status_code=404, detail="this assessment has no questions.")
        return qs
    q = session.get(Question, invite.question_id) if invite.question_id else None
    if q is None:
        raise HTTPException(status_code=404, detail="the question for this invite no longer exists.")
    return [q]


def _invite_duration(invite: Invite, session: Session) -> int | None:
    """Total time budget for the sitting: the assessment's (T4) or, for a legacy
    invite, the single question's. None = untimed."""
    if invite.assessment_id is not None:
        a = session.get(Assessment, invite.assessment_id)
        return a.duration_minutes if a else None
    q = session.get(Question, invite.question_id) if invite.question_id else None
    return q.duration_minutes if q else None


def _resolve_question(
    invite: Invite, question_id: str | None, email: str, session: Session
) -> Question:
    """The question a run/submit targets for `email`. `question_id` None targets the
    single question of a legacy invite; for a multi-question assessment it is
    required and must name one of the candidate's questions — for a variant-set slot
    (VS2) that is the variant assigned to this candidate, so it must be resolved
    against this candidate's own question list."""
    questions = _invite_questions(invite, session, email)
    if question_id is None:
        if len(questions) == 1:
            return questions[0]
        raise HTTPException(
            status_code=400, detail="question_id is required for a multi-question assessment."
        )
    for q in questions:
        if q.id == question_id:
            return q
    raise HTTPException(status_code=404, detail="that question is not part of this invite.")


def _deadline_for(started_at: datetime, duration_minutes: int | None) -> datetime | None:
    """Absolute submit deadline for a timed attempt, or None when untimed."""
    if duration_minutes is None:
        return None
    return as_utc(started_at) + timedelta(minutes=duration_minutes)


def _get_or_start_attempt(
    invite: Invite, email: str, session: Session, *, candidate_name: str | None = None
) -> CandidateAttempt:
    """Return this candidate's attempt for the invite, creating it (stamping
    started_at = now, and candidate_name if given — A10) on first call.
    started_at is never moved once set, so re-opening the link can't reset a
    timed assessment's clock. candidate_name is filled in **once** if the
    existing row doesn't have one yet (e.g. /start ran before any client sent a
    name) — this is a one-time backfill of a blank, not overwriting an
    already-set name, so a later resubmission still can't rename the sitting.
    The unique constraint makes the get-or-create race-safe: a loser re-reads
    the winner's row.
    """
    existing = session.exec(
        select(CandidateAttempt).where(
            CandidateAttempt.invite_id == invite.id,
            CandidateAttempt.candidate_email == email,
        )
    ).first()
    if existing is not None:
        if existing.candidate_name is None and candidate_name is not None:
            existing.candidate_name = candidate_name
            existing.updated_at = datetime.now(timezone.utc)
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return existing
    attempt = CandidateAttempt(
        invite_id=_require_id(invite.id), candidate_email=email, candidate_name=candidate_name
    )
    session.add(attempt)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raced = session.exec(
            select(CandidateAttempt).where(
                CandidateAttempt.invite_id == invite.id,
                CandidateAttempt.candidate_email == email,
            )
        ).first()
        if raced is None:  # pragma: no cover — the constraint guarantees a row here
            raise
        return raced
    session.refresh(attempt)
    return attempt


def _submit_is_late(invite: Invite, attempt: CandidateAttempt, session: Session) -> bool:
    """Whether a submit arriving now is past the sitting's window — recorded but
    flagged, no longer rejected, so a candidate's actual work is never discarded
    (the client auto-submits at the buzzer for exactly this reason).

    Server-authoritative: the deadline is `attempt.started_at` (stamped at /start)
    + the invite's total duration (the assessment's, or a legacy question's), plus
    a grace window that absorbs the auto-submit round-trip — a submit inside grace
    counts as on-time. Always False for an untimed sitting. Note the invite's own
    lifecycle (revoked / expired) is enforced separately in `_load_invite_or_error`
    and still hard-blocks a submit; only the per-candidate timer is relaxed here.
    """
    duration = _invite_duration(invite, session)
    if duration is None:
        return False
    deadline = _deadline_for(attempt.started_at, duration)
    assert deadline is not None  # duration is not None here
    return datetime.now(timezone.utc) > deadline + timedelta(seconds=config.SUBMIT_GRACE_SECONDS)


def _candidate_question_view(
    invite: Invite, session: Session, attempt: CandidateAttempt | None = None
) -> InvitePublicOut:
    # Candidate-facing view only — never expose test_cases or expected outputs.
    # Pass the candidate's email so a variant-set slot (VS2) resolves (and freezes)
    # to this candidate's own variant; None before /start just lists placeholders.
    email = attempt.candidate_email if attempt is not None else None
    questions = _invite_questions(invite, session, email)
    deadline = _deadline_for(attempt.started_at, _invite_duration(invite, session)) if attempt else None
    # Which of these questions this candidate has already submitted, so the UI can
    # mark them done and lock their editors.
    submitted_ids: set[str] = set()
    if attempt is not None:
        submitted_ids = set(
            session.exec(
                select(Submission.question_id).where(
                    Submission.invite_id == invite.id,
                    Submission.candidate_email == attempt.candidate_email,
                )
            ).all()
        )
    public = [
        CandidateQuestionPublic(
            id=q.id,
            title=q.title,
            prompt=q.prompt,
            constraints=q.constraints,
            example_input=q.example_input,
            example_output=q.example_output,
            time_limit_s=q.time_limit_s,
            submitted=q.id in submitted_ids,
        )
        for q in questions
    ]
    first = questions[0]
    return InvitePublicOut(
        # Legacy singular view = the first question (keeps the pre-T4 UI working).
        question=CandidateQuestionView(
            title=first.title,
            prompt=first.prompt,
            constraints=first.constraints,
            example_input=first.example_input,
            example_output=first.example_output,
            time_limit_s=first.time_limit_s,
        ),
        questions=public,
        languages=config.SUPPORTED_LANGUAGES,
        deadline=deadline,
        # Per-assessment branding (A12) — None for a legacy single-question
        # invite or an unbranded assessment; the candidate UI falls back to a
        # generic header in either case.
        assessment_title=invite.assessment.title if invite.assessment else None,
        org_name=invite.assessment.org_name if invite.assessment else None,
        logo_url=invite.assessment.logo_url if invite.assessment else None,
        # Integrity monitoring (I1), frozen on the invite when it was minted.
        proctored=invite.proctored,
    )


@app.get("/invite/{token}", response_model=InviteStatusOut)
def get_invite(token: str, session: Session = Depends(get_session)) -> InviteStatusOut:
    """Liveness probe for the link: 404 if unknown, 410 if revoked/expired.

    Returns no question data on purpose. The problem is only handed out by
    `POST /invite/{token}/start`, once the caller has identified as an invited
    recipient — otherwise the email check below would be decorative, since anyone
    with the link could just read the question straight off this endpoint.
    """
    invite = _load_invite_or_error(token, session)
    # Whether this sitting is monitored (I1) — needed before /start so the gate
    # screen can disclose it up front. Read from the invite's own frozen
    # snapshot, so it says what this sitting will actually do.
    return InviteStatusOut(status="active", proctored=invite.proctored)


@app.post("/invite/{token}/start", response_model=InvitePublicOut)
def start_invite(
    token: str,
    body: CandidateStartIn,
    request: Request,
    session: Session = Depends(get_session),
) -> InvitePublicOut:
    """Identify as an invited recipient and receive the question.

    Rate-limited because it is an oracle: without a limit it would let a link
    holder enumerate which addresses were invited (403 vs 200) or which have
    already finished (409).
    """
    limiter.check(
        "start", client_ip(request), config.SUBMIT_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S
    )
    invite = _load_invite_or_error(token, session)
    email = _normalize_email(body.candidate_email)
    _check_invited(invite, email)
    # A legacy single-question invite is one attempt: block re-entry once submitted.
    # A multi-question assessment invite lets the candidate return to finish other
    # questions — the view carries per-question submitted status instead.
    if invite.assessment_id is None and invite.question_id is not None:
        _check_not_already_submitted(invite, email, invite.question_id, session)
    # Stamp (or re-read) the clock start for this candidate, so the returned
    # deadline is stable across reloads and device switches. candidate_name is
    # anchored the same way (A10) — ignored on re-entry once already set.
    attempt = _get_or_start_attempt(invite, email, session, candidate_name=body.candidate_name)
    return _candidate_question_view(invite, session, attempt)


def _load_invite_for_candidate(
    token: str, email: str, question_id: str | None, session: Session
) -> tuple[Invite, Question]:
    """Shared guard for the candidate's in-editor actions (run / run-tests).

    Same gates as /start: the link must be live, the caller must be an invited
    recipient, and they must not have submitted THIS question already. Without
    this, anyone holding the link could burn agent compute for free.
    """
    invite = _load_invite_or_error(token, session)
    _check_invited(invite, email)
    question = _resolve_question(invite, question_id, email, session)
    _check_not_already_submitted(invite, email, question.id, session)
    return invite, question


async def _agent_run_call(what: str, call: Callable[[], Awaitable[dict]]) -> dict:
    """Await an agent run call, mapping its failures to ours."""
    try:
        return await call()
    except httpx.HTTPStatusError as exc:
        # The agent rejected the request (e.g. unsupported language) — pass its
        # reason through as a 400 rather than a blank 502.
        if exc.response.status_code == 400:
            raise HTTPException(status_code=400, detail=_agent_detail(exc)) from exc
        raise HTTPException(status_code=502, detail=f"{what} failed: {exc}") from exc
    except Exception as exc:  # agent unreachable / timed out
        raise HTTPException(status_code=502, detail=f"{what} failed: {exc}") from exc


@app.post("/invite/{token}/run", response_model=CandidateRunOut)
async def candidate_run(
    token: str,
    body: CandidateRunIn,
    request: Request,
    session: Session = Depends(get_session),
) -> CandidateRunOut:
    """Run the candidate's code against their own stdin and return its output.

    Not a submission: nothing is stored and it does not consume their one
    attempt. Rate-limited because it is free, unmetered compute on the agent.
    """
    limiter.check("run", client_ip(request), config.RUN_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S)
    email = _normalize_email(body.candidate_email)
    _load_invite_for_candidate(token, email, body.question_id, session)

    result = await _agent_run_call(
        "run", lambda: agent_client.run_code(body.code, body.language, body.stdin)
    )
    if result.get("infra_error"):
        # The agent couldn't run this language at all — our problem, not theirs.
        raise HTTPException(status_code=502, detail=f"run failed: {result['infra_error']}")
    return CandidateRunOut(
        stdout=result.get("stdout", ""),
        stderr=result.get("stderr"),
        duration_s=result.get("duration_s", 0.0),
        timed_out=bool(result.get("timed_out")),
        compile_error=result.get("compile_error"),
    )


@app.post("/invite/{token}/run-tests", response_model=CandidateRunTestsOut)
async def candidate_run_tests(
    token: str,
    body: CandidateRunTestsIn,
    request: Request,
    session: Session = Depends(get_session),
) -> CandidateRunTestsOut:
    """Run the question's test suite and report pass/fail per case.

    The candidate's rehearsal before submitting: they learn how many cases pass,
    never what the cases are. The agent already withholds the I/O on this path;
    we drop the case *names* too and identify cases positionally, so nothing
    about the answer key reaches the candidate.

    Not a submission — nothing stored, their attempt is untouched.
    """
    limiter.check("run", client_ip(request), config.RUN_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S)
    email = _normalize_email(body.candidate_email)
    _, question = _load_invite_for_candidate(token, email, body.question_id, session)

    result = await _agent_run_call(
        "run-tests", lambda: agent_client.run_tests(question, body.code, body.language)
    )
    if result.get("infra_error"):
        raise HTTPException(status_code=502, detail=f"run-tests failed: {result['infra_error']}")

    cases = [
        CandidateTestOutcomeOut(
            index=i,
            category=c.get("category", "correctness"),
            status=c.get("status", "FAIL"),
            duration_s=c.get("duration_s", 0.0),
        )
        for i, c in enumerate(result.get("test_cases", []), start=1)
    ]
    return CandidateRunTestsOut(
        total=len(cases),
        passed=sum(1 for c in cases if c.status == "PASS"),
        compile_error=result.get("compile_error"),
        test_cases=cases,
    )


@app.post("/invite/{token}/submit", response_model=CandidateSubmitOut, status_code=201)
async def candidate_submit(
    token: str,
    body: CandidateSubmitIn,
    request: Request,
    session: Session = Depends(get_session),
) -> CandidateSubmitOut:
    limiter.check(
        "submit", client_ip(request), config.SUBMIT_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S
    )
    invite = _load_invite_or_error(token, session)
    # Re-check the gates here, not just in /start: the start screen is only UI, so a
    # caller can POST straight to this route and skip it.
    email = _normalize_email(body.candidate_email)
    _check_invited(invite, email)
    # Which question this submits (the single one for a legacy invite; a named one
    # for an assessment — the candidate's assigned variant for a set-slot). One
    # attempt per (invite, candidate, question).
    question = _resolve_question(invite, body.question_id, email, session)
    _check_not_already_submitted(invite, email, question.id, session)
    # Anchor identity once per (invite, email) — A10: the attempt's stored name
    # always wins once set (from the first /start or, lacking that, this first
    # /submit), so a later resubmission with a differently-typed name can't
    # fork one candidate's sitting into inconsistently-labeled rows.
    attempt = _get_or_start_attempt(invite, email, session, candidate_name=body.candidate_name)
    # Timed sitting: a submit past the window is RECORDED (flagged late), not
    # discarded — the candidate's work always counts; the flag lets the
    # interviewer weigh it. No-op (late=False) for an untimed sitting.
    late = _submit_is_late(invite, attempt, session)

    sub = Submission(
        id=uuid.uuid4().hex,
        question_id=question.id,
        invite_id=invite.id,
        candidate=attempt.candidate_name or body.candidate_name,
        candidate_email=email,
        language=body.language,
        code=body.code,
        status="pending",
        late=late,
    )
    session.add(sub)
    try:
        session.commit()
    except IntegrityError as exc:
        # Lost the race: a concurrent submit for this (invite, candidate) committed
        # between our check above and this insert, and the unique constraint caught
        # what the check structurally cannot. Same answer either way — one attempt.
        session.rollback()
        raise HTTPException(status_code=409, detail=_ALREADY_SUBMITTED_DETAIL) from exc
    session.refresh(sub)

    sub = await _trigger_agent(session, question, sub)
    return CandidateSubmitOut(submission_id=sub.id, status=sub.status)


@app.post("/invite/{token}/events", status_code=204)
def candidate_integrity_events(
    token: str,
    body: IntegrityEventsIn,
    request: Request,
    session: Session = Depends(get_session),
) -> Response:
    """Record a batch of integrity signals from the candidate's browser (I1).

    Same identity gates as the rest of the candidate surface (live link + invited
    recipient), but deliberately NOT gated on "hasn't submitted yet": the last
    batch of a sitting is flushed alongside the submit, and a signal that arrives
    a moment late is still worth keeping. It also never creates a
    `CandidateAttempt` — recording that someone switched tabs must not start
    anyone's clock — so signals from a candidate who never called /start are
    accepted with offsets measured from zero.

    Returns 204: the candidate UI fires this in the background and has nothing to
    do with a response body. Rate-limited on the submit bucket, since it is an
    unauthenticated write.
    """
    limiter.check(
        "events", client_ip(request), config.SUBMIT_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S
    )
    invite = _load_invite_or_error(token, session)
    email = _normalize_email(body.candidate_email)
    _check_invited(invite, email)

    # Clamp client-reported offsets to the window the server can actually vouch
    # for — [0, time since this candidate's attempt started]. A forged offset can
    # still land anywhere inside a real sitting, but it can't place an event
    # before the start or hours after it. No attempt yet ⇒ nothing elapsed.
    attempt = session.exec(
        select(CandidateAttempt).where(
            CandidateAttempt.invite_id == invite.id,
            CandidateAttempt.candidate_email == email,
        )
    ).first()
    elapsed_ms = 0
    if attempt is not None:
        started = as_utc(attempt.started_at)
        elapsed_ms = max(0, int((datetime.now(timezone.utc) - started).total_seconds() * 1000))

    for ev in body.events:
        session.add(
            IntegrityEvent(
                invite_id=invite.id,
                candidate_email=email,
                question_id=body.question_id,
                kind=ev.kind,
                offset_ms=min(ev.offset_ms, elapsed_ms),
                duration_ms=ev.duration_ms,
                size=ev.size,
                blocked=ev.blocked,
            )
        )
    session.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------- #
# Submissions                                                                   #
# --------------------------------------------------------------------------- #


async def _trigger_agent(session: Session, question: Question, sub: Submission) -> Submission:
    """Trigger an agent job for `sub` and persist the outcome.

    Shared by the initial submit and the manual retry: on success sets the new
    agent_job_id and flips status to "running"; on failure flips to "error" and
    raises 502 (submission left in "error"). The caller must have already looked
    up the question.
    """
    callback_url = f"{PLATFORM_BASE_URL}/assessments/callback"
    try:
        job_id = await agent_client.trigger_assessment(question, sub, callback_url)
    except Exception as exc:  # agent unreachable / rejected the job
        sub.status = "error"
        session.add(sub)
        session.commit()
        session.refresh(sub)
        logger.warning("submission %s: agent trigger failed: %s", sub.id, exc)
        raise HTTPException(status_code=502, detail=f"agent call failed: {exc}") from exc

    sub.agent_job_id = job_id
    sub.status = "running"
    session.add(sub)
    session.commit()
    session.refresh(sub)
    # Correlation breadcrumb: ties this submission to the agent job so a later
    # callback (or a reap) can be traced back through the logs by either id.
    logger.info("submission %s triggered agent job %s (status=running)", sub.id, job_id)
    return sub


def _reap_stale_running(session: Session) -> list[str]:
    """Flip submissions stuck in "running" past the grace window to "error".

    A submission is "running" from the agent's 202 until its callback lands; if the
    callback never arrives the row is stranded and retry (error-only) can't recover
    it. Called on the interviewer read paths, so viewing the dashboard heals
    stranded attempts. Only `status` changes — `agent_job_id` is left intact, so a
    late callback still matches and can still land its result. Returns the reaped
    submission ids. Reaping is disabled when REAP_RUNNING_AFTER_S <= 0.
    """
    if config.REAP_RUNNING_AFTER_S <= 0:
        return []
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=config.REAP_RUNNING_AFTER_S)
    running = session.exec(
        select(Submission).where(Submission.status == "running")
    ).all()
    reaped: list[str] = []
    for sub in running:
        if as_utc(sub.updated_at) < cutoff:
            sub.status = "error"
            session.add(sub)
            reaped.append(sub.id)
            logger.warning(
                "reaped stale submission %s (agent_job_id=%s): no callback within %ss",
                sub.id,
                sub.agent_job_id,
                config.REAP_RUNNING_AFTER_S,
            )
    if reaped:
        session.commit()
    return reaped


@app.post("/submissions", response_model=SubmissionOut, status_code=201)
async def create_submission(
    body: SubmissionCreate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> SubmissionOut:
    question = _owned_question(body.question_id, current, session)  # 404/403 guard

    sub = Submission(
        id=uuid.uuid4().hex,
        question_id=body.question_id,
        candidate=body.candidate,
        language=body.language,
        code=body.code,
        status="pending",
    )
    session.add(sub)
    session.commit()
    session.refresh(sub)

    sub = await _trigger_agent(session, question, sub)
    return _submission_out(sub, None)


@app.post("/submissions/{submission_id}/retry", response_model=SubmissionOut)
async def retry_submission(
    submission_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> SubmissionOut:
    """Re-trigger the agent for a submission stuck in "error" (its prior trigger failed).

    Submissions are immutable; this only re-runs the SAME submission — it does not
    create a new one. Only allowed from "error"; other states are a 409.
    """
    sub = _owned_submission(submission_id, current, session)  # 404/403 guard
    if sub.status != "error":
        raise HTTPException(
            status_code=409,
            detail=f"retry only allowed for submissions in status 'error'; this one is {sub.status!r}.",
        )

    question = session.get(Question, sub.question_id)
    if question is None:
        raise HTTPException(
            status_code=404, detail=f"no question with id {sub.question_id!r}."
        )

    # Clear the prior failed attempt before re-triggering.
    sub.agent_job_id = None
    sub = await _trigger_agent(session, question, sub)
    return _submission_out(sub, None)


@app.get("/submissions", response_model=Page[SubmissionSummaryOut])
def list_submissions(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> Page[SubmissionSummaryOut]:
    _reap_stale_running(session)  # heal submissions stranded in "running" on view
    # Only submissions for the caller's own questions. Lean rows: the full `code`
    # and `full_result` blobs are fetched per-id via GET /submissions/{id}, so a
    # page here stays small even at hundreds of rows.
    total = session.exec(
        select(func.count())
        .select_from(Submission)
        .join(Question)
        .where(Question.owner_id == current.id)
    ).one()
    subs = session.exec(
        select(Submission)
        .join(Question)  # FK Submission.question_id -> Question.id infers the ON clause
        .where(Question.owner_id == current.id)
        .order_by(col(Submission.created_at).desc(), col(Submission.id))
        .offset(offset)
        .limit(limit)
    ).all()
    results = _results_by_submission(subs, session)
    assessments = _assessments_by_submission(subs, session)
    integrity = _integrity_by_submission(subs, session)
    items = [
        _submission_summary(
            sub, results.get(sub.id), assessments.get(sub.id), integrity[sub.id]
        )
        for sub in subs
    ]
    return Page(items=items, total=total, limit=limit, offset=offset)


@app.get("/submissions/export")
def export_submissions(
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> Response:
    """Owner-scoped CSV of every submission across the caller's questions.

    A full export (not paginated) for spreadsheets / ATS import — the lean summary
    columns plus the question title, so a row is readable without a second lookup.
    Declared BEFORE `/submissions/{submission_id}` so "export" isn't swallowed as
    an id by the path-param route.
    """
    _reap_stale_running(session)
    subs = session.exec(
        select(Submission)
        .join(Question)
        .where(Question.owner_id == current.id)
        .order_by(col(Submission.created_at).desc(), col(Submission.id))
    ).all()
    results = _results_by_submission(subs, session)
    integrity = _integrity_by_submission(subs, session)
    titles = {
        q.id: q.title
        for q in session.exec(select(Question).where(Question.owner_id == current.id)).all()
    }

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "submission_id", "question_id", "question_title", "candidate",
            "candidate_email", "language", "status", "verdict", "score_pct", "late",
            "integrity_signals", "integrity_blocked_pastes", "created_at",
        ]
    )
    for sub in subs:
        r = results.get(sub.id)
        signals, blocked_pastes = integrity[sub.id]
        writer.writerow(
            [
                sub.id, sub.question_id, titles.get(sub.question_id, ""), sub.candidate,
                sub.candidate_email or "", sub.language, sub.status,
                r.verdict if r else "", r.score_pct if r else "", sub.late,
                # Blank (not 0) when the sitting wasn't monitored — "nothing
                # recorded" and "nothing to record" must not look alike.
                signals if signals is not None else "",
                blocked_pastes if signals is not None else "",
                sub.created_at.isoformat(),
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="submissions.csv"'},
    )


@app.get("/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(
    submission_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> SubmissionOut:
    _reap_stale_running(session)  # heal a submission stranded in "running" on view
    sub = _owned_submission(submission_id, current, session)  # 404/403 guard
    result = session.exec(
        select(AssessmentResult).where(AssessmentResult.submission_id == sub.id)
    ).first()
    return _submission_out(sub, result)


@app.get("/submissions/{submission_id}/integrity", response_model=IntegrityReportOut)
def get_submission_integrity(
    submission_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> IntegrityReportOut:
    """The integrity signals recorded during the sitting this submission came from.

    Scoped to the *sitting* (invite + candidate), not to this one question: a tab
    switch belongs to the sitting, and a multi-question assessment shows the same
    timeline on each of its submissions with every event naming its own question.
    An interviewer's direct `POST /submissions` (no invite, no candidate) has no
    sitting at all and reports unmonitored with nothing in it.
    """
    sub = _owned_submission(submission_id, current, session)  # 404/403 guard
    if sub.invite_id is None or sub.candidate_email is None:
        return _integrity_report(monitored=False, events=[], session=session)

    invite = session.get(Invite, sub.invite_id)
    monitored = invite.proctored if invite is not None else True
    rows = session.exec(
        select(IntegrityEvent)
        .where(
            IntegrityEvent.invite_id == sub.invite_id,
            IntegrityEvent.candidate_email == sub.candidate_email,
        )
        .order_by(col(IntegrityEvent.offset_ms), col(IntegrityEvent.id))
    ).all()
    return _integrity_report(monitored=monitored, events=list(rows), session=session)


def _integrity_report(
    *, monitored: bool, events: list[IntegrityEvent], session: Session
) -> IntegrityReportOut:
    """Shape stored signals into the interviewer's view: the summary counts first,
    then the timeline. The counts are derived here rather than stored so a new
    signal kind can't leave a stale total behind."""
    titles: dict[str, str] = {}
    for qid in {e.question_id for e in events if e.question_id}:
        question = session.get(Question, qid)
        if question is not None:
            titles[question.id] = question.title
    summary = IntegritySummaryOut(
        total=len(events),
        focus_losses=sum(1 for e in events if e.kind == "focus_loss"),
        away_ms=sum(e.duration_ms or 0 for e in events if e.kind == "focus_loss"),
        fullscreen_exits=sum(1 for e in events if e.kind == "fullscreen_exit"),
        pastes_blocked=sum(1 for e in events if e.kind == "paste_external" and e.blocked),
        devtools_opens=sum(1 for e in events if e.kind == "devtools"),
    )
    # Recorded events are always scored, whatever the monitoring flag says; risk
    # is null only when there is nothing to score AND the sitting was unmonitored
    # (a monitored, quiet sitting scores an explicit 0 / "none").
    risk = None
    if events or monitored:
        score, reasons = integrity.risk_score(list(events))
        risk = IntegrityRiskOut(
            score=score,
            level=integrity.risk_level(score),
            reasons=[IntegrityRiskReasonOut(label=lb, points=p) for lb, p in reasons],
        )
    return IntegrityReportOut(
        monitored=monitored,
        summary=summary,
        risk=risk,
        events=[
            IntegrityEventOut(
                kind=e.kind,
                offset_ms=e.offset_ms,
                duration_ms=e.duration_ms,
                size=e.size,
                blocked=e.blocked,
                question_id=e.question_id,
                question_title=titles.get(e.question_id) if e.question_id else None,
            )
            for e in events
        ],
    )


@app.get("/submissions/{submission_id}/report")
async def submission_report(
    submission_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> Response:
    """Download a PDF report for a graded submission.

    Proxies to the agent's `/report`: the platform owns the pieces the serialized
    result omits, so it loads the stored result, the candidate's submitted code,
    and the full question, POSTs `{result, question, code, candidate}`, and streams
    the rendered PDF back as an attachment. The agent renders; the platform only
    assembles and serves — it never derives anything from the result here.
    """
    sub = _owned_submission(submission_id, current, session)  # 404/403 guard
    result = session.exec(
        select(AssessmentResult).where(AssessmentResult.submission_id == sub.id)
    ).first()
    if result is None:
        raise HTTPException(status_code=409, detail="submission has not been graded yet.")
    question = session.get(Question, sub.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail=f"no question with id {sub.question_id!r}.")

    try:
        pdf = await agent_client.request_report(
            result=result.full_result,
            question=question,
            code=sub.code,
            candidate=sub.candidate,
        )
    except httpx.HTTPError as exc:
        # Any agent failure (bad status or unreachable) is a clean 502 — don't leak
        # the agent's internals to the interviewer.
        logger.warning("report generation failed for submission %s: %s", sub.id, exc)
        raise HTTPException(status_code=502, detail="could not generate the report.") from exc

    filename = f"report-{sub.id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# Dashboard (interviewer: submissions for one of their questions)               #
# --------------------------------------------------------------------------- #


@app.get("/questions/{question_id}/submissions", response_model=Page[DashboardSubmissionOut])
def question_submissions(
    question_id: str,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> Page[DashboardSubmissionOut]:
    _reap_stale_running(session)  # heal submissions stranded in "running" on view
    _owned_question(question_id, current, session)  # 404/403 guard
    total = session.exec(
        select(func.count())
        .select_from(Submission)
        .where(Submission.question_id == question_id)
    ).one()
    subs = session.exec(
        select(Submission)
        .where(Submission.question_id == question_id)
        .order_by(col(Submission.created_at).desc(), col(Submission.id))
        .offset(offset)
        .limit(limit)
    ).all()
    results = _results_by_submission(subs, session)
    integrity = _integrity_by_submission(subs, session)
    items = []
    for sub in subs:
        result = results.get(sub.id)
        signals, blocked_pastes = integrity[sub.id]
        items.append(
            DashboardSubmissionOut(
                submission_id=sub.id,
                candidate_name=sub.candidate,
                candidate_email=sub.candidate_email,
                language=sub.language,
                status=sub.status,
                verdict=result.verdict if result else None,
                score_pct=result.score_pct if result else None,
                late=sub.late,
                integrity_signals=signals,
                integrity_blocked=blocked_pastes,
                created_at=sub.created_at,
            )
        )
    return Page(items=items, total=total, limit=limit, offset=offset)


# --------------------------------------------------------------------------- #
# Agent callback                                                                #
# --------------------------------------------------------------------------- #


def _require_callback_token(x_assess_token: str | None = Header(default=None)) -> None:
    """Verify the agent's shared secret on inbound callbacks.

    Enforced only when `CALLBACK_TOKEN` is set (unset => no auth, for dev/tests).
    Runs as a route dependency so a bad/missing token 401s BEFORE any job_id logic.
    """
    expected = config.CALLBACK_TOKEN
    if expected and not _secret_matches(x_assess_token, expected):
        raise HTTPException(status_code=401, detail=f"invalid or missing {config.AUTH_HEADER}.")


async def _require_callback_signature(request: Request) -> None:
    """Verify the agent's HMAC body signature on inbound callbacks.

    Enforced only when `CALLBACK_SIGNING_SECRET` is set (unset => no signing, for
    dev/tests). Async so it can read the raw body — Starlette caches it, so the
    route still parses the JSON payload afterwards. Proves the callback is really
    the agent and the result wasn't altered, beyond the shared-secret token.
    """
    secret = config.CALLBACK_SIGNING_SECRET
    if not secret:
        return
    if not signing.verify(secret, await request.body(), request.headers.get(signing.SIGNATURE_HEADER)):
        raise HTTPException(status_code=401, detail="invalid or missing callback signature.")


def _is_error_payload(payload: dict[str, Any], verdict: str) -> bool:
    """An assessment is an ERROR when the code couldn't be graded — a top-level
    agent error, an infra failure, or an explicit ERROR verdict. A `compile_error`
    is a normal FAIL (the candidate's code is wrong), not a platform error."""
    return (
        verdict == "ERROR"
        or bool(payload.get("error"))
        or bool(payload.get("infra_error"))
    )


@app.post(
    "/assessments/callback",
    dependencies=[Depends(_require_callback_token), Depends(_require_callback_signature)],
)
def assessments_callback(
    payload: dict[str, Any], session: Session = Depends(get_session)
) -> dict:
    """Receive the agent's result and persist it verbatim. Always returns 200.

    We never derive the grade here — verdict/score/reason are taken as the agent
    reported them; the whole payload is stored in `full_result`.
    """
    job_id = payload.get("job_id")
    if not job_id:
        raise HTTPException(status_code=400, detail="callback payload missing job_id.")

    sub = session.exec(
        select(Submission).where(Submission.agent_job_id == job_id)
    ).first()
    if sub is None:
        # Unknown job: acknowledge (200) so the agent doesn't retry a job we can't
        # match, but log it so the dropped callback is observable, not silent.
        logger.warning("callback for unknown job_id %r; no matching submission", job_id)
        return {"status": "ignored", "reason": f"no submission for job_id {job_id!r}"}

    verdict = str(payload.get("verdict") or "ERROR")
    is_error = _is_error_payload(payload, verdict)
    reason = str(payload.get("reason") or payload.get("error") or "")
    score_pct = float(payload.get("score_pct") or 0.0)

    existing = session.exec(
        select(AssessmentResult).where(AssessmentResult.submission_id == sub.id)
    ).first()
    if existing is not None:
        # Idempotent-ish: a re-delivered callback updates the stored record.
        existing.verdict = verdict
        existing.score_pct = score_pct
        existing.reason = reason
        existing.full_result = payload
        session.add(existing)
    else:
        session.add(
            AssessmentResult(
                submission_id=sub.id,
                verdict=verdict,
                score_pct=score_pct,
                reason=reason,
                full_result=payload,
            )
        )

    sub.status = "error" if is_error else "done"
    session.add(sub)
    session.commit()
    logger.info(
        "callback for agent job %s matched submission %s -> %s", job_id, sub.id, sub.status
    )
    return {"status": "ok", "submission_id": sub.id}


def main() -> None:
    """Entry point for `uv run platform-api` — serve on port 9000 by default."""
    import os

    import uvicorn

    uvicorn.run(
        "assessment_platform.api:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "9000")),
        reload=bool(os.getenv("RELOAD")),
    )
