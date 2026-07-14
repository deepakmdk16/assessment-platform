"""Runtime configuration, read from the environment.

All settings have dev-friendly defaults so the service runs with zero config.
`DATABASE_URL` is a full SQLAlchemy URL so swapping SQLite for Postgres later is
only an env change (no code change).
"""

from __future__ import annotations

import os

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
