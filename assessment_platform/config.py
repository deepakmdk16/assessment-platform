"""Runtime configuration, read from the environment.

All settings have dev-friendly defaults so the service runs with zero config.
`DATABASE_URL` is a full SQLAlchemy URL so swapping SQLite for Postgres later is
only an env change (no code change).

A `.env` file at the repo root is loaded if present, so secrets (SMTP password,
JWT_SECRET, agent tokens) live in one gitignored file rather than your shell
history. Real environment variables take precedence, so a deployment that sets
them properly is unaffected. See `.env.example`; never commit `.env` itself.
"""

from __future__ import annotations

import logging
import os
import secrets
from typing import Literal, cast

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# override=False: anything already exported in the environment wins over the file.
load_dotenv(override=False)

# SQLAlchemy URL. Default: local SQLite file. Set to a postgresql+psycopg URL in prod.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./platform.db")

# Test mode, set by the harness (pytest conftest + the Playwright webServer). When
# on, integrations that would otherwise hit the network are forced OFF, so a
# developer's real `.env` (loaded above) can't make the suite send live email.
TESTING = os.getenv("PLATFORM_TESTING", "").lower() in {"1", "true"}

# Whether to write candidate PII (recipient emails, invite links) to the logs
# verbatim. OFF by default so production log aggregation never ingests it; turn ON
# locally (LOG_PII=true) to get the copy-pasteable invite link when SMTP is unset.
LOG_PII = os.getenv("LOG_PII", "").lower() in {"1", "true"}

# Root log level for the server process (see api.configure_logging). Uvicorn only
# configures its own loggers, so this is what makes the package's INFO
# breadcrumbs (callback correlation, the stale-running reaper) actually print.
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Hard ceiling on any request body, enforced from Content-Length before the JSON
# is parsed. The per-field caps in schemas.py bound what we STORE; this bounds
# what we are willing to READ, so an unauthenticated candidate route can't make
# the server buffer a multi-megabyte blob just to 422 it. Generous enough for a
# variant set of eight hand-authored questions with many test cases.
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", str(4 * 1024 * 1024)))

# Create tables on startup via SQLModel.metadata.create_all. OFF by default:
# production runs the Alembic migrations, and an unconditional create_all silently
# masks a missing migration (a model change works in dev without one, then a fresh
# prod DB gets create_all's schema instead of Alembic's). Dev and E2E opt in.
AUTO_CREATE_TABLES = os.getenv("AUTO_CREATE_TABLES", "false").lower() == "true"

# Base URL of the (stateless) Assessment Agent we POST jobs to.
AGENT_BASE_URL = os.getenv("AGENT_BASE_URL", "http://127.0.0.1:8000")

# This platform's own public base URL, used to build the callback_url handed to
# the agent so it can POST the result back to us.
PLATFORM_BASE_URL = os.getenv("PLATFORM_BASE_URL", "http://127.0.0.1:9000")

# Timeout (seconds) for the outbound call that triggers an agent job. The agent
# returns 202 immediately, so this only needs to cover the accept, not the grade.
AGENT_TIMEOUT_S = float(os.getenv("AGENT_TIMEOUT_S", "10.0"))

# Timeout (seconds) for the SYNCHRONOUS question-draft call. Unlike triggering a
# job, drafting runs an LLM + executes the reference inline before responding, so
# it needs a much longer budget than AGENT_TIMEOUT_S (a complex draft takes tens
# of seconds). The agent also re-drafts internally when the first attempt is
# unusable (ASSESS_DRAFT_ATTEMPTS, default 2), so this must cover *all* of its
# attempts — otherwise we'd time out on a draft that was about to succeed.
AGENT_DRAFT_TIMEOUT_S = float(os.getenv("AGENT_DRAFT_TIMEOUT_S", "240.0"))

# Timeout (seconds) for the SYNCHRONOUS candidate run calls (`/run`, `/run/tests`).
# These compile and execute code inline before responding, so they need more than
# the 10s accept budget — but far less than a draft (no LLM). The agent bounds each
# execution with its own per-case time limit; this is the outer transport budget.
AGENT_RUN_TIMEOUT_S = float(os.getenv("AGENT_RUN_TIMEOUT_S", "60.0"))

# Shared-secret auth, matching the agent's contract exactly. Both sides use the
# `X-Assess-Token` header; enforcement is per-token and only active when the
# relevant env var is set (unset => no auth, for dev/tests).
#   CALLBACK_TOKEN   — secret the AGENT sends to our POST /assessments/callback;
#                      we REQUIRE it on inbound callbacks when set.
#   ASSESS_API_TOKEN — secret WE send when triggering the agent's POST /assessments.
AUTH_HEADER = "X-Assess-Token"
CALLBACK_TOKEN = os.getenv("CALLBACK_TOKEN") or None
ASSESS_API_TOKEN = os.getenv("ASSESS_API_TOKEN") or None

