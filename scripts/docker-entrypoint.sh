#!/usr/bin/env bash
# Container entrypoint: bring the schema up to date, then exec the server.
#
# Why migrate here rather than in a separate step someone has to remember:
# AUTO_CREATE_TABLES is off in production (see db.py), so a container started
# against a database one migration behind serves 500s on the first query that
# reads a new column. Running `alembic upgrade head` before the port is bound
# makes that a boot failure on the box instead of an error in front of a
# candidate. Alembic is a no-op when the database is already at head, so this is
# safe on every restart.
#
# Concurrency: with more than one replica, run this as a one-shot release task
# and start the replicas with `--no-migrate` (below) — two containers racing
# `upgrade head` can deadlock on the same DDL.
set -euo pipefail

if [[ "${1:-}" == "--no-migrate" ]]; then
    shift
else
    echo "==> alembic upgrade head"
    alembic upgrade head
fi

exec "$@"
