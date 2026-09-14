"""Rate-limit coverage (gate G8): a route that anyone can reach, that checks a
password, or that sends mail, must consume rate-limit quota.

Rate limiting here is opt-IN per route — `limiter.check(...)` is a line inside the
handler, not a dependency or middleware — so a new route is unlimited by default
and nothing says so. Every hole the 2026-09-14 audit found is a route someone
added without that line: the draft oracle (R2-032), the password re-entry paths
(R2-066), and invite creation, which makes a free account an outbound mail relay
on the product's sending domain (R2-013).

This walks `app.routes` and applies three rules. It is deliberately a *static*
check on the handler's own source: what it proves is that the author thought
about the limit, which is the thing that was actually missing.

Known gaps are listed in `KNOWN_GAPS` with their finding and closing session, and
the list is strict both ways — a gap that gains a limiter fails here until its
line is deleted, and an entry naming a route that no longer exists fails too. New
routes get no grace: add the limit, or add a reason to `NO_LIMIT_NEEDED`.
"""

from __future__ import annotations

import inspect

from fastapi import params
from fastapi.routing import APIRoute

from assessment_platform import auth
from assessment_platform.api import app

# Depending on either of these means FastAPI has already rejected an anonymous
# caller before the handler runs, so the route is not a public surface.
_AUTH_DEPENDENCIES = frozenset({auth.get_current_interviewer, auth.get_current_membership})

# Handler source markers. `verify_password` is the account-takeover guess path;
# the mail markers are how a route turns a request into outbound email.
_PASSWORD_MARKER = "verify_password"
_MAIL_MARKERS = ("send_invite", "send_org_invite", "send_verification", "send_reset", "email_client.")
_LIMITER_MARKER = "limiter.check"


# Routes that must NOT consume quota, each with the reason it is safe. Being on
# this list is a claim about the route's own protection, not an exemption.
NO_LIMIT_NEEDED: dict[str, str] = {
    "GET /health": "liveness probe — a limit here takes the deployment down under its own monitoring",
    "GET /metrics": "scrape endpoint, same reason; exposure is a deployment concern (X09)",
    "GET /public-config": "static, non-secret boot config; no work and no enumeration",
    "GET /logos/{sha256}": "content-addressed: the sha256 IS the capability, and it is served cached",
    "POST /billing/webhook": "Stripe-signature gated; limiting it would drop real payment events",
    "POST /assessments/callback": "shared-secret + HMAC gated, and dropping one loses a grade (R2-001)",
    "POST /auth/refresh": "presents a signed refresh cookie; a limit logs real sessions out",
    "POST /auth/logout": "clears a cookie, touches nothing, and must always succeed",
    "POST /auth/reset-password": "consumes a single-use signed token; not guessable by volume",
    "POST /auth/verify-email": "single-use signed token, as above",
    "POST /auth/confirm-email-change": "single-use signed token, as above",
    "GET /invite/{token}": "pre-start probe on a 32-byte token_urlsafe; brute force is infeasible",
}

# Gaps that exist today, installed with the gate so nothing NEW can be added.
# Delete the entry in the same commit as the fix.
KNOWN_GAPS: dict[str, str] = {
    "GET /invite/{token}/draft": "R2-032 — recipient-enumeration oracle (403 vs 200), closed by S07",
    "POST /auth/change-password": "R2-066 — password re-entry unlimited, closed by S06",
    "DELETE /auth/me": "R2-066 — password re-entry unlimited, closed by S06",
    "POST /orgs/current/invites": "R2-013 — unmetered outbound mail, closed by S06",
    "POST /questions/{question_id}/invites": "R2-013 — unmetered outbound mail, closed by S07",
    "POST /assessments/{assessment_id}/invites": "R2-013 — unmetered outbound mail, closed by S07",
    "POST /variant-sets/{set_id}/invites": "R2-013 — unmetered outbound mail, closed by S07",
}


def _routes() -> dict[str, APIRoute]:
    out: dict[str, APIRoute] = {}
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods:
                if method != "HEAD":
                    out[f"{method} {route.path}"] = route
    return out


def _is_authenticated(route: APIRoute) -> bool:
    signature = inspect.signature(route.endpoint)
    dependencies = {
        p.default.dependency
        for p in signature.parameters.values()
        if isinstance(p.default, params.Depends) and p.default.dependency is not None
    }
    return bool(dependencies & _AUTH_DEPENDENCIES)


def _why_it_needs_a_limit(route: APIRoute) -> str | None:
    """The reason this route must consume quota, or None if it need not."""
    source = inspect.getsource(route.endpoint)
    if not _is_authenticated(route):
        return "it is reachable without authentication"
    if _PASSWORD_MARKER in source:
        return "it verifies a password, so it is an account-takeover guess path"
    if any(marker in source for marker in _MAIL_MARKERS):
        return "it sends email, so it is an outbound mail relay"
    return None


def test_every_exposed_route_consumes_rate_limit_quota() -> None:
    routes = _routes()
    unlimited: list[str] = []
    for key, route in sorted(routes.items()):
        if key in NO_LIMIT_NEEDED or key in KNOWN_GAPS:
            continue
        reason = _why_it_needs_a_limit(route)
        if reason and _LIMITER_MARKER not in inspect.getsource(route.endpoint):
            unlimited.append(f"  {key} — {reason}")

    assert not unlimited, (
        "these routes need a rate limit and do not call `limiter.check`:\n"
        + "\n".join(unlimited)
        + "\n\nAdd the limit, or — if the route genuinely must not consume quota — add it to "
        "NO_LIMIT_NEEDED in this file with the reason why."
    )


def test_known_gaps_are_still_gaps() -> None:
    """A fixed gap must leave this list, or the list stops meaning anything."""
    fixed = [
        f"  {key} ({note})"
        for key, note in sorted(KNOWN_GAPS.items())
        if (route := _routes().get(key)) is not None
        and _LIMITER_MARKER in inspect.getsource(route.endpoint)
    ]
    assert not fixed, (
        "these routes now call `limiter.check` but are still listed as known gaps:\n"
        + "\n".join(fixed)
        + "\n\nDelete them from KNOWN_GAPS — the fix landed."
    )


def test_the_lists_name_routes_that_exist() -> None:
    """A renamed or deleted route must not leave a silent exemption behind."""
    routes = _routes()
    stale = sorted((set(NO_LIMIT_NEEDED) | set(KNOWN_GAPS)) - set(routes))
    assert not stale, (
        "these entries name routes that no longer exist:\n  "
        + "\n  ".join(stale)
        + "\n\nDelete them, or correct the path — an exemption for a route nobody can "
        "call is an exemption waiting to cover the wrong thing."
    )
