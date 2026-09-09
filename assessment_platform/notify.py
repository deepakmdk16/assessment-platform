"""Proactive result delivery — telling the interviewer a sitting finished (X06).

Until this existed the platform graded a candidate, stored the result, and said
nothing: the only way to learn that someone had completed an assessment was to
open the dashboard and look. Two channels now fire from the agent's callback,
once the LAST question of a sitting is graded:

- **Email** to the interviewer who sent the invitation, carrying the verdict for
  every question and a link to the submission.
- **Webhook** POST to the organisation's `results_webhook_url`, HMAC-signed with
  the same scheme as the platform<->agent link (`signing.py`), so an ATS or a
  chat relay can consume results without polling.

**The notification is per SITTING, not per submission.** A three-question
assessment produces three independent callbacks; firing on each would mail the
interviewer three times about one candidate. So the work splits in two:

- `claim_sitting` runs INLINE in the callback request. It decides whether the
  sitting is now complete and, if so, wins a compare-and-swap on
  `CandidateAttempt.results_notified_at`. Two callbacks landing together, and a
  re-delivered callback arriving days later, all resolve to exactly one winner.
- `deliver` runs in a BACKGROUND task. It is the slow half — SMTP, and an HTTP
  POST to an address a customer chose — and none of it may be on the callback's
  critical path: a callback the agent waits too long for is a callback the agent
  retries, and neither an unreachable mail host nor a broken customer endpoint
  may cost a candidate their grade. Both channels are best-effort and log rather
  than raise, for the same reason.

**The webhook URL is customer-supplied and fetched server-side**, which is the
textbook SSRF shape. `webhook_url_error` is the gate, and it runs twice on
purpose: at configuration time, so an interviewer typing an unusable URL is told
immediately, and again at send time in `deliver`, because the name resolved at
configuration time is not necessarily the address reached minutes or months
later. Redirects are never followed — a 302 is exactly how an allowed host hands
the request to a forbidden one.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import secrets
import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import urlsplit

import httpx
from sqlalchemy import CursorResult, update
from sqlmodel import Session, col, select

from . import config, email_client, signing
from .models import (
    AssessmentQuestion,
    AssessmentResult,
    CandidateAttempt,
    Interviewer,
    Invite,
    Organization,
    Question,
    Submission,
)

logger = logging.getLogger(__name__)

# The statuses that mean the agent is finished with a submission, one way or the
# other. "error" counts: a sitting whose last question failed to grade is still
# over, and the interviewer needs to hear about it more than about a clean pass.
TERMINAL = ("done", "error")

EVENT = "results.ready"


@dataclass(frozen=True)
class GradedQuestion:
    """One question's outcome as the notification reports it."""

    submission_id: str
    question_id: str
    title: str
    verdict: str
    score_pct: float


@dataclass(frozen=True)
class ResultsReady:
    """Everything the two channels need, read from the session while the request
    still has one. Deliberately a plain value: `deliver` runs after the response
    and after the session is closed, so it must not hold ORM rows."""

    org_id: int
    invite_id: int
    candidate: str
    candidate_email: str | None
    title: str
    results_url: str
    recipient: str | None
    webhook_url: str | None
    webhook_secret: str | None
    questions: list[GradedQuestion] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Webhook URL validation (SSRF gate)                                            #
# --------------------------------------------------------------------------- #


def webhook_url_error(url: str) -> str | None:
    """Why `url` is unusable as a results webhook, or None if it is fine.

    Returns a message rather than raising so both callers can use it: the API
    route turns it into a 422 the interviewer reads, and `deliver` turns it into
    a log line and a dropped send.

    The host must resolve to publicly-routable addresses only. Loopback, private
    ranges, link-local (which is where every cloud metadata service lives) and
    the rest of the reserved space are refused, and refused for EVERY address the
    name resolves to — a name with one public and one private A record must not
    be usable to reach the private one.
    """
    try:
        parts = urlsplit(url)
        # `.port` PARSES on access and raises for a malformed or out-of-range
        # one, so it has to be read inside the guard: unread, a URL like
        # "https://h:99999/x" would 500 the settings route and, worse, throw out
        # of a background task that promises never to raise.
        port = parts.port or 443
    except ValueError:
        return "webhook URL is not a valid URL."
    allowed_schemes = ("https", "http") if config.ALLOW_PRIVATE_WEBHOOKS else ("https",)
    if parts.scheme not in allowed_schemes:
        return "webhook URL must use https."
    if not parts.hostname:
        return "webhook URL has no host."
    if config.ALLOW_PRIVATE_WEBHOOKS:
        return None
    try:
        resolved = socket.getaddrinfo(parts.hostname, port, proto=socket.IPPROTO_TCP)
    except OSError:
        return f"webhook host {parts.hostname!r} does not resolve."
    for info in resolved:
        address = ipaddress.ip_address(cast(tuple[str, int], info[4])[0])
        if not address.is_global or address.is_multicast:
            return (
                f"webhook host {parts.hostname!r} resolves to a non-public address "
                f"({address}); it must be reachable on the public internet."
            )
    return None


