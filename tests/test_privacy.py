"""Candidate erasure, retention and recorded consent (X03/X04).

The audit's finding was that a candidate's data could be created but never
removed: deletion was refused once any activity existed, nothing expired on a
schedule, and a monitored sitting recorded no agreement to being monitored.

Three things are pinned here. That an erasure destroys **everything that
identifies a person, including their submitted work and the grading detail
derived from it**, while leaving the anonymous statistical record intact. That
retention erases only what an organisation has actually asked to expire. And
that a sitting cannot begin without a consent record, by any route.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from assessment_platform import agent_client, config, privacy
from assessment_platform import db as db_module
from assessment_platform.models import (
    AssessmentResult,
    CandidateAttempt,
    CandidateDraft,
    IntegrityEvent,
    Invite,
    Organization,
    Submission,
)

CANDIDATE = "cand@x.io"


def _question(qid: str = "q1") -> dict[str, Any]:
    return {
        "id": qid,
        "title": f"Q {qid}",
        "prompt": "p",
        "constraints": "c",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "test_cases": [
            {"name": f"t{i}", "stdin": "1\n", "expected": "1", "category": "correctness"}
            for i in range(4)
        ]
        + [{"name": "big", "stdin": "9\n", "expected": "9", "category": "performance"}],
    }


def _callback(job_id: str) -> dict[str, Any]:
    """A grading payload shaped like the agent's. `candidate` and the per-case
    `actual` are the reason `full_result` counts as personal data: the name is in
    it, and the rest is output produced by running the candidate's own code."""
    return {
        "job_id": job_id,
        "verdict": "PASS",
        "reason": "all tests passed",
        "score_pct": 100.0,
        "candidate": "Jane Doe",
        "test_cases": [{"name": "t1", "status": "PASS", "actual": "7", "input": "2\n3 4\n"}],
        "judge_cost_usd": 0.0094,
    }


def _invite(client: TestClient, qid: str = "q1", email: str = CANDIDATE) -> str:
    assert client.post("/questions", json=_question(qid)).status_code == 201
    resp = client.post(f"/questions/{qid}/invites", json={"recipients": [email]})
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


def _full_sitting(
    client: TestClient, monkeypatch, *, qid: str = "q1", email: str = CANDIDATE
) -> tuple[str, str]:
    """A candidate who started, drafted, tripped an integrity signal, submitted
    and was graded — every table erasure has to reach, in one place."""
    token = _invite(client, qid, email)
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": email, "consent": True}
    ).status_code == 200
    assert client.put(
        f"/invite/{token}/draft",
        json={"candidate_email": email, "code": "draft code", "language": "python"},
    ).status_code == 204
    assert client.post(
        f"/invite/{token}/events",
        json={
            "candidate_email": email,
            "question_id": qid,
            "events": [{"kind": "focus_loss", "offset_ms": 1000, "duration_ms": 500}],
        },
    ).status_code == 204

    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    resp = client.post(
        f"/invite/{token}/submit",
        json={
            "candidate_name": "Jane Doe",
            "candidate_email": email,
            "language": "python",
            "code": "print('my secret solution')",
            "consent": True,
        },
    )
    assert resp.status_code == 201, resp.text
    sub_id = resp.json()["submission_id"]
    assert client.post("/assessments/callback", json=_callback("job-1")).status_code == 200
    return token, sub_id


def _erase(client: TestClient, email: str = CANDIDATE) -> Any:
    return client.request("DELETE", f"/candidates/{email}")


# --------------------------------------------------------------------------- #
# Erasure                                                                       #
# --------------------------------------------------------------------------- #


