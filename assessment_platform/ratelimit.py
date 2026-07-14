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


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def check(self, bucket: str, client: str, max_requests: int, window_s: int) -> None:
        """Record a hit for (bucket, client); raise 429 if over the limit."""
        if max_requests <= 0:
            return
        now = time.monotonic()
        cutoff = now - window_s
        key = (bucket, client)
        with self._lock:
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
    return request.client.host if request.client else "unknown"
