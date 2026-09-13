"""P2b — the support address a candidate is given, and the feedback they can
leave once a sitting is over.

Two rules are pinned here. A candidate is never shown an interviewer's personal
address: the invitation's Reply-To is the interviewer's own header, but the
product's screens show the platform's mailbox, tagged per organisation only once
the caller has identified as an invited recipient. And feedback is personal data
like any other: one row per sitting, and every erasure path takes it with them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from conftest import async_return, register_interviewer
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from assessment_platform import agent_client, config, privacy, support
from assessment_platform import db as db_module
from assessment_platform.models import CandidateAttempt, CandidateFeedback, Organization

CANDIDATE = "cand@x.io"


def _question(qid: str) -> dict[str, Any]:
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


def _sitting(client: TestClient, monkeypatch, *, org_name: str = "Acme Corp") -> str:
    """An assessment invite for one candidate, with the organisation named. Returns
    the invite token; nothing has been submitted yet."""
    client.patch("/orgs/current", json={"name": org_name})
    for qid in ("q1", "q2"):
        assert client.post("/questions", json=_question(qid)).status_code == 201
    client.post("/assessments", json={"id": "a1", "title": "A", "question_ids": ["q1", "q2"]})
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    return client.post("/assessments/a1/invites", json={"recipients": [CANDIDATE]}).json()["token"]


def _submit(client: TestClient, token: str, qid: str, email: str = CANDIDATE) -> int:
    return client.post(
        f"/invite/{token}/submit",
        json={
            "candidate_name": "C",
            "candidate_email": email,
            "consent": True,
            "language": "python",
            "code": "print(1)",
            "question_id": qid,
        },
    ).status_code


def _feedback(rating: int = 4, comment: str = "Clear prompts.", **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "candidate_email": CANDIDATE,
        "rating": rating,
        "difficulty_fair": "fair",
        "comment": comment,
    }
    body.update(over)
    return body


# --------------------------------------------------------------------------- #
# The support address                                                           #
# --------------------------------------------------------------------------- #


def test_the_probe_is_untagged_and_the_sitting_is_tagged(client, monkeypatch) -> None:
    """Before /start anyone holding the link is reading the response, so it must
    not say whose assessment it is; after /start the caller has proved they were
    invited, so the address carries the organisation's routing tag."""
    monkeypatch.setattr(config, "SUPPORT_EMAIL", "support@assess.dev")
    token = _sitting(client, monkeypatch)

    probe = client.get(f"/invite/{token}").json()
    assert probe["support_email"] == "support@assess.dev"

    started = client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True}
    ).json()
    with Session(db_module.engine) as session:
        org_id = session.exec(select(Organization)).one().id
    assert started["support_email"] == f"support+acme-corp-{org_id}@assess.dev"


def test_no_address_configured_shows_no_contact_at_all(client, monkeypatch) -> None:
    monkeypatch.setattr(config, "SUPPORT_EMAIL", "")
    token = _sitting(client, monkeypatch)
    assert client.get(f"/invite/{token}").json()["support_email"] is None
    started = client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True}
    ).json()
    assert started["support_email"] is None


def test_the_tag_is_skipped_when_it_would_be_wrong(monkeypatch) -> None:
    """Unit: every case where tagging can't apply falls back to the plain address
    rather than inventing one."""
    org = Organization(id=7, name="Acme Corp")
    monkeypatch.setattr(config, "SUPPORT_EMAIL", "support@assess.dev")

    monkeypatch.setattr(config, "SUPPORT_EMAIL_ORG_TAG", False)
    assert support.contact_email(org) == "support@assess.dev"

    monkeypatch.setattr(config, "SUPPORT_EMAIL_ORG_TAG", True)
    assert support.contact_email(None) == "support@assess.dev"

    # An operator who already tags the address keeps their own tag.
    monkeypatch.setattr(config, "SUPPORT_EMAIL", "support+hiring@assess.dev")
    assert support.contact_email(org) == "support+hiring@assess.dev"

    # A name with nothing addressable left in it still gets a per-org tag.
    monkeypatch.setattr(config, "SUPPORT_EMAIL", "support@assess.dev")
    assert support.contact_email(Organization(id=7, name="株式会社")) == "support+org7@assess.dev"


