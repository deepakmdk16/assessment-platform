"""Results-ready notification (X06) — email + per-org webhook.

Fully offline: SMTP is hard-nulled under test (conftest), `email_client` is
patched to capture, and the webhook's outbound POST is patched at
`notify.httpx.post`. Nothing here touches the network or a real mail host.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient
from test_api import _age_submission

from assessment_platform import (
    agent_client,
    api,
    config,
    email_client,
    email_templates,
    notify,
    signing,
)


def _question(qid: str) -> dict[str, Any]:
    return {
        "id": qid,
        "title": f"Q {qid}",
        "prompt": "p",
        "constraints": "c",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "test_cases": [
            {"name": "t1", "stdin": "1\n", "expected": "1", "category": "correctness"},
            {"name": "t2", "stdin": "2\n", "expected": "2", "category": "correctness"},
            {"name": "t3", "stdin": "3\n", "expected": "3", "category": "correctness"},
            {"name": "t4", "stdin": "4\n", "expected": "4", "category": "correctness"},
            {"name": "big", "stdin": "9\n", "expected": "9", "category": "performance"},
        ],
    }


def _callback(job_id: str, verdict: str = "PASS", score: float = 100.0) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "verdict": verdict,
        "reason": "all tests passed",
        "score_pct": score,
        "test_cases": [],
    }


@pytest.fixture
def mails(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    """Capture every results email instead of sending one."""
    sent: list[dict[str, str]] = []

    def fake(to: str, email: email_templates.Email, url: str) -> email_client.Delivery:
        sent.append({"to": to, "subject": email.subject, "body": email.text, "html": email.html, "url": url})
        return email_client.Delivery(to, sent=True)

    monkeypatch.setattr(email_client, "send_results_email", fake)
    return sent


@pytest.fixture
def echo_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """The agent echoes the platform-minted job id (the submission's own id), so
    each question in a sitting gets a distinct, addressable callback."""

    async def _trigger(_question: Any, submission: Any, _url: str, base_url: Any = None) -> str:
        return str(submission.id)

    monkeypatch.setattr(agent_client, "trigger_assessment", _trigger)


def _sit(client: TestClient, token: str, email: str, qid: str | None = None) -> str:
    """Start (if needed) and submit one question; return the submission id."""
    body: dict[str, Any] = {
        "candidate_name": "Jane Doe",
        "candidate_email": email,
        "consent": True,
        "language": "python",
        "code": "print(1)",
    }
    if qid is not None:
        body["question_id"] = qid
    resp = client.post(f"/invite/{token}/submit", json=body)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["submission_id"])


def _quick_screen(client: TestClient, email: str = "cand@x.io") -> str:
    client.post("/questions", json=_question("q1"))
    token = client.post(
        "/questions/q1/invites", json={"recipients": [email]}
    ).json()["token"]
    client.post(f"/invite/{token}/start", json={"candidate_email": email, "consent": True})
    return str(token)


def _assessment(client: TestClient, *qids: str, email: str = "cand@x.io") -> str:
    for qid in qids:
        client.post("/questions", json=_question(qid))
    client.post("/assessments", json={"id": "a1", "title": "Backend Screen", "question_ids": list(qids)})
    token = client.post("/assessments/a1/invites", json={"recipients": [email]}).json()["token"]
    client.post(f"/invite/{token}/start", json={"candidate_email": email, "consent": True})
    return str(token)


# --------------------------------------------------------------------------- #
# When the interviewer is told                                                  #
# --------------------------------------------------------------------------- #


def test_single_question_sitting_emails_the_interviewer(client, echo_agent, mails) -> None:
    token = _quick_screen(client)
    sub_id = _sit(client, token, "cand@x.io")

    assert client.post("/assessments/callback", json=_callback(sub_id)).status_code == 200

    assert len(mails) == 1
    mail = mails[0]
    assert mail["to"] == "owner@test.io"  # the interviewer who sent the invite
    assert "Jane Doe" in mail["subject"]
    assert "PASS" in mail["body"]
    assert f"/submissions/{sub_id}" in mail["body"]


def test_redelivered_callback_does_not_email_twice(client, echo_agent, mails) -> None:
    """The agent may re-deliver a callback at any time; the notified stamp is a
    compare-and-swap, so only the first one ever sends."""
    token = _quick_screen(client)
    sub_id = _sit(client, token, "cand@x.io")

    client.post("/assessments/callback", json=_callback(sub_id))
    client.post("/assessments/callback", json=_callback(sub_id))

    assert len(mails) == 1


def test_multi_question_sitting_waits_for_the_last_question(client, echo_agent, mails) -> None:
    """Three callbacks, one email — and it lists every question, not just the
    one whose callback happened to land last."""
    token = _assessment(client, "q1", "q2")
    first = _sit(client, token, "cand@x.io", "q1")
    second = _sit(client, token, "cand@x.io", "q2")

    client.post("/assessments/callback", json=_callback(first, "PASS", 100.0))
    assert mails == []  # half a sitting is not a result

    client.post("/assessments/callback", json=_callback(second, "FAIL", 40.0))
    assert len(mails) == 1
    body = mails[0]["body"]
    assert "Backend Screen" in mails[0]["subject"]
    assert "PASS" in body and "FAIL" in body
    assert "Q q1" in body and "Q q2" in body


def test_a_sitting_that_errored_still_notifies(client, echo_agent, mails) -> None:
    """An ungradable last question ends the sitting too — and is the case the
    interviewer most needs to hear about."""
    token = _quick_screen(client)
    sub_id = _sit(client, token, "cand@x.io")

    payload = _callback(sub_id, "ERROR", 0.0)
    payload["infra_error"] = "python toolchain missing"
    client.post("/assessments/callback", json=payload)

    assert len(mails) == 1
    assert "ERROR" in mails[0]["body"]


def test_interviewer_own_submission_notifies_nobody(client, monkeypatch, mails) -> None:
    """POST /submissions has no invite: the interviewer is holding the response
    already, so there is nothing to announce."""
    client.post("/questions", json=_question("q1"))
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-direct"))
    client.post(
        "/submissions",
        json={"question_id": "q1", "candidate": "Jane", "language": "python", "code": "x"},
    )

    assert client.post("/assessments/callback", json=_callback("job-direct")).status_code == 200
    assert mails == []


def test_a_sitting_the_reaper_gives_up_on_still_notifies(client, echo_agent, mails, monkeypatch) -> None:
    """The agent never calls back and the reaper writes the sitting off. That
    ends the sitting exactly as a callback would, so the interviewer hears about
    it — otherwise the one outcome nobody is told about is the broken one."""
    monkeypatch.setattr(config, "MAX_TRIGGER_ATTEMPTS", 1)
    token = _quick_screen(client)
    sub_id = _sit(client, token, "cand@x.io")

    _age_submission(sub_id, config.REAP_RUNNING_AFTER_S + 60)
    asyncio.run(api._reap_tick())

    assert client.get(f"/submissions/{sub_id}").json()["status"] == "error"
    assert len(mails) == 1
    assert "ERROR" in mails[0]["body"]


# --------------------------------------------------------------------------- #
# The per-organisation webhook                                                  #
# --------------------------------------------------------------------------- #


@pytest.fixture
def allow_local_webhooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SSRF gate resolves DNS and refuses private addresses; a test endpoint
    is by definition private, so open the documented development escape hatch."""
    monkeypatch.setattr(config, "ALLOW_PRIVATE_WEBHOOKS", True)


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the gate's lookup answer without a network: any name resolves to one
    publicly-routable address. Keeps the suite offline (CONVENTIONS §Tests) while
    still exercising the real `webhook_url_error` path."""

    def fake_getaddrinfo(host: str, port: int, **_kw: Any) -> list[Any]:
        return [(0, 0, 0, "", ("93.184.216.34", port))]

    monkeypatch.setattr(notify.socket, "getaddrinfo", fake_getaddrinfo)


@pytest.fixture
def posts(monkeypatch: pytest.MonkeyPatch, allow_local_webhooks: None) -> list[dict[str, Any]]:
    """Capture the webhook's outbound POST; never leaves the process."""
    calls: list[dict[str, Any]] = []

    class _Resp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

    def fake_post(url: str, **kw: Any) -> _Resp:
        calls.append({"url": url, **kw})
        return _Resp()

    monkeypatch.setattr(notify.httpx, "post", fake_post)
    return calls


def _set_webhook(client: TestClient, url: str) -> str:
    resp = client.patch("/orgs/current", json={"results_webhook_url": url})
    assert resp.status_code == 200, resp.text
    secret = resp.json()["results_webhook_secret"]
    assert secret
    return str(secret)


def test_webhook_receives_a_signed_results_event(client, echo_agent, mails, posts) -> None:
    secret = _set_webhook(client, "http://127.0.0.1:9999/hook")
    token = _quick_screen(client)
    sub_id = _sit(client, token, "cand@x.io")

    client.post("/assessments/callback", json=_callback(sub_id))

    assert len(posts) == 1
    call = posts[0]
    assert call["url"] == "http://127.0.0.1:9999/hook"
    # A redirect is how an allowed host hands the request to a forbidden one.
    assert call["follow_redirects"] is False

    body = call["content"]
    assert signing.verify(secret, body, call["headers"][signing.SIGNATURE_HEADER])
    document = json.loads(body)
    assert document["event"] == "results.ready"
    assert document["candidate"] == {"name": "Jane Doe", "email": "cand@x.io"}
    assert document["results"][0]["verdict"] == "PASS"
    assert document["results"][0]["submission_id"] == sub_id


def test_no_webhook_configured_posts_nothing(client, echo_agent, mails, posts) -> None:
    token = _quick_screen(client)
    client.post("/assessments/callback", json=_callback(_sit(client, token, "cand@x.io")))

    assert len(mails) == 1 and posts == []


def test_a_failing_webhook_costs_neither_the_grade_nor_the_email(
    client, echo_agent, mails, posts, monkeypatch
) -> None:
    _set_webhook(client, "http://127.0.0.1:9999/hook")

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("customer endpoint is down")

    monkeypatch.setattr(notify.httpx, "post", boom)

    token = _quick_screen(client)
    sub_id = _sit(client, token, "cand@x.io")
    resp = client.post("/assessments/callback", json=_callback(sub_id))

    assert resp.status_code == 200
    assert client.get(f"/submissions/{sub_id}").json()["status"] == "done"
    assert len(mails) == 1


# --------------------------------------------------------------------------- #
# Configuring the webhook (the SSRF gate, and the secret)                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/hook",  # plain http
        "https://127.0.0.1/hook",  # loopback
        "https://169.254.169.254/latest/meta-data",  # cloud metadata
        "https://10.0.0.5/internal",  # private range
        "ftp://example.com/hook",  # not http at all
        "https://example.com:99999/hook",  # port that does not parse
        "https:///hook",  # no host
    ],
)
def test_webhook_url_must_be_public_https(client, url) -> None:
    resp = client.patch("/orgs/current", json={"results_webhook_url": url})
    assert resp.status_code == 422, resp.text


