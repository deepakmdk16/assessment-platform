"""Plans, quotas and usage metering — what an organisation may use, and what it
has used (X02).

Three ideas, deliberately kept apart:

- **Plan** — a frozen table of entitlements (`PLANS`), not database rows. Prices
  and limits are product decisions that change by editing this file and
  redeploying; storing them per organisation would mean a migration every time
  the pricing page changes, and a fleet of orgs on limits nobody remembers
  setting. `Organization.plan` stores only *which* plan, and `plan_status`
  whether it is still paid for.
- **Metering** (`record`) — a faithful count of what happened, per organisation
  per calendar month. It never blocks; a sitting that ran is recorded even if it
  ran past the limit.
- **The budget** (`consume`) — an atomic claim on an allowance *before* the money
  is spent. The conditional UPDATE (`count + n <= limit`, evaluated by the
  database) is what makes it a budget rather than an approximation: two workers
  racing at the boundary cannot both win. Same shape as
  `ratelimit.DbRateLimiter`, for the same reason.

Cost columns (`judge_cost_usd`, `draft_cost_usd`) are the per-tenant rollup of
LLM spend the audit found nowhere: the agent prices each judged submission and
each drafted question, and the numbers were previously kept only inside an
opaque JSON blob per row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import cast

from fastapi import HTTPException
from sqlalchemy import CursorResult, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from . import config
from .models import Organization, OrgUsage


@dataclass(frozen=True)
class Plan:
    """One row of the pricing page, as the server understands it."""

    key: str
    label: str
    price_usd_month: int
    # Candidate sittings started per calendar month. The metered unit of the
    # product: one candidate opening one invite is one sitting, however many
    # questions the assessment holds and however many times they reload.
    sittings: int
    # AI-drafted questions per calendar month. A variant set of N costs N — it is
    # N full drafts on the agent, at N times the price.
    drafts: int
    # Seats: memberships in the organisation, pending invitations included.
    seats: int


PLANS: dict[str, Plan] = {
    "free": Plan("free", "Free", 0, sittings=10, drafts=5, seats=2),
    "starter": Plan("starter", "Starter", 49, sittings=100, drafts=50, seats=5),
    "growth": Plan("growth", "Growth", 199, sittings=500, drafts=250, seats=20),
}
FREE = PLANS["free"]

# Subscription states that still entitle an organisation to its paid plan.
# `past_due` is deliberately included: Stripe holds a subscription there while it
# retries a card over several days, and cutting a paying customer's assessments
# off on the first failed retry loses more than the invoice is worth. Everything
# else (canceled, unpaid, incomplete, paused) falls back to the free limits —
# never to zero, so a lapsed account keeps its data and can still be evaluated.
ENTITLED_STATUSES = frozenset({"active", "trialing", "past_due"})

# The metered allowances, in the order the UI shows them. Each name is both a
# `Plan` field and an `OrgUsage` column — that symmetry is what lets `consume`
# and `remaining` take a metric by name.
METRICS = ("sittings", "drafts", "seats")

# Allowances counted per calendar month; `seats` is a standing headcount instead,
# so it is compared against the roster rather than against a usage row.
MONTHLY_METRICS = ("sittings", "drafts")


def plan_for(org: Organization) -> Plan:
    """The entitlements that apply to this organisation right now.

    An unknown plan name (a Stripe price renamed, a hand-edited row) resolves to
    free rather than raising: the fallback is a smaller allowance, never a larger
    one, so a mistake here can't hand out an unpaid Growth plan.
    """
    if org.plan_status not in ENTITLED_STATUSES:
        return FREE
    return PLANS.get(org.plan, FREE)


def period_key(now: datetime | None = None) -> str:
    """The billing period a moment falls in: the UTC calendar month, ``YYYY-MM``.

    UTC, not local time, so every worker agrees on which month a sitting at
    midnight belongs to (the same reason the rate limiter floors wall-clock).
    """
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m")


def previous_period(period: str) -> str:
    """The period before this one — "2026-01" goes back to "2025-12"."""
    year, month = (int(part) for part in period.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def allowance(org: Organization, metric: str, row: OrgUsage) -> int:
    """What this organisation may actually use this period.

    The plan's entitlement less whatever the previous period overran by. Never
    negative: a debt bigger than a month's allowance stops that month rather
    than compounding into the next, which would take an organisation months to
    climb out of over a single mistake.
    """
    plan_limit = cast(int, getattr(plan_for(org), metric))
    return max(0, plan_limit - cast(int, getattr(row, f"{metric}_carried")))


def usage(session: Session, org_id: int, period: str | None = None) -> OrgUsage:
    """This period's counters for an organisation.

    Returns a transient all-zero row when nothing has been metered yet, so a read
    path (the billing page) never writes to the database just by being looked at.
    """
    period = period or period_key()
    row = session.exec(
        select(OrgUsage).where(OrgUsage.org_id == org_id, OrgUsage.period == period)
    ).first()
    return row or OrgUsage(org_id=org_id, period=period)


def _carried_from(session: Session, org: Organization | None, org_id: int, period: str) -> dict[str, int]:
    """What the previous period overran, to be charged against this one.

    Settled lazily, when the new period's row is first created, because there is
    no scheduler to settle it on the stroke of the month — and the first metered
    event of a period is exactly when the answer is first needed.

    The overage is measured against the plan in force *now*, not the one that
    was in force then (nothing stores a plan's history). That errs in the
    customer's favour: an organisation that has since upgraded carries less, and
    one that has downgraded is the case this exists to catch anyway.
    """
    if org is None:
        return {}
    previous = session.exec(
        select(OrgUsage).where(
            OrgUsage.org_id == org_id, OrgUsage.period == previous_period(period)
        )
    ).first()
    if previous is None:
        return {}
    plan = plan_for(org)
    carried = {}
    for metric in MONTHLY_METRICS:
        # Against the previous period's own effective allowance, so a debt that
        # was already served there is not charged twice.
        served = max(0, cast(int, getattr(plan, metric)) - cast(int, getattr(previous, f"{metric}_carried")))
        over = cast(int, getattr(previous, metric)) - served
        if over > 0:
            carried[f"{metric}_carried"] = over
    return carried


def _ensure_row(
    session: Session, org_id: int, period: str, org: Organization | None = None
) -> None:
    """Insert this period's counter row, tolerating a sibling worker's insert.

    Creating the row is also when the previous period is settled — see
    `_carried_from`. The organisation is looked up when the caller hasn't
    already got it (`record` has only an id): a month whose first event is a
    cost record rather than a claim must still settle the previous one, or the
    debt is silently forgiven by whichever event happened to come first.
    """
    org = org or session.get(Organization, org_id)
    try:
        session.add(OrgUsage(org_id=org_id, period=period, **_carried_from(session, org, org_id, period)))
        session.commit()
    except IntegrityError:
        session.rollback()


def remaining(session: Session, org: Organization, metric: str, used: int | None = None) -> int:
    """How many more units of `metric` this organisation may use this period.

    Never negative: usage can exceed an allowance (a plan downgraded mid-month,
    a deployment that meters without enforcing), and "how much is left" is
    nought in that case, not a negative allowance — the overrun is settled by
    `_carried_from` at the period boundary instead.

    `used` must be supplied for `seats`, which is a live headcount rather than
    a column on the usage row.
    """
    row = usage(session, _org_id(org))
    limit = (
        cast(int, getattr(plan_for(org), metric))
        if metric not in MONTHLY_METRICS
        else allowance(org, metric, row)
    )
    if used is None:
        used = cast(int, getattr(row, metric))
    return max(0, limit - used)


def _org_id(org: Organization) -> int:
    if org.id is None:  # pragma: no cover — a persisted org always has one
        raise RuntimeError("organisation has no id")
    return org.id


def quota_error(org: Organization, metric: str, limit: int | None = None) -> HTTPException:
    """The 402 an interviewer-facing route raises when an allowance is spent.

    402 Payment Required is the whole point of the status code, and it is what
    lets the web client show an upgrade prompt without parsing the message.
    `limit` is the effective allowance where that differs from the plan's — a
    message naming a limit the organisation did not actually get is a support
    ticket.
    """
    plan = plan_for(org)
    if limit is None:
        limit = cast(int, getattr(plan, metric))
    noun = {"sittings": "candidate sittings", "drafts": "AI question drafts", "seats": "seats"}[
        metric
    ]
    period = "" if metric == "seats" else " this month"
    return HTTPException(
        status_code=402,
        detail=(
            f"the {plan.label} plan's limit of {limit} {noun}{period} is used up. "
            "Upgrade the plan in Settings → Billing to continue."
        ),
    )


def consume(session: Session, org: Organization, metric: str, n: int = 1) -> None:
    """Claim `n` units of a monthly allowance, or raise 402 if it won't fit.

    Atomic: the limit is checked inside the UPDATE, so concurrent callers at the
    boundary can never both be allowed through. A rejected claim leaves the
    counter untouched.

    Not enforced when `config.BILLING_ENFORCED` is off — the usage is still
    recorded, so a deployment can meter first and start charging later.
    """
    if n <= 0:
        return
    if not config.BILLING_ENFORCED:
        record(session, _org_id(org), **{metric: n})
        return
    org_id = _org_id(org)
    period = period_key()
    # The row has to exist before the claim, because the allowance depends on
    # what it carries from last period. Settled once per period, so reading it
    # here and using it in the conditional UPDATE below stays race-free.
    row = usage(session, org_id, period)
    if row.id is None:
        _ensure_row(session, org_id, period, org)
        row = usage(session, org_id, period)
    limit = allowance(org, metric, row)
    column = getattr(OrgUsage, metric)
    claim = (
        update(OrgUsage)
        .where(
            col(OrgUsage.org_id) == org_id,
            col(OrgUsage.period) == period,
            col(column) + n <= limit,
        )
        .values(**{metric: col(column) + n})
    )
    if not cast(CursorResult[object], session.execute(claim)).rowcount:
        # The row exists (created above), so this is the allowance being spent.
        session.rollback()
        raise quota_error(org, metric, limit)
    session.commit()


def release(session: Session, org_id: int, metric: str, n: int = 1) -> None:
    """Hand back a claim whose work never happened (the agent refused the draft).

    Floored at zero so a double release can't mint allowance out of nothing.
    """
    row = usage(session, org_id)
    if row.id is None:
        return
    setattr(row, metric, max(0, cast(int, getattr(row, metric)) - n))
    session.add(row)
    session.commit()


def record(
    session: Session,
    org_id: int,
    *,
    sittings: int = 0,
    drafts: int = 0,
    judge_cost_usd: float = 0.0,
    draft_cost_usd: float = 0.0,
) -> None:
    """Add to this period's counters. Never refuses — this is the record of what
    happened, and `consume` is the gate that decides whether it may.

    Call it *after* the route has committed its own work: metering a sitting that
    then failed to be stored would bill for nothing.
    """
    deltas = {
        "sittings": sittings,
        "drafts": drafts,
        "judge_cost_usd": judge_cost_usd,
        "draft_cost_usd": draft_cost_usd,
    }
    deltas = {k: v for k, v in deltas.items() if v}
    if not deltas:
        return
    period = period_key()
    bump = (
        update(OrgUsage)
        .where(col(OrgUsage.org_id) == org_id, col(OrgUsage.period) == period)
        .values(**{k: col(getattr(OrgUsage, k)) + v for k, v in deltas.items()})
    )
    if not cast(CursorResult[object], session.execute(bump)).rowcount:
        _ensure_row(session, org_id, period)
        session.execute(bump)
    session.commit()
