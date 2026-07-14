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