def test_webhook_secret_is_revealed_once_and_never_read_back(client, allow_local_webhooks) -> None:
    _set_webhook(client, "http://127.0.0.1:9999/hook")

    shown = client.get("/orgs/current").json()
    assert shown["results_webhook_url"] == "http://127.0.0.1:9999/hook"
    assert shown["results_webhook_secret"] is None


def test_resaving_the_same_url_keeps_the_working_secret(client, allow_local_webhooks) -> None:
    """`GET /orgs/current` returns the URL, so a read-modify-write settings form
    re-sends it on every save. That must not rotate the key under a receiver
    that is working."""
    _set_webhook(client, "http://127.0.0.1:9999/hook")

    again = client.patch("/orgs/current", json={"results_webhook_url": "http://127.0.0.1:9999/hook"})
    assert again.status_code == 200
    assert again.json()["results_webhook_secret"] is None  # nothing minted, nothing revealed


def test_rotating_is_clear_then_set(client, allow_local_webhooks) -> None:
    """The deliberate path for a lost secret — and the only thing that changes it."""
    first = _set_webhook(client, "http://127.0.0.1:9999/hook")
    client.patch("/orgs/current", json={"results_webhook_url": None})

    assert _set_webhook(client, "http://127.0.0.1:9999/hook") != first