def test_erasure_destroys_identifiers_and_work_but_keeps_the_verdict(client, monkeypatch) -> None:
    """The whole shape of the decision in one test: nothing left that names the
    person or reproduces their work; the statistical record still standing."""
    _token, sub_id = _full_sitting(client, monkeypatch)

    body = _erase(client).json()
    assert body["erased"] is True
    assert body["submissions"] == 1 and body["results"] == 1 and body["attempts"] == 1
    assert body["drafts_deleted"] == 1 and body["integrity_events"] == 1
    assert body["invites_amended"] == 1

    with Session(db_module.engine) as s:
        sub = s.get(Submission, sub_id)
        assert sub is not None
        assert sub.candidate == privacy.ERASED_NAME
        assert sub.candidate_email is not None
        assert sub.candidate_email.endswith(privacy.TOMBSTONE_DOMAIN)
        assert sub.code == ""
        # The grade survives: an erasure must not silently rewrite the
        # organisation's pass-rate history.
        result = s.exec(select(AssessmentResult)).one()
        assert result.verdict == "PASS" and result.score_pct == 100.0
        # ...but not the payload, which carries the name and the run output.
        assert result.full_result == privacy.ERASED_RESULT
        assert "Jane Doe" not in str(result.full_result)

        attempt = s.exec(select(CandidateAttempt)).one()
        assert attempt.candidate_name is None
        assert attempt.candidate_email.endswith(privacy.TOMBSTONE_DOMAIN)
        assert attempt.erased_at is not None
        # Drafts have no reader, so there is nothing to preserve them for.
        assert s.exec(select(CandidateDraft)).all() == []
        # The signal survives as a count; whose it was does not.
        event = s.exec(select(IntegrityEvent)).one()
        assert event.kind == "focus_loss"
        assert event.candidate_email.endswith(privacy.TOMBSTONE_DOMAIN)
        # The address is personal data on the invitation itself.
        invite = s.exec(select(Invite)).one()
        assert invite.recipients == [] and invite.deliveries == []


def test_the_tombstone_is_not_derivable_from_the_address(client, monkeypatch) -> None:
    """A hash would be reversible: an email address has nowhere near the entropy
    to survive a dictionary attack, so hashing it would be erasure in appearance
    only. Two erasures of the same address must not produce the same value."""
    _full_sitting(client, monkeypatch)
    _erase(client)
    with Session(db_module.engine) as s:
        first = s.exec(select(CandidateAttempt)).one().candidate_email
    assert CANDIDATE.split("@")[0] not in first

    _full_sitting(client, monkeypatch, qid="q2", email=CANDIDATE)
    _erase(client)
    with Session(db_module.engine) as s:
        values = {a.candidate_email for a in s.exec(select(CandidateAttempt)).all()}
    assert len(values) == 2, "a shared tombstone would link two erasures back together"


def test_two_candidates_on_one_invite_can_both_be_erased(client, monkeypatch) -> None:
    """`uq_attempt_invite_candidate` is (invite_id, candidate_email). A shared
    literal like "[erased]" would make the second erasure violate it."""
    token = _invite(client, "q1", "a@x.io")
    with Session(db_module.engine) as s:
        invite = s.exec(select(Invite)).one()
        invite.recipients = ["a@x.io", "b@x.io"]
        s.add(invite)
        s.commit()
    for email in ("a@x.io", "b@x.io"):
        assert client.post(
            f"/invite/{token}/start", json={"candidate_email": email, "consent": True}
        ).status_code == 200

    assert _erase(client, "a@x.io").json()["erased"] is True
    assert _erase(client, "b@x.io").json()["erased"] is True

    with Session(db_module.engine) as s:
        emails = [a.candidate_email for a in s.exec(select(CandidateAttempt)).all()]
    assert len(emails) == 2 and len(set(emails)) == 2


def test_erasure_is_scoped_to_the_callers_organisation(anon_client, monkeypatch) -> None:
    """The same person may have sat for two customers. One customer's erasure
    request is not the other's to make."""
    token_a = register_interviewer(anon_client, "a@corp.io", name="A")
    token_b = register_interviewer(anon_client, "b@corp.io", name="B")

    anon_client.headers["Authorization"] = f"Bearer {token_a}"
    _full_sitting(anon_client, monkeypatch, qid="qa")
    anon_client.headers["Authorization"] = f"Bearer {token_b}"
    _full_sitting(anon_client, monkeypatch, qid="qb")

    # B erases; A's identical candidate is untouched.
    assert _erase(anon_client).json()["submissions"] == 1

    with Session(db_module.engine) as s:
        surviving = [
            sub.candidate_email
            for sub in s.exec(select(Submission)).all()
            if sub.candidate_email == CANDIDATE
        ]
    assert surviving == [CANDIDATE], "the other organisation's record was erased too"


def test_the_graders_narrative_is_erased_with_the_payload(client, monkeypatch) -> None:
    """`reason` reads like metadata but it is prose about this candidate's code,
    routinely quoting the output it produced — and unlike `full_result` it is
    rendered straight into the interviewer's view."""
    _full_sitting(client, monkeypatch)
    _erase(client)
    with Session(db_module.engine) as s:
        result = s.exec(select(AssessmentResult)).one()
    assert result.reason == privacy.ERASED_REASON
    assert result.verdict == "PASS"  # the grade itself still stands