# HMAC body-signing secrets (defense in depth over the bearer tokens above, which
# travel in the clear). Never transmitted; enforced only when set. Must match the
# agent's ASSESS_SIGNING_SECRET / CALLBACK_SIGNING_SECRET. See signing.py.
#   ASSESS_SIGNING_SECRET   — WE sign outbound requests to the agent with it.
#   CALLBACK_SIGNING_SECRET — the agent signs its callback; we VERIFY with it.
ASSESS_SIGNING_SECRET = os.getenv("ASSESS_SIGNING_SECRET") or None
CALLBACK_SIGNING_SECRET = os.getenv("CALLBACK_SIGNING_SECRET") or None

# Interviewer auth (JWT bearer). JWT_SECRET is REQUIRED in production; if unset we
# fall back to an ephemeral per-process secret so dev/tests work out of the box —
# tokens then don't survive a restart, hence the warning.
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = secrets.token_urlsafe(32)
    logger.warning(
        "JWT_SECRET is not set; using an ephemeral dev secret (tokens will not "
        "survive a restart). Set JWT_SECRET in production."
    )
JWT_ALGORITHM = "HS256"
# Access-token lifetime. Short on purpose: it is the token an XSS could lift from
# the page, so it must be worthless within minutes. Sessions outlive it through
# the refresh cookie below, which script on the page can't read.
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "15"))
# Refresh-token lifetime (an httpOnly cookie scoped to /auth): how long a browser
# stays signed in without re-entering the password. Sliding — every refresh
# re-issues it.
REFRESH_EXPIRE_DAYS = int(os.getenv("REFRESH_EXPIRE_DAYS", "30"))
# Cookie attributes. Secure defaults to ON whenever the API is served over https
# (from PLATFORM_BASE_URL) and off for plain-http dev — a browser drops a Secure
# cookie set over http, which would make sign-in silently not stick. SameSite
# `lax` covers the SPA and the API on one site (127.0.0.1:5173 → :9000, or
# app./api. subdomains of one domain); set `none` (Secure required) only when
# they live on unrelated domains.
COOKIE_SECURE = (
    os.getenv("COOKIE_SECURE", str(PLATFORM_BASE_URL.startswith("https://"))).lower() == "true"
)
_samesite = os.getenv("COOKIE_SAMESITE", "lax").lower()
if _samesite not in ("lax", "strict", "none"):
    raise RuntimeError(f"COOKIE_SAMESITE must be lax, strict or none (got {_samesite!r})")
COOKIE_SAMESITE = cast(Literal["lax", "strict", "none"], _samesite)
# Check every new password against Have I Been Pwned (k-anonymity range API —
# only a 5-char hash prefix leaves the machine; fails open when the service is
# unreachable). Off under test so the suite never touches the network.
PASSWORD_BREACH_CHECK = (
    False if TESTING else os.getenv("PASSWORD_BREACH_CHECK", "true").lower() == "true"
)

# Base URL of the interviewer/candidate frontend, used to build candidate invite
# links (f"{FRONTEND_BASE_URL}/t/{token}").
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://127.0.0.1:5173")

# Browser origins allowed to call the API (CORS). The SPA is a separate origin,
# so without this every browser request is blocked by the preflight. Comma-
# separated; defaults to the dev frontend origin.
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("CORS_ORIGINS", FRONTEND_BASE_URL).split(",")
    if o.strip()
]

# Interviewer sign-up gate. When set, POST /auth/register requires a matching
# `registration_code` in the body (403 otherwise). Unset => open sign-up (dev).
REGISTRATION_CODE = os.getenv("REGISTRATION_CODE") or None

# Whether to believe X-Forwarded-For when identifying the caller for rate limits.
# Behind a reverse proxy or load balancer every request arrives from the PROXY's
# address, so all callers collapse into one shared bucket and the first few
# exhaust the limit for everyone. Reading the forwarded header fixes that — but it
# is client-supplied and trivially forged, so it is only trustworthy when a proxy
# you control is guaranteed to rewrite it. OFF by default: correct for the direct
# uvicorn dev setup, and safe (not permissive) if a deploy forgets to set it.
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"

# SMTP for emailing invite links. When SMTP_HOST is unset the mailer logs the
# link instead of sending (dev/tests), so nothing here is required to run. Under
# test we hard-null it so a developer's .env can't make invite tests hit Gmail.
SMTP_HOST = None if TESTING else (os.getenv("SMTP_HOST") or None)
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER") or None
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or None
SMTP_FROM = os.getenv("SMTP_FROM", "no-reply@assessment.local")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() != "false"

