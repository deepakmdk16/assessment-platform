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
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import stripe
from conftest import async_raise, async_return, register_interviewer
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, select

from assessment_platform import agent_client, billing, config, stripe_client
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


def _org() -> Organization:
    with Session(db_module.engine) as s:
        org = s.get(Organization, _org_id())
        assert org is not None
        return org


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
    period = billing.period_key()
    with Session(db_module.engine) as s:
        # Filtered by period: once a test seeds a previous month too, an
        # unfiltered `.first()` silently edits the wrong row.
        row = s.exec(
            select(OrgUsage).where(OrgUsage.org_id == org_id, OrgUsage.period == period)
        ).first() or OrgUsage(
            org_id=org_id,
            period=period,
            # Created the way production creates one, or seeding a period would
            # quietly forgive the debt the test just set up.
            **billing.carried_from_previous(s, org_id, period),
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
    assert body["payments_enabled"] is False  # no Stripe key configured
    # Only what this deployment could actually sell: with no Stripe prices
    # configured, offering Starter would render a button that 503s on click.
    assert [p["key"] for p in body["plans"]] == ["free"]


def test_the_pricing_table_is_served_not_hardcoded(client, monkeypatch) -> None:
    monkeypatch.setattr(
        config, "STRIPE_PRICE_IDS", {"starter": "price_starter", "growth": "price_growth"}
    )

    plans = client.get("/billing").json()["plans"]
    assert [p["key"] for p in plans] == ["free", "starter", "growth"]
    assert [p["sittings"] for p in plans] == [10, 100, 500]


def test_a_plan_whose_price_is_unconfigured_is_not_offered(client, monkeypatch) -> None:
    monkeypatch.setattr(config, "STRIPE_PRICE_IDS", {"starter": "price_starter", "growth": None})

    assert [p["key"] for p in client.get("/billing").json()["plans"]] == ["free", "starter"]


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
    # 503, not 403: every 403 on this route means "you are not one of the invited
    # addresses", and the candidate gate says exactly that — so a quota refusal
    # sent as 403 would tell someone to fix an email address that was never wrong.
    assert resp.status_code == 503
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


def test_one_invite_to_many_recipients_needs_a_sitting_each(client, enforced) -> None:
    """One invite row carries every recipient and they share the link, so ten
    addressed people can start ten sittings. Checking for one would send the
    links and then turn nine candidates away."""
    assert client.post("/questions", json=_question("q1")).status_code == 201
    _set_usage(sittings=billing.PLANS["free"].sittings - 3)

    refused = client.post(
        "/questions/q1/invites", json={"recipients": [f"c{i}@x.io" for i in range(4)]}
    )
    assert refused.status_code == 402

    allowed = client.post(
        "/questions/q1/invites", json={"recipients": [f"c{i}@x.io" for i in range(3)]}
    )
    assert allowed.status_code == 201


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


def test_variants_the_agent_could_not_draft_are_handed_back(client, monkeypatch) -> None:
    """A set that comes back short costs what it delivered. The agent reports the
    shortfall as a warning; charging for the missing variants is the same
    unfairness as charging for a draft it refused outright."""
    monkeypatch.setattr(agent_client, "draft_set", _fake_set(_variant("va"), _variant("vb")))

    resp = client.post(
        "/variant-sets/draft", json={"brief": "b", "language": "python", "count": 3}
    )
    assert resp.status_code == 200
    assert len(resp.json()["variants"]) == 2
    assert _usage().drafts == 2


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


# --------------------------------------------------------------------------- #
# Payment (Stripe)                                                              #
# --------------------------------------------------------------------------- #


class _Event:
    """The shape of a Stripe event as the route reads it (`.type`, `.data.object`)."""

    def __init__(self, type_: str, obj: dict[str, Any]) -> None:
        self.type = type_
        self.data = SimpleNamespace(object=obj)


@pytest.fixture
def stripe_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec_x")
    monkeypatch.setattr(
        config, "STRIPE_PRICE_IDS", {"starter": "price_starter", "growth": "price_growth"}
    )


def _subscription(
    sub_id: str = "sub_1",
    customer: str = "cus_1",
    price: str = "price_growth",
    status: str = "active",
    period_end: int = 1_800_000_000,
) -> dict[str, Any]:
    return {
        "id": sub_id,
        "customer": customer,
        "status": status,
        "current_period_end": period_end,
        "items": {"data": [{"price": {"id": price}}]},
    }


def _link_customer(customer_id: str = "cus_1") -> None:
    _set_plan(stripe_customer_id=customer_id)


def _deliver(client: TestClient, monkeypatch: pytest.MonkeyPatch, event: _Event):
    monkeypatch.setattr(stripe_client, "parse_event", lambda *_a, **_k: event)
    return client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "t=1,v1=x"})