def test_the_tag_carries_the_org_id_so_a_rename_cannot_take_someone_elses(monkeypatch) -> None:
    """Names are neither unique nor fixed — any admin can rename their
    organisation. Without the id, two customers called Acme share a tag and a
    rename moves mail routing onto someone else's queue."""
    monkeypatch.setattr(config, "SUPPORT_EMAIL", "support@assess.dev")
    monkeypatch.setattr(config, "SUPPORT_EMAIL_ORG_TAG", True)
    one = support.contact_email(Organization(id=7, name="Acme Corp"))
    impostor = support.contact_email(Organization(id=8, name="Acme Corp"))
    assert one == "support+acme-corp-7@assess.dev"
    assert impostor == "support+acme-corp-8@assess.dev"
    assert one != impostor


def test_the_invitation_email_carries_the_tagged_address(client, monkeypatch) -> None:
    """Through the real invite route: the template is given the address by
    `_invite_email`, and a test that hands the template its own string would pass
    with that wiring deleted."""
    from assessment_platform import email_client

    monkeypatch.setattr(config, "SUPPORT_EMAIL", "support@assess.dev")
    sent: list[Any] = []
    monkeypatch.setattr(
        email_client,
        "send_invite_emails",
        lambda recipients, email, url, **kw: sent.append(email) or [],
    )
    _sitting(client, monkeypatch)

    assert sent, "the invite route sent no email"
    with Session(db_module.engine) as session:
        org_id = session.exec(select(Organization)).one().id
    tagged = f"support+acme-corp-{org_id}@assess.dev"
    assert tagged in sent[0].text
    # Escaped exactly once — _layout escapes the footer itself.
    assert tagged in sent[0].html and "&amp;" not in sent[0].html


def test_no_address_configured_leaves_the_invitation_email_alone(client, monkeypatch) -> None:
    from assessment_platform import email_client

    monkeypatch.setattr(config, "SUPPORT_EMAIL", "")
    sent: list[Any] = []
    monkeypatch.setattr(
        email_client,
        "send_invite_emails",
        lambda recipients, email, url, **kw: sent.append(email) or [],
    )
    _sitting(client, monkeypatch)
    assert sent and "Questions about this assessment" not in sent[0].text


def test_a_dead_link_can_still_say_where_to_write(anon_client, monkeypatch) -> None:
    """The probe answers 404/410 with no body, so the invalid/expired screens have
    no invite to read an address off. /public-config is where they get one — and
    it is the untagged address, which names no organisation."""
    monkeypatch.setattr(config, "SUPPORT_EMAIL", "support@assess.dev")
    monkeypatch.setattr(config, "SUPPORT_EMAIL_ORG_TAG", True)
    assert anon_client.get("/invite/nope").status_code == 404
    assert anon_client.get("/public-config").json() == {"support_email": "support@assess.dev"}

    monkeypatch.setattr(config, "SUPPORT_EMAIL", "")
    assert anon_client.get("/public-config").json() == {"support_email": None}


# --------------------------------------------------------------------------- #
# Leaving feedback                                                              #
# --------------------------------------------------------------------------- #


def test_feedback_needs_a_finished_piece_of_work(client, monkeypatch) -> None:
    """Nothing submitted, nothing to have an opinion about — and the 404 is the
    same whether the sitting never started or only ever loaded the page."""
    token = _sitting(client, monkeypatch)
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 404

    client.post(f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True})
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 404

    assert _submit(client, token, "q1") == 201
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 204