# The .env.example placeholder. `.local` is a reserved mDNS TLD with no MX, so a
# send with this From is accepted locally and then bounced by every real
# receiver. `missing_smtp_vars` counts it as unset rather than as a configured
# sender — otherwise a presence-only check waves through a server whose every
# mail bounces, which is exactly the "no original email exists" failure.
SMTP_FROM_PLACEHOLDER = "no-reply@assessment.local"

# Per socket operation, not per send: smtplib hands this to each connect, TLS
# handshake, login and send in turn.
SMTP_TIMEOUT_S = float(os.getenv("SMTP_TIMEOUT_S", "10"))
# Ceiling on one whole multi-recipient delivery. Without it the worst case for a
# ten-recipient invite is SMTP_TIMEOUT_S multiplied by every operation in the
# loop, all of it inline on someone's HTTP request.
SMTP_DEADLINE_S = float(os.getenv("SMTP_DEADLINE_S", "30"))

# The single, deliberate escape hatch for the startup mail check. OFF by default:
# a deploy that forgets SMTP must fail on the box where .env is still editable,
# not silently swallow every invite, confirmation and password reset. Turn it on
# only for offline local dev, where the mailer logs the link instead of sending
# it (pair with LOG_PII=true to get the link verbatim).
ALLOW_UNCONFIGURED_EMAIL = os.getenv("ALLOW_UNCONFIGURED_EMAIL", "").lower() in {"1", "true"}


def missing_smtp_vars() -> list[str]:
    """Names of the mail settings that are unset or still on the placeholder.

    Reads the environment directly rather than the module constants above,
    because SMTP_HOST is hard-nulled under TESTING — using the constant would
    report it missing in every test process.
    """
    required = {
        "SMTP_HOST": os.getenv("SMTP_HOST"),
        "SMTP_PORT": os.getenv("SMTP_PORT", "587"),
        "SMTP_USER": SMTP_USER,
        "SMTP_PASSWORD": SMTP_PASSWORD,
        "SMTP_FROM": None if SMTP_FROM == SMTP_FROM_PLACEHOLDER else SMTP_FROM,
    }
    return [name for name, value in required.items() if not value]


# Rate limits (requests per window, seconds). Guards brute-force on login and
# spam on the public candidate submit (which triggers paid agent jobs).
# Set the *_MAX to 0 to disable a given limiter.
# Backend (SEC4): "memory" counts per process — fine for a single-process deploy,
# but N workers silently multiply every limit by N. Set "db" whenever the API
# runs with more than one process/instance: counters live in the shared database,
# so the limit holds fleet-wide. Deploy-checklist item alongside
# TRUST_PROXY_HEADERS (both make the limiter mean what it says in prod).
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "memory")
RATE_LIMIT_WINDOW_S = int(os.getenv("RATE_LIMIT_WINDOW_S", "60"))
LOGIN_RATE_LIMIT_MAX = int(os.getenv("LOGIN_RATE_LIMIT_MAX", "10"))
SUBMIT_RATE_LIMIT_MAX = int(os.getenv("SUBMIT_RATE_LIMIT_MAX", "20"))
# Sign-up. Login was capped but register wasn't, and sign-up is OPEN whenever
# REGISTRATION_CODE is unset (the default) — so anyone could mint accounts in bulk,
# and every account reaches the LLM-backed draft endpoint below.
REGISTER_RATE_LIMIT_MAX = int(os.getenv("REGISTER_RATE_LIMIT_MAX", "5"))
# Question drafting: the ONLY endpoint that spends real LLM money, and each call
# can hold a worker thread for AGENT_DRAFT_TIMEOUT_S (default 240s). Uncapped it is
# both a billing hole and a way to exhaust the thread pool. Generous enough for
# real authoring (a draft takes tens of seconds), low enough to stop a loop.
DRAFT_RATE_LIMIT_MAX = int(os.getenv("DRAFT_RATE_LIMIT_MAX", "10"))

# Candidate draft autosaves (CX2). Debounced client-side, but a fast typist with
# short pauses can legitimately save every few seconds — generous like the run
# bucket, cheap single-row upserts.
DRAFT_SAVE_RATE_LIMIT_MAX = int(os.getenv("DRAFT_SAVE_RATE_LIMIT_MAX", "60"))
# Candidate Run / Run-against-tests. Higher than submit (a candidate iterates
# many times in a sitting) but still capped: these execute untrusted code on the
# agent for free, and run-tests is a pass/fail oracle — unlimited, it would let
# someone reverse-engineer the test suite one guess at a time.
RUN_RATE_LIMIT_MAX = int(os.getenv("RUN_RATE_LIMIT_MAX", "60"))