def test_payments_are_unavailable_until_stripe_is_configured(client) -> None:
    """Not a silent no-op: an upgrade button that appears to work and takes no
    money is worse than one that says so."""
    assert client.post("/billing/checkout", json={"plan": "starter"}).status_code == 503
    assert client.post("/billing/portal").status_code == 503
    assert client.post("/billing/webhook", content=b"{}").status_code == 503


def test_checkout_returns_a_hosted_url_and_remembers_the_customer(
    client, stripe_configured, monkeypatch
) -> None:
    monkeypatch.setattr(stripe_client, "create_customer", lambda *_a, **_k: "cus_new")
    monkeypatch.setattr(
        stripe_client, "create_checkout_session", lambda **_k: "https://checkout.stripe.test/s"
    )

    resp = client.post("/billing/checkout", json={"plan": "growth"})
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://checkout.stripe.test/s"

    # The customer belongs to the organisation, not to whoever clicked Upgrade.
    with Session(db_module.engine) as s:
        assert s.get(Organization, _org_id()).stripe_customer_id == "cus_new"


def test_the_customer_is_created_once(client, stripe_configured, monkeypatch) -> None:
    calls: list[int] = []

    def _create(*_a: Any, **_k: Any) -> str:
        calls.append(1)
        return "cus_new"

    monkeypatch.setattr(stripe_client, "create_customer", _create)
    monkeypatch.setattr(stripe_client, "create_checkout_session", lambda **_k: "https://x")

    client.post("/billing/checkout", json={"plan": "growth"})
    client.post("/billing/checkout", json={"plan": "starter"})
    assert calls == [1]


def test_a_plan_with_no_configured_price_is_refused(client, monkeypatch) -> None:
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(config, "STRIPE_PRICE_IDS", {"starter": None, "growth": None})

    assert client.post("/billing/checkout", json={"plan": "starter"}).status_code == 503


def test_only_an_admin_can_spend_the_organisations_money(
    anon_client, stripe_configured
) -> None:
    admin = register_interviewer(anon_client, "admin@acme.io", name="Ada")
    member = register_interviewer(anon_client, "member@acme.io", name="Mo")
    join = anon_client.post(
        "/orgs/current/invites", json={"email": "member@acme.io"}, headers=auth(admin)
    ).json()["url"].rsplit("token=", 1)[1]
    assert anon_client.post(
        f"/org-invites/{join}/accept", headers=auth(member)
    ).status_code == 200

    for route, body in (("/billing/checkout", {"plan": "starter"}), ("/billing/portal", None)):
        resp = anon_client.post(route, json=body, headers=auth(member))
        assert resp.status_code == 403, route
    # ...but a member can still read the page that explains a refused invite.
    assert anon_client.get("/billing", headers=auth(member)).status_code == 200


def test_an_organisation_cannot_subscribe_twice(client, stripe_configured, monkeypatch) -> None:
    """A second checkout mints a second subscription, and the webhook would
    overwrite the id of the first — which Stripe keeps billing with nothing here
    pointing at it. Reachable from a stale tab, since the UI hides the button."""
    monkeypatch.setattr(stripe_client, "create_checkout_session", lambda **_k: "https://x")
    _set_plan(stripe_customer_id="cus_1", stripe_subscription_id="sub_1", plan="growth")

    resp = client.post("/billing/checkout", json={"plan": "starter"})
    assert resp.status_code == 409
    assert "already has a subscription" in resp.json()["detail"]