def test_an_unparseable_address_does_not_500(client) -> None:
    """The path parameter is whatever the caller typed. Validating it on the way
    back out raised *after* the erasure had been committed."""
    resp = client.request("DELETE", "/candidates/not-an-email")
    assert resp.status_code == 200, resp.text
    assert resp.json()["erased"] is False


def test_an_unknown_address_answers_200_with_nothing_erased(client) -> None:
    """404 here would be an existence oracle — an unbounded way to ask whether a
    given person has ever been assessed by this organisation."""
    resp = _erase(client, "never-heard-of@x.io")
    assert resp.status_code == 200
    body = resp.json()
    assert body["erased"] is False and body["submissions"] == 0


def test_only_an_admin_may_erase(anon_client, monkeypatch) -> None:
    admin = register_interviewer(anon_client, "admin@corp.io", name="Admin")
    anon_client.headers["Authorization"] = f"Bearer {admin}"
    _full_sitting(anon_client, monkeypatch)
    invite = anon_client.post(
        "/orgs/current/invites", json={"email": "member@corp.io", "role": "member"}
    )
    assert invite.status_code == 201, invite.text
    join_token = invite.json()["url"].split("token=")[1]

    member = register_interviewer(anon_client, "member@corp.io", name="Member")
    anon_client.headers["Authorization"] = f"Bearer {member}"
    assert anon_client.post(f"/org-invites/{join_token}/accept").status_code == 200
    assert _erase(anon_client).status_code == 403


def test_erasure_survives_foreign_keys_being_enforced(client, monkeypatch) -> None:
    """Foreign keys ON, as Postgres does and SQLite does not unless asked.

    Erasure deletes drafts and rewrites rows that other rows point at; a wrong
    order is invisible in dev and aborts in production. Same guard as the
    account-deletion path, for the same reason (X02's lesson: a test that only
    runs on SQLite proves nothing about a Postgres FK).
    """
    _full_sitting(client, monkeypatch)
    with Session(db_module.engine) as s:
        s.execute(text("PRAGMA foreign_keys=ON"))
    assert _erase(client).json()["erased"] is True


def test_an_erased_candidate_can_no_longer_use_the_old_link(client, monkeypatch) -> None:
    """Erasure takes the address off the invitation too, so the link that was
    sent to them stops admitting them — `_check_invited` has nothing left to
    match. Reassessing an erased candidate means sending a fresh invitation,
    which is the coherent reading of having forgotten them: the organisation no
    longer holds a record that this person was ever invited.

    Worth pinning because the alternative is worse in both directions — leaving
    the address on the invite would keep personal data the request asked to
    destroy, and silently revoking nothing would let a stale link resurrect it.
    """
    token, _ = _full_sitting(client, monkeypatch)
    _erase(client)
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True}
    ).status_code == 403

    # A fresh invitation works, and starts a sitting with no memory of the old one.
    resp = client.post("/questions/q1/invites", json={"recipients": [CANDIDATE]})
    assert resp.status_code == 201
    fresh = resp.json()["token"]
    assert client.post(
        f"/invite/{fresh}/start", json={"candidate_email": CANDIDATE, "consent": True}
    ).status_code == 200


# --------------------------------------------------------------------------- #
# Retention                                                                     #
# --------------------------------------------------------------------------- #


def _age_sitting(days: int) -> None:
    with Session(db_module.engine) as s:
        for attempt in s.exec(select(CandidateAttempt)).all():
            attempt.started_at = datetime.now(timezone.utc) - timedelta(days=days)
            s.add(attempt)
        for invite in s.exec(select(Invite)).all():
            invite.created_at = datetime.now(timezone.utc) - timedelta(days=days)
            s.add(invite)
        s.commit()


def _set_retention(days: int | None) -> None:
    with Session(db_module.engine) as s:
        organization = s.exec(select(Organization)).one()
        organization.retention_days = days
        s.add(organization)
        s.commit()


def test_no_window_configured_erases_nothing(client, monkeypatch) -> None:
    """The most important test here. A default window would have deleted every
    existing customer's hiring record on the first deploy after the migration."""
    _full_sitting(client, monkeypatch)
    _age_sitting(days=4000)

    with Session(db_module.engine) as s:
        assert privacy.purge_expired(s) == 0

    with Session(db_module.engine) as s:
        assert s.exec(select(CandidateAttempt)).one().candidate_email == CANDIDATE


