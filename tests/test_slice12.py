"""Slice 12 tests: draft-call retry policy.

Two separate retries exist, deliberately:
  - the AGENT re-drafts when its own output is unusable (stochastic model);
  - the PLATFORM (here) retries only failures a retry could fix — it can't
    reach the agent, or the agent is overloaded.

The interesting behaviour is what we DON'T retry: a missing API key (503), an
unusable draft (422) and a bad request (400) give the same answer every time, so
retrying them only makes the interviewer wait longer for the same error.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from assessment_platform import agent_client


def _response(status: int) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        json={"detail": "nope"},
        request=httpx.Request("POST", "http://agent/questions/draft"),
    )


def _ok_response() -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json={"engine": "test", "question": {"id": "q"}, "warnings": []},
        request=httpx.Request("POST", "http://agent/questions/draft"),
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Don't actually back off — these tests assert call counts, not wall clock."""
    monkeypatch.setattr(agent_client.time, "sleep", lambda _s: None)


def _post_returning(monkeypatch: pytest.MonkeyPatch, outcomes: list[Any]) -> list[int]:
    """Stub httpx.post to yield `outcomes` in order (exceptions are raised)."""
    calls: list[int] = []

    def _fake(*a: Any, **k: Any) -> httpx.Response:
        item = outcomes[len(calls)]
        calls.append(1)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(agent_client.httpx, "post", _fake)
    return calls


def _draft() -> dict:
    return agent_client.draft_question(brief="b", language="python")


# --------------------------------------------------------------------------- #
# Retries that help                                                             #
# --------------------------------------------------------------------------- #


def test_retries_when_the_agent_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent restarting shouldn't surface as a dead end."""
    calls = _post_returning(monkeypatch, [httpx.ConnectError("refused"), _ok_response()])
    assert _draft()["engine"] == "test"
    assert len(calls) == 2


def test_retries_when_the_agent_is_overloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _post_returning(monkeypatch, [_response(429), _ok_response()])
    assert _draft()["engine"] == "test"
    assert len(calls) == 2


def test_gives_up_after_the_attempt_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _post_returning(monkeypatch, [httpx.ConnectError("refused")] * 3)
    with pytest.raises(httpx.ConnectError):
        _draft()
    assert len(calls) == 3  # _DRAFT_TRANSPORT_ATTEMPTS


def test_a_first_try_success_makes_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _post_returning(monkeypatch, [_ok_response()])
    assert _draft()["engine"] == "test"
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# Failures that a retry cannot fix — fail fast instead of stalling the UI       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "why"),
    [
        (503, "no ANTHROPIC_API_KEY on the worker — config, not luck"),
        (422, "unusable draft — the agent already re-drafted internally"),
        (400, "bad request, e.g. unsupported language"),
    ],
)
def test_does_not_retry_a_deterministic_failure(
    monkeypatch: pytest.MonkeyPatch, status: int, why: str
) -> None:
    calls = _post_returning(monkeypatch, [_response(status)] * 3)
    with pytest.raises(httpx.HTTPStatusError) as exc:
        _draft()
    assert exc.value.response.status_code == status
    assert len(calls) == 1, f"should not retry {status}: {why}"


def test_does_not_retry_a_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """The draft budget is already minutes; retrying just waits it out twice."""
    calls = _post_returning(monkeypatch, [httpx.ReadTimeout("slow")] * 3)
    with pytest.raises(httpx.ReadTimeout):
        _draft()
    assert len(calls) == 1


# --------------------------------------------------------------------------- #
# The route still maps the agent's reason through (regression guard)            #
# --------------------------------------------------------------------------- #


def test_route_surfaces_agent_503_without_retrying(
    anon_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conftest import register_interviewer
    from test_slice1 import _auth

    calls = _post_returning(monkeypatch, [_response(503)] * 3)
    tok = register_interviewer(anon_client, "s12@x.io")
    resp = anon_client.post(
        "/questions/draft", json={"brief": "b", "language": "python"}, headers=_auth(tok)
    )
    assert resp.status_code == 503
    assert len(calls) == 1