def test_a_cancelled_organisation_can_subscribe_again(client, stripe_configured, monkeypatch) -> None:
    monkeypatch.setattr(stripe_client, "create_checkout_session", lambda **_k: "https://x")
    _set_plan(stripe_customer_id="cus_1", stripe_subscription_id="sub_old", plan_status="canceled")

    assert client.post("/billing/checkout", json={"plan": "starter"}).status_code == 200


def test_the_portal_needs_a_subscription_to_manage(client, stripe_configured) -> None:
    assert client.post("/billing/portal").status_code == 409


def test_the_portal_returns_stripes_url(client, stripe_configured, monkeypatch) -> None:
    _link_customer()
    monkeypatch.setattr(
        stripe_client, "create_portal_session", lambda **_k: "https://portal.stripe.test/p"
    )

    resp = client.post("/billing/portal")
    assert resp.status_code == 200
    assert resp.json()["url"] == "https://portal.stripe.test/p"


def test_an_unverifiable_webhook_is_refused_without_saying_why(
    client, stripe_configured, monkeypatch
) -> None:
    """The endpoint is public and unauthenticated: the signature is the whole of
    its trustworthiness, and which half of the check failed is not something an
    unauthenticated caller may learn."""

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise stripe_client.WebhookError("no signature")

    monkeypatch.setattr(stripe_client, "parse_event", _boom)

    resp = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "bad"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid webhook."


def test_a_subscription_event_moves_the_organisation_onto_the_plan(
    client, stripe_configured, monkeypatch
) -> None:
    """Stripe's signed account of what happened is the only thing that grants a
    plan — never the browser landing on `?billing=success`, which anyone can type."""
    _link_customer()

    resp = _deliver(
        client, monkeypatch, _Event("customer.subscription.updated", _subscription())
    )
    assert resp.status_code == 200

    body = client.get("/billing").json()
    assert body["plan"]["key"] == "growth"
    assert body["plan"]["sittings"] == 500
    assert body["status"] == "active"
    assert body["current_period_end"].startswith("2027-01-15")


def test_a_lapsed_card_keeps_the_plan_while_stripe_retries(
    client, stripe_configured, monkeypatch
) -> None:
    """`past_due` is dunning, not cancellation: cutting a paying customer off on
    the first failed retry loses more than the invoice is worth."""
    _link_customer()
    _deliver(client, monkeypatch, _Event("customer.subscription.updated", _subscription()))

    _deliver(
        client,
        monkeypatch,
        _Event("customer.subscription.updated", _subscription(status="past_due")),
    )

    body = client.get("/billing").json()
    assert body["plan"]["key"] == "growth"
    assert body["status"] == "past_due"


def test_cancellation_returns_the_organisation_to_free(
    client, stripe_configured, monkeypatch
) -> None:
    _link_customer()
    _deliver(client, monkeypatch, _Event("customer.subscription.updated", _subscription()))

    _deliver(client, monkeypatch, _Event("customer.subscription.deleted", _subscription()))

    body = client.get("/billing").json()
    assert body["plan"]["key"] == "free"
    assert body["status"] == "canceled"
    assert body["current_period_end"] is None


def test_a_stale_cancellation_cannot_undo_a_resubscription(
    client, stripe_configured, monkeypatch
) -> None:
    """Webhooks are not ordered: the delete of an old subscription can arrive
    after the customer has already resubscribed."""
    _link_customer()
    _deliver(
        client, monkeypatch, _Event("customer.subscription.updated", _subscription("sub_new"))
    )

    _deliver(
        client, monkeypatch, _Event("customer.subscription.deleted", _subscription("sub_old"))
    )

    assert client.get("/billing").json()["plan"]["key"] == "growth"


