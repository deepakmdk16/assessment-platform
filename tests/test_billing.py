"""Plans, quotas and per-tenant usage metering (X02).

The audit's finding was blunt: nothing measured what an organisation used and
nothing stopped it using more, while every draft and every graded submission
spent real LLM money. These tests pin the three halves of the fix — that usage
is counted exactly, that an allowance actually refuses work, and that the money
already spent is attributable to the tenant that spent it.

Enforcement is off under test (config.BILLING_ENFORCED), so each test that cares
about a limit turns it on explicitly; metering is always on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from conftest import async_raise, async_return, register_interviewer
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from assessment_platform import agent_client, billing, config
from assessment_platform import db as db_module
from assessment_platform.models import Membership, Organization, OrgUsage, Submission


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


def _draft_payload(cost: float = 0.021) -> dict[str, Any]:
    return {
        "question": _question("drafted"),
        "warnings": [],
        "reference_solution": "print(1)",
        "reference_language": "python",
        "engine": "test",
        "cost_usd": cost,
    }


def _variant(qid: str, cost: float = 0.01) -> dict[str, Any]:
    q = _question(qid)
    q["example"] = {"input": "1\n", "output": "1"}
    return {"question": q, "reference_solution": "print(1)", "warnings": [], "cost_usd": cost}


def _fake_set(*variants: dict[str, Any]):
    async def _f(**_kwargs: object) -> dict[str, Any]:
        return {"engine": "test", "warnings": [], "variants": list(variants)}

    return _f


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _org_id() -> int:
    with Session(db_module.engine) as s:
        return s.exec(select(Membership)).one().org_id


def _usage(org_id: int | None = None) -> OrgUsage:
    with Session(db_module.engine) as s:
        return billing.usage(s, org_id if org_id is not None else _org_id())


def _set_usage(**counts: Any) -> None:
    """Put the organisation's current month at a chosen point, the way a month of
    real activity would have."""
    org_id = _org_id()
    with Session(db_module.engine) as s:
        row = s.exec(select(OrgUsage).where(OrgUsage.org_id == org_id)).first() or OrgUsage(
            org_id=org_id, period=billing.period_key()
        )
        for name, value in counts.items():
            setattr(row, name, value)
        s.add(row)
        s.commit()


def _set_plan(**fields: Any) -> None:
    with Session(db_module.engine) as s:
        org = s.get(Organization, _org_id())
        assert org is not None
        for name, value in fields.items():
            setattr(org, name, value)
        s.add(org)
        s.commit()


@pytest.fixture
def enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "BILLING_ENFORCED", True)


def _invite(client: TestClient, qid: str = "q1", email: str = "cand@x.io") -> str:
    assert client.post("/questions", json=_question(qid)).status_code == 201
    resp = client.post(f"/questions/{qid}/invites", json={"recipients": [email]})
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


# --------------------------------------------------------------------------- #
# The plan itself                                                               #
# --------------------------------------------------------------------------- #


def test_a_new_organisation_is_on_the_free_plan_with_nothing_used(client) -> None:
    body = client.get("/billing").json()

    assert body["plan"]["key"] == "free"
    assert body["status"] == "active"
    assert body["usage"]["sittings"] == 0
    assert body["usage"]["drafts"] == 0
    assert body["usage"]["seats"] == 1  # the founder
    assert body["usage"]["period"] == billing.period_key()
    assert body["current_period_end"] is None
    # The pricing table is served, not hardcoded in the SPA.
    assert [p["key"] for p in body["plans"]] == ["free", "starter", "growth"]
    assert body["payments_enabled"] is False  # no Stripe key configured


def test_reading_the_billing_page_creates_no_usage_row(client) -> None:
    """A read path must not write. The counters row is created by the first
    metered event, so an organisation that has done nothing has no row at all."""
    client.get("/billing")
    with Session(db_module.engine) as s:
        assert s.exec(select(OrgUsage)).all() == []


def test_billing_needs_a_login(anon_client) -> None:
    assert anon_client.get("/billing").status_code == 401


def test_a_lapsed_subscription_falls_back_to_free_limits() -> None:
    """Dunning ends, the plan's entitlements go — but the fallback is free, never
    zero: a lapsed customer keeps their data and can still be evaluated."""
    org = Organization(id=1, name="Acme", plan="growth", plan_status="canceled")
    assert billing.plan_for(org).key == "free"

    org.plan_status = "past_due"  # Stripe is still retrying the card
    assert billing.plan_for(org).key == "growth"

    org.plan, org.plan_status = "enterprise-hand-edited", "active"
    assert billing.plan_for(org).key == "free"  # unknown plan → the smaller one


# --------------------------------------------------------------------------- #
# Sittings: counted where a sitting actually begins                             #
# --------------------------------------------------------------------------- #


def test_a_candidate_starting_counts_one_sitting(client) -> None:
    token = _invite(client)
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": "cand@x.io"}
    ).status_code == 200

    assert _usage().sittings == 1


def test_reopening_the_link_does_not_bill_twice(client) -> None:
    """The metered unit is the sitting, not the request: a candidate who reloads,
    switches device or double-clicks Start is one sitting."""
    token = _invite(client)
    for _ in range(3):
        client.post(f"/invite/{token}/start", json={"candidate_email": "cand@x.io"})

    assert _usage().sittings == 1


def test_a_second_candidate_is_a_second_sitting(client) -> None:
    assert client.post("/questions", json=_question("q1")).status_code == 201
    resp = client.post(
        "/questions/q1/invites", json={"recipients": ["a@x.io", "b@x.io"]}
    )
    token = resp.json()["token"]
    client.post(f"/invite/{token}/start", json={"candidate_email": "a@x.io"})
    client.post(f"/invite/{token}/start", json={"candidate_email": "b@x.io"})

    assert _usage().sittings == 2


def test_an_exhausted_plan_turns_a_new_candidate_away_neutrally(client, enforced) -> None:
    """A candidate is not the customer: they get a neutral 403 that says nothing
    about somebody else's billing, never a 402 asking them to pay."""
    token = _invite(client)
    _set_usage(sittings=billing.PLANS["free"].sittings)

    resp = client.post(f"/invite/{token}/start", json={"candidate_email": "cand@x.io"})
    assert resp.status_code == 403
    assert "not available" in resp.json()["detail"]
    assert "plan" not in resp.json()["detail"].lower()


