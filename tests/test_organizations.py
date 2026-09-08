"""Organisations, membership and org invites (X01).

Before this, every resource was scoped to the interviewer who created it, so a
company was one login: a second hiring manager saw an empty dashboard, and there
was no way to hand work over when someone left. These tests pin the two halves
of the fix — that colleagues in one organisation genuinely share a library, and
that two organisations still can't see each other at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import register_interviewer  # pytest adds tests/ to sys.path
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from assessment_platform import db as db_module
from assessment_platform.models import Membership, Organization, OrgInvite, Question


def question_payload(qid: str = "sum_n", title: str = "Sum of N") -> dict:
    return {
        "id": qid,
        "title": title,
        "prompt": "Read N then N integers; print their sum.",
        "constraints": "1 <= N <= 1e5",
        "time_limit_s": 2.0,
        "pass_threshold": 0.9,
        "test_cases": [
            {"name": f"t{i}", "stdin": "1\n5\n", "expected": "5", "category": "correctness"}
            for i in range(4)
        ]
        + [{"name": "big", "stdin": "9", "expected": "9", "category": "performance"}],
    }


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def invite_colleague(client: TestClient, admin_token: str, email: str, role: str = "member") -> str:
    """Invite `email` and return the join token from the emailed URL."""
    resp = client.post(
        "/orgs/current/invites", json={"email": email, "role": role}, headers=auth(admin_token)
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["url"].rsplit("token=", 1)[1]


# --------------------------------------------------------------------------- #
# Every account has exactly one organisation                                    #
# --------------------------------------------------------------------------- #


def test_register_founds_an_organisation_with_the_caller_as_admin(anon_client) -> None:
    token = register_interviewer(anon_client, "founder@acme.io", name="Founder")
    org = anon_client.get("/orgs/current", headers=auth(token)).json()
    assert org["role"] == "admin"
    assert org["member_count"] == 1
    assert org["name"] == "Founder's organisation"


def test_register_honours_an_explicit_org_name(anon_client) -> None:
    anon_client.post(
        "/auth/register",
        json={
            "email": "founder@acme.io",
            "password": "pw-long-enough-12",
            "name": "Founder",
            "org_name": "Acme Corp",
        },
    )
    token = anon_client.post(
        "/auth/login", json={"email": "founder@acme.io", "password": "pw-long-enough-12"}
    ).json()["access_token"]
    assert anon_client.get("/orgs/current", headers=auth(token)).json()["name"] == "Acme Corp"


def test_two_separate_signups_cannot_see_each_other(anon_client) -> None:
    """The isolation X01 must not weaken: separate sign-ups are separate tenants."""
    a = register_interviewer(anon_client, "a@one.io")
    b = register_interviewer(anon_client, "b@two.io")
    assert (
        anon_client.post("/questions", json=question_payload(), headers=auth(a)).status_code == 201
    )

    assert anon_client.get("/questions", headers=auth(b)).json()["items"] == []
    assert anon_client.get("/questions/sum_n", headers=auth(b)).status_code == 403


# --------------------------------------------------------------------------- #
# The point of the feature: a colleague works the same library                  #
# --------------------------------------------------------------------------- #


def test_invited_colleague_sees_and_can_edit_the_org_library(anon_client) -> None:
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    anon_client.post("/questions", json=question_payload(), headers=auth(admin))

    join_token = invite_colleague(anon_client, admin, "sam@acme.io")
    anon_client.post(
        "/auth/register",
        json={
            "email": "sam@acme.io",
            "password": "pw-long-enough-12",
            "name": "Sam",
            "org_invite_token": join_token,
        },
    )
    sam = anon_client.post(
        "/auth/login", json={"email": "sam@acme.io", "password": "pw-long-enough-12"}
    ).json()["access_token"]

    listing = anon_client.get("/questions", headers=auth(sam)).json()
    assert [q["id"] for q in listing["items"]] == ["sum_n"]
    # Not just readable — a colleague is a colleague, so they can author too.
    assert (
        anon_client.post("/questions", json=question_payload("second", "Second"), headers=auth(sam))
    ).status_code == 201
    assert anon_client.get("/questions", headers=auth(admin)).json()["total"] == 2

    org = anon_client.get("/orgs/current", headers=auth(sam)).json()
    assert (org["member_count"], org["role"]) == (2, "member")


def test_authorship_is_recorded_even_though_access_is_org_wide(anon_client) -> None:
    """`owner_id` survives as provenance; `org_id` is what grants access."""
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    anon_client.post("/questions", json=question_payload(), headers=auth(admin))
    with Session(db_module.engine) as s:
        q = s.get(Question, "sum_n")
        assert q is not None and q.owner_id is not None and q.org_id is not None


def test_an_existing_account_can_accept_an_invitation(anon_client) -> None:
    """Two people who each signed up separately and now want one library — the
    likeliest way a team actually forms. Sam's sign-up organisation is an empty
    shell, so joining costs nothing and is allowed."""
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    anon_client.post("/questions", json=question_payload(), headers=auth(admin))
    sam = register_interviewer(anon_client, "sam@acme.io", name="Sam")

    join_token = invite_colleague(anon_client, admin, "sam@acme.io")
    accepted = anon_client.post(f"/org-invites/{join_token}/accept", headers=auth(sam))
    assert accepted.status_code == 200
    assert accepted.json()["member_count"] == 2
    assert [q["id"] for q in anon_client.get("/questions", headers=auth(sam)).json()["items"]] == [
        "sum_n"
    ]
    with Session(db_module.engine) as s:
        # The shell organisation went with it rather than being left orphaned.
        assert len(s.exec(select(Organization)).all()) == 1


def test_accepting_is_refused_when_it_would_abandon_real_work(anon_client) -> None:
    """An invitation must not be a way to quietly delete a question bank."""
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    sam = register_interviewer(anon_client, "sam@acme.io", name="Sam")
    anon_client.post("/questions", json=question_payload("sams_own", "Sam's"), headers=auth(sam))

    join_token = invite_colleague(anon_client, admin, "sam@acme.io")
    refused = anon_client.post(f"/org-invites/{join_token}/accept", headers=auth(sam))
    assert refused.status_code == 409
    assert "cannot be moved" in refused.json()["detail"]
    # Nothing was destroyed, and the invitation is still there to accept later.
    assert anon_client.get("/questions/sams_own", headers=auth(sam)).status_code == 200
    assert anon_client.get(f"/org-invites/{join_token}").status_code == 200


def test_accepting_is_refused_while_colleagues_depend_on_you(anon_client, two_person_org) -> None:
    admin, member, _member_id = two_person_org
    other = register_interviewer(anon_client, "other@beta.io", name="Other")
    join_token = invite_colleague(anon_client, other, "sam@acme.io")
    refused = anon_client.post(f"/org-invites/{join_token}/accept", headers=auth(member))
    assert refused.status_code == 409
    assert "other members" in refused.json()["detail"]


# --------------------------------------------------------------------------- #
# The invitation is a credential, and behaves like one                          #
# --------------------------------------------------------------------------- #


def test_join_page_reads_the_invite_without_a_session(anon_client) -> None:
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    anon_client.patch("/orgs/current", json={"name": "Acme Corp"}, headers=auth(admin))
    join_token = invite_colleague(anon_client, admin, "sam@acme.io")

    public = anon_client.get(f"/org-invites/{join_token}")
    assert public.status_code == 200
    assert public.json() == {"org_name": "Acme Corp", "email": "sam@acme.io", "role": "member"}
    # Holding a link must not enumerate the company.
    assert "members" not in public.text


def test_a_forwarded_invitation_is_useless_to_another_address(anon_client) -> None:
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    join_token = invite_colleague(anon_client, admin, "sam@acme.io")

    at_register = anon_client.post(
        "/auth/register",
        json={
            "email": "mallory@evil.io",
            "password": "pw-long-enough-12",
            "name": "Mallory",
            "org_invite_token": join_token,
        },
    )
    assert at_register.status_code == 403
    # And the rejected sign-up left no account behind.
    assert (
        anon_client.post(
            "/auth/login", json={"email": "mallory@evil.io", "password": "pw-long-enough-12"}
        ).status_code
        == 401
    )

    mallory = register_interviewer(anon_client, "mallory@evil.io", name="Mallory")
    assert (
        anon_client.post(f"/org-invites/{join_token}/accept", headers=auth(mallory)).status_code
        == 403
    )


def test_an_invitation_cannot_be_used_twice(anon_client) -> None:
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    join_token = invite_colleague(anon_client, admin, "sam@acme.io")
    anon_client.post(
        "/auth/register",
        json={
            "email": "sam@acme.io",
            "password": "pw-long-enough-12",
            "name": "Sam",
            "org_invite_token": join_token,
        },
    )
    assert anon_client.get(f"/org-invites/{join_token}").status_code == 404


def test_an_expired_invitation_is_refused(anon_client) -> None:
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    join_token = invite_colleague(anon_client, admin, "sam@acme.io")
    with Session(db_module.engine) as s:
        invite = s.exec(select(OrgInvite).where(OrgInvite.token == join_token)).one()
        invite.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        s.add(invite)
        s.commit()
    assert anon_client.get(f"/org-invites/{join_token}").status_code == 404


def test_an_invitation_bypasses_the_registration_code(anon_client, monkeypatch) -> None:
    """Org invites replace REGISTRATION_CODE for adding people to a company; the
    code still gates founding a brand-new organisation."""
    from assessment_platform import config

    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    join_token = invite_colleague(anon_client, admin, "sam@acme.io")
    monkeypatch.setattr(config, "REGISTRATION_CODE", "s3cret")

    assert (
        anon_client.post(
            "/auth/register",
            json={"email": "nope@x.io", "password": "pw-long-enough-12", "name": "N"},
        ).status_code
        == 403
    )
    invited = anon_client.post(
        "/auth/register",
        json={
            "email": "sam@acme.io",
            "password": "pw-long-enough-12",
            "name": "Sam",
            "org_invite_token": join_token,
        },
    )
    assert invited.status_code == 201


def test_inviting_reveals_nothing_about_whether_the_address_has_an_account(
    anon_client,
) -> None:
    """Same response either way, so an admin can't sweep a domain for accounts."""
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    register_interviewer(anon_client, "known@other.io", name="Known")
    known = anon_client.post(
        "/orgs/current/invites", json={"email": "known@other.io"}, headers=auth(admin)
    )
    unknown = anon_client.post(
        "/orgs/current/invites", json={"email": "stranger@other.io"}, headers=auth(admin)
    )
    assert known.status_code == unknown.status_code == 201
    assert known.json().keys() == unknown.json().keys()


