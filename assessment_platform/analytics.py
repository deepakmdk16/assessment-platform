"""Pure aggregation helpers for the analytics endpoints (AR1).

These functions take already-fetched primitives (numbers, datetimes, plain
tuples) and never touch the DB, Pydantic, or FastAPI — the routes in `api.py` do
the querying and owner-scoping, then call these to turn rows into stats. Keeping
the maths here (and DB-free) makes it unit-testable without a database, matching
the repo's "tested logic half" convention. All rates are fractions in [0, 1];
the frontend formats them as percentages.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from statistics import median


def mean(values: Sequence[float]) -> float | None:
    """Arithmetic mean, or None for an empty sequence (no data ≠ zero)."""
    return sum(values) / len(values) if values else None


def median_value(values: Sequence[float]) -> float | None:
    """Median, or None for an empty sequence. Named to avoid shadowing
    `statistics.median`, which raises on empty input."""
    return float(median(values)) if values else None


def rate(numerator: int, denominator: int) -> float | None:
    """A fraction in [0, 1], or None when the denominator is zero (undefined,
    not zero — e.g. pass rate over 0 graded submissions is unknown, not 0%)."""
    return numerator / denominator if denominator else None


def time_to_solve_seconds(started_at: datetime | None, submitted_at: datetime | None) -> float | None:
    """Seconds from opening the invite (`CandidateAttempt.started_at`) to a
    submission. None when either endpoint is missing, or the delta is negative
    (clock skew / naive-vs-aware oddities) — a negative time-to-solve is noise,
    not data."""
    if started_at is None or submitted_at is None:
        return None
    delta = (submitted_at - started_at).total_seconds()
    return delta if delta >= 0 else None


def daily_series(events: Iterable[tuple[datetime, bool, bool]]) -> list[dict]:
    """A per-day time series for the workspace trend chart. Each event is
    `(created_at, graded, passed)`; the output is one dict per day that has any
    submission, sorted ascending, carrying submissions/graded/passed counts and
    the pass rate over *graded* rows that day (None when nothing graded yet)."""
    buckets: dict[date, list[int]] = defaultdict(lambda: [0, 0, 0])  # subs, graded, passed
    for created_at, graded, passed in events:
        b = buckets[created_at.date()]
        b[0] += 1
        if graded:
            b[1] += 1
            if passed:
                b[2] += 1
    out: list[dict] = []
    for day in sorted(buckets):
        subs, graded_n, passed_n = buckets[day]
        out.append(
            {
                "date": day,
                "submissions": subs,
                "graded": graded_n,
                "passed": passed_n,
                "pass_rate": rate(passed_n, graded_n),
            }
        )
    return out


def score_distribution(scores: Sequence[float], bucket_size: float = 20.0) -> list[dict]:
    """Histogram of scores (0..100) into fixed-width buckets for the distribution
    chart. Buckets are `[0,20), [20,40), … , [80,100]` by default; the top edge
    is inclusive so a perfect 100 lands in the last bucket rather than a lone
    overflow one. Returns every bucket (including empties) so the chart has a
    stable x-axis."""
    edges = []
    lo = 0.0
    while lo < 100.0:
        edges.append(lo)
        lo += bucket_size
    counts = [0] * len(edges)
    for s in scores:
        idx = min(int(s // bucket_size), len(edges) - 1)  # 100 -> last bucket
        counts[max(idx, 0)] += 1
    out: list[dict] = []
    for i, edge in enumerate(edges):
        hi = min(edge + bucket_size, 100.0)
        out.append({"low": edge, "high": hi, "count": counts[i]})
    return out


def rank_and_percentile(value: float, population: Sequence[float]) -> tuple[int, float | None]:
    """A candidate's competition rank (1-based, standard competition ranking:
    ties share a rank, the next rank skips) and percentile within `population`
    (the share scoring at or below them, in [0, 1]). `value` must be a member of
    `population`. Percentile is None only for an empty population."""
    if not population:
        return 1, None
    strictly_greater = sum(1 for v in population if v > value)
    at_or_below = sum(1 for v in population if v <= value)
    return strictly_greater + 1, at_or_below / len(population)
