"""Rate limiting, in two backends selected by `RATE_LIMIT_BACKEND` (SEC4).

- `memory` (default): sliding-window counters keyed by (bucket, client-ip) in a
  process-local dict. Enough to blunt login brute-force and public-endpoint spam
  on a single-process deploy — but each worker counts alone, so N workers
  multiply every limit by N.
- `db`: fixed-window counters in the shared database (`RateLimitCounter`), so
  every worker/instance sharing the DB shares the counts. Set this whenever the
  API runs with more than one process.

Either way enforcement is opt-out: a `max_requests` of 0 disables the bucket,
and a request that gets 429'd never consumes quota.
"""

from __future__ import annotations

import threading
import time
from typing import cast

from fastapi import HTTPException, Request
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col

from . import config
from . import db as db_module
from .models import RateLimitCounter

# Above this many tracked (bucket, client) keys, drop the ones whose hits have all
# aged out. Keys are only ever pruned lazily on their own next hit, so without this
# a public endpoint — where the set of client IPs is unbounded — grows the dict
# forever with entries for callers never seen again.
_MAX_TRACKED_KEYS = 10_000


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _purge_expired(self, cutoff: float) -> None:
        """Drop keys with no hits left inside the window. Caller must hold the lock."""
        for key in [k for k, hits in self._hits.items() if not any(t > cutoff for t in hits)]:
            del self._hits[key]

    def check(self, bucket: str, client: str, max_requests: int, window_s: int) -> None:
        """Record a hit for (bucket, client); raise 429 if over the limit."""
        if max_requests <= 0:
            return
        now = time.monotonic()
        cutoff = now - window_s
        key = (bucket, client)
        with self._lock:
            if len(self._hits) > _MAX_TRACKED_KEYS:
                self._purge_expired(cutoff)
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= max_requests:
                raise HTTPException(
                    status_code=429, detail="too many requests; slow down and retry shortly."
                )
            hits.append(now)
            self._hits[key] = hits

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


# Rows whose window started longer ago than this are dead for any sane window
# size and get swept opportunistically on later checks. Generous on purpose:
# purging is about bounding growth from one-time clients, not correctness, and a
# grace far above any configured window can never delete a live counter.
_PURGE_GRACE_S = 86_400


class DbRateLimiter:
    """Fixed-window counters in the shared database — see the module docstring.

    The hot path is one conditional UPDATE (`count = count + 1 WHERE count <
    max`): atomic on any backend, so concurrent workers can never both increment
    past the limit. Only a key's first hit in a window takes the INSERT branch,
    and losing that race to a sibling worker falls back to the same UPDATE.
    A blocked request leaves the counter untouched, matching the memory backend.
    """

    def check(self, bucket: str, client: str, max_requests: int, window_s: int) -> None:
        """Record a hit for (bucket, client); raise 429 if over the limit."""
        if max_requests <= 0:
            return
        # Wall clock, not monotonic: the window boundary must be the same number
        # in every process, and monotonic clocks are per-process.
        now = int(time.time())
        window_start = now - (now % window_s)
        key = (
            col(RateLimitCounter.bucket) == bucket,
            col(RateLimitCounter.client) == client,
            col(RateLimitCounter.window_start) == window_start,
        )
        increment = (
            update(RateLimitCounter)
            .where(*key, col(RateLimitCounter.count) < max_requests)
            .values(count=col(RateLimitCounter.count) + 1)
        )
        with Session(db_module.engine) as session:
            session.execute(
                delete(RateLimitCounter).where(
                    col(RateLimitCounter.window_start) < now - _PURGE_GRACE_S
                )
            )
            allowed = cast(CursorResult[object], session.execute(increment)).rowcount
            if not allowed:
                # No row updated: either the counter is at the cap, or this is
                # the window's first hit and the row doesn't exist yet.
                at_cap = session.execute(
                    select(col(RateLimitCounter.count)).where(*key)
                ).first()
                if at_cap:
                    session.commit()  # keep the purge even when rejecting
                    raise HTTPException(
                        status_code=429, detail="too many requests; slow down and retry shortly."
                    )
                try:
                    session.execute(
                        insert(RateLimitCounter).values(
                            bucket=bucket, client=client, window_start=window_start, count=1
                        )
                    )
                except IntegrityError:
                    # A sibling worker inserted this window's row first; count
                    # through the same conditional increment it uses.
                    session.rollback()
                    allowed = cast(CursorResult[object], session.execute(increment)).rowcount
                    if not allowed:
                        session.commit()
                        # The duplicate-key error is the race being lost, not
                        # this rejection's cause — don't chain it into the 429.
                        raise HTTPException(
                            status_code=429,
                            detail="too many requests; slow down and retry shortly.",
                        ) from None
            session.commit()

    def reset(self) -> None:
        with Session(db_module.engine) as session:
            session.execute(delete(RateLimitCounter))
            session.commit()


limiter: RateLimiter | DbRateLimiter = (
    DbRateLimiter() if config.RATE_LIMIT_BACKEND == "db" else RateLimiter()
)


def client_ip(request: Request) -> str:
    """The address to rate-limit this request against.

    Direct (the default): the socket peer. Behind a proxy that peer is the PROXY
    for every request, so every caller shares one bucket and the first few exhaust
    the limit for everybody — hence `TRUST_PROXY_HEADERS`.

    When trusted, take the RIGHTMOST X-Forwarded-For entry, not the leftmost. A
    proxy appends the peer it actually saw, so the rightmost hop is the only
    address in that list your own infrastructure vouches for; everything to its
    left arrived from the client and can be forged to get a fresh bucket per
    request. The leftmost entry is the "real" client only if nobody lies.

    This assumes exactly one trusted proxy. With a chain (CDN in front of a load
    balancer) the trusted hop moves one place left per proxy — revisit this then
    rather than guessing a depth now.
    """
    if config.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"