def test_a_sitting_past_the_window_is_erased(client, monkeypatch) -> None:
    _token, sub_id = _full_sitting(client, monkeypatch)
    _set_retention(30)
    _age_sitting(days=31)

    with Session(db_module.engine) as s:
        assert privacy.purge_expired(s) == 1

    with Session(db_module.engine) as s:
        sub = s.get(Submission, sub_id)
        assert sub is not None and sub.code == ""
        assert s.exec(select(CandidateAttempt)).one().erased_at is not None


def test_a_sitting_inside_the_window_is_untouched(client, monkeypatch) -> None:
    _full_sitting(client, monkeypatch)
    _set_retention(30)
    _age_sitting(days=29)

    with Session(db_module.engine) as s:
        assert privacy.purge_expired(s) == 0
    with Session(db_module.engine) as s:
        assert s.exec(select(CandidateAttempt)).one().candidate_email == CANDIDATE


def test_the_sweep_is_idempotent(client, monkeypatch) -> None:
    """`erased_at` is what stops the second pass re-erasing — and re-minting a
    fresh tombstone every hour, which would churn the table forever."""
    _full_sitting(client, monkeypatch)
    _set_retention(30)
    _age_sitting(days=31)

    with Session(db_module.engine) as s:
        assert privacy.purge_expired(s) == 1
        first = s.exec(select(CandidateAttempt)).one().candidate_email
        assert privacy.purge_expired(s) == 0
        assert s.exec(select(CandidateAttempt)).one().candidate_email == first


def test_retention_is_measured_from_the_sitting_not_the_invitation(client, monkeypatch) -> None:
    """A link sent in January and taken in June expires six months after the
    sitting, not before it — and the old invitation must not be stripped of the
    recipient who is still sitting on it.

    The first version of the sweep blanked the recipients of every invitation
    older than the window, which reads as tidy housekeeping and is in fact data
    loss: `_check_invited` admits exactly the listed addresses, so a candidate
    mid-assessment on a thirteen-month-old link was locked out with everything
    they had written still unsubmitted.
    """
    token, _ = _full_sitting(client, monkeypatch)
    _set_retention(30)
    with Session(db_module.engine) as s:
        invite = s.exec(select(Invite)).one()
        invite.created_at = datetime.now(timezone.utc) - timedelta(days=200)
        s.add(invite)
        attempt = s.exec(select(CandidateAttempt)).one()
        attempt.started_at = datetime.now(timezone.utc) - timedelta(days=5)
        s.add(attempt)
        s.commit()

    with Session(db_module.engine) as s:
        assert privacy.purge_expired(s) == 0

    with Session(db_module.engine) as s:
        assert s.exec(select(Invite)).one().recipients == [CANDIDATE]
    # The credential still works, which is the point. 409 is the
    # already-submitted guard firing *after* the invite check passed; 403 would
    # mean the address had been stripped and the candidate locked out.
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True}
    ).status_code == 409


def test_an_old_invitation_sheds_a_recipient_who_never_sat(client) -> None:
    """The other half: an address with nothing behind it is stale personal data
    on an invitation long past the window, and does go."""
    token = _invite(client, "q1", "never-came@x.io")
    _set_retention(30)
    with Session(db_module.engine) as s:
        invite = s.exec(select(Invite)).one()
        invite.created_at = datetime.now(timezone.utc) - timedelta(days=100)
        s.add(invite)
        s.commit()

    with Session(db_module.engine) as s:
        privacy.purge_expired(s)
    with Session(db_module.engine) as s:
        assert s.exec(select(Invite)).one().recipients == []
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": "never-came@x.io", "consent": True}
    ).status_code == 403


