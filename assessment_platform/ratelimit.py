"""A tiny in-process rate limiter.

Fixed-window counters keyed by (bucket, client-ip), kept in memory. Enough to
blunt login brute-force and public-endpoint spam on a single-process deploy; a
multi-process/prod setup would swap this for Redis. Enforcement is opt-out: a
`max_requests` of 0 disables the bucket.
"""

from __future__ import annotations

import threading
import time

from fastapi import HTTPException, Request

from . import config

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


limiter = RateLimiter()


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