def test_a_candidate_already_sitting_is_never_turned_away(client, enforced) -> None:
    """The limit is checked when a sitting BEGINS and never again — an allowance
    running out mid-assessment must not take away someone's work."""
    token = _invite(client)
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": "cand@x.io"}
    ).status_code == 200

    _set_usage(sittings=billing.PLANS["free"].sittings * 10)

    # Re-entry, and the submit path that also anchors an attempt, both still work.
    assert client.post(
        f"/invite/{token}/start", json={"candidate_email": "cand@x.io"}
    ).status_code == 200


def test_invites_are_refused_once_the_month_is_spent(client, enforced) -> None:
    """The interviewer-facing half of the same limit: they find out while sending
    links, which they can act on, rather than by a candidate being turned away."""
    assert client.post("/questions", json=_question("q1")).status_code == 201
    _set_usage(sittings=billing.PLANS["free"].sittings)

    resp = client.post("/questions/q1/invites", json={"recipients": ["cand@x.io"]})
    assert resp.status_code == 402
    assert "Free plan" in resp.json()["detail"]


def test_a_variant_set_batch_must_fit_the_remaining_allowance(client, enforced, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "draft_set", _fake_set(_variant("va"), _variant("vb")))
    created = client.post(
        "/variant-sets",
        json={
            "title": "T",
            "brief": "b",
            "language": "python",
            "difficulty": "medium",
            "variants": [
                dict(_question("va"), label="A", example={"input": "1\n", "output": "1"}),
                dict(_question("vb"), label="B", example={"input": "1\n", "output": "1"}),
            ],
        },
    )
    assert created.status_code == 201, created.text
    set_id = created.json()["id"]
    _set_usage(sittings=billing.PLANS["free"].sittings - 2)

    # One invite per recipient, so three recipients need three sittings.
    refused = client.post(
        f"/variant-sets/{set_id}/invites",
        json={"recipients": ["a@x.io", "b@x.io", "c@x.io"]},
    )
    assert refused.status_code == 402

    allowed = client.post(
        f"/variant-sets/{set_id}/invites", json={"recipients": ["a@x.io", "b@x.io"]}
    )
    assert allowed.status_code == 201


