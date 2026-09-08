"""The Stripe boundary — every call that leaves this process for Stripe.

One module for the same reason as `agent_client` and `email_client`: it is what
the tests mock, and nothing else in the codebase needs to know Stripe exists.
The routes deal in "start a checkout for this plan" and "this subscription is
now active"; the vocabulary of prices, customers and events stops here.

Nothing is called unless `STRIPE_SECRET_KEY` is set. Unconfigured, the payment
routes report themselves unavailable rather than half-working — an organisation
stays on the free plan, every limit still applies, and nothing pretends a card
was taken.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import stripe

from . import config

logger = logging.getLogger(__name__)


class WebhookError(Exception):
    """A webhook that could not be trusted: bad signature, or a malformed body.

    Stripe's own exception types stop here, so the route can answer 400 without
    importing the SDK.
    """


@dataclass(frozen=True)
class Subscription:
    """What a Stripe subscription means to us, and nothing more.

    `plan` is None when the price on the subscription maps to no plan we sell —
    a price created by hand in the Stripe dashboard, or one whose id was never
    put in the environment. The caller treats that as "unknown, leave the plan
    alone" rather than guessing.
    """

    id: str
    customer_id: str
    status: str
    plan: str | None
    current_period_end: datetime | None


def _key() -> str:
    if not config.STRIPE_SECRET_KEY:  # pragma: no cover — routes guard first
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
    return config.STRIPE_SECRET_KEY


def price_id(plan: str) -> str | None:
    """The Stripe Price backing one of our plan keys, if it is configured."""
    return config.STRIPE_PRICE_IDS.get(plan)


def plan_for_price(price: str | None) -> str | None:
    """Our plan key for a Stripe Price id — the reverse of `price_id`."""
    if price is None:
        return None
    for plan, configured in config.STRIPE_PRICE_IDS.items():
        if configured and configured == price:
            return plan
    return None


def create_customer(org_id: int, name: str, email: str) -> str:
    """Create the Stripe customer for an organisation and return its id.

    `metadata.org_id` is the link back: a webhook that arrives with only a
    customer id can still find the organisation even if our own
    `stripe_customer_id` column were somehow lost.
    """
    customer = stripe.Customer.create(
        api_key=_key(),
        name=name,
        email=email,
        metadata={"org_id": str(org_id)},
    )
    return str(customer.id)


def create_checkout_session(
    *, customer_id: str, plan: str, org_id: int, success_url: str, cancel_url: str
) -> str:
    """Start a hosted Checkout for a subscription; return the URL to send the
    admin to.

    Hosted, not an embedded card form: the card details then never touch this
    server, which is the difference between a PCI SAQ-A questionnaire and an
    audit. `client_reference_id` carries the organisation through the redirect
    so the completion webhook needs no session state of ours.
    """
    price = price_id(plan)
    if not price:  # pragma: no cover — routes guard first
        raise RuntimeError(f"no Stripe price configured for plan {plan!r}")
    session = stripe.checkout.Session.create(
        api_key=_key(),
        mode="subscription",
        customer=customer_id,
        client_reference_id=str(org_id),
        line_items=[{"price": price, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        subscription_data={"metadata": {"org_id": str(org_id), "plan": plan}},
    )
    return str(session.url)


def create_portal_session(*, customer_id: str, return_url: str) -> str:
    """Open Stripe's customer portal — where a subscription is changed or
    cancelled and invoices are downloaded. Building any of that ourselves would
    be re-implementing a product Stripe gives away with the payment."""
    session = stripe.billing_portal.Session.create(
        api_key=_key(), customer=customer_id, return_url=return_url
    )
    return str(session.url)


def parse_event(payload: bytes, signature: str | None) -> stripe.Event:
    """Verify a webhook's signature and return the event.

    The signature is the whole of a webhook's trustworthiness: the endpoint is
    public and unauthenticated, so without this any caller could POST
    "subscription active" and grant themselves a plan. `construct_event` also
    enforces a timestamp tolerance, which is what stops a captured event being
    replayed later.

    A malformed body and a bad signature both raise `WebhookError`; the route
    answers 400 to either, telling an unauthenticated caller nothing about which
    of the two it was.
    """
    if not config.STRIPE_WEBHOOK_SECRET:  # pragma: no cover — the route guards first
        raise RuntimeError("STRIPE_WEBHOOK_SECRET is not set")
    try:
        return stripe.Webhook.construct_event(
            payload, signature or "", config.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise WebhookError(str(exc)) from exc


def _as_datetime(epoch: Any) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if isinstance(epoch, int) else None


def subscription_from(obj: Any) -> Subscription | None:
    """Read a Stripe subscription object into the four facts we store.

    Takes the object out of the event rather than re-fetching it: the event is
    signed, and a fetch on a webhook makes delivery depend on Stripe being
    reachable from inside a request we have already accepted.
    """
    if not obj:
        return None
    sub_id = obj.get("id")
    customer = obj.get("customer")
    if not isinstance(sub_id, str) or not isinstance(customer, str):
        logger.warning("stripe subscription payload has no id/customer; ignored")
        return None
    items = (obj.get("items") or {}).get("data") or []
    price = (items[0].get("price") or {}).get("id") if items else None
    # `current_period_end` moved onto the subscription item in recent API
    # versions and stayed on the subscription in older ones; read either.
    period_end = obj.get("current_period_end")
    if period_end is None and items:
        period_end = items[0].get("current_period_end")
    return Subscription(
        id=sub_id,
        customer_id=customer,
        status=str(obj.get("status") or "active"),
        plan=plan_for_price(price if isinstance(price, str) else None),
        current_period_end=_as_datetime(period_end),
    )
