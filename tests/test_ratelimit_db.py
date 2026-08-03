"""DbRateLimiter (SEC4): fixed-window counters shared through the database.

The point of the backend is that limits hold across processes, so the tests
drive TWO limiter instances against one engine wherever sharing is the claim —
one instance would pass even with per-instance state.
"""

from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from assessment_platform import db as db_module
from assessment_platform import ratelimit
from assessment_platform.models import RateLimitCounter
from assessment_platform.ratelimit import DbRateLimiter

WINDOW = 60


@pytest.fixture
def db_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    yield engine
    engine.dispose()


def _freeze_time(monkeypatch: pytest.MonkeyPatch, t: float) -> None:
    monkeypatch.setattr(ratelimit.time, "time", lambda: t)


def _rows(engine: object) -> list[RateLimitCounter]:
    with Session(engine) as session:  # type: ignore[arg-type]
        return list(session.exec(select(RateLimitCounter)).all())


def test_limit_is_shared_across_limiter_instances(db_engine, monkeypatch) -> None:
    # Two instances stand in for two worker processes: hits recorded through one
    # must count against the other, which is exactly what the memory backend
    # cannot do.
    _freeze_time(monkeypatch, 1_000_000)
    a, b = DbRateLimiter(), DbRateLimiter()
    a.check("login", "1.2.3.4", 2, WINDOW)
    b.check("login", "1.2.3.4", 2, WINDOW)
    with pytest.raises(HTTPException) as exc:
        a.check("login", "1.2.3.4", 2, WINDOW)
    assert exc.value.status_code == 429


def test_blocked_request_does_not_consume_quota(db_engine, monkeypatch) -> None:
    # Matches the memory backend: a 429'd hit leaves the counter untouched, so
    # hammering while blocked can't inflate the recorded count.
    _freeze_time(monkeypatch, 1_000_000)
    lim = DbRateLimiter()
    lim.check("login", "1.2.3.4", 1, WINDOW)
    for _ in range(3):
        with pytest.raises(HTTPException):
            lim.check("login", "1.2.3.4", 1, WINDOW)
    (row,) = _rows(db_engine)
    assert row.count == 1


def test_separate_buckets_and_clients_do_not_share_counts(db_engine, monkeypatch) -> None:
    _freeze_time(monkeypatch, 1_000_000)
    lim = DbRateLimiter()
    lim.check("login", "1.2.3.4", 1, WINDOW)
    lim.check("register", "1.2.3.4", 1, WINDOW)  # other bucket, same client
    lim.check("login", "5.6.7.8", 1, WINDOW)  # same bucket, other client
    with pytest.raises(HTTPException):
        lim.check("login", "1.2.3.4", 1, WINDOW)


def test_window_rollover_grants_fresh_quota(db_engine, monkeypatch) -> None:
    t0 = 1_000_000 - (1_000_000 % WINDOW)  # aligned so +WINDOW is a new window
    _freeze_time(monkeypatch, t0)
    lim = DbRateLimiter()
    lim.check("login", "1.2.3.4", 1, WINDOW)
    with pytest.raises(HTTPException):
        lim.check("login", "1.2.3.4", 1, WINDOW)
    _freeze_time(monkeypatch, t0 + WINDOW)
    lim.check("login", "1.2.3.4", 1, WINDOW)  # new window, no raise


def test_zero_max_disables_the_bucket(db_engine, monkeypatch) -> None:
    _freeze_time(monkeypatch, 1_000_000)
    lim = DbRateLimiter()
    for _ in range(5):
        lim.check("login", "1.2.3.4", 0, WINDOW)
    assert _rows(db_engine) == []


def test_reset_clears_all_counters(db_engine, monkeypatch) -> None:
    _freeze_time(monkeypatch, 1_000_000)
    lim = DbRateLimiter()
    lim.check("login", "1.2.3.4", 1, WINDOW)
    lim.reset()
    assert _rows(db_engine) == []
    lim.check("login", "1.2.3.4", 1, WINDOW)  # quota is fresh again


def test_dead_windows_are_purged_on_later_checks(db_engine, monkeypatch) -> None:
    t0 = 1_000_000
    _freeze_time(monkeypatch, t0)
    lim = DbRateLimiter()
    lim.check("login", "1.2.3.4", 5, WINDOW)
    # Long after the grace, an unrelated client's check sweeps the dead row.
    _freeze_time(monkeypatch, t0 + ratelimit._PURGE_GRACE_S + WINDOW)
    lim.check("login", "5.6.7.8", 5, WINDOW)
    assert {r.client for r in _rows(db_engine)} == {"5.6.7.8"}


def test_losing_the_first_hit_race_falls_back_to_incrementing(db_engine, monkeypatch) -> None:
    # Simulate a sibling worker winning the window's first INSERT between this
    # process's cap-check and its own INSERT: the patched insert() lands the
    # sibling's row, then raises the duplicate-key error the loser would see.
    t0 = 1_000_000
    _freeze_time(monkeypatch, t0)
    window_start = t0 - (t0 % WINDOW)

    def racing_insert(table: object) -> object:
        with Session(db_engine) as session:
            session.add(
                RateLimitCounter(
                    bucket="login", client="1.2.3.4", window_start=window_start, count=1
                )
            )
            session.commit()
        raise IntegrityError("INSERT INTO ratelimitcounter", {}, Exception("duplicate key"))

    monkeypatch.setattr(ratelimit, "insert", racing_insert)
    lim = DbRateLimiter()
    lim.check("login", "1.2.3.4", 2, WINDOW)  # loses the race, still counted
    (row,) = _rows(db_engine)
    assert row.count == 2  # the sibling's hit + this one


def test_losing_the_race_at_the_cap_rejects(db_engine, monkeypatch) -> None:
    # Same race, but the sibling's hit was the last allowed one: the fallback
    # increment finds the counter at the cap and this request 429s.
    t0 = 1_000_000
    _freeze_time(monkeypatch, t0)
    window_start = t0 - (t0 % WINDOW)

    def racing_insert(table: object) -> object:
        with Session(db_engine) as session:
            session.add(
                RateLimitCounter(
                    bucket="login", client="1.2.3.4", window_start=window_start, count=1
                )
            )
            session.commit()
        raise IntegrityError("INSERT INTO ratelimitcounter", {}, Exception("duplicate key"))

    monkeypatch.setattr(ratelimit, "insert", racing_insert)
    lim = DbRateLimiter()
    with pytest.raises(HTTPException) as exc:
        lim.check("login", "1.2.3.4", 1, WINDOW)
    assert exc.value.status_code == 429