def new_webhook_secret() -> str:
    """A fresh signing secret for an organisation's webhook.

    Minted here rather than accepted from the customer so it cannot be a
    password they reused, and so every organisation's is independent.
    """
    return secrets.token_urlsafe(32)


# --------------------------------------------------------------------------- #
# Deciding that a sitting is over (inline, transactional)                       #
# --------------------------------------------------------------------------- #


def claim_sitting(session: Session, sub: Submission) -> ResultsReady | None:
    """If `sub` completed its sitting and nobody has been notified yet, claim the
    notification and return what to send. Otherwise None.

    Called from the agent callback with the submission already committed in its
    terminal state, so the count below includes `sub` itself.
    """
    if sub.invite_id is None or not sub.candidate_email:
        # No invite means the interviewer POSTed the submission themselves and is
        # holding the response; there is nobody to proactively tell.
        return None
    invite = session.get(Invite, sub.invite_id)
    if invite is None:
        return None

    expected = _slot_count(session, invite)
    graded = _graded_submissions(session, invite, sub.candidate_email)
    if len(graded) < expected:
        return None

    attempt = session.exec(
        select(CandidateAttempt).where(
            col(CandidateAttempt.invite_id) == invite.id,
            col(CandidateAttempt.candidate_email) == sub.candidate_email,
        )
    ).first()
    if attempt is None:
        # Every candidate sitting is stamped at /start, so this is a submission
        # that never went through the candidate flow. Nothing to claim against.
        return None
    if not _claim(session, attempt):
        return None

    return _payload(session, invite, sub, graded)


def _slot_count(session: Session, invite: Invite) -> int:
    """How many graded submissions make this invite's sitting complete.

    An assessment invite is done when every slot has been graded; a legacy
    single-question ("quick screen") invite has exactly one.
    """
    if invite.assessment_id is None:
        return 1
    slots = session.exec(
        select(AssessmentQuestion).where(
            col(AssessmentQuestion.assessment_id) == invite.assessment_id
        )
    ).all()
    return len(slots) or 1


def _graded_submissions(session: Session, invite: Invite, candidate_email: str) -> list[Submission]:
    return list(
        session.exec(
            select(Submission).where(
                col(Submission.invite_id) == invite.id,
                col(Submission.candidate_email) == candidate_email,
                col(Submission.status).in_(TERMINAL),
            )
        ).all()
    )


