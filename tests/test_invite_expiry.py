"""R2-004 — an invite's expiry is a *start* deadline, not a kill switch on a
sitting already in progress.

A 24-hour link opened 30 minutes before it expires, for a 60-minute assessment,
used to lose the work at the buzzer: every candidate route resolved the token
through `_load_invite_or_error`, which 410s on `expires_at` regardless of an open
attempt. The candidate was never shown the expiry either, so nothing warned them.

What the expiry means now: it bounds when a sitting may BEGIN. Once this
candidate has an attempt, their own deadline (`started_at` + the sitting's
duration) is the only clock that ends it. Revocation is unchanged — that is a
deliberate act by the interviewer and it stops a sitting mid-flight.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from assessment_platform import agent_client
from assessment_platform import db as db_module
from assessment_platform.models import Invite

CANDIDATE = "c@x.io"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _question(qid: str, duration_minutes: int | None = 60) -> dict[str, Any]:
    return {
        "id": qid,
        "title": "Timed problem",
        "prompt": "Read N then N integers; print their sum.",
        "constraints": "1 <= N <= 1e5",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "duration_minutes": duration_minutes,
        # 4 correctness + 1 performance to satisfy the authoring-time floor (A1).
        "test_cases": [
            {"name": "t1", "stdin": "2\n3 4\n", "expected": "7", "category": "correctness"},
            {"name": "t2", "stdin": "1\n5\n", "expected": "5", "category": "correctness"},
            {"name": "t3", "stdin": "3\n1 2 3\n", "expected": "6", "category": "correctness"},
            {"name": "t4", "stdin": "1\n0\n", "expected": "0", "category": "correctness"},
            {"name": "big", "stdin": "9\n1\n", "expected": "1", "category": "performance"},
        ],
    }


def _invited(client: TestClient, email: str = CANDIDATE) -> tuple[str, str]:
    """An interviewer with one timed question and a live invite. Returns the
    interviewer's bearer token and the candidate's invite token."""
    tok = register_interviewer(client, f"expiry-{email}")
    assert client.post("/questions", json=_question("q_exp"), headers=_auth(tok)).status_code == 201
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    resp = client.post(
        "/questions/q_exp/invites",
        json={"recipients": [email], "expires_at": expires.isoformat()},
        headers=_auth(tok),
    )
    assert resp.status_code == 201
    return tok, resp.json()["token"]


def _expire(invite_token: str, *, seconds_ago: int = 60) -> None:
    """Move the invite's expiry into the past, modelling the clock catching up
    with a link that was live when the candidate opened it."""
    with Session(db_module.engine) as s:
        invite = s.exec(select(Invite).where(Invite.token == invite_token)).one()
        invite.expires_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
        s.add(invite)
        s.commit()


def _start(client: TestClient, invite_token: str, email: str = CANDIDATE):
    return client.post(
        f"/invite/{invite_token}/start",
        json={"candidate_email": email, "candidate_name": "C", "consent": True},
    )


def test_expired_link_cannot_start_a_sitting(anon_client: TestClient) -> None:
    """The guard the fix must not open: nobody starts on a dead link."""
    _tok, link = _invited(anon_client)
    _expire(link)

    resp = _start(anon_client, link)
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"]


def test_probe_shows_the_expiry_instead_of_dying_on_it(anon_client: TestClient) -> None:
    """The candidate is told when the link expires, before and after the moment.

    The probe answering 410 is what made the expiry invisible AND unrecoverable:
    a candidate mid-sitting reloads the page, and the first call the page makes
    is this one. It now reports the state and lets /start decide who may go on.
    """
    _tok, link = _invited(anon_client)

    live = anon_client.get(f"/invite/{link}")
    assert live.status_code == 200
    assert live.json()["status"] == "active"
    assert live.json()["expires_at"] is not None

    _expire(link)
    dead = anon_client.get(f"/invite/{link}")
    assert dead.status_code == 200
    assert dead.json()["status"] == "expired"
    assert dead.json()["expires_at"] is not None


def test_expiry_does_not_strand_a_sitting_already_started(
    anon_client: TestClient, monkeypatch
) -> None:
    """Every route the candidate needs between /start and the buzzer keeps
    working once their attempt exists — including /start itself, which is how a
    reload gets back in."""
    tok, link = _invited(anon_client)
    started = _start(anon_client, link)
    assert started.status_code == 200
    deadline = started.json()["deadline"]

    _expire(link)

    # Re-entry after a reload: same sitting, same deadline, not a new clock.
    again = _start(anon_client, link)
    assert again.status_code == 200
    assert again.json()["deadline"] == deadline

    # Autosave and restore.
    assert (
        anon_client.put(
            f"/invite/{link}/draft",
            json={"candidate_email": CANDIDATE, "question_id": "q_exp", "language": "python", "code": "x=1"},
        ).status_code
        == 204
    )
    drafts = anon_client.get(f"/invite/{link}/draft", params={"candidate_email": CANDIDATE})
    assert drafts.status_code == 200
    assert [d["code"] for d in drafts.json()["drafts"]] == ["x=1"]

    # Integrity signals.
    assert (
        anon_client.post(
            f"/invite/{link}/events",
            json={
                "candidate_email": CANDIDATE,
                "events": [{"kind": "focus_loss", "offset_ms": 3000}],
            },
        ).status_code
        == 204
    )

    # The editor's two agent calls.
    monkeypatch.setattr(
        agent_client, "run_code", async_return({"stdout": "7", "duration_s": 0.1})
    )
    assert (
        anon_client.post(
            f"/invite/{link}/run",
            json={"candidate_email": CANDIDATE, "language": "python", "code": "print(7)", "stdin": ""},
        ).status_code
        == 200
    )
    monkeypatch.setattr(
        agent_client, "run_tests", async_return({"cases": [], "passed": 0, "total": 0})
    )
    assert (
        anon_client.post(
            f"/invite/{link}/run-tests",
            json={"candidate_email": CANDIDATE, "language": "python", "code": "print(7)"},
        ).status_code
        == 200
    )

    # The buzzer itself — the moment R2-004 cost the candidate their work.
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-exp"))
    submitted = anon_client.post(
        f"/invite/{link}/submit",
        json={
            "candidate_name": "C",
            "candidate_email": CANDIDATE,
            "consent": True,
            "language": "python",
            "code": "print(7)",
        },
    )
    assert submitted.status_code == 201
    # On time: the sitting's own 60-minute deadline has not passed, and the
    # invite's expiry is not a deadline.
    sid = submitted.json()["submission_id"]
    assert anon_client.get(f"/submissions/{sid}", headers=_auth(tok)).json()["late"] is False


def test_expiry_still_stops_a_candidate_who_never_started(anon_client: TestClient) -> None:
    """Holding an attempt is per candidate, not per link: one recipient starting
    before the expiry does not reopen the link for the others."""
    tok = register_interviewer(anon_client, "expiry-two@x.io")
    anon_client.post("/questions", json=_question("q_two"), headers=_auth(tok))
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    link = anon_client.post(
        "/questions/q_two/invites",
        json={"recipients": ["early@x.io", "late@x.io"], "expires_at": expires.isoformat()},
        headers=_auth(tok),
    ).json()["token"]

    assert _start(anon_client, link, "early@x.io").status_code == 200
    _expire(link)

    assert _start(anon_client, link, "early@x.io").status_code == 200
    resp = _start(anon_client, link, "late@x.io")
    assert resp.status_code == 410
    assert "expired" in resp.json()["detail"]


def test_revoking_still_ends_a_sitting_in_progress(anon_client: TestClient, monkeypatch) -> None:
    """Expiry is the clock running out; revocation is the interviewer shutting the
    sitting down. Only the first one yields to an open attempt."""
    tok, link = _invited(anon_client, "revoked@x.io")
    assert _start(anon_client, link, "revoked@x.io").status_code == 200

    assert (
        anon_client.post(f"/questions/q_exp/invites/{link}/revoke", headers=_auth(tok)).status_code
        == 200
    )

    assert anon_client.get(f"/invite/{link}").status_code == 410
    assert _start(anon_client, link, "revoked@x.io").status_code == 410
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-rev"))
    assert (
        anon_client.post(
            f"/invite/{link}/submit",
            json={
                "candidate_name": "C",
                "candidate_email": "revoked@x.io",
                "consent": True,
                "language": "python",
                "code": "print(7)",
            },
        ).status_code
        == 410
    )


def test_feedback_survives_the_expiry_too(anon_client: TestClient, monkeypatch) -> None:
    """The last thing a candidate does. Only an assessment-backed sitting can take
    feedback (P2b), so it needs its own invite rather than the quick screen above."""
    tok = register_interviewer(anon_client, "expiry-feedback@x.io")
    anon_client.post("/questions", json=_question("q_fb"), headers=_auth(tok))
    aid = anon_client.post(
        "/assessments",
        json={"title": "Screen", "question_ids": ["q_fb"], "duration_minutes": 60},
        headers=_auth(tok),
    ).json()["id"]
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    link = anon_client.post(
        f"/assessments/{aid}/invites",
        json={"recipients": [CANDIDATE], "expires_at": expires.isoformat()},
        headers=_auth(tok),
    ).json()["token"]

    assert _start(anon_client, link).status_code == 200
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-fb"))
    assert (
        anon_client.post(
            f"/invite/{link}/submit",
            json={
                "candidate_name": "C",
                "candidate_email": CANDIDATE,
                "consent": True,
                "language": "python",
                "code": "print(7)",
                "question_id": "q_fb",
            },
        ).status_code
        == 201
    )

    _expire(link)

    assert (
        anon_client.post(
            f"/invite/{link}/feedback",
            json={"candidate_email": CANDIDATE, "rating": 4, "difficulty_fair": "fair", "comment": "fine"},
        ).status_code
        == 204
    )


def test_an_untimed_sitting_still_ends_when_the_link_does(anon_client: TestClient, monkeypatch) -> None:
    """The one sitting with no clock of its own is bounded by the link's.

    Expiry yields to a sitting under way because that sitting has its own
    deadline. An untimed one has none, so yielding unconditionally would leave it
    open for ever — a candidate could start on day 1 of a 7-day link and submit
    on day 30, burning agent compute the whole time on a link the interviewer
    reads as dead.
    """
    tok = register_interviewer(anon_client, "expiry-untimed@x.io")
    anon_client.post("/questions", json=_question("q_untimed", None), headers=_auth(tok))
    expires = datetime.now(timezone.utc) + timedelta(hours=24)
    link = anon_client.post(
        "/questions/q_untimed/invites",
        json={"recipients": [CANDIDATE], "expires_at": expires.isoformat()},
        headers=_auth(tok),
    ).json()["token"]

    started = _start(anon_client, link)
    assert started.status_code == 200 and started.json()["deadline"] is None

    _expire(link)

    assert _start(anon_client, link).status_code == 410
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-u"))
    assert (
        anon_client.post(
            f"/invite/{link}/submit",
            json={
                "candidate_name": "C",
                "candidate_email": CANDIDATE,
                "consent": True,
                "language": "python",
                "code": "print(7)",
            },
        ).status_code
        == 410
    )


def test_any_invite_can_be_revoked_by_its_organisation(anon_client: TestClient) -> None:
    """Revocation is the only way to end a sitting under way, so it has to exist
    for every kind of invite — not just the quick screen.

    The nested `/questions/{id}/invites/{token}/revoke` route covers one of the
    three invite kinds. STATUS's P03 accepted that gap because "expiry is now the
    only control an interviewer has over one"; once expiry stops ending a live
    sitting, that reasoning is spent and an assessment invite needs a way in.
    """
    tok = register_interviewer(anon_client, "expiry-revoke@x.io")
    anon_client.post("/questions", json=_question("q_rev"), headers=_auth(tok))
    aid = anon_client.post(
        "/assessments",
        json={"title": "Screen", "question_ids": ["q_rev"], "duration_minutes": 60},
        headers=_auth(tok),
    ).json()["id"]
    link = anon_client.post(
        f"/assessments/{aid}/invites", json={"recipients": [CANDIDATE]}, headers=_auth(tok)
    ).json()["token"]

    assert _start(anon_client, link).status_code == 200

    revoked = anon_client.post(f"/invites/{link}/revoke", headers=_auth(tok))
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert _start(anon_client, link).status_code == 410


def test_an_expired_invite_can_still_be_revoked(anon_client: TestClient) -> None:
    """The window where revocation matters most: the link is closed to new
    sittings, one candidate is still working, and the interviewer wants them
    stopped."""
    tok, link = _invited(anon_client, "expired-revoke@x.io")
    assert _start(anon_client, link, "expired-revoke@x.io").status_code == 200
    _expire(link)

    assert anon_client.post(f"/invites/{link}/revoke", headers=_auth(tok)).status_code == 200
    assert _start(anon_client, link, "expired-revoke@x.io").status_code == 410


def test_revoking_is_scoped_to_the_organisation_that_owns_the_invite(
    anon_client: TestClient,
) -> None:
    _tok, link = _invited(anon_client, "scoped@x.io")
    outsider = register_interviewer(anon_client, "outsider@x.io")

    assert anon_client.post(f"/invites/{link}/revoke", headers=_auth(outsider)).status_code == 404
    assert anon_client.post("/invites/not-a-token/revoke", headers=_auth(outsider)).status_code == 404