# --------------------------------------------------------------------------- #
# Only admins manage the roster                                                 #
# --------------------------------------------------------------------------- #


@pytest.fixture
def two_person_org(anon_client) -> tuple[str, str, int]:
    """An org with an admin and a plain member; returns (admin, member, member id)."""
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    join_token = invite_colleague(anon_client, admin, "sam@acme.io")
    anon_client.post(
        "/auth/register",
        json={
            "email": "sam@acme.io",
            "password": "pw-long-enough-12",
            "name": "Sam",
            "org_invite_token": join_token,
        },
    )
    member = anon_client.post(
        "/auth/login", json={"email": "sam@acme.io", "password": "pw-long-enough-12"}
    ).json()["access_token"]
    roster = anon_client.get("/orgs/current/members", headers=auth(admin)).json()
    member_id = next(m["interviewer_id"] for m in roster if m["role"] == "member")
    return admin, member, member_id


def test_a_member_reads_the_roster_but_cannot_change_it(anon_client, two_person_org) -> None:
    admin, member, member_id = two_person_org
    roster = anon_client.get("/orgs/current/members", headers=auth(member))
    assert roster.status_code == 200
    assert {m["role"] for m in roster.json()} == {"admin", "member"}

    for call in (
        anon_client.post(
            "/orgs/current/invites", json={"email": "x@acme.io"}, headers=auth(member)
        ),
        anon_client.patch(
            f"/orgs/current/members/{member_id}", json={"role": "admin"}, headers=auth(member)
        ),
        anon_client.delete(f"/orgs/current/members/{member_id}", headers=auth(member)),
        anon_client.patch("/orgs/current", json={"name": "Hijack"}, headers=auth(member)),
        anon_client.get("/orgs/current/invites", headers=auth(member)),
    ):
        assert call.status_code == 403, call.request.url


