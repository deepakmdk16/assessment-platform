"""AR1 — aggregate analytics. Unit tests for the DB-free maths in `analytics.py`
plus offline integration tests for the three `/analytics/*` endpoints (seeded
through the real submit + callback path, no network / no LLM). Owner-scoped."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient

from assessment_platform import agent_client, analytics

# --------------------------------------------------------------------------- #
# Pure helpers                                                                  #
# --------------------------------------------------------------------------- #


def test_mean_median_rate_empty_is_none() -> None:
    assert analytics.mean([]) is None
    assert analytics.median_value([]) is None
    assert analytics.rate(0, 0) is None  # undefined, not 0
    assert analytics.mean([2.0, 4.0]) == 3.0
    assert analytics.median_value([1.0, 2.0, 3.0]) == 2.0
    assert analytics.median_value([1.0, 3.0]) == 2.0
    assert analytics.rate(1, 4) == 0.25


def test_time_to_solve_seconds() -> None:
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert analytics.time_to_solve_seconds(t0, t0 + timedelta(seconds=90)) == 90.0
    assert analytics.time_to_solve_seconds(None, t0) is None
    assert analytics.time_to_solve_seconds(t0, None) is None
    # negative (clock skew) is noise, not data
    assert analytics.time_to_solve_seconds(t0, t0 - timedelta(seconds=5)) is None


def test_daily_series_buckets_by_day() -> None:
    d1 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    d2 = datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc)
    series = analytics.daily_series(
        [
            (d1, True, True),  # graded, passed
            (d1, True, False),  # graded, failed
            (d1, False, False),  # ungraded
            (d2, True, True),
        ]
    )
    assert [p["date"] for p in series] == [d1.date(), d2.date()]  # ascending
    day1 = series[0]
    assert (day1["submissions"], day1["graded"], day1["passed"]) == (3, 2, 1)
    assert day1["pass_rate"] == 0.5  # over graded, not submissions
    assert series[1]["pass_rate"] == 1.0


def test_score_distribution_top_edge_inclusive() -> None:
    buckets = analytics.score_distribution([15.0, 25.0, 100.0], bucket_size=20.0)
    assert len(buckets) == 5  # [0,20) .. [80,100]
    assert buckets[0]["count"] == 1  # 15
    assert buckets[1]["count"] == 1  # 25
    assert buckets[-1]["count"] == 1  # 100 lands in the last bucket, not overflow
    assert buckets[-1]["high"] == 100.0


def test_rank_and_percentile_competition_ranking() -> None:
    pop = [90.0, 80.0, 70.0]
    assert analytics.rank_and_percentile(90.0, pop) == (1, 1.0)
    assert analytics.rank_and_percentile(80.0, pop) == (2, 2 / 3)
    assert analytics.rank_and_percentile(70.0, pop) == (3, 1 / 3)
    # ties share the rank (the next rank skips)
    tied = [90.0, 90.0, 70.0]
    assert analytics.rank_and_percentile(90.0, tied)[0] == 1
    assert analytics.rank_and_percentile(70.0, tied)[0] == 3


# --------------------------------------------------------------------------- #
# Endpoints (integration, seeded via the real candidate flow)                  #
# --------------------------------------------------------------------------- #


def _question(qid: str) -> dict[str, Any]:
    return {
        "id": qid,
        "title": f"Q {qid}",
        "prompt": "p",
        "constraints": "c",
        "test_cases": [
            {"name": "t1", "stdin": "1\n", "expected": "1", "category": "correctness"},
            {"name": "t2", "stdin": "2\n", "expected": "2", "category": "correctness"},
            {"name": "t3", "stdin": "3\n", "expected": "3", "category": "correctness"},
            {"name": "t4", "stdin": "4\n", "expected": "4", "category": "correctness"},
            {"name": "big", "stdin": "9\n", "expected": "9", "category": "performance"},
        ],
    }


def _callback(job_id: str, verdict: str, score: float) -> dict[str, Any]:
    return {"job_id": job_id, "verdict": verdict, "score_pct": score, "reason": "r"}


def _seed_assessment(client: TestClient, monkeypatch) -> None:
    """q1/q2 in assessment a1; cand1 submits both (q1 PASS 100, q2 FAIL 40),
    cand2 submits only q1 (PASS 80). One question stays ungraded for cand2."""
    for qid in ("q1", "q2"):
        assert client.post("/questions", json=_question(qid)).status_code == 201
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1", "q2"]})
    tok = client.post(
        "/assessments/a1/invites", json={"recipients": ["cand1@x.io", "cand2@x.io"]}
    ).json()["token"]

    def submit(email: str, name: str, qid: str, job_id: str) -> None:
        monkeypatch.setattr(agent_client, "trigger_assessment", async_return(job_id))
        resp = client.post(
            f"/invite/{tok}/submit",
            json={
                "candidate_name": name, "candidate_email": email,
                "language": "python", "code": "x", "question_id": qid,
            },
        )
        assert resp.status_code == 201

    client.post(f"/invite/{tok}/start", json={"candidate_email": "cand1@x.io", "candidate_name": "One"})
    submit("cand1@x.io", "One", "q1", "job-1a")
    submit("cand1@x.io", "One", "q2", "job-1b")
    client.post(f"/invite/{tok}/start", json={"candidate_email": "cand2@x.io", "candidate_name": "Two"})
    submit("cand2@x.io", "Two", "q1", "job-2a")

    client.post("/assessments/callback", json=_callback("job-1a", "PASS", 100.0))
    client.post("/assessments/callback", json=_callback("job-1b", "FAIL", 40.0))
    client.post("/assessments/callback", json=_callback("job-2a", "PASS", 80.0))


def test_overview(client, monkeypatch) -> None:
    _seed_assessment(client, monkeypatch)
    o = client.get("/analytics/overview").json()
    assert o["questions"] == 2
    assert o["submissions"] == 3
    assert o["graded"] == 3
    assert o["candidates"] == 2
    assert o["passed"] == 2
    assert o["pass_rate"] == 2 / 3
    assert o["avg_score_pct"] == (100 + 40 + 80) / 3
    # all seeded on one day -> a single trend point carrying that day's counts
    assert len(o["trend"]) == 1
    assert (o["trend"][0]["submissions"], o["trend"][0]["graded"], o["trend"][0]["passed"]) == (3, 3, 2)


def test_overview_empty_workspace(client) -> None:
    o = client.get("/analytics/overview").json()
    assert (o["questions"], o["submissions"], o["graded"], o["candidates"]) == (0, 0, 0, 0)
    assert o["pass_rate"] is None and o["avg_score_pct"] is None
    assert o["trend"] == []
    # the histogram always has its five buckets, all empty
    assert [b["count"] for b in o["score_distribution"]] == [0, 0, 0, 0, 0]


def test_days_window_excludes_old_submissions(client, monkeypatch) -> None:
    """`?days=N` windows the submission-derived stats; older rows drop out while
    the all-time view still counts them."""
    from sqlmodel import Session, select

    from assessment_platform import db as db_module
    from assessment_platform.models import Submission

    _seed_assessment(client, monkeypatch)
    # Backdate the (single) q2 submission to well outside a 30-day window.
    with Session(db_module.engine) as s:
        sub = s.exec(select(Submission).where(Submission.question_id == "q2")).one()
        sub.created_at = datetime.now(timezone.utc) - timedelta(days=60)
        s.add(sub)
        s.commit()

    windowed = client.get("/analytics/overview?days=30").json()
    assert windowed["submissions"] == 2  # only the two q1 submissions remain
    assert windowed["graded"] == 2
    assert client.get("/analytics/overview").json()["submissions"] == 3  # all-time unchanged

    page = client.get("/analytics/questions?days=30").json()
    by_id = {q["question_id"]: q for q in page["items"]}
    assert by_id["q2"]["submissions"] == 0  # its only submission is outside the window
    assert by_id["q1"]["submissions"] == 2


def test_per_question(client, monkeypatch) -> None:
    _seed_assessment(client, monkeypatch)
    page = client.get("/analytics/questions").json()
    assert page["total"] == 2
    by_id = {q["question_id"]: q for q in page["items"]}

    q1 = by_id["q1"]
    assert (q1["submissions"], q1["graded"], q1["passed"]) == (2, 2, 2)
    assert q1["pass_rate"] == 1.0
    assert q1["avg_score_pct"] == 90.0  # (100 + 80) / 2
    assert q1["median_score_pct"] == 90.0
    assert q1["late"] == 0
    assert q1["avg_time_to_solve_s"] is not None and q1["avg_time_to_solve_s"] >= 0

    q2 = by_id["q2"]
    assert (q2["submissions"], q2["graded"], q2["passed"]) == (1, 1, 0)
    assert q2["pass_rate"] == 0.0
    assert q2["avg_score_pct"] == 40.0


def test_per_assessment(client, monkeypatch) -> None:
    _seed_assessment(client, monkeypatch)
    a = client.get("/analytics/assessments/a1").json()
    assert a["slot_count"] == 2
    assert a["candidates_started"] == 2
    assert a["candidates_completed"] == 1  # only cand1 submitted both slots
    assert a["avg_score_pct"] == 75.0  # mean of per-candidate avgs (70, 80)
    assert a["pass_rate"] == 2 / 3  # 2 passed of 3 graded question-attempts

    cands = {c["candidate_email"]: c for c in a["candidates"]}
    assert cands["cand1@x.io"]["submitted_count"] == 2  # both slots
    assert cands["cand2@x.io"]["submitted_count"] == 1  # only q1
    assert cands["cand2@x.io"]["rank"] == 1  # 80 > 70
    assert cands["cand2@x.io"]["percentile"] == 1.0
    assert cands["cand1@x.io"]["rank"] == 2
    assert cands["cand1@x.io"]["percentile"] == 0.5
    assert cands["cand1@x.io"]["time_to_solve_s"] is not None
    # distribution covers the per-candidate averages (70 and 80)
    assert sum(b["count"] for b in a["score_distribution"]) == 2


def test_analytics_owner_scoped(anon_client: TestClient, monkeypatch) -> None:
    """A second interviewer sees none of the first's questions/results."""
    owner = register_interviewer(anon_client, "a@test.io", name="A")
    anon_client.headers["Authorization"] = f"Bearer {owner}"
    _seed_assessment(anon_client, monkeypatch)

    other = register_interviewer(anon_client, "b@test.io", name="B")
    anon_client.headers["Authorization"] = f"Bearer {other}"
    o = anon_client.get("/analytics/overview").json()
    assert (o["questions"], o["submissions"]) == (0, 0)
    assert anon_client.get("/analytics/questions").json()["total"] == 0
    # the other interviewer can't read this assessment's analytics (owned by A)
    assert anon_client.get("/analytics/assessments/a1").status_code == 403


def test_analytics_requires_auth(anon_client: TestClient) -> None:
    assert anon_client.get("/analytics/overview").status_code == 401
    assert anon_client.get("/analytics/questions").status_code == 401
