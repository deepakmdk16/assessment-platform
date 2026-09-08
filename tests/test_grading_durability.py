"""Grading durability (STATUS §E P05 / P10 / P15, agent A04).

The platform mints the agent job id (the submission's own id) and commits it
BEFORE triggering, never 502s a submit, retries the trigger at the transport
level, and a background reaper re-triggers stranded submissions and gives up
loudly. Fully offline: the agent is mocked at `agent_client` or at the HTTP
boundary; the reaper loop is off under test and its tick is driven directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from typing import Any

import httpx
import pytest
from conftest import async_raise, async_return, patch_async_post
from sqlmodel import Session
from test_api import (
    _age_submission,
    _callback_payload,
    _create_running_submission,
    _sample_question,
    _tick,
)

from assessment_platform import agent_client, api, config
from assessment_platform import db as db_module
from assessment_platform.models import Question, Submission

SUBMIT = {"question_id": "sum_of_n", "candidate": "Jane", "language": "python", "code": "x"}


def _state(sub_id: str) -> tuple[str, str | None, int]:
    """(status, agent_job_id, attempts) straight from the database."""
    with Session(db_module.engine) as s:
        row = s.get(Submission, sub_id)
        assert row is not None
        return row.status, row.agent_job_id, row.attempts


# --- P05: the job id is ours, and it is committed before the agent hears of it --


def test_job_id_is_the_submission_id_committed_before_the_trigger(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    seen: dict[str, Any] = {}

    async def fake_trigger(question, submission, callback_url, base_url=None):  # noqa: ANN001
        # What a concurrent reader — the agent's callback — sees mid-trigger.
        with Session(db_module.engine) as s:
            row = s.get(Submission, submission.id)
            assert row is not None
            seen.update(job_id=row.agent_job_id, status=row.status, attempts=row.attempts)
        return submission.agent_job_id

    monkeypatch.setattr(agent_client, "trigger_assessment", fake_trigger)
    resp = client.post("/submissions", json=SUBMIT)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["agent_job_id"] == body["id"]
    assert seen == {"job_id": body["id"], "status": "pending", "attempts": 1}
    assert body["status"] == "running"


def test_callback_arriving_before_the_202_is_recorded_still_lands(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())

    async def fast_agent(question, submission, callback_url, base_url=None):  # noqa: ANN001
        # The agent graded and called back before we even processed its 202.
        with Session(db_module.engine) as s:
            out = api.assessments_callback(_callback_payload(submission.agent_job_id), session=s)
        assert out["status"] == "ok"
        return submission.agent_job_id

    monkeypatch.setattr(agent_client, "trigger_assessment", fast_agent)
    resp = client.post("/submissions", json=SUBMIT)
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "done"  # never regressed to "running"
    sub = client.get(f"/submissions/{resp.json()['id']}").json()
    assert sub["status"] == "done"
    assert sub["result"]["verdict"] == "PASS"


def test_an_older_agent_that_mints_its_own_id_still_works(client, monkeypatch) -> None:
    # Backwards compatibility: whatever id the agent echoes is stored, so its
    # callback matches even if it ignored ours.
    sub_id = _create_running_submission(client, monkeypatch, "agent-minted")
    assert _state(sub_id) == ("running", "agent-minted", 1)
    resp = client.post("/assessments/callback", json=_callback_payload("agent-minted"))
    assert resp.json()["status"] == "ok"
    assert _state(sub_id)[0] == "done"


# --- P15: the trigger is retried, and a submit never burns the attempt ---------


@pytest.mark.parametrize(
    ("first_failure", "second_status"),
    [
        (httpx.ConnectError, 503),  # agent down, then mid-restart
        (httpx.ReadTimeout, 429),  # lost 202 (safe: the agent de-dups the id), then throttled
    ],
)
def test_trigger_retries_transient_failures_with_the_same_job_id(
    client, monkeypatch, first_failure, second_status
) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(agent_client, "_TRIGGER_RETRY_BACKOFF_S", 0.0)
    calls: list[dict[str, Any]] = []

    def on_post(url, timeout, **kw):  # noqa: ANN001
        calls.append(json.loads(kw["content"]))
        request = httpx.Request("POST", url)
        if len(calls) == 1:
            raise first_failure("transient", request=request)
        if len(calls) == 2:
            return httpx.Response(second_status, json={"detail": "later"}, request=request)
        return httpx.Response(202, json={"job_id": "sub-1", "status": "accepted"}, request=request)

    patch_async_post(monkeypatch, on_post)
    sub = Submission(
        id="sub-1", question_id="sum_of_n", candidate="J", language="python", code="x",
        agent_job_id="sub-1",
    )
    with Session(db_module.engine) as s:
        question = s.get(Question, "sum_of_n")
        assert question is not None
        job_id = asyncio.run(agent_client.trigger_assessment(question, sub, "http://cb"))
    assert job_id == "sub-1"
    assert [c["job_id"] for c in calls] == ["sub-1", "sub-1", "sub-1"]


def test_trigger_does_not_retry_a_rejected_job(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(agent_client, "_TRIGGER_RETRY_BACKOFF_S", 0.0)
    calls: list[str] = []

    def on_post(url, timeout, **kw):  # noqa: ANN001
        calls.append(url)
        return httpx.Response(
            400, json={"detail": "unsupported language"}, request=httpx.Request("POST", url)
        )

    patch_async_post(monkeypatch, on_post)
    sub = Submission(
        id="sub-2", question_id="sum_of_n", candidate="J", language="cobol", code="x",
        agent_job_id="sub-2",
    )
    with Session(db_module.engine) as s:
        question = s.get(Question, "sum_of_n")
        assert question is not None
        try:
            asyncio.run(agent_client.trigger_assessment(question, sub, "http://cb"))
        except httpx.HTTPStatusError as exc:
            assert exc.response.status_code == 400
        else:  # pragma: no cover
            raise AssertionError("a 400 must surface, not be retried")
    assert len(calls) == 1


def test_candidate_submit_never_502s_when_the_agent_is_down(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    token = client.post(
        "/questions/sum_of_n/invites", json={"recipients": ["cand@test.io"]}
    ).json()["token"]
    monkeypatch.setattr(
        agent_client, "trigger_assessment", async_raise(RuntimeError("agent down"))
    )
    resp = client.post(
        f"/invite/{token}/submit",
        json={
            "candidate_name": "Cand",
            "candidate_email": "cand@test.io",
            "language": "python",
            "code": "print(1)",
        },
    )
    # The attempt is recorded, not burned: 201 + pending, and a resubmit is the
    # usual one-attempt 409, never a "try again" on a lost grade.
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "pending"
    assert _state(resp.json()["submission_id"]) == ("pending", resp.json()["submission_id"], 1)


def test_stranded_pending_recovers_when_the_agent_returns(client, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(
        agent_client, "trigger_assessment", async_raise(RuntimeError("agent down"))
    )
    sub_id = client.post("/submissions", json=SUBMIT).json()["id"]
    assert _state(sub_id) == ("pending", sub_id, 1)

    assert _tick() == []  # too fresh: the first trigger might still be on the wire
    _age_submission(sub_id, config.TRIGGER_RETRY_AFTER_S + 1)

    async def agent_back(question, submission, callback_url, base_url=None):  # noqa: ANN001
        return submission.agent_job_id

    monkeypatch.setattr(agent_client, "trigger_assessment", agent_back)
    assert _tick() == [sub_id]
    assert _state(sub_id) == ("running", sub_id, 2)


def test_stranded_pending_is_given_up_with_an_alert_after_max_attempts(
    client, monkeypatch, caplog
) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(config, "MAX_TRIGGER_ATTEMPTS", 2)
    monkeypatch.setattr(
        agent_client, "trigger_assessment", async_raise(RuntimeError("agent down"))
    )
    sub_id = client.post("/submissions", json=SUBMIT).json()["id"]

    _age_submission(sub_id, config.TRIGGER_RETRY_AFTER_S + 1)
    assert _tick() == [sub_id]  # attempt 2, still down -> stays pending
    assert _state(sub_id) == ("pending", sub_id, 2)

    _age_submission(sub_id, config.TRIGGER_RETRY_AFTER_S + 1)
    with caplog.at_level(logging.ERROR, logger="assessment_platform.api"):
        assert _tick() == [sub_id]
    assert _state(sub_id) == ("error", sub_id, 2)
    assert any("needs a manual retry" in r.getMessage() for r in caplog.records)
    # The interviewer's manual path is open again from here.
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return(sub_id))
    assert client.post(f"/submissions/{sub_id}/retry").json()["status"] == "running"
    assert _state(sub_id) == ("running", sub_id, 3)


# --- A04 (platform half): the agent's worker-error callback re-queues -----------


def test_requeued_submission_is_retriggered_by_the_reaper(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-x")
    resp = client.post(
        "/assessments/callback",
        json={"job_id": "job-x", "status": "error", "error": "agent worker shut down"},
    )
    assert resp.json()["status"] == "requeued"
    assert _state(sub_id) == ("pending", "job-x", 1)

    _age_submission(sub_id, config.TRIGGER_RETRY_AFTER_S + 1)
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-x2"))
    assert _tick() == [sub_id]
    assert _state(sub_id) == ("running", "job-x2", 2)


def test_worker_error_after_a_grade_landed_is_ignored(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-x")
    client.post("/assessments/callback", json=_callback_payload("job-x"))
    resp = client.post(
        "/assessments/callback",
        json={"job_id": "job-x", "status": "error", "error": "agent worker shut down"},
    )
    assert resp.json()["status"] == "ignored"
    sub = client.get(f"/submissions/{sub_id}").json()
    assert sub["status"] == "done"
    assert sub["result"]["verdict"] == "PASS"


# --- P10: the claim is a compare-and-swap, so N workers can't double-trigger ---


def test_two_workers_loading_the_same_stale_row_trigger_it_once(client, monkeypatch) -> None:
    sub_id = _create_running_submission(client, monkeypatch, "job-cas")
    _age_submission(sub_id, config.REAP_RUNNING_AFTER_S + 60)
    triggered: list[str] = []

    async def count_trigger(question, submission, callback_url, base_url=None):  # noqa: ANN001
        triggered.append(submission.id)
        return submission.agent_job_id

    monkeypatch.setattr(agent_client, "trigger_assessment", count_trigger)

    async def two_workers() -> None:
        with Session(db_module.engine) as s1, Session(db_module.engine) as s2:
            a, b = s1.get(Submission, sub_id), s2.get(Submission, sub_id)
            q1, q2 = s1.get(Question, "sum_of_n"), s2.get(Question, "sum_of_n")
            assert a is not None and b is not None and q1 is not None and q2 is not None
            assert (a.status, a.attempts) == (b.status, b.attempts)  # both loaded the same version
            await api._trigger_agent(s1, q1, a)
            await api._trigger_agent(s2, q2, b)  # loses the claim: version moved on
            assert (b.status, b.attempts) == ("running", 2)  # refreshed to the DB truth

    asyncio.run(two_workers())
    assert triggered == [sub_id]
    assert _state(sub_id) == ("running", sub_id, 2)


def test_lifespan_starts_the_reaper_when_enabled_and_cancels_it_on_shutdown(monkeypatch) -> None:
    events: list[str] = []

    async def fake_loop() -> None:
        events.append("started")
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            events.append("cancelled")
            raise

    monkeypatch.setattr(api, "_reaper_loop", fake_loop)
    monkeypatch.setattr(config, "AUTO_CREATE_TABLES", False)

    async def run(interval: int) -> None:
        monkeypatch.setattr(config, "REAP_INTERVAL_S", interval)
        async with api._lifespan(api.app):
            await asyncio.sleep(0)  # let the task get scheduled

    asyncio.run(run(60))
    assert events == ["started", "cancelled"]
    events.clear()
    asyncio.run(run(0))  # disabled (the test default): no task at all
    assert events == []


def test_reaper_loop_survives_a_failing_tick(monkeypatch, caplog) -> None:
    ticks: list[int] = []

    async def flaky_tick() -> list[str]:
        ticks.append(1)
        if len(ticks) == 1:
            raise RuntimeError("db hiccup")
        return []

    monkeypatch.setattr(api, "_reap_tick", flaky_tick)
    monkeypatch.setattr(config, "REAP_INTERVAL_S", 0.001)

    async def run() -> None:
        task = asyncio.create_task(api._reaper_loop())
        while len(ticks) < 3:
            await asyncio.sleep(0.005)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    with caplog.at_level(logging.ERROR, logger="assessment_platform.api"):
        asyncio.run(run())
    assert len(ticks) >= 3  # kept ticking after the failure
    assert any("reaper tick failed" in r.getMessage() for r in caplog.records)
