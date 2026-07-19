#!/usr/bin/env bash
# One-command local dev server: bring the dev DB up to date, then serve.
#
# Why this exists: AUTO_CREATE_TABLES=true only helps a FRESH database — it
# never ALTERs an existing one, so a dev.db created before a later migration
# silently misses that migration's new columns, and the first query reading one
# 500s ("no such column: ..."). Running `alembic upgrade head` first evolves the
# existing dev.db instead of leaving it stranded on an old schema.
#
# DATABASE_URL is pinned to ./dev.db unless you already exported one, so the app
# and Alembic always target the same file (the raw `uv run platform-api` uses the
# config default, ./platform.db — this keeps the two from drifting apart).
set -euo pipefail
cd "$(dirname "$0")/.."

export DATABASE_URL="${DATABASE_URL:-sqlite:///./dev.db}"

uv run alembic upgrade head
exec uv run platform-api
