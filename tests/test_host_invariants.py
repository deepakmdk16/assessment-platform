"""One spelling of the loopback host, everywhere.

`localhost` and `127.0.0.1` are different *sites* to a browser. Mixing them is
not cosmetic: the SPA goes cross-site with the API, the httpOnly SameSite=lax
refresh cookie is then neither stored nor sent, and the session stops surviving a
reload while everything still looks signed in. Meanwhile any link the API mints
at a host nothing is bound to is simply dead.

The system cannot standardise on `localhost` either — the agent's SSRF guard
rejects a callback_url whose host is exactly that string — so `127.0.0.1` is the
one spelling, and these tests keep the defaults on it.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from fastapi import Response

from assessment_platform import auth, config


def test_frontend_and_platform_share_one_host() -> None:
    """Same host => same site => the refresh cookie is actually sent on the
    SPA's API calls. A future default that split these would break sign-in
    persistence silently, which is exactly the failure this pins."""
    frontend = urlparse(config.FRONTEND_BASE_URL).hostname
    platform = urlparse(config.PLATFORM_BASE_URL).hostname
    assert frontend == platform, (
        f"FRONTEND_BASE_URL host {frontend!r} != PLATFORM_BASE_URL host {platform!r}; "
        "the SPA would be cross-site with its own API and the refresh cookie would "
        "be dropped."
    )


def test_defaults_use_the_ip_literal_not_localhost() -> None:
    """`localhost` is unusable as the canonical spelling: the agent rejects it in
    callback_url, so PLATFORM_BASE_URL on localhost would 400 every grade
    trigger. Pin the shipped defaults to the spelling that works end to end."""
    for name in ("FRONTEND_BASE_URL", "PLATFORM_BASE_URL", "AGENT_BASE_URL"):
        if os.getenv(name):
            continue  # a deliberate deployment override, not the shipped default
        assert urlparse(getattr(config, name)).hostname == "127.0.0.1", name


def test_cors_defaults_to_exactly_one_origin() -> None:
    """Widening CORS to both spellings is what turns this bug from a loud CORS
    error into a silent dead session, so the default must stay single-origin.
    Skipped when CORS_ORIGINS is set, which is a deliberate override."""
    if os.getenv("CORS_ORIGINS"):
        return
    assert config.CORS_ORIGINS == [config.FRONTEND_BASE_URL]


def test_refresh_cookie_is_host_only_and_lax() -> None:
    """`Domain=` would make the cookie cross-host and undo the same-site
    reasoning above; Path and HttpOnly are what keep it off the page's JS."""
    response = Response()
    auth.set_refresh_cookie(response, "a.b.c")
    header = response.headers["set-cookie"]

    assert header.startswith(f"{auth.REFRESH_COOKIE}=")
    assert f"Path={auth.REFRESH_COOKIE_PATH}" in header
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Domain=" not in header