def test_clearing_the_webhook_drops_the_secret_with_it(client, allow_local_webhooks) -> None:
    _set_webhook(client, "http://127.0.0.1:9999/hook")

    resp = client.patch("/orgs/current", json={"results_webhook_url": None})
    assert resp.status_code == 200
    assert resp.json()["results_webhook_url"] is None

    org = client.get("/orgs/current").json()
    assert org["results_webhook_url"] is None and org["results_webhook_secret"] is None


def test_setting_the_webhook_needs_admin(client) -> None:
    """Same guard as every other organisation setting."""
    from test_organizations import auth, invite_colleague

    join = invite_colleague(client, client.headers["Authorization"].split()[1], "member@test.io")
    member = register_interviewer(client, "member@test.io", name="Member")
    assert client.post(f"/org-invites/{join}/accept", headers=auth(member)).status_code == 200

    resp = client.patch(
        "/orgs/current",
        json={"results_webhook_url": "https://example.com/hook"},
        headers=auth(member),
    )
    assert resp.status_code == 403


def test_retention_can_still_be_set_without_touching_the_webhook(client, public_dns) -> None:
    """`model_fields_set` keeps the two independent — the Privacy panel must not
    silently clear a webhook it never sent."""
    client.patch("/orgs/current", json={"results_webhook_url": "https://example.com/hook"})
    resp = client.patch("/orgs/current", json={"retention_days": 30})

    assert resp.status_code == 200
    assert resp.json()["retention_days"] == 30
    assert resp.json()["results_webhook_url"] == "https://example.com/hook"