def test_admin_promotes_and_demotes(anon_client, two_person_org) -> None:
    admin, member, member_id = two_person_org
    promoted = anon_client.patch(
        f"/orgs/current/members/{member_id}", json={"role": "admin"}, headers=auth(admin)
    )
    assert promoted.status_code == 200 and promoted.json()["role"] == "admin"
    # Now that there are two admins, the first can be demoted.
    roster = anon_client.get("/orgs/current/members", headers=auth(admin)).json()
    admin_id = next(m["interviewer_id"] for m in roster if m["interviewer_id"] != member_id)
    assert (
        anon_client.patch(
            f"/orgs/current/members/{admin_id}", json={"role": "member"}, headers=auth(member)
        ).status_code
        == 200
    )


def test_the_last_admin_cannot_be_demoted_or_removed(anon_client, two_person_org) -> None:
    """Otherwise an organisation reaches a state only a database edit can undo."""
    admin, _member, member_id = two_person_org
    roster = anon_client.get("/orgs/current/members", headers=auth(admin)).json()
    admin_id = next(m["interviewer_id"] for m in roster if m["role"] == "admin")

    assert (
        anon_client.patch(
            f"/orgs/current/members/{admin_id}", json={"role": "member"}, headers=auth(admin)
        ).status_code
        == 409
    )
    assert (
        anon_client.delete(f"/orgs/current/members/{admin_id}", headers=auth(admin)).status_code
        == 409
    )
    # A plain member is removable; the guard is about admins, not about anyone.
    assert (
        anon_client.delete(f"/orgs/current/members/{member_id}", headers=auth(admin)).status_code
        == 204
    )


