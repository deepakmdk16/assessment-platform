# Production image for the assessment platform's API — the stateful system of
# record. Unlike the agent (../AssesmentAgent/Dockerfile) this container runs no
# untrusted code, so it needs no sandbox, no toolchains and no privileges: it is
# an ordinary non-root Python service.
#
# RUN (see docker-compose.yml for the wired-up version):
#
#   docker build -t assessment-platform .
#   docker run --rm -p 9000:9000 --env-file .env assessment-platform
#
# The entrypoint runs `alembic upgrade head` before serving. AUTO_CREATE_TABLES
# is deliberately left off (db.py): create_all only ever helps a FRESH database
# and silently skips later migrations on an existing one, so production evolves
# the schema through Alembic and a missing migration surfaces as an error rather
# than a 500 on the first query that reads a new column.

# 3.12 matches the version CI tests against (.github/workflows/checks.yml), so
# the image runs the interpreter the test suite actually passed on.
FROM python:3.12-slim

# uv for reproducible, frozen installs — same pin as the agent image.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Resolve dependencies first so a source-only change doesn't re-install them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY assessment_platform ./assessment_platform
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev
# After the install: the entrypoint is the one copied file it does not read, so
# copying it earlier would rebuild the project layer on every edit to the script.
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Put the project venv on PATH and call `alembic` / `platform-api` directly
# rather than through `uv run`: the dependencies are already installed and
# frozen, and this keeps the runtime free of a resolver step (and of uv's need
# for a writable cache) under the non-root user below.
ENV PATH="/app/.venv/bin:$PATH"

# Bind on all interfaces. The app's default is 127.0.0.1 — right for a bare
# `uv run platform-api` on a dev box, but inside a container that is unreachable
# through `-p 9000:9000`.
ENV HOST=0.0.0.0 \
    PORT=9000 \
    PYTHONUNBUFFERED=1

# Nothing here writes to the image; the database lives in Postgres and the only
# state is the migration Alembic applies at boot.
# No chown: `chown -R /app` would copy the whole virtualenv into a second layer
# (measured: 103 MB of pure duplication, pushed and pulled on every deploy) to
# buy nothing — this user only ever reads /app, which 0755 already allows.
RUN useradd --create-home --uid 10001 platform
USER platform

EXPOSE 9000

# /health checks the database round trip (api.py), so a container that cannot
# reach Postgres reports unhealthy instead of accepting traffic it will 500 on.
# Uses the interpreter that is already here rather than adding curl to the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=4)"]

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["platform-api"]
