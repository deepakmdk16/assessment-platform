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

import logging
import secrets
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from . import agent_client, config, email_client
from .auth import (
    create_access_token,
    get_current_interviewer,
    hash_password,
    verify_password,
)
from .config import PLATFORM_BASE_URL
from .db import get_session, init_db
from .models import (
    AssessmentResult,
    Interviewer,
    Invite,
    Question,
    QuestionTestCase,
    Submission,
    as_utc,
)
from .ratelimit import client_ip, limiter
from .schemas import (
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
    InterviewerOut,
    InviteCreate,
    InviteDeliveryOut,
    InviteOut,
    InvitePublicOut,
    InviteStatusOut,
    LoginIn,
    QuestionCreate,
    QuestionDraftIn,
    QuestionDraftOut,
    QuestionOut,
    QuestionUpdate,
    RegisterIn,
    ResultOut,
    SubmissionCreate,
    SubmissionOut,
    TestCaseOut,
    TokenOut,
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
        result=result_out,
    )


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


def _invite_out(inv: Invite, deliveries: list[email_client.Delivery] | None = None) -> InviteOut:
    return InviteOut(
        token=inv.token,
        url=_invite_url(inv.token),
        question_id=inv.question_id,
        recipients=inv.recipients,
        expires_at=inv.expires_at,
        status=inv.status,
        deliveries=[
            InviteDeliveryOut(recipient=d.recipient, sent=d.sent, error=d.error)
            for d in (deliveries or [])
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
    return InterviewerOut(
        id=_require_id(interviewer.id), email=interviewer.email, name=interviewer.name
    )


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
    return InterviewerOut(id=_require_id(current.id), email=current.email, name=current.name)


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


@app.post("/questions", response_model=QuestionOut, status_code=201)
def create_question(
    body: QuestionCreate,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> QuestionOut:
    if session.get(Question, body.id) is not None:
        raise HTTPException(status_code=409, detail=f"question {body.id!r} already exists.")
    q = Question(
        id=body.id,
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


@app.post("/questions/draft", response_model=QuestionDraftOut)
def draft_question(
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
        payload = agent_client.draft_question(
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

    q = payload.get("question") or {}
    example = q.get("example") or {}
    # The agent should send these, but guard explicit nulls so a stray one is a
    # usable draft, not a 500 (`.get(k, default)` only defaults an absent key).
    pass_threshold = q.get("pass_threshold")
    time_limit_s = q.get("time_limit_s")
    question = QuestionCreate(
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
    return QuestionDraftOut(
        question=question,
        warnings=payload.get("warnings", []),
        reference_solution=payload.get("reference_solution"),
        reference_language=payload.get("reference_language"),
        engine=payload.get("engine", ""),
        cost_usd=payload.get("cost_usd"),
    )


@app.get("/questions", response_model=list[QuestionOut])
def list_questions(
    include_archived: bool = False,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> list[QuestionOut]:
    stmt = select(Question).where(Question.owner_id == current.id)
    if not include_archived:
        # Archived questions are retired: hidden from the dashboard by default but
        # still reachable (and their submissions kept) via ?include_archived=true.
        stmt = stmt.where(Question.status == "active")
    return [_question_out(q) for q in session.exec(stmt).all()]


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
    q.title = body.title
    q.prompt = body.prompt
    q.constraints = body.constraints
    q.time_limit_s = body.time_limit_s
    q.pass_threshold = body.pass_threshold
    q.required_complexity = body.required_complexity
    q.example_input = body.example_input
    q.example_output = body.example_output
    q.difficulty = body.difficulty
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
    return _invite_out(invite, deliveries)


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


def _check_not_already_submitted(invite: Invite, email: str, session: Session) -> None:
    """409 if `email` already submitted on this invite (one attempt per candidate).

    The fast path only: it is a SELECT before an INSERT, so it cannot stop two
    concurrent submits from both passing. The `uq_submission_invite_candidate`
    constraint is what actually enforces the rule; this just turns the common,
    uncontended case into a clean 409 instead of a caught IntegrityError.
    """
    already = session.exec(
        select(Submission).where(
            Submission.invite_id == invite.id,
            Submission.candidate_email == email,
        )
    ).first()
    if already is not None:
        raise HTTPException(status_code=409, detail=_ALREADY_SUBMITTED_DETAIL)


def _candidate_question_view(invite: Invite, session: Session) -> InvitePublicOut:
    q = session.get(Question, invite.question_id)
    if q is None:  # question deleted after the invite was issued
        raise HTTPException(status_code=404, detail="the question for this invite no longer exists.")
    # Candidate-facing view only — never expose test_cases or expected outputs.
    return InvitePublicOut(
        question=CandidateQuestionView(
            title=q.title,
            prompt=q.prompt,
            constraints=q.constraints,
            example_input=q.example_input,
            example_output=q.example_output,
            time_limit_s=q.time_limit_s,
        ),
        languages=config.SUPPORTED_LANGUAGES,
    )


@app.get("/invite/{token}", response_model=InviteStatusOut)
def get_invite(token: str, session: Session = Depends(get_session)) -> InviteStatusOut:
    """Liveness probe for the link: 404 if unknown, 410 if revoked/expired.

    Returns no question data on purpose. The problem is only handed out by
    `POST /invite/{token}/start`, once the caller has identified as an invited
    recipient — otherwise the email check below would be decorative, since anyone
    with the link could just read the question straight off this endpoint.
    """
    _load_invite_or_error(token, session)
    return InviteStatusOut(status="active")


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
    _check_not_already_submitted(invite, email, session)
    return _candidate_question_view(invite, session)


def _load_invite_for_candidate(token: str, email: str, session: Session) -> tuple[Invite, Question]:
    """Shared guard for the candidate's in-editor actions (run / run-tests).

    Same gates as /start: the link must be live, the caller must be an invited
    recipient, and they must not have submitted already. Without this, anyone
    holding the link could burn agent compute for free.
    """
    invite = _load_invite_or_error(token, session)
    _check_invited(invite, email)
    _check_not_already_submitted(invite, email, session)
    question = session.get(Question, invite.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="the question for this invite no longer exists.")
    return invite, question


def _agent_run_call(what: str, call: Callable[[], dict]) -> dict:
    """Invoke a synchronous agent run call, mapping its failures to ours."""
    try:
        return call()
    except httpx.HTTPStatusError as exc:
        # The agent rejected the request (e.g. unsupported language) — pass its
        # reason through as a 400 rather than a blank 502.
        if exc.response.status_code == 400:
            raise HTTPException(status_code=400, detail=_agent_detail(exc)) from exc
        raise HTTPException(status_code=502, detail=f"{what} failed: {exc}") from exc
    except Exception as exc:  # agent unreachable / timed out
        raise HTTPException(status_code=502, detail=f"{what} failed: {exc}") from exc


@app.post("/invite/{token}/run", response_model=CandidateRunOut)
def candidate_run(
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
    _load_invite_for_candidate(token, email, session)

    result = _agent_run_call(
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
def candidate_run_tests(
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
    _, question = _load_invite_for_candidate(token, email, session)

    result = _agent_run_call(
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
def candidate_submit(
    token: str,
    body: CandidateSubmitIn,
    request: Request,
    session: Session = Depends(get_session),
) -> CandidateSubmitOut:
    limiter.check(
        "submit", client_ip(request), config.SUBMIT_RATE_LIMIT_MAX, config.RATE_LIMIT_WINDOW_S
    )
    invite = _load_invite_or_error(token, session)
    question = session.get(Question, invite.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="the question for this invite no longer exists.")

    # Re-check both gates here, not just in /start: the start screen is only UI,
    # so a caller can POST straight to this route and skip it.
    email = _normalize_email(body.candidate_email)
    _check_invited(invite, email)
    _check_not_already_submitted(invite, email, session)

    sub = Submission(
        id=uuid.uuid4().hex,
        question_id=question.id,
        invite_id=invite.id,
        candidate=body.candidate_name,
        candidate_email=email,
        language=body.language,
        code=body.code,
        status="pending",
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

    sub = _trigger_agent(session, question, sub)
    return CandidateSubmitOut(submission_id=sub.id, status=sub.status)


# --------------------------------------------------------------------------- #
# Submissions                                                                   #
# --------------------------------------------------------------------------- #


def _trigger_agent(session: Session, question: Question, sub: Submission) -> Submission:
    """Trigger an agent job for `sub` and persist the outcome.

    Shared by the initial submit and the manual retry: on success sets the new
    agent_job_id and flips status to "running"; on failure flips to "error" and
    raises 502 (submission left in "error"). The caller must have already looked
    up the question.
    """
    callback_url = f"{PLATFORM_BASE_URL}/assessments/callback"
    try:
        job_id = agent_client.trigger_assessment(question, sub, callback_url)
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
def create_submission(
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

    sub = _trigger_agent(session, question, sub)
    return _submission_out(sub, None)


@app.post("/submissions/{submission_id}/retry", response_model=SubmissionOut)
def retry_submission(
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
    sub = _trigger_agent(session, question, sub)
    return _submission_out(sub, None)


@app.get("/submissions", response_model=list[SubmissionOut])
def list_submissions(
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> list[SubmissionOut]:
    _reap_stale_running(session)  # heal submissions stranded in "running" on view
    # Only submissions for the caller's own questions.
    subs = session.exec(
        select(Submission)
        .join(Question)  # FK Submission.question_id -> Question.id infers the ON clause
        .where(Question.owner_id == current.id)
    ).all()
    results = _results_by_submission(subs, session)
    return [_submission_out(sub, results.get(sub.id)) for sub in subs]


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


# --------------------------------------------------------------------------- #
# Dashboard (interviewer: submissions for one of their questions)               #
# --------------------------------------------------------------------------- #


@app.get("/questions/{question_id}/submissions", response_model=list[DashboardSubmissionOut])
def question_submissions(
    question_id: str,
    current: Interviewer = Depends(get_current_interviewer),
    session: Session = Depends(get_session),
) -> list[DashboardSubmissionOut]:
    _reap_stale_running(session)  # heal submissions stranded in "running" on view
    _owned_question(question_id, current, session)  # 404/403 guard
    subs = session.exec(
        select(Submission).where(Submission.question_id == question_id)
    ).all()
    results = _results_by_submission(subs, session)
    out = []
    for sub in subs:
        result = results.get(sub.id)
        out.append(
            DashboardSubmissionOut(
                submission_id=sub.id,
                candidate_name=sub.candidate,
                candidate_email=sub.candidate_email,
                language=sub.language,
                status=sub.status,
                verdict=result.verdict if result else None,
                score_pct=result.score_pct if result else None,
                created_at=sub.created_at,
            )
        )
    return out


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


def _is_error_payload(payload: dict[str, Any], verdict: str) -> bool:
    """An assessment is an ERROR when the code couldn't be graded — a top-level
    agent error, an infra failure, or an explicit ERROR verdict. A `compile_error`
    is a normal FAIL (the candidate's code is wrong), not a platform error."""
    return (
        verdict == "ERROR"
        or bool(payload.get("error"))
        or bool(payload.get("infra_error"))
    )


@app.post("/assessments/callback", dependencies=[Depends(_require_callback_token)])
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
