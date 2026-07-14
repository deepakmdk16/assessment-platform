"""FastAPI app — the Assessment Platform HTTP surface.

The platform is the system of record: it stores questions, submissions, and the
results the agent returns. It never grades. `POST /submissions` triggers a job
on the agent (passing a callback_url pointing back here); the agent later POSTs
the full result to `POST /assessments/callback`, which we persist verbatim.

Auth is intentionally absent in v1. A shared secret on the inbound submit AND on
the callback is a required TODO before production (see README).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlmodel import Session, select

from . import agent_client, config
from .config import PLATFORM_BASE_URL
from .db import get_session, init_db
from .models import AssessmentResult, Question, QuestionTestCase, Submission
from .schemas import (
    QuestionCreate,
    QuestionOut,
    QuestionUpdate,
    ResultOut,
    SubmissionCreate,
    SubmissionOut,
    TestCaseOut,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()  # v1: create tables on startup (no Alembic yet)
    yield


app = FastAPI(
    title="Assessment Platform",
    description="System of record for coding questions, submissions, and agent results.",
    version="0.1.0",
    lifespan=_lifespan,
)


# --------------------------------------------------------------------------- #
# Serialization helpers                                                         #
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Health                                                                        #
# --------------------------------------------------------------------------- #


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --------------------------------------------------------------------------- #
# Questions CRUD                                                                #
# --------------------------------------------------------------------------- #


@app.post("/questions", response_model=QuestionOut, status_code=201)
def create_question(body: QuestionCreate, session: Session = Depends(get_session)) -> QuestionOut:
    if session.get(Question, body.id) is not None:
        raise HTTPException(status_code=409, detail=f"question {body.id!r} already exists.")
    q = Question(
        id=body.id,
        title=body.title,
        prompt=body.prompt,
        constraints=body.constraints,
        time_limit_s=body.time_limit_s,
        pass_threshold=body.pass_threshold,
        required_complexity=body.required_complexity,
        example_input=body.example_input,
        example_output=body.example_output,
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


@app.get("/questions", response_model=list[QuestionOut])
def list_questions(session: Session = Depends(get_session)) -> list[QuestionOut]:
    questions = session.exec(select(Question)).all()
    return [_question_out(q) for q in questions]


@app.get("/questions/{question_id}", response_model=QuestionOut)
def get_question(question_id: str, session: Session = Depends(get_session)) -> QuestionOut:
    q = session.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail=f"no question with id {question_id!r}.")
    return _question_out(q)


@app.put("/questions/{question_id}", response_model=QuestionOut)
def update_question(
    question_id: str, body: QuestionUpdate, session: Session = Depends(get_session)
) -> QuestionOut:
    q = session.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail=f"no question with id {question_id!r}.")
    q.title = body.title
    q.prompt = body.prompt
    q.constraints = body.constraints
    q.time_limit_s = body.time_limit_s
    q.pass_threshold = body.pass_threshold
    q.required_complexity = body.required_complexity
    q.example_input = body.example_input
    q.example_output = body.example_output
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


@app.delete("/questions/{question_id}", status_code=204)
def delete_question(question_id: str, session: Session = Depends(get_session)) -> None:
    q = session.get(Question, question_id)
    if q is None:
        raise HTTPException(status_code=404, detail=f"no question with id {question_id!r}.")
    session.delete(q)
    session.commit()


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
        raise HTTPException(status_code=502, detail=f"agent call failed: {exc}") from exc

    sub.agent_job_id = job_id
    sub.status = "running"
    session.add(sub)
    session.commit()
    session.refresh(sub)
    return sub


@app.post("/submissions", response_model=SubmissionOut, status_code=201)
def create_submission(
    body: SubmissionCreate, session: Session = Depends(get_session)
) -> SubmissionOut:
    question = session.get(Question, body.question_id)
    if question is None:
        raise HTTPException(status_code=404, detail=f"no question with id {body.question_id!r}.")

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
    submission_id: str, session: Session = Depends(get_session)
) -> SubmissionOut:
    """Re-trigger the agent for a submission stuck in "error" (its prior trigger failed).

    Submissions are immutable; this only re-runs the SAME submission — it does not
    create a new one. Only allowed from "error"; other states are a 409.
    """
    sub = session.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail=f"no submission with id {submission_id!r}.")
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
def list_submissions(session: Session = Depends(get_session)) -> list[SubmissionOut]:
    subs = session.exec(select(Submission)).all()
    out = []
    for sub in subs:
        result = session.exec(
            select(AssessmentResult).where(AssessmentResult.submission_id == sub.id)
        ).first()
        out.append(_submission_out(sub, result))
    return out


@app.get("/submissions/{submission_id}", response_model=SubmissionOut)
def get_submission(submission_id: str, session: Session = Depends(get_session)) -> SubmissionOut:
    sub = session.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(status_code=404, detail=f"no submission with id {submission_id!r}.")
    result = session.exec(
        select(AssessmentResult).where(AssessmentResult.submission_id == sub.id)
    ).first()
    return _submission_out(sub, result)


# --------------------------------------------------------------------------- #
# Agent callback                                                                #
# --------------------------------------------------------------------------- #


def _require_callback_token(x_assess_token: str | None = Header(default=None)) -> None:
    """Verify the agent's shared secret on inbound callbacks.

    Enforced only when `CALLBACK_TOKEN` is set (unset => no auth, for dev/tests).
    Runs as a route dependency so a bad/missing token 401s BEFORE any job_id logic.
    """
    expected = config.CALLBACK_TOKEN
    if expected and x_assess_token != expected:
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
