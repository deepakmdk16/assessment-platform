"""Runtime configuration, read from the environment.

All settings have dev-friendly defaults so the service runs with zero config.
`DATABASE_URL` is a full SQLAlchemy URL so swapping SQLite for Postgres later is
only an env change (no code change).
"""

from __future__ import annotations

import logging
import os
import secrets

logger = logging.getLogger(__name__)

# SQLAlchemy URL. Default: local SQLite file. Set to a postgresql+psycopg URL in prod.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./platform.db")

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
JWT_EXPIRE_MIN = int(os.getenv("JWT_EXPIRE_MIN", "720"))

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

# SMTP for emailing invite links. When SMTP_HOST is unset the mailer logs the
# link instead of sending (dev/tests), so nothing here is required to run.
SMTP_HOST = os.getenv("SMTP_HOST") or None
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER") or None
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD") or None
SMTP_FROM = os.getenv("SMTP_FROM", "no-reply@assessment.local")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() != "false"

# In-process rate limits (requests per window, seconds). Guards brute-force on
# login and spam on the public candidate submit (which triggers paid agent jobs).
# Set the *_MAX to 0 to disable a given limiter.
RATE_LIMIT_WINDOW_S = int(os.getenv("RATE_LIMIT_WINDOW_S", "60"))
LOGIN_RATE_LIMIT_MAX = int(os.getenv("LOGIN_RATE_LIMIT_MAX", "10"))
SUBMIT_RATE_LIMIT_MAX = int(os.getenv("SUBMIT_RATE_LIMIT_MAX", "20"))
# Candidate Run / Run-against-tests. Higher than submit (a candidate iterates
# many times in a sitting) but still capped: these execute untrusted code on the
# agent for free, and run-tests is a pass/fail oracle — unlimited, it would let
# someone reverse-engineer the test suite one guess at a time.
RUN_RATE_LIMIT_MAX = int(os.getenv("RUN_RATE_LIMIT_MAX", "60"))

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