def _claim(session: Session, attempt: CandidateAttempt) -> bool:
    """Compare-and-swap the notified stamp; True iff this caller won it.

    A conditional UPDATE checked by rowcount, like `api._cas` and the rate-limit
    counter — portable across SQLite and Postgres, and the only thing that makes
    "notify once" true when the last two questions of a sitting are graded
    concurrently. A read-then-write would let both callbacks see NULL and both
    send.
    """
    stmt = (
        update(CandidateAttempt)
        .where(
            col(CandidateAttempt.id) == attempt.id,
            col(CandidateAttempt.results_notified_at).is_(None),
        )
        .values(results_notified_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    won = bool(cast(CursorResult[object], session.execute(stmt)).rowcount)
    session.commit()
    return won


def _payload(
    session: Session, invite: Invite, sub: Submission, graded: list[Submission]
) -> ResultsReady:
    question = session.get(Question, sub.question_id)
    org_id = question.org_id if question is not None else 0
    organization = session.get(Organization, org_id) if org_id else None
    recipient = None
    if invite.created_by is not None:
        interviewer = session.get(Interviewer, invite.created_by)
        recipient = interviewer.email if interviewer is not None else None

    title = "Coding assessment"
    if invite.assessment_id is not None and invite.assessment is not None:
        title = invite.assessment.title
    elif question is not None:
        title = question.title

    return ResultsReady(
        org_id=org_id,
        invite_id=cast(int, invite.id),
        candidate=sub.candidate,
        candidate_email=sub.candidate_email,
        title=title,
        # The interviewer lands on the submission that finished the sitting; the
        # rest of it is one click away from there.
        results_url=f"{config.FRONTEND_BASE_URL}/submissions/{sub.id}",
        recipient=recipient,
        webhook_url=organization.results_webhook_url if organization else None,
        webhook_secret=organization.results_webhook_secret if organization else None,
        questions=[_graded_question(session, s) for s in graded],
    )


def _graded_question(session: Session, sub: Submission) -> GradedQuestion:
    question = session.get(Question, sub.question_id)
    result = session.exec(
        select(AssessmentResult).where(col(AssessmentResult.submission_id) == sub.id)
    ).first()
    return GradedQuestion(
        submission_id=sub.id,
        question_id=sub.question_id,
        title=question.title if question is not None else sub.question_id,
        # A submission can reach "error" with no result row at all (the worker
        # gave up), and that is exactly the case the interviewer must be told
        # about rather than shown a blank.
        verdict=result.verdict if result is not None else "ERROR",
        score_pct=result.score_pct if result is not None else 0.0,
    )


# --------------------------------------------------------------------------- #
# Delivery (background, best-effort)                                            #
# --------------------------------------------------------------------------- #


def deliver(payload: ResultsReady) -> None:
    """Send both channels. Never raises — this runs after the response."""
    _send_email(payload)
    _send_webhook(payload)


def _send_email(payload: ResultsReady) -> None:
    if not payload.recipient:
        logger.info(
            "results ready for invite %s: no interviewer to email (invite has no sender)",
            payload.invite_id,
        )
        return
    try:
        email_client.send_results_email(
            payload.recipient,
            f"Assessment complete: {payload.candidate} — {payload.title}",
            _email_body(payload),
            payload.results_url,
        )
    except Exception:  # a mailer bug must not take the webhook down with it
        logger.exception("results email failed for invite %s", payload.invite_id)


def _email_body(payload: ResultsReady) -> str:
    lines = [
        f"{payload.candidate} has completed {payload.title}.",
        "",
    ]
    for question in payload.questions:
        lines.append(f"  {question.verdict:<5} {question.score_pct:5.1f}%  {question.title}")
    lines += [
        "",
        "Full result, code and per-test-case detail:",
        payload.results_url,
    ]
    return "\n".join(lines)


def _send_webhook(payload: ResultsReady) -> None:
    if not payload.webhook_url or not payload.webhook_secret:
        return
    error = webhook_url_error(payload.webhook_url)
    if error:
        # Re-checked here, not only at configuration time: DNS can have moved
        # under a URL that was legitimate when it was saved.
        logger.warning(
            "results webhook for org %s not sent: %s", payload.org_id, error
        )
        return
    body = _webhook_body(payload)
    try:
        response = httpx.post(
            payload.webhook_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                signing.SIGNATURE_HEADER: signing.sign(payload.webhook_secret, body),
            },
            timeout=config.RESULTS_WEBHOOK_TIMEOUT_S,
            # A redirect is how an allowed host hands the request to a forbidden
            # one; the gate above would have checked the wrong address.
            follow_redirects=False,
        )
        response.raise_for_status()
        logger.info(
            "results webhook for org %s delivered for invite %s (%s)",
            payload.org_id,
            payload.invite_id,
            response.status_code,
        )
    except Exception as exc:
        # One attempt, no retry queue. The dashboard remains the system of
        # record and the email still went; a customer endpoint that was down is
        # a customer problem we surface in logs rather than a job we own.
        logger.warning(
            "results webhook for org %s failed for invite %s: %s",
            payload.org_id,
            payload.invite_id,
            exc,
        )


def _webhook_body(payload: ResultsReady) -> bytes:
    """The signed bytes ARE the sent bytes — serialize once, exactly as
    `agent_client._signed_post` does, so the receiver's HMAC check can succeed."""
    document: dict[str, Any] = {
        "event": EVENT,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": payload.org_id,
        "invite_id": payload.invite_id,
        "title": payload.title,
        "candidate": {"name": payload.candidate, "email": payload.candidate_email},
        "results_url": payload.results_url,
        "results": [
            {
                "submission_id": q.submission_id,
                "question_id": q.question_id,
                "title": q.title,
                "verdict": q.verdict,
                "score_pct": q.score_pct,
            }
            for q in payload.questions
        ],
    }
    return json.dumps(document, separators=(",", ":")).encode()