def test_a_removed_member_keeps_their_account_and_can_start_again(
    anon_client, two_person_org
) -> None:
    admin, member, member_id = two_person_org
    anon_client.post("/questions", json=question_payload(), headers=auth(member))
    anon_client.delete(f"/orgs/current/members/{member_id}", headers=auth(admin))

    # Removed, so scoped routes refuse — but the login still works and the
    # question they wrote stayed with the organisation.
    assert anon_client.get("/questions", headers=auth(member)).status_code == 403
    assert anon_client.get("/questions", headers=auth(admin)).json()["total"] == 1

    founded = anon_client.post("/orgs", json={"name": "Sam Consulting"}, headers=auth(member))
    assert founded.status_code == 201 and founded.json()["role"] == "admin"
    assert anon_client.get("/questions", headers=auth(member)).json()["items"] == []
    # And founding a second one is not a way to escape the one-org rule.
    assert (
        anon_client.post("/orgs", json={"name": "Again"}, headers=auth(member)).status_code == 409
    )


def test_pending_invitations_are_listed_and_revocable(anon_client) -> None:
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    invite_colleague(anon_client, admin, "sam@acme.io")
    listed = anon_client.get("/orgs/current/invites", headers=auth(admin)).json()
    assert [i["email"] for i in listed] == ["sam@acme.io"]

    assert (
        anon_client.delete(
            f"/orgs/current/invites/{listed[0]['id']}", headers=auth(admin)
        ).status_code
        == 204
    )
    assert anon_client.get("/orgs/current/invites", headers=auth(admin)).json() == []


def test_re_inviting_replaces_the_pending_invitation(anon_client) -> None:
    """Otherwise "resend" quietly leaves two live keys for one seat."""
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    first = invite_colleague(anon_client, admin, "sam@acme.io")
    second = invite_colleague(anon_client, admin, "sam@acme.io")
    assert first != second
    assert anon_client.get(f"/org-invites/{first}").status_code == 404
    assert anon_client.get(f"/org-invites/{second}").status_code == 200
    assert len(anon_client.get("/orgs/current/invites", headers=auth(admin)).json()) == 1


# --------------------------------------------------------------------------- #
# Deleting an account: the organisation is not one person's to destroy          #
# --------------------------------------------------------------------------- #


def test_deleting_a_teammates_account_leaves_the_organisation_intact(
    anon_client, two_person_org
) -> None:
    """The regression this guards against is severe: before organisations, account
    deletion removed every row the account owned. Applied unchanged to a team, one
    member deleting their account would take colleagues' questions and other
    people's submissions with it."""
    admin, member, _member_id = two_person_org
    anon_client.post("/questions", json=question_payload(), headers=auth(member))

    gone = anon_client.request(
        "DELETE", "/auth/me", json={"password": "pw-long-enough-12"}, headers=auth(member)
    )
    assert gone.status_code == 204

    listing = anon_client.get("/questions", headers=auth(admin)).json()
    assert [q["id"] for q in listing["items"]] == ["sum_n"]
    org = anon_client.get("/orgs/current", headers=auth(admin)).json()
    assert org["member_count"] == 1
    # Authorship is cut rather than left dangling at a row that no longer exists.
    with Session(db_module.engine) as s:
        q = s.get(Question, "sum_n")
        assert q is not None and q.owner_id is None and q.org_id is not None


def test_the_last_member_deleting_their_account_still_purges_everything(anon_client) -> None:
    """The sole-trader case is unchanged: deleting the account deletes the
    workspace, which is what a data-subject request requires."""
    solo = register_interviewer(anon_client, "solo@acme.io", name="Solo")
    anon_client.post("/questions", json=question_payload(), headers=auth(solo))
    anon_client.request(
        "DELETE", "/auth/me", json={"password": "pw-long-enough-12"}, headers=auth(solo)
    )
    with Session(db_module.engine) as s:
        assert s.get(Question, "sum_n") is None
        assert s.exec(select(Membership)).all() == []