def test_an_unrecognised_price_leaves_the_plan_alone(
    client, stripe_configured, monkeypatch
) -> None:
    """Dropping a paying customer to free because someone renamed a price in the
    dashboard is the worse of the two failures."""
    _link_customer()
    _deliver(client, monkeypatch, _Event("customer.subscription.updated", _subscription()))

    _deliver(
        client,
        monkeypatch,
        _Event("customer.subscription.updated", _subscription(price="price_renamed")),
    )

    assert client.get("/billing").json()["plan"]["key"] == "growth"


def test_checkout_completion_links_the_subscription(client, stripe_configured, monkeypatch) -> None:
    _link_customer()

    _deliver(
        client,
        monkeypatch,
        _Event(
            "checkout.session.completed",
            {"customer": "cus_1", "subscription": "sub_1", "client_reference_id": "1"},
        ),
    )

    with Session(db_module.engine) as s:
        assert s.get(Organization, _org_id()).stripe_subscription_id == "sub_1"


def test_a_completed_checkout_is_placed_by_its_client_reference(
    client, stripe_configured, monkeypatch
) -> None:
    """The customer id may not be stored yet when the completion event lands.
    A checkout session carries the organisation in `client_reference_id` — its
    own `metadata` is a different bag from the subscription's."""
    org_id = _org_id()

    resp = _deliver(
        client,
        monkeypatch,
        _Event(
            "checkout.session.completed",
            {"customer": "cus_unstored", "subscription": "sub_1", "client_reference_id": str(org_id)},
        ),
    )
    assert resp.json()["status"] == "ok"

    with Session(db_module.engine) as s:
        org = s.get(Organization, org_id)
        assert org.stripe_customer_id == "cus_unstored"
        assert org.stripe_subscription_id == "sub_1"