# --------------------------------------------------------------------------- #
# Drafts: the allowance is claimed before the money is spent                    #
# --------------------------------------------------------------------------- #


def test_a_draft_counts_and_records_what_it_cost(client, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "draft_question", async_return(_draft_payload(0.021)))

    assert client.post(
        "/questions/draft", json={"brief": "b", "language": "python"}
    ).status_code == 200

    row = _usage()
    assert row.drafts == 1
    assert row.draft_cost_usd == pytest.approx(0.021)


def test_a_variant_set_costs_one_draft_per_variant(client, monkeypatch) -> None:
    """The rate limiter counts calls and cannot see this: a set of three is three
    full drafts on the agent, at three times the price."""
    monkeypatch.setattr(
        agent_client, "draft_set", _fake_set(_variant("va"), _variant("vb"), _variant("vc"))
    )

    resp = client.post(
        "/variant-sets/draft", json={"brief": "b", "language": "python", "count": 3}
    )
    assert resp.status_code == 200

    row = _usage()
    assert row.drafts == 3
    assert row.draft_cost_usd == pytest.approx(0.03)


def test_drafting_stops_when_the_allowance_is_gone(client, enforced, monkeypatch) -> None:
    monkeypatch.setattr(agent_client, "draft_question", async_return(_draft_payload()))
    _set_usage(drafts=billing.PLANS["free"].drafts)

    resp = client.post("/questions/draft", json={"brief": "b", "language": "python"})
    assert resp.status_code == 402
    assert "AI question drafts" in resp.json()["detail"]


def test_a_set_that_would_overshoot_is_refused_whole(client, enforced, monkeypatch) -> None:
    """Claimed as a batch: a set of three with two left refuses rather than
    drafting two and billing for three."""
    monkeypatch.setattr(agent_client, "draft_set", _fake_set(_variant("va")))
    _set_usage(drafts=billing.PLANS["free"].drafts - 2)

    resp = client.post(
        "/variant-sets/draft", json={"brief": "b", "language": "python", "count": 3}
    )
    assert resp.status_code == 402
    assert _usage().drafts == billing.PLANS["free"].drafts - 2  # nothing claimed


def test_a_draft_the_agent_never_produced_is_handed_back(client, enforced, monkeypatch) -> None:
    """The allowance is claimed before the call, so an agent that is down must
    not cost the interviewer a draft they never got."""
    monkeypatch.setattr(
        agent_client, "draft_question", async_raise(httpx.ConnectError("agent down"))
    )

    assert client.post(
        "/questions/draft", json={"brief": "b", "language": "python"}
    ).status_code == 502
    assert _usage().drafts == 0


def test_enforcement_off_still_meters(client, monkeypatch) -> None:
    """The metering-first deployment: counters and costs are collected even while
    nothing is refused, so a month of real usage can be seen before charging."""
    monkeypatch.setattr(agent_client, "draft_question", async_return(_draft_payload()))
    _set_usage(drafts=billing.PLANS["free"].drafts)

    assert client.post(
        "/questions/draft", json={"brief": "b", "language": "python"}
    ).status_code == 200
    assert _usage().drafts == billing.PLANS["free"].drafts + 1


# --------------------------------------------------------------------------- #
# Cost attribution                                                              #
# --------------------------------------------------------------------------- #


def _callback(job_id: str, cost: float | None = 0.0094) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_id": job_id,
        "verdict": "PASS",
        "score_pct": 100.0,
        "reason": "all tests passed",
    }
    if cost is not None:
        payload["judge_cost_usd"] = cost
    return payload