def test_the_retention_window_is_per_organisation(anon_client, monkeypatch) -> None:
    token_a = register_interviewer(anon_client, "a@corp.io", name="A")
    token_b = register_interviewer(anon_client, "b@corp.io", name="B")
    anon_client.headers["Authorization"] = f"Bearer {token_a}"
    _full_sitting(anon_client, monkeypatch, qid="qa")
    anon_client.headers["Authorization"] = f"Bearer {token_b}"
    _full_sitting(anon_client, monkeypatch, qid="qb")
    _age_sitting(days=100)

    # Only B sets a window.
    assert anon_client.patch("/orgs/current", json={"retention_days": 30}).status_code == 200

    with Session(db_module.engine) as s:
        assert privacy.purge_expired(s) == 1
    with Session(db_module.engine) as s:
        remaining = [
            a.candidate_email
            for a in s.exec(select(CandidateAttempt)).all()
            if a.erased_at is None
        ]
    assert remaining == [CANDIDATE], "the organisation with no window lost data"


def test_the_window_is_settable_and_clearable_over_the_api(client) -> None:
    assert client.get("/orgs/current").json()["retention_days"] is None
    assert client.patch("/orgs/current", json={"retention_days": 90}).json()["retention_days"] == 90
    # Changing the name alone must not silently clear the window.
    assert client.patch("/orgs/current", json={"name": "Acme"}).json()["retention_days"] == 90
    # An explicit null turns the policy off — distinguishable from an omitted field.
    assert client.patch("/orgs/current", json={"retention_days": None}).json()[
        "retention_days"
    ] is None


def test_a_nonsensical_window_is_refused(client) -> None:
    """0 would read as "delete everything immediately" from a mis-typed form."""
    assert client.patch("/orgs/current", json={"retention_days": 0}).status_code == 422
    assert client.patch("/orgs/current", json={"retention_days": 99999}).status_code == 422


def test_only_an_admin_may_change_the_window(anon_client) -> None:
    admin = register_interviewer(anon_client, "admin@corp.io", name="Admin")
    anon_client.headers["Authorization"] = f"Bearer {admin}"
    join = anon_client.post(
        "/orgs/current/invites", json={"email": "member@corp.io", "role": "member"}
    ).json()["url"].split("token=")[1]
    member = register_interviewer(anon_client, "member@corp.io", name="Member")
    anon_client.headers["Authorization"] = f"Bearer {member}"
    assert anon_client.post(f"/org-invites/{join}/accept").status_code == 200
    assert anon_client.patch("/orgs/current", json={"retention_days": 30}).status_code == 403


# --------------------------------------------------------------------------- #
# Consent                                                                       #
# --------------------------------------------------------------------------- #


def test_a_sitting_cannot_start_without_consent(client) -> None:
    token = _invite(client)
    resp = client.post(f"/invite/{token}/start", json={"candidate_email": CANDIDATE})
    assert resp.status_code == 422
    assert "agree" in resp.json()["detail"]
    with Session(db_module.engine) as s:
        assert s.exec(select(CandidateAttempt)).all() == []


def test_the_refusal_is_not_a_403(client) -> None:
    """The candidate gate renders a 403 as "this assessment wasn't sent to that
    email address" — telling the candidate to fix the one thing that isn't
    wrong. The same mistake X02 made with a quota refusal."""
    token = _invite(client)
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE}
    ).status_code != 403


def test_consent_is_recorded_with_the_policy_version(client) -> None:
    token = _invite(client)
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True}
    ).status_code == 200
    with Session(db_module.engine) as s:
        attempt = s.exec(select(CandidateAttempt)).one()
    assert attempt.consent_at is not None
    assert attempt.consent_version == config.PRIVACY_POLICY_VERSION


def test_returning_to_a_consented_sitting_does_not_ask_again(client) -> None:
    """Consent belongs to the sitting, recorded once. A reload is not a new
    agreement, and re-stamping it would overwrite when they actually agreed."""
    token = _invite(client)
    client.post(f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True})
    with Session(db_module.engine) as s:
        first = s.exec(select(CandidateAttempt)).one().consent_at

    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE}
    ).status_code == 200
    with Session(db_module.engine) as s:
        assert s.exec(select(CandidateAttempt)).one().consent_at == first


def test_submitting_without_starting_still_needs_consent(client, monkeypatch) -> None:
    """The start screen is only UI. A caller that POSTs straight to /submit
    begins a sitting too, and `_get_or_start_attempt` is where both paths meet."""
    token = _invite(client)
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job-1"))
    resp = client.post(
        f"/invite/{token}/submit",
        json={
            "candidate_name": "Jane",
            "candidate_email": CANDIDATE,
            "language": "python",
            "code": "print(1)",
        },
    )
    assert resp.status_code == 422
    with Session(db_module.engine) as s:
        assert s.exec(select(Submission)).all() == []