def test_feedback_is_accepted_once_per_sitting(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 204
    # A second send is refused rather than allowed to overwrite an answer an
    # interviewer may already have read.
    again = client.post(f"/invite/{token}/feedback", json=_feedback(rating=1, comment="no"))
    assert again.status_code == 409

    with Session(db_module.engine) as session:
        rows = session.exec(select(CandidateFeedback)).all()
    assert len(rows) == 1
    assert (rows[0].rating, rows[0].comment) == (4, "Clear prompts.")


def test_only_an_invited_recipient_may_leave_feedback(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    stranger = client.post(
        f"/invite/{token}/feedback", json=_feedback(candidate_email="someone@else.io")
    )
    assert stranger.status_code == 403


def test_a_rating_outside_the_scale_is_refused(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    assert client.post(f"/invite/{token}/feedback", json=_feedback(rating=6)).status_code == 422
    assert (
        client.post(f"/invite/{token}/feedback", json=_feedback(difficulty_fair="brutal")).status_code
        == 422
    )
    assert (
        client.post(f"/invite/{token}/feedback", json=_feedback(comment="x" * 2001)).status_code
        == 422
    )


def test_a_dead_link_takes_the_feedback_form_with_it(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    with Session(db_module.engine) as session:
        from assessment_platform.models import Invite

        invite = session.exec(select(Invite).where(Invite.token == token)).one()
        invite.status = "revoked"
        session.add(invite)
        session.commit()
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 410


# --------------------------------------------------------------------------- #
# What the interviewer sees                                                     #
# --------------------------------------------------------------------------- #


def test_feedback_reaches_the_attempts_grid_and_the_rollup(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    assert (
        client.post(
            f"/invite/{token}/feedback",
            json=_feedback(rating=5, difficulty_fair="too_hard", comment="Q2 was a stretch."),
        ).status_code
        == 204
    )

    row = client.get("/assessments/a1/attempts").json()[0]
    assert row["feedback"] == {
        "rating": 5,
        "difficulty_fair": "too_hard",
        "comment": "Q2 was a stretch.",
        "created_at": row["feedback"]["created_at"],
    }
    assert row["feedback"]["created_at"] is not None

    rollup = client.get("/analytics/assessments/a1").json()["feedback"]
    assert rollup["responses"] == 1
    assert rollup["avg_rating"] == 5.0
    assert (rollup["too_easy"], rollup["fair"], rollup["too_hard"]) == (0, 0, 1)
    assert rollup["comments"][0]["candidate_name"] == "C"
    assert rollup["comments"][0]["comment"] == "Q2 was a stretch."


def test_the_rollup_aggregates_across_candidates_and_orders_the_comments(
    client, monkeypatch
) -> None:
    """Three answers, three difficulties, one of them wordless: the average, the
    buckets, the comment filter and the newest-first order are each only visible
    with more than one row."""
    token = _sitting(client, monkeypatch)
    people = [
        ("a@x.io", 5, "too_easy", "Breezy."),
        ("b@x.io", 3, "fair", ""),
        ("c@x.io", 1, "too_hard", "Ran out of time."),
    ]
    client.post("/assessments/a1/invites", json={"recipients": [e for e, *_ in people]})
    invites = client.get("/assessments/a1/invites").json()
    token_for = {inv["token"]: inv for inv in invites}
    other = [t for t in token_for if t != token][0]

    for email, rating, level, comment in people:
        assert _submit(client, other, "q1", email=email) == 201
        assert (
            client.post(
                f"/invite/{other}/feedback",
                json={
                    "candidate_email": email,
                    "rating": rating,
                    "difficulty_fair": level,
                    "comment": comment,
                },
            ).status_code
            == 204
        )

    rollup = client.get("/analytics/assessments/a1").json()["feedback"]
    assert rollup["responses"] == 3
    assert rollup["avg_rating"] == 3.0
    assert (rollup["too_easy"], rollup["fair"], rollup["too_hard"]) == (1, 1, 1)
    # The wordless answer counts in the numbers and is not an empty quotation.
    assert [c["comment"] for c in rollup["comments"]] == ["Ran out of time.", "Breezy."]


def test_the_response_rate_counts_only_sittings_that_could_have_answered(
    client, monkeypatch
) -> None:
    """Someone who opened the link and submitted nothing is not a non-response —
    they were never asked. Counting them would understate every rate."""
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 204

    client.post("/assessments/a1/invites", json={"recipients": ["idle@x.io"]})
    idle = [
        inv["token"] for inv in client.get("/assessments/a1/invites").json() if inv["token"] != token
    ][0]
    client.post(f"/invite/{idle}/start", json={"candidate_email": "idle@x.io", "consent": True})

    rollup = client.get("/analytics/assessments/a1").json()["feedback"]
    assert len(client.get("/assessments/a1/attempts").json()) == 2
    assert (rollup["responses"], rollup["finished"]) == (1, 1)


def test_the_comment_is_stored_stripped(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    assert (
        client.post(f"/invite/{token}/feedback", json=_feedback(comment="  spaced out  ")).status_code
        == 204
    )
    with Session(db_module.engine) as session:
        assert session.exec(select(CandidateFeedback)).one().comment == "spaced out"


def test_a_quick_screen_sitting_is_never_asked(client, monkeypatch) -> None:
    """A question-only invite has no Assessment, and both surfaces that show
    feedback are reached through one — so the sitting says up front that it takes
    none, and the route refuses rather than storing something nobody can read."""
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return("job"))
    assert client.post("/questions", json=_question("solo")).status_code == 201
    token = client.post(
        "/questions/solo/invites", json={"recipients": [CANDIDATE]}
    ).json()["token"]

    started = client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True}
    ).json()
    assert started["feedback_enabled"] is False

    assert (
        client.post(
            f"/invite/{token}/submit",
            json={
                "candidate_name": "C",
                "candidate_email": CANDIDATE,
                "consent": True,
                "language": "python",
                "code": "print(1)",
            },
        ).status_code
        == 201
    )
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 404
    assert _feedback_rows() == 0


def test_an_assessment_sitting_says_it_takes_feedback(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    started = client.post(
        f"/invite/{token}/start", json={"candidate_email": CANDIDATE, "consent": True}
    ).json()
    assert started["feedback_enabled"] is True


def test_a_sitting_without_feedback_reports_none(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    assert client.get("/assessments/a1/attempts").json()[0]["feedback"] is None
    rollup = client.get("/analytics/assessments/a1").json()["feedback"]
    assert (rollup["responses"], rollup["avg_rating"], rollup["comments"]) == (0, None, [])
    # The denominator is the sittings that could have answered, not the roster.
    assert rollup["finished"] == 1


# --------------------------------------------------------------------------- #
# Erasure — every path that removes a candidate must remove this too            #
# --------------------------------------------------------------------------- #


def _feedback_rows() -> int:
    with Session(db_module.engine) as session:
        return len(session.exec(select(CandidateFeedback)).all())


def test_a_data_subject_erasure_deletes_the_feedback(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 204

    erased = client.delete(f"/candidates/{CANDIDATE}").json()
    assert erased["feedback_deleted"] == 1
    assert erased["erased"] is True
    assert _feedback_rows() == 0


def test_the_retention_sweep_deletes_the_feedback(client, monkeypatch) -> None:
    token = _sitting(client, monkeypatch)
    assert _submit(client, token, "q1") == 201
    assert client.post(f"/invite/{token}/feedback", json=_feedback()).status_code == 204

    with Session(db_module.engine) as session:
        org = session.exec(select(Organization)).one()
        org.retention_days = 1
        session.add(org)
        attempt = session.exec(select(CandidateAttempt)).one()
        attempt.started_at = datetime.now(timezone.utc) - timedelta(days=30)
        session.add(attempt)
        session.commit()
        assert privacy.purge_expired(session) == 1
        session.commit()

    assert _feedback_rows() == 0


def test_deleting_the_account_deletes_the_feedback(anon_client, monkeypatch) -> None:
    """Foreign keys ON, as Postgres enforces them and SQLite does not unless
    asked: a table missing from `_purge_org`'s delete list aborts the delete
    instead of silently orphaning rows, which is the whole reason that list is
    written out by hand."""
    token = register_interviewer(anon_client, "solo@test.io", name="Solo")
    anon_client.headers["Authorization"] = f"Bearer {token}"
    invite_token = _sitting(anon_client, monkeypatch)
    assert _submit(anon_client, invite_token, "q1") == 201
    assert anon_client.post(f"/invite/{invite_token}/feedback", json=_feedback()).status_code == 204
    assert _feedback_rows() == 1

    with Session(db_module.engine) as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
    deleted = anon_client.request(
        "DELETE", "/auth/me", json={"password": "pw-long-enough-12"}
    )
    assert deleted.status_code == 204
    assert _feedback_rows() == 0