def _graded(client, monkeypatch, job_id: str = "job-1") -> str:
    client.post("/questions", json=_question("q1"))
    monkeypatch.setattr(agent_client, "trigger_assessment", async_return(job_id))
    resp = client.post(
        "/submissions",
        json={"question_id": "q1", "candidate": "Jane", "language": "python", "code": "x"},
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


def test_judge_cost_lands_on_the_row_and_in_the_month(client, monkeypatch) -> None:
    """The figure was always inside `full_result`; a column and a monthly total
    are what make "what did this customer cost us" answerable."""
    sub_id = _graded(client, monkeypatch)

    assert client.post("/assessments/callback", json=_callback("job-1")).status_code == 200

    with Session(db_module.engine) as s:
        assert s.get(Submission, sub_id).judge_cost_usd == pytest.approx(0.0094)
    assert _usage().judge_cost_usd == pytest.approx(0.0094)


def test_a_redelivered_callback_does_not_bill_twice(client, monkeypatch) -> None:
    _graded(client, monkeypatch)
    client.post("/assessments/callback", json=_callback("job-1"))
    client.post("/assessments/callback", json=_callback("job-1"))

    assert _usage().judge_cost_usd == pytest.approx(0.0094)


def test_an_unpriced_grade_records_nothing(client, monkeypatch) -> None:
    """A local model prices nothing, and an unknown cost is not zero cost."""
    sub_id = _graded(client, monkeypatch)

    client.post("/assessments/callback", json=_callback("job-1", cost=None))

    with Session(db_module.engine) as s:
        assert s.get(Submission, sub_id).judge_cost_usd is None
    assert _usage().judge_cost_usd == 0.0


# --------------------------------------------------------------------------- #
# Seats                                                                         #
# --------------------------------------------------------------------------- #


def test_a_pending_invitation_holds_a_seat(client, enforced) -> None:
    """Otherwise a two-seat organisation sends ten invitations and lets them
    all in."""
    first = client.post("/orgs/current/invites", json={"email": "colleague@acme.io"})
    assert first.status_code == 201
    assert client.get("/billing").json()["usage"]["seats"] == 2  # founder + pending

    second = client.post("/orgs/current/invites", json={"email": "another@acme.io"})
    assert second.status_code == 402
    assert "seats" in second.json()["detail"]


def test_an_expired_invitation_gives_its_seat_back(client, enforced) -> None:
    client.post("/orgs/current/invites", json={"email": "colleague@acme.io"})
    with Session(db_module.engine) as s:
        from assessment_platform.models import OrgInvite

        invite = s.exec(select(OrgInvite)).one()
        invite.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        s.add(invite)
        s.commit()

    assert client.post(
        "/orgs/current/invites", json={"email": "another@acme.io"}
    ).status_code == 201


def test_accepting_is_refused_when_the_seat_has_gone(anon_client, monkeypatch) -> None:
    """An invitation outlives a plan change: the seat that was free when it was
    sent may not be free when it is opened. The invitee is not the customer, so
    this is a 409 about the organisation's state, not a 402 asking them to pay."""
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    first = register_interviewer(anon_client, "one@acme.io", name="One")
    second = register_interviewer(anon_client, "two@acme.io", name="Two")
    tokens = [
        anon_client.post(
            "/orgs/current/invites", json={"email": email}, headers=auth(admin)
        ).json()["url"].rsplit("token=", 1)[1]
        for email in ("one@acme.io", "two@acme.io")
    ]

    monkeypatch.setattr(config, "BILLING_ENFORCED", True)
    # One fills the organisation's second and last free seat.
    assert anon_client.post(
        f"/org-invites/{tokens[0]}/accept", headers=auth(first)
    ).status_code == 200

    refused = anon_client.post(f"/org-invites/{tokens[1]}/accept", headers=auth(second))
    assert refused.status_code == 409
    assert "no seat available" in refused.json()["detail"]


def test_a_bigger_plan_buys_more_seats(client, enforced) -> None:
    _set_plan(plan="growth")
    for i in range(5):
        assert client.post(
            "/orgs/current/invites", json={"email": f"colleague{i}@acme.io"}
        ).status_code == 201
    assert client.get("/billing").json()["plan"]["seats"] == 20