# Grading durability. A submission is "pending" from its insert until the agent
# 202s the trigger, then "running" until the agent's callback lands. A background
# reaper (one task per worker process, see `api._reaper_loop`) re-triggers rows
# that sit too long in either state — a trigger that failed because the agent was
# down at submit, a job the agent lost to a crash or deploy, a callback that never
# arrived — and once MAX_TRIGGER_ATTEMPTS triggers have been made gives up with an
# ERROR log, leaving the row in "error" for the interviewer's manual retry.
#
# How often the reaper runs. <= 0 disables the background task entirely; forced
# off under test, where the suite drives `api._reap_tick` directly.
REAP_INTERVAL_S = 0 if TESTING else int(os.getenv("REAP_INTERVAL_S", "60"))
# A "running" row (accepted, no callback yet) older than this is re-triggered.
# Generous so a merely-slow grade isn't re-run mid-job; <= 0 leaves running rows
# alone.
REAP_RUNNING_AFTER_S = int(os.getenv("REAP_RUNNING_AFTER_S", "900"))
# A "pending" row (trigger never accepted, or re-queued by the agent's shutdown
# callback) older than this is re-triggered. Must exceed the longest possible
# in-flight trigger so a second worker's reaper can't double-trigger a row whose
# first trigger is still on the wire: AGENT_TRIGGER_TRANSPORT_ATTEMPTS (3) × up to
# ~3 × AGENT_TIMEOUT_S (httpx applies the timeout per phase — connect, write,
# read) + the linear backoff between attempts (1 s + 2 s) ≈ 93 s.
TRIGGER_RETRY_AFTER_S = int(os.getenv("TRIGGER_RETRY_AFTER_S", "120"))
# Total agent triggers per submission (the first one included) before the reaper
# gives up. 3 = the original plus two automatic retries, ~4 minutes of agent
# outage tolerated before a human is needed.
MAX_TRIGGER_ATTEMPTS = int(os.getenv("MAX_TRIGGER_ATTEMPTS", "3"))

# Grace window past a timed assessment's deadline within which a submit is still
# accepted. Covers clock skew, network latency, and the round-trip of the client's
# auto-submit fired at 0:00 — without it, an on-time auto-submit could just miss.
# A submit later than deadline + this is refused as "time's up".
SUBMIT_GRACE_SECONDS = int(os.getenv("SUBMIT_GRACE_SECONDS", "15"))

# Languages offered to candidates (UI-facing; the agent enforces what it supports).
SUPPORTED_LANGUAGES = [
    "python",
    "javascript",
    "java",
    "cpp",
    "c",
    "go",
    "ruby",
    "rust",
]

# --------------------------------------------------------------------------- #
# Billing (X02)                                                                 #
# --------------------------------------------------------------------------- #

# Whether plan limits actually refuse work. OFF has one honest use: metering a
# deployment for a month to see real usage before switching the charging on —
# `billing.record` runs either way, so the counters and the per-tenant cost
# rollup are collected whatever this says. Forced off under test, like
# PASSWORD_BREACH_CHECK: the suite's fixtures create far more than a free plan's
# ten sittings, and the tests that cover enforcement turn it on explicitly.
BILLING_ENFORCED = (
    False if TESTING else os.getenv("BILLING_ENFORCED", "true").lower() != "false"
)

# Stripe. Unset (the default) means the payment routes report themselves
# unavailable rather than half-working: an organisation stays on the free plan,
# every limit still applies, and nothing pretends a card was taken. The webhook
# secret is what makes an inbound webhook trustworthy — without it any caller
# could POST a "subscription active" event — so the webhook route refuses to
# process anything while it is unset.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY") or None
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET") or None

# Charge VAT / sales tax on subscriptions via Stripe Tax (X17). ON by default:
# selling into the EU/UK without charging and remitting it is a liability that
# grows silently with revenue, and retro-fitting it means reissuing invoices.
# Requires Stripe Tax to be ACTIVATED on the Stripe account and a registration
# in each jurisdiction where a threshold is crossed — without that, checkout
# fails at session creation, which is the loud failure rather than the silent
# one. Turn off only for a deployment that genuinely sells in one untaxed place.
STRIPE_AUTOMATIC_TAX = os.getenv("STRIPE_AUTOMATIC_TAX", "true").lower() != "false"

# The Stripe Price id backing each paid plan key in `billing.PLANS`. Prices live
# in Stripe (that is where they are versioned and where a currency lives); this
# is only the mapping from our plan name to theirs.
STRIPE_PRICE_IDS = {
    "starter": os.getenv("STRIPE_PRICE_STARTER") or None,
    "growth": os.getenv("STRIPE_PRICE_GROWTH") or None,
}


def billing_enabled() -> bool:
    """Whether checkout/portal can actually be reached.

    A function, not a constant, so a test (or a deploy that sets the key after
    import) sees the current value rather than one frozen at import time.
    """
    return bool(STRIPE_SECRET_KEY)
