"""X08 — request correlation, structured logs, error-report scrubbing, metrics.

Fully offline: no Sentry client is ever initialised, the agent is mocked at the
HTTP boundary, and every number the scrape reports is asserted against rows this
suite wrote into the test database.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from conftest import patch_async_post
from fastapi.testclient import TestClient
from sqlmodel import Session
from test_api import _sample_question

from assessment_platform import agent_client, config, observability, signing
from assessment_platform import db as db_module
from assessment_platform.models import AssessmentResult, Submission

MINTED = re.compile(r"^[0-9a-f]{16}$")


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #


def _samples(text: str) -> dict[str, float]:
    """Parse Prometheus text exposition into {series: value}.

    Deliberately strict about the format — a malformed line (a stray newline in a
    label, a missing value) makes this raise rather than silently skip, which is
    the point: a scraper would reject the whole response the same way.
    """
    out: dict[str, float] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        series, _, value = line.rpartition(" ")
        assert series, f"unparseable exposition line: {raw!r}"
        out[series] = float(value)
    return out


def _families(text: str) -> dict[str, str]:
    """{metric name: TYPE} from the `# TYPE` lines."""
    return {
        parts[2]: parts[3]
        for parts in (line.split() for line in text.splitlines())
        if len(parts) == 4 and parts[:2] == ["#", "TYPE"]
    }


def _add(*rows: Any) -> None:
    with Session(db_module.engine) as session:
        for row in rows:
            session.add(row)
        session.commit()


def _submission(sub_id: str, status: str, **kw: Any) -> Submission:
    return Submission(
        id=sub_id,
        question_id="sum_of_n",
        candidate="Jane",
        language="python",
        code="x",
        status=status,
        **kw,
    )


def _access_record(path: str) -> logging.LogRecord:
    """A record shaped exactly like uvicorn's access log call.

    uvicorn logs `'%s - "%s %s HTTP/%s" %d'` with
    `(client_addr, method, full_path, http_version, status_code)`; QueryStringFilter
    rewrites args[2], so the tuple's shape is the contract under test.
    """
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:54321", "GET", path, "1.1", 200),
        exc_info=None,
    )


# --------------------------------------------------------------------------- #
# 1. Request ids                                                                #
# --------------------------------------------------------------------------- #


def test_adopt_request_id_takes_a_well_formed_inbound_id() -> None:
    for inbound in ("abc123", "A-b_C", "9" * 64):
        assert observability.adopt_request_id(inbound) == inbound
        assert observability.current_request_id() == inbound


@pytest.mark.parametrize(
    "inbound",
    [None, "", "x" * 65, "has space", "semi;colon", "sl/ash", "uniçode", "quote\"d"],
)
def test_adopt_request_id_mints_one_when_the_inbound_is_unusable(inbound: str | None) -> None:
    minted = observability.adopt_request_id(inbound)
    assert MINTED.match(minted), minted
    assert observability.current_request_id() == minted


def test_minted_ids_are_unique() -> None:
    assert len({observability.new_request_id() for _ in range(200)}) == 200


def test_current_request_id_outside_a_request_is_the_placeholder() -> None:
    # A fresh Context has no value for the var, which is what the reaper, the
    # retention sweep and a CLI import see.
    assert contextvars.Context().run(observability.current_request_id) == (
        observability.NO_REQUEST_ID
    )


# --------------------------------------------------------------------------- #
# 2-3. Middleware round trip, and the ordering property                         #
# --------------------------------------------------------------------------- #


def test_response_carries_a_minted_request_id(anon_client: TestClient) -> None:
    resp = anon_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}  # the body is pinned elsewhere; don't drift
    assert MINTED.match(resp.headers[observability.REQUEST_ID_HEADER])


def test_inbound_request_id_is_echoed(anon_client: TestClient) -> None:
    resp = anon_client.get("/health", headers={observability.REQUEST_ID_HEADER: "trace-42"})
    assert resp.headers[observability.REQUEST_ID_HEADER] == "trace-42"


def test_hostile_request_id_is_replaced_not_echoed(anon_client: TestClient) -> None:
    hostile = '" onload=alert(1) ' + "x" * 200
    resp = anon_client.get("/health", headers={observability.REQUEST_ID_HEADER: hostile})
    echoed = resp.headers[observability.REQUEST_ID_HEADER]
    assert echoed != hostile
    assert MINTED.match(echoed)


def test_a_413_still_carries_a_request_id(anon_client: TestClient, monkeypatch) -> None:
    """The reason `_request_context` is registered LAST (= outermost).

    `_limit_body_size` returns its 413 without calling downstream, so if the two
    were swapped the rejection would come back with no id — and a body rejected
    unread is exactly the event someone later asks about by id. Reordering the
    middleware would silently regress this.
    """
    monkeypatch.setattr(config, "MAX_BODY_BYTES", 16)
    resp = anon_client.post(
        "/submissions",
        json={"question_id": "q", "candidate": "J", "language": "python", "code": "x" * 100},
        headers={observability.REQUEST_ID_HEADER: "over-size"},
    )
    assert resp.status_code == 413
    assert resp.headers[observability.REQUEST_ID_HEADER] == "over-size"


# --------------------------------------------------------------------------- #
# 4. CORS exposure                                                              #
# --------------------------------------------------------------------------- #


def test_request_id_is_exposed_to_cross_origin_javascript(anon_client: TestClient) -> None:
    origin = config.CORS_ORIGINS[0]
    resp = anon_client.get("/health", headers={"Origin": origin})
    assert resp.status_code == 200
    exposed = [
        h.strip().lower() for h in resp.headers["access-control-expose-headers"].split(",")
    ]
    assert observability.REQUEST_ID_HEADER.lower() in exposed


# --------------------------------------------------------------------------- #
# 5. Log formatting                                                             #
# --------------------------------------------------------------------------- #


def test_request_id_filter_stamps_the_current_id() -> None:
    observability.adopt_request_id("req-stamp")
    record = _access_record("/health")
    assert observability.RequestIdFilter().filter(record) is True
    assert record.request_id == "req-stamp"


def test_json_formatter_emits_one_object_per_line() -> None:
    observability.adopt_request_id("req-json")
    record = logging.LogRecord(
        name="assessment_platform.api",
        level=logging.WARNING,
        pathname=__file__,
        lineno=7,
        msg="graded %s in %ss",
        args=("sub-1", 3),
        exc_info=None,
    )
    record.submission_id = "sub-1"  # an `extra=` field a call site passed
    observability.RequestIdFilter().filter(record)

    line = observability.JsonFormatter().format(record)
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "assessment_platform.api"
    assert payload["request_id"] == "req-json"
    assert payload["msg"] == "graded sub-1 in 3s"
    assert payload["submission_id"] == "sub-1"
    assert payload["ts"]
    assert "exc" not in payload


def test_json_formatter_without_the_filter_still_has_a_request_id_key() -> None:
    record = _access_record("/health")
    payload = json.loads(observability.JsonFormatter().format(record))
    assert payload["request_id"] == observability.NO_REQUEST_ID


def test_json_formatter_includes_the_traceback_and_never_raises() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="x", level=logging.ERROR, pathname=__file__, lineno=1,
            msg="failed", args=(), exc_info=sys.exc_info(),
        )
    # An unserialisable extra must not blow up the one place a server may not fail.
    record.thing = object()
    payload = json.loads(observability.JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exc"]
    assert isinstance(payload["thing"], str)


def test_logging_config_routes_uvicorn_through_our_handlers() -> None:
    cfg = observability.logging_config("INFO", json_format=True)
    assert cfg["handlers"]["console"]["formatter"] == "json"
    # uvicorn sets propagate=False on its own loggers; these entries are what put
    # its lines in our format rather than half-converting the output.
    assert cfg["loggers"]["uvicorn"]["propagate"] is True
    access = cfg["loggers"]["uvicorn.access"]
    assert access["handlers"] == ["access"] and access["propagate"] is False
    assert cfg["handlers"]["access"]["filters"] == ["request_id", "query_string"]
    assert observability.logging_config("DEBUG", json_format=False)["root"]["level"] == "DEBUG"


# --------------------------------------------------------------------------- #
# 6. The access-line query-string redaction (a silent PII leak if it breaks)     #
# --------------------------------------------------------------------------- #

_PII_PATH = "/invite/tok/draft?candidate_email=a@b.c&token=SECRET-TOKEN"


def _formatted(record: logging.LogRecord) -> str:
    assert observability.QueryStringFilter().filter(record) is True
    observability.RequestIdFilter().filter(record)
    return logging.Formatter(observability._PLAIN_FORMAT).format(record)


def test_query_string_filter_redacts_candidate_pii_by_default() -> None:
    text = _formatted(_access_record(_PII_PATH))
    assert "candidate_email" not in text
    assert "a@b.c" not in text
    assert "SECRET-TOKEN" not in text
    # The route is still identifiable — redaction, not deletion.
    assert '"GET /invite/tok/draft?<redacted> HTTP/1.1" 200' in text


def test_query_string_filter_is_opt_out_under_log_pii(monkeypatch) -> None:
    monkeypatch.setattr(config, "LOG_PII", True)
    text = _formatted(_access_record(_PII_PATH))
    assert "a@b.c" in text
    assert "SECRET-TOKEN" in text


def test_query_string_filter_leaves_a_path_without_a_query_alone() -> None:
    text = _formatted(_access_record("/health"))
    assert '"GET /health HTTP/1.1" 200' in text
    assert "redacted" not in text


def test_query_string_filter_tolerates_a_record_of_another_shape() -> None:
    """A non-access record reaching the filter must pass through untouched."""
    record = logging.LogRecord(
        name="uvicorn.access", level=logging.INFO, pathname=__file__, lineno=1,
        msg="a plain %s", args=("line",), exc_info=None,
    )
    assert observability.QueryStringFilter().filter(record) is True
    assert record.getMessage() == "a plain line"


# --------------------------------------------------------------------------- #
# 7-9. GET /metrics                                                             #
# --------------------------------------------------------------------------- #

_DECLARED = {
    "platform_submissions": "gauge",
    "platform_submissions_stalled": "gauge",
    "platform_grade_giveups": "gauge",
    "platform_results": "gauge",
    "platform_grade_latency_seconds": "histogram",
}


def test_metrics_exposes_every_series_even_at_zero(anon_client: TestClient) -> None:
    resp = anon_client.get("/metrics")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert _families(resp.text) == _DECLARED

    samples = _samples(resp.text)
    for status in ("pending", "running", "done", "error"):
        assert samples[f'platform_submissions{{status="{status}"}}'] == 0
    for state in ("pending", "running"):
        assert samples[f'platform_submissions_stalled{{state="{state}"}}'] == 0
    for verdict in ("PASS", "FAIL", "ERROR"):
        assert samples[f'platform_results{{verdict="{verdict}"}}'] == 0
    assert samples["platform_grade_giveups"] == 0
    assert samples["platform_grade_latency_seconds_count"] == 0
    assert samples["platform_grade_latency_seconds_sum"] == 0
    assert samples['platform_grade_latency_seconds_bucket{le="+Inf"}'] == 0


def test_metrics_token_is_enforced_only_when_set(anon_client: TestClient, monkeypatch) -> None:
    assert anon_client.get("/metrics").status_code == 200  # unset => open (dev/tests)

    monkeypatch.setattr(config, "METRICS_TOKEN", "scrape-secret")
    assert anon_client.get("/metrics").status_code == 401
    assert anon_client.get("/metrics", headers={config.AUTH_HEADER: "wrong"}).status_code == 401
    ok = anon_client.get("/metrics", headers={config.AUTH_HEADER: "scrape-secret"})
    assert ok.status_code == 200
    assert "platform_submissions" in ok.text


def test_metrics_counts_submissions_by_status(client: TestClient) -> None:
    assert client.post("/questions", json=_sample_question()).status_code == 201
    _add(
        _submission("s-p1", "pending"),
        _submission("s-p2", "pending"),
        _submission("s-r1", "running"),
        _submission("s-d1", "done"),
        _submission("s-d2", "done"),
        _submission("s-d3", "done"),
        _submission("s-e1", "error"),
    )
    samples = _samples(client.get("/metrics").text)
    assert samples['platform_submissions{status="pending"}'] == 2
    assert samples['platform_submissions{status="running"}'] == 1
    assert samples['platform_submissions{status="done"}'] == 3
    assert samples['platform_submissions{status="error"}'] == 1


def test_metrics_counts_results_by_verdict(client: TestClient) -> None:
    client.post("/questions", json=_sample_question())
    _add(*[_submission(f"s-{i}", "done") for i in range(4)])
    _add(
        AssessmentResult(submission_id="s-0", verdict="PASS", score_pct=100.0, reason="ok"),
        AssessmentResult(submission_id="s-1", verdict="PASS", score_pct=95.0, reason="ok"),
        AssessmentResult(submission_id="s-2", verdict="FAIL", score_pct=10.0, reason="no"),
        AssessmentResult(submission_id="s-3", verdict="ERROR", score_pct=0.0, reason="boom"),
    )
    samples = _samples(client.get("/metrics").text)
    assert samples['platform_results{verdict="PASS"}'] == 2
    assert samples['platform_results{verdict="FAIL"}'] == 1
    assert samples['platform_results{verdict="ERROR"}'] == 1


def test_grade_latency_lands_in_the_right_bucket(client: TestClient) -> None:
    client.post("/questions", json=_sample_question())
    now = datetime.now(timezone.utc)
    _add(_submission("s-lat", "done", created_at=now - timedelta(seconds=3)))
    _add(
        AssessmentResult(
            submission_id="s-lat", verdict="PASS", score_pct=100.0, reason="ok", received_at=now
        )
    )
    samples = _samples(client.get("/metrics").text)
    assert samples["platform_grade_latency_seconds_count"] == 1
    assert 2.9 <= samples["platform_grade_latency_seconds_sum"] <= 3.5
    # Cumulative buckets: below 2.5s nothing, from 5s on everything.
    assert samples['platform_grade_latency_seconds_bucket{le="1"}'] == 0
    assert samples['platform_grade_latency_seconds_bucket{le="2.5"}'] == 0
    assert samples['platform_grade_latency_seconds_bucket{le="5"}'] == 1
    assert samples['platform_grade_latency_seconds_bucket{le="300"}'] == 1
    assert samples['platform_grade_latency_seconds_bucket{le="+Inf"}'] == 1


def test_grade_latency_ignores_grades_outside_the_window(client: TestClient, monkeypatch) -> None:
    client.post("/questions", json=_sample_question())
    monkeypatch.setattr(config, "METRICS_WINDOW_S", 3600)
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    _add(_submission("s-old", "done", created_at=old - timedelta(seconds=2)))
    _add(
        AssessmentResult(
            submission_id="s-old", verdict="PASS", score_pct=100.0, reason="ok", received_at=old
        )
    )
    samples = _samples(client.get("/metrics").text)
    assert samples["platform_grade_latency_seconds_count"] == 0
    # The result itself is still counted; only the latency window excludes it.
    assert samples['platform_results{verdict="PASS"}'] == 1


def test_stalled_counts_only_rows_past_their_grace(client: TestClient) -> None:
    client.post("/questions", json=_sample_question())
    now = datetime.now(timezone.utc)
    _add(
        _submission(
            "s-stuck-p", "pending", updated_at=now - timedelta(seconds=config.TRIGGER_RETRY_AFTER_S + 60)
        ),
        _submission("s-fresh-p", "pending", updated_at=now),
        _submission(
            "s-stuck-r", "running", updated_at=now - timedelta(seconds=config.REAP_RUNNING_AFTER_S + 60)
        ),
        _submission("s-fresh-r", "running", updated_at=now),
        # A row past every grace but no longer awaiting the reaper.
        _submission("s-done", "done", updated_at=now - timedelta(days=7)),
    )
    samples = _samples(client.get("/metrics").text)
    assert samples['platform_submissions_stalled{state="pending"}'] == 1
    assert samples['platform_submissions_stalled{state="running"}'] == 1
    assert samples['platform_submissions{status="pending"}'] == 2


def test_giveups_counts_error_rows_at_the_attempt_ceiling(client: TestClient) -> None:
    client.post("/questions", json=_sample_question())
    _add(
        _submission("s-gave-up", "error", attempts=config.MAX_TRIGGER_ATTEMPTS),
        _submission("s-gave-up-2", "error", attempts=config.MAX_TRIGGER_ATTEMPTS + 1),
        # Errored but still retriable — a human is not needed yet.
        _submission("s-retriable", "error", attempts=config.MAX_TRIGGER_ATTEMPTS - 1),
        # At the ceiling but still running: the reaper has not given up on it.
        _submission("s-running", "running", attempts=config.MAX_TRIGGER_ATTEMPTS),
    )
    samples = _samples(client.get("/metrics").text)
    assert samples["platform_grade_giveups"] == 2


# --------------------------------------------------------------------------- #
# 10. The outbound hop                                                          #
# --------------------------------------------------------------------------- #


def test_signed_post_forwards_the_request_id_without_breaking_the_signature(monkeypatch) -> None:
    monkeypatch.setattr(config, "ASSESS_SIGNING_SECRET", "shared-secret")
    monkeypatch.setattr(config, "ASSESS_API_TOKEN", "agent-token")
    seen: dict[str, Any] = {}

    def on_post(url: str, timeout: float, **kw: Any) -> httpx.Response:
        seen.update(headers=kw["headers"], content=kw["content"])
        return httpx.Response(202, json={"ok": True}, request=httpx.Request("POST", url))

    patch_async_post(monkeypatch, on_post)
    observability.adopt_request_id("hop-id-1")
    asyncio.run(agent_client._signed_post("http://agent/assessments", {"job_id": "j"}, timeout=1.0))

    assert seen["headers"][observability.REQUEST_ID_HEADER] == "hop-id-1"
    assert seen["headers"][config.AUTH_HEADER] == "agent-token"
    # The HMAC covers the body only, so a header added beside it still verifies.
    assert signing.verify(
        "shared-secret", seen["content"], seen["headers"][signing.SIGNATURE_HEADER]
    )
    assert json.loads(seen["content"]) == {"job_id": "j"}


def test_signed_post_omits_the_header_outside_a_request(monkeypatch) -> None:
    """The reaper and the retention sweep have no request. "-" matches the
    agent's id pattern, so sending it would have the agent adopt the sentinel as
    a genuine id and file every reaper-driven grade under one meaningless key —
    send no header instead and let the agent mint its own."""
    seen: dict[str, Any] = {}

    def on_post(url: str, timeout: float, **kw: Any) -> httpx.Response:
        seen.update(kw["headers"])
        return httpx.Response(202, json={}, request=httpx.Request("POST", url))

    patch_async_post(monkeypatch, on_post)

    def _call() -> None:
        asyncio.run(agent_client._signed_post("http://agent/x", {}, timeout=1.0))

    contextvars.Context().run(_call)
    assert observability.REQUEST_ID_HEADER not in seen


# --------------------------------------------------------------------------- #
# 11. Sentry                                                                    #
# --------------------------------------------------------------------------- #


def test_init_sentry_is_off_under_test_even_with_a_dsn(monkeypatch) -> None:
    monkeypatch.setattr(config, "SENTRY_DSN", "https://public@example.invalid/1")
    assert config.TESTING is True
    assert observability.init_sentry() is False


def test_init_sentry_is_off_without_a_dsn(monkeypatch) -> None:
    monkeypatch.setattr(config, "TESTING", False)
    monkeypatch.setattr(config, "SENTRY_DSN", "")
    assert observability.init_sentry() is False


def test_scrub_event_strips_everything_a_candidate_owns() -> None:
    event: Any = {
        "request": {
            "url": "http://host/invite/TOK/submit?candidate_email=a@b.c",
            "query_string": "candidate_email=a@b.c",
            "data": {"code": "print('my solution')"},
            "cookies": {"refresh_token": "SECRET"},
            "headers": {
                "Host": "host",
                "User-Agent": "curl/8",
                "Content-Type": "application/json",
                "Authorization": "Bearer JWT",
                "Cookie": "refresh_token=SECRET",
                "X-Assess-Token": "shared",
            },
        },
        "user": {"email": "a@b.c", "ip_address": "1.2.3.4"},
        "exception": {"values": [{"type": "ValueError"}]},
    }
    scrubbed = observability._scrub_event(event, {})
    request = scrubbed["request"]
    assert "data" not in request
    assert "cookies" not in request
    assert "query_string" not in request
    assert request["url"] == "http://host/invite/TOK/submit"
    assert set(request["headers"]) == {"Host", "User-Agent", "Content-Type"}
    assert "user" not in scrubbed
    # The part worth reporting survives.
    assert scrubbed["exception"]["values"][0]["type"] == "ValueError"
    serialised = json.dumps(scrubbed)
    assert "a@b.c" not in serialised
    assert "my solution" not in serialised
    assert "SECRET" not in serialised
    assert "Bearer JWT" not in serialised


def test_scrub_event_tolerates_an_event_with_no_request() -> None:
    assert observability._scrub_event({"message": "hi"}, {}) == {"message": "hi"}  # type: ignore[arg-type]