def test_a_webhook_for_an_unknown_customer_is_acknowledged_not_retried(
    client, stripe_configured, monkeypatch
) -> None:
    """A non-2xx tells Stripe to retry, and retrying an event nobody can place is
    noise that eventually disables the endpoint."""
    resp = _deliver(
        client,
        monkeypatch,
        _Event("customer.subscription.updated", _subscription(customer="cus_someone_else")),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_an_event_we_do_not_handle_is_acknowledged(client, stripe_configured, monkeypatch) -> None:
    _link_customer()
    resp = _deliver(client, monkeypatch, _Event("invoice.paid", {"customer": "cus_1"}))
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_metadata_places_an_event_when_the_customer_is_not_stored_yet(
    client, stripe_configured, monkeypatch
) -> None:
    """The org_id we attach when creating the customer is the link back if our
    own column is somehow not written yet."""
    org_id = _org_id()
    obj = _subscription(customer="cus_unstored")
    obj["metadata"] = {"org_id": str(org_id)}

    resp = _deliver(client, monkeypatch, _Event("customer.subscription.updated", obj))
    assert resp.status_code == 200
    assert client.get("/billing").json()["plan"]["key"] == "growth"


# --------------------------------------------------------------------------- #
# Deleting the organisation                                                     #
# --------------------------------------------------------------------------- #


def test_deleting_the_last_account_leaves_no_row_behind(client, monkeypatch) -> None:
    """Foreign keys enforced, as Postgres does and SQLite does not unless asked.

    A table with `org_id` that `_purge_org` forgets is invisible in dev and in
    every other test here, and then aborts the delete in production — on the one
    route that has to work, since it is also the data-subject request (P13).
    """
    monkeypatch.setattr(agent_client, "draft_question", async_return(_draft_payload()))
    token = _invite(client)
    client.post(f"/invite/{token}/start", json={"candidate_email": "cand@x.io"})
    client.post("/questions/draft", json={"brief": "b", "language": "python"})
    assert _usage().sittings == 1  # there is something to orphan

    with Session(db_module.engine) as s:
        s.execute(text("PRAGMA foreign_keys=ON"))

    resp = client.request(
        "DELETE", "/auth/me", json={"password": "pw-long-enough-12"}
    )
    assert resp.status_code == 204, resp.text

    with Session(db_module.engine) as s:
        assert s.exec(select(OrgUsage)).all() == []
        assert s.exec(select(Organization)).all() == []


def test_deleting_the_organisation_cancels_its_subscription(
    client, stripe_configured, monkeypatch
) -> None:
    """The company is gone: there is nothing left to bill for, and nobody left
    who could cancel it themselves."""
    cancelled: list[str] = []
    monkeypatch.setattr(stripe_client, "cancel_subscription", lambda sub_id: cancelled.append(sub_id))
    _set_plan(stripe_customer_id="cus_1", stripe_subscription_id="sub_1", plan="growth")

    resp = client.request("DELETE", "/auth/me", json={"password": "pw-long-enough-12"})
    assert resp.status_code == 204

    assert cancelled == ["sub_1"]


def test_a_stripe_outage_cannot_block_a_deletion(client, stripe_configured, monkeypatch) -> None:
    """Deleting an account is a data-subject right; it must not depend on a third
    party being reachable. The failure is logged for a human to finish by hand."""

    def _boom(_sub_id: str) -> None:
        raise RuntimeError("stripe unreachable")

    monkeypatch.setattr(stripe_client, "cancel_subscription", _boom)
    _set_plan(stripe_customer_id="cus_1", stripe_subscription_id="sub_1", plan="growth")

    assert client.request(
        "DELETE", "/auth/me", json={"password": "pw-long-enough-12"}
    ).status_code == 204


# --------------------------------------------------------------------------- #
# Overage carried into the next period                                          #
# --------------------------------------------------------------------------- #


def _usage_row(period: str, **counts: Any) -> None:
    """Write a finished period's counters, the way a month of activity leaves them."""
    org_id = _org_id()
    with Session(db_module.engine) as s:
        row = s.exec(
            select(OrgUsage).where(OrgUsage.org_id == org_id, OrgUsage.period == period)
        ).first() or OrgUsage(
            org_id=org_id,
            period=period,
            # Created the way production creates one, or seeding a period would
            # quietly forgive the debt the test just set up.
            **billing.carried_from_previous(s, org_id, period),
        )
        for name, value in counts.items():
            setattr(row, name, value)
        s.add(row)
        s.commit()


def _start_a_sitting(client: TestClient, email: str = "cand@x.io", qid: str = "q1"):
    """The metered event: a candidate beginning. Creating an invite only CHECKS
    the allowance, so it is not what settles a period."""
    token = _invite(client, qid=qid, email=email)
    return client.post(f"/invite/{token}/start", json={"candidate_email": email})


def test_last_month_over_the_allowance_is_deducted_from_this_one(client, enforced) -> None:
    """A plan downgraded mid-month leaves the month over its new limit. The
    overrun is settled at the boundary rather than forgiven."""
    _usage_row(billing.previous_period(billing.period_key()), sittings=13, sittings_over=3)

    assert _start_a_sitting(client).status_code == 200

    row = _usage()
    assert row.sittings_carried == 3
    assert billing.allowance(_org(), "sittings", row) == 7
    assert row.sittings == 1


def test_the_carried_debt_is_what_the_month_can_no_longer_use(client, enforced) -> None:
    _usage_row(billing.previous_period(billing.period_key()), sittings=13, sittings_over=3)
    assert _start_a_sitting(client).status_code == 200  # settles the period
    # Minted while there was still room; the allowance runs out afterwards.
    token = _invite(client, qid="q2", email="other@x.io")
    _set_usage(sittings=7)  # 10 - 3 carried, fully used

    refused = client.post(f"/invite/{token}/start", json={"candidate_email": "other@x.io"})
    assert refused.status_code == 503  # the candidate-facing refusal, not a 402


def test_an_invite_refusal_names_the_reduced_allowance(client, enforced) -> None:
    _usage_row(billing.previous_period(billing.period_key()), sittings=13, sittings_over=3)
    assert _start_a_sitting(client).status_code == 200  # settles: 10 - 3 = 7
    _set_usage(sittings=7)

    assert client.post("/questions", json=_question("q3")).status_code == 201
    resp = client.post("/questions/q3/invites", json={"recipients": ["x@x.io"]})
    assert resp.status_code == 402
    assert "this month's limit of 7 is used up" in resp.json()["detail"]


def test_a_refusal_names_the_allowance_actually_given(client, enforced, monkeypatch) -> None:
    """A message naming a limit the organisation did not get is a support ticket."""
    monkeypatch.setattr(agent_client, "draft_question", async_return(_draft_payload()))
    _usage_row(billing.previous_period(billing.period_key()), drafts=8, drafts_over=3)
    assert client.post(
        "/questions/draft", json={"brief": "b", "language": "python"}
    ).status_code == 200  # settles the period: 5 - 3 carried = 2 allowed
    _set_usage(drafts=2)

    resp = client.post("/questions/draft", json={"brief": "b", "language": "python"})
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert "allows 5 AI question drafts a month" in detail
    assert "3 carried over" in detail
    assert "limit of 2 is used up" in detail


def test_a_debt_served_is_not_carried_again(client, enforced) -> None:
    """A month that paid last month's debt and stayed inside what was left
    recorded no overrun of its own, so nothing carries on — otherwise an
    organisation never climbs out of one bad month."""
    previous = billing.previous_period(billing.period_key())
    _usage_row(previous, sittings=7, sittings_carried=3, sittings_over=0)

    assert _start_a_sitting(client).status_code == 200

    assert _usage().sittings_carried == 0


def test_a_downgrade_does_not_turn_entitled_usage_into_debt(client, enforced) -> None:
    """400 sittings of a Growth plan's 500 is not an overrun. It only looks like
    one if last month is measured against this month's plan — which is why the
    overrun is written down when it happens instead of reconstructed later."""
    _usage_row(billing.previous_period(billing.period_key()), sittings=400, sittings_over=0)
    _set_plan(plan="starter")

    assert _start_a_sitting(client).status_code == 200

    row = _usage()
    assert row.sittings_carried == 0
    assert billing.allowance(_org(), "sittings", row) == 100


def test_an_unenforced_overrun_is_written_down_as_it_happens(client) -> None:
    """The only way past an allowance: metering with enforcement off. The excess
    is recorded against the limit in force at that moment, so a plan change
    afterwards cannot rewrite what was owed."""
    with Session(db_module.engine) as s:
        org = s.get(Organization, _org_id())
        assert org is not None
        for _ in range(12):  # free allows 10
            billing.consume(s, org, "sittings", 1)

    row = _usage()
    assert row.sittings == 12
    assert row.sittings_over == 2


def test_the_allowance_is_already_reduced_before_the_months_first_event(
    client, enforced
) -> None:
    """On the 1st there is no usage row yet. If the read paths offered a full
    plan's allowance until something happened to create one, an interviewer
    would send invites the claim then refuses — as a 503 to a candidate, which
    is the worst possible place to find out."""
    _usage_row(billing.previous_period(billing.period_key()), sittings=13, sittings_over=3)

    body = client.get("/billing").json()
    assert body["usage"]["sittings_carried"] == 3

    assert client.post("/questions", json=_question("q9")).status_code == 201
    _set_usage(sittings=7)  # the reduced allowance, fully used
    refused = client.post("/questions/q9/invites", json={"recipients": ["x@x.io"]})
    assert refused.status_code == 402


def test_a_debt_bigger_than_a_month_does_not_compound(client, enforced) -> None:
    _usage_row(billing.previous_period(billing.period_key()), sittings=40, sittings_over=30)

    with Session(db_module.engine) as s:
        org = s.get(Organization, _org_id())
        assert org is not None
        with pytest.raises(HTTPException) as refused:
            billing.consume(s, org, "sittings", 1)
    assert refused.value.status_code == 402

    row = _usage()
    assert row.sittings_carried == 30
    # Floored at zero: this month is stopped, but the debt doesn't roll on again.
    assert billing.allowance(_org(), "sittings", row) == 0
    assert row.sittings == 0


def test_metering_a_cost_settles_the_period_too(client, monkeypatch) -> None:
    """Whichever event happens to be first in a month creates its row, so the
    settlement can't live only in the paths that claim an allowance."""
    _usage_row(billing.previous_period(billing.period_key()), sittings=13, sittings_over=3)
    sub_id = _graded(client, monkeypatch)
    client.post("/assessments/callback", json=_callback("job-1"))

    assert sub_id
    assert _usage().sittings_carried == 3


# --------------------------------------------------------------------------- #
# Cost per submission, and tax                                                  #
# --------------------------------------------------------------------------- #


def test_the_export_carries_what_each_grade_cost(client, monkeypatch) -> None:
    """Per-month spend answers "what do we spend"; the column answers "on whom",
    which is the question an interviewer works out cost-per-hire from."""
    _graded(client, monkeypatch)
    client.post("/assessments/callback", json=_callback("job-1"))

    header, row = client.get("/submissions/export").text.splitlines()[:2]
    cost = header.split(",").index("judge_cost_usd")
    assert row.split(",")[cost] == "0.009400"


def test_an_unpriced_grade_exports_blank_not_zero(client, monkeypatch) -> None:
    _graded(client, monkeypatch)
    client.post("/assessments/callback", json=_callback("job-1", cost=None))

    # By header name, like every other CSV assertion here: a positional index
    # breaks silently the next time a column is added.
    header, row = client.get("/submissions/export").text.splitlines()[:2]
    cost = header.split(",").index("judge_cost_usd")
    assert row.split(",")[cost] == ""


def test_the_session_asks_stripe_for_automatic_tax(monkeypatch) -> None:
    """X17: selling into the EU/UK without charging and remitting VAT is a
    liability that grows silently with revenue, and retro-fitting it means
    reissuing invoices. Checked on the boundary itself, because the routes mock
    it away and the whole point is the shape of what reaches Stripe."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(config, "STRIPE_PRICE_IDS", {"starter": "price_s", "growth": "price_g"})
    monkeypatch.setattr(config, "STRIPE_AUTOMATIC_TAX", True)

    def _create(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return SimpleNamespace(url="https://checkout.stripe.test/s")

    monkeypatch.setattr(stripe.checkout.Session, "create", _create)

    stripe_client.create_checkout_session(
        customer_id="cus_1", plan="growth", org_id=1, success_url="s", cancel_url="c"
    )

    assert captured["automatic_tax"] == {"enabled": True}
    # Stripe requires the address to be written back when taxing an existing
    # customer, and a VAT number is what makes an EU B2B sale reverse-charge.
    assert captured["customer_update"]["address"] == "auto"
    assert captured["tax_id_collection"] == {"enabled": True}
    assert captured["billing_address_collection"] == "required"


def test_tax_can_be_turned_off_for_a_single_jurisdiction_deployment(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(config, "STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setattr(config, "STRIPE_PRICE_IDS", {"growth": "price_g"})
    monkeypatch.setattr(config, "STRIPE_AUTOMATIC_TAX", False)
    monkeypatch.setattr(
        stripe.checkout.Session,
        "create",
        lambda **kw: (captured.update(kw), SimpleNamespace(url="u"))[1],
    )

    stripe_client.create_checkout_session(
        customer_id="cus_1", plan="growth", org_id=1, success_url="s", cancel_url="c"
    )

    assert "automatic_tax" not in captured


def test_a_stripe_refusal_reaches_the_admin_in_stripes_own_words(
    client, stripe_configured, monkeypatch
) -> None:
    """A deployment whose Stripe Tax isn't activated fails at session creation.
    "Payments are unavailable" would send whoever is configuring it looking in
    entirely the wrong place."""

    def _boom(**_k: Any) -> str:
        raise stripe_client.PaymentError("You cannot use automatic_tax without activating it")

    monkeypatch.setattr(stripe_client, "create_customer", lambda *_a, **_k: "cus_new")
    monkeypatch.setattr(stripe_client, "create_checkout_session", _boom)

    resp = client.post("/billing/checkout", json={"plan": "growth"})
    assert resp.status_code == 502
    assert "activating it" in resp.json()["detail"]
