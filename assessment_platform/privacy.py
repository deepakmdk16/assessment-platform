"""Candidate erasure and retention — the data-subject side of the record (X03).

Two operations over one graph, kept in a single module because they have to
agree about what "candidate data" is: an **erasure** answers one person's
request now, and **retention** applies the organisation's own policy on a
schedule. Both end up in `_erase`, so a table added for one is never missed by
the other — the same reasoning that makes `api._purge_org` one list.

**Erasure anonymises the sitting; it does not delete it.** The identifiers and
the candidate's own work go — name, email, submitted code, autosaved drafts,
and the agent's verbatim `full_result`, which carries per-test-case output
produced by *running* that code and is therefore candidate-authored content
however opaque the blob looks. Verdict, score, timings and integrity counts
stay, so an organisation's pass-rate history and its billing record don't
silently rewrite themselves when someone exercises a right. What remains
describes an assessment that happened, not a person.

**The tombstone is random, not a hash of the address.** Every row of one erased
sitting gets the same freshly-minted `erased-<random>@erased.invalid`. Sharing
one value keeps the sitting internally joinable — attempt ↔ integrity events ↔
submissions still line up for the interviewer's timeline — and minting it fresh
keeps it irreversible: an email address has nowhere near the entropy to survive
a dictionary attack on a hash, so hashing would be erasure in appearance only.
Per-erasure uniqueness is also what keeps `uq_attempt_invite_candidate`
satisfiable when two candidates on the same invite are both erased; a shared
literal like "[erased]" would collide on the second one.

`candidate_email` is NOT NULL on four of these tables, which is why erasure
writes a tombstone rather than nulling the column.

**Erasure retires the invitation too.** The address is personal data on the
invite itself — held there whether or not the person ever opened the link — so
it is removed from `recipients`, and `api._check_invited` then has nothing left
to match: the link that was sent to them stops admitting them. Reassessing an
erased candidate means issuing a fresh invitation, which is the coherent
reading of having forgotten them. Both alternatives are worse: keeping the
address on the invite retains data the request asked to destroy, and the
already-submitted check (which also matches on the address) would otherwise let
a stale link resurrect a sitting that no longer exists.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import cast

from sqlalchemy import CursorResult, delete, or_, update
from sqlmodel import Session, col, select

from .models import (
    Assessment,
    AssessmentResult,
    CandidateAttempt,
    CandidateDraft,
    CandidateSlotVariant,
    IntegrityEvent,
    Invite,
    Organization,
    Question,
    Submission,
)

logger = logging.getLogger(__name__)

# The display name left on an erased submission. Unlike the email tombstone this
# one may safely be a shared literal: no uniqueness constraint covers it.
ERASED_NAME = "[erased]"

# What replaces the agent's stored payload. A marker rather than NULL, so a
# reader can tell "erased" from "never graded" — the column is not nullable and
# the difference matters when an interviewer asks why a row has no detail.
ERASED_RESULT: dict = {"erased": True}

# `AssessmentResult.reason` goes with it. It reads like metadata but it is the
# grader's prose about this candidate's code, routinely quoting the output that
# code produced, and `ResultOut` shows it to interviewers — so keeping it would
# leave the most readable candidate-derived text on the row while destroying the
# JSON blob it was summarising.
ERASED_REASON = "[erased]"

# Suffix of every minted tombstone. `.invalid` is reserved by RFC 2606, so the
# address can never route anywhere or collide with a real candidate's.
TOMBSTONE_DOMAIN = "erased.invalid"


def _naive_utc(moment: datetime) -> datetime:
    """Drop the tzinfo for a comparison the database performs.

    Every timestamp column here is timezone-naive UTC (P14), and everywhere else
    in this codebase a stored datetime is compared in Python via `as_utc`. These
    two queries filter in SQL instead — a retention scan should not load every
    sitting to date one — so the bound has to be naive UTC or the comparison is
    between an offset-carrying value and a bare one: silently tolerated by
    SQLite, and off by the session's TimeZone on Postgres.
    """
    return moment.replace(tzinfo=None) if moment.tzinfo else moment


def _tombstone() -> str:
    return f"erased-{uuid.uuid4().hex[:16]}@{TOMBSTONE_DOMAIN}"


def _rowcount(session: Session, statement: object) -> int:
    return cast(CursorResult, session.execute(statement)).rowcount  # type: ignore[arg-type]


@dataclass(frozen=True)
class ErasureCounts:
    """What one erasure touched. Returned to the caller (and logged) so a
    data-subject request has an answer more specific than "done"."""

    submissions: int = 0
    results: int = 0
    attempts: int = 0
    slot_variants: int = 0
    integrity_events: int = 0
    drafts_deleted: int = 0
    invites_amended: int = 0

    @property
    def touched_anything(self) -> bool:
        return any(
            (
                self.submissions,
                self.results,
                self.attempts,
                self.slot_variants,
                self.integrity_events,
                self.drafts_deleted,
                self.invites_amended,
            )
        )


def org_invite_ids(org_id: int, session: Session) -> list[int]:
    """Every invite belonging to an organisation, reached through the question or
    assessment it points at — never through `created_by`, which records only who
    clicked send and may name someone who has since left (same rule as
    `api._purge_org`)."""
    question_ids = select(Question.id).where(Question.org_id == org_id)
    assessment_ids = select(Assessment.id).where(Assessment.org_id == org_id)
    rows = session.exec(
        select(Invite.id).where(
            or_(
                col(Invite.question_id).in_(question_ids),
                col(Invite.assessment_id).in_(assessment_ids),
            )
        )
    ).all()
    return [r for r in rows if r is not None]


def _scrub_invite_recipients(invite: Invite, email: str) -> bool:
    """Drop one address from an invite's recipient list and its delivery log.

    Both are JSON columns, so the new value is *assigned* rather than mutated in
    place — an in-place edit of a list inside a JSON column is not seen as dirty
    by SQLAlchemy and would be silently dropped at commit.
    """
    recipients = [r for r in invite.recipients if r != email]
    deliveries = [d for d in invite.deliveries if d.get("recipient") != email]
    if len(recipients) == len(invite.recipients) and len(deliveries) == len(invite.deliveries):
        return False
    invite.recipients = recipients
    invite.deliveries = deliveries
    return True


def _erase(
    session: Session,
    *,
    email: str,
    invite_ids: Sequence[int],
    submission_ids: Sequence[str],
    now: datetime,
) -> ErasureCounts:
    """Anonymise one candidate across a fixed set of invites and submissions.

    Ids are resolved by the caller, which is what lets the same worker serve both
    a whole-organisation request (every invite) and the retention job (one
    expired sitting). Does not commit — the caller owns the transaction, exactly
    like `api._purge_org`.
    """
    if not invite_ids and not submission_ids:
        return ErasureCounts()

    tombstone = _tombstone()
    ids = list(invite_ids)

    results = 0
    submissions = 0
    if submission_ids:
        subs = list(submission_ids)
        # Results first: they hang off the submissions and are scoped by their ids.
        results = _rowcount(
            session,
            update(AssessmentResult)
            .where(col(AssessmentResult.submission_id).in_(subs))
            .values(full_result=ERASED_RESULT, reason=ERASED_REASON),
        )
        submissions = _rowcount(
            session,
            update(Submission)
            .where(col(Submission.id).in_(subs))
            .values(candidate=ERASED_NAME, candidate_email=tombstone, code="", updated_at=now),
        )

    attempts = slot_variants = integrity_events = drafts = 0
    if ids:
        attempts = _rowcount(
            session,
            update(CandidateAttempt)
            .where(
                col(CandidateAttempt.invite_id).in_(ids),
                col(CandidateAttempt.candidate_email) == email,
            )
            .values(
                candidate_email=tombstone, candidate_name=None, erased_at=now, updated_at=now
            ),
        )
        slot_variants = _rowcount(
            session,
            update(CandidateSlotVariant)
            .where(
                col(CandidateSlotVariant.invite_id).in_(ids),
                col(CandidateSlotVariant.candidate_email) == email,
            )
            .values(candidate_email=tombstone),
        )
        integrity_events = _rowcount(
            session,
            update(IntegrityEvent)
            .where(
                col(IntegrityEvent.invite_id).in_(ids),
                col(IntegrityEvent.candidate_email) == email,
            )
            .values(candidate_email=tombstone),
        )
        # Drafts are deleted outright rather than tombstoned: an unsubmitted
        # work-in-progress has no reader (no surface exposes it) and so nothing
        # to preserve for, while its `code` is the candidate's own content.
        drafts = _rowcount(
            session,
            delete(CandidateDraft).where(
                col(CandidateDraft.invite_id).in_(ids),
                col(CandidateDraft.candidate_email) == email,
            ),
        )

    # The address is PII on the invite itself even when the person never opened
    # the link, so this runs whether or not any sitting was found above.
    amended = 0
    for invite in session.exec(select(Invite).where(col(Invite.id).in_(ids))).all() if ids else []:
        if _scrub_invite_recipients(invite, email):
            session.add(invite)
            amended += 1

    return ErasureCounts(
        submissions=submissions,
        results=results,
        attempts=attempts,
        slot_variants=slot_variants,
        integrity_events=integrity_events,
        drafts_deleted=drafts,
        invites_amended=amended,
    )


def erase_candidate(session: Session, *, org_id: int, email: str) -> ErasureCounts:
    """Erase one candidate everywhere they appear in one organisation — the
    data-subject request. `email` must already be normalised (lower-cased).

    Scoped to the organisation, never global: the same person may have sat for
    two customers, and one customer's erasure request is not the other's to make.
    """
    invite_ids = org_invite_ids(org_id, session)
    question_ids = select(Question.id).where(Question.org_id == org_id)
    submission_ids = [
        s
        for s in session.exec(
            select(Submission.id).where(
                col(Submission.candidate_email) == email,
                or_(
                    col(Submission.question_id).in_(question_ids),
                    col(Submission.invite_id).in_(invite_ids) if invite_ids else col(Submission.id).is_(None),
                ),
            )
        ).all()
        if s is not None
    ]
    counts = _erase(
        session,
        email=email,
        invite_ids=invite_ids,
        submission_ids=submission_ids,
        now=datetime.now(timezone.utc),
    )
    logger.info(
        "erased candidate data in org %s: %s submission(s), %s result(s), %s attempt(s), "
        "%s draft(s) deleted, %s invite(s) amended",
        org_id,
        counts.submissions,
        counts.results,
        counts.attempts,
        counts.drafts_deleted,
        counts.invites_amended,
    )
    return counts


def erase_sitting(
    session: Session, *, invite_id: int, email: str, now: datetime | None = None
) -> ErasureCounts:
    """Erase one candidate's sitting on one invite — the unit retention expires.

    Retention is per sitting rather than per person on purpose: a candidate who
    sat twelve months apart has one expired sitting and one live one, and
    erasing by address would take both.
    """
    stamp = now or datetime.now(timezone.utc)
    submission_ids = [
        s
        for s in session.exec(
            select(Submission.id).where(
                col(Submission.invite_id) == invite_id,
                col(Submission.candidate_email) == email,
            )
        ).all()
        if s is not None
    ]
    return _erase(
        session, email=email, invite_ids=[invite_id], submission_ids=submission_ids, now=stamp
    )


def expired_sittings(
    session: Session, *, now: datetime, org_id: int, days: int
) -> list[tuple[int, str]]:
    """The `(invite_id, candidate_email)` pairs of this organisation's sittings
    that have outlived its retention window and have not already been erased.

    Measured from `started_at` — when the candidate actually sat — not from the
    invite's creation, so a link sent in January and taken in June expires six
    months after the sitting rather than before it.
    """
    invite_ids = org_invite_ids(org_id, session)
    if not invite_ids:
        return []
    cutoff = _naive_utc(now - timedelta(days=days))
    rows = session.exec(
        select(CandidateAttempt.invite_id, CandidateAttempt.candidate_email).where(
            col(CandidateAttempt.invite_id).in_(invite_ids),
            col(CandidateAttempt.started_at) < cutoff,
            col(CandidateAttempt.erased_at).is_(None),
        )
    ).all()
    return [(invite_id, email) for invite_id, email in rows]


def _expire_invite_recipients(
    session: Session, *, org_id: int, now: datetime, days: int
) -> None:
    """Drop stale addresses from old invitations, without stranding anyone.

    An address is personal data on the invitation whether or not the person ever
    opened the link, so an invitation past the window should not still be
    carrying one. But the invitation is also the *credential*:
    `api._check_invited` admits exactly the addresses listed here, so removing
    one ends that person's access.

    Which makes the naive version of this — wipe every recipient of an invite
    older than the window — a bug that loses a candidate's work. Retention is
    measured from when someone *sat*, so an invitation sent thirteen months ago
    and opened yesterday is old while the sitting on it is current; blanking its
    recipients locks that candidate out mid-assessment with everything they had
    written still unsubmitted.

    So only addresses with nothing live are dropped: no attempt at all (they
    never came, and the link is long past the window) or an attempt already
    anonymised (`_erase` removed them as part of the sitting). An address still
    holding an un-erased sitting stays until that sitting expires on its own.
    """
    cutoff = _naive_utc(now - timedelta(days=days))
    stale = session.exec(
        select(Invite).where(
            col(Invite.id).in_(org_invite_ids(org_id, session)),
            col(Invite.created_at) < cutoff,
        )
    ).all()
    for invite in stale:
        if not invite.recipients and not invite.deliveries:
            continue
        live = {
            attempt.candidate_email.strip().lower()
            for attempt in session.exec(
                select(CandidateAttempt).where(
                    col(CandidateAttempt.invite_id) == invite.id,
                    col(CandidateAttempt.erased_at).is_(None),
                )
            ).all()
        }
        keep = [r for r in invite.recipients if r.strip().lower() in live]
        deliveries = [
            d for d in invite.deliveries if str(d.get("recipient", "")).strip().lower() in live
        ]
        if len(keep) == len(invite.recipients) and len(deliveries) == len(invite.deliveries):
            continue
        invite.recipients = keep
        invite.deliveries = deliveries
        session.add(invite)


def purge_expired(session: Session, *, now: datetime | None = None) -> int:
    """Apply every organisation's retention policy once; returns the number of
    sittings erased. Commits per organisation, so one tenant's failure cannot
    roll back another's completed work.

    Organisations with `retention_days` unset (the default) are skipped
    entirely — retention is something a customer turns on, never a window this
    platform picks on their behalf and starts deleting under.

    Invitations past the window also shed the addresses that have nothing live
    behind them — see `_expire_invite_recipients`, which is careful not to strand
    a sitting that is still inside the window.
    """
    stamp = now or datetime.now(timezone.utc)
    erased = 0
    orgs = session.exec(
        select(Organization).where(col(Organization.retention_days).is_not(None))
    ).all()
    for organization in orgs:
        days = organization.retention_days
        org_id = organization.id
        if days is None or days <= 0 or org_id is None:
            continue
        try:
            for invite_id, email in expired_sittings(
                session, now=stamp, org_id=org_id, days=days
            ):
                erase_sitting(session, invite_id=invite_id, email=email, now=stamp)
                erased += 1
            _expire_invite_recipients(session, org_id=org_id, now=stamp, days=days)
            session.commit()
        except Exception:  # one tenant's failure must not stop the rest
            session.rollback()
            logger.exception("retention purge failed for organisation %s", org_id)
    if erased:
        logger.info("retention purge erased %s expired sitting(s)", erased)
    return erased
