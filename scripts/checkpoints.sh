#!/usr/bin/env bash
# Deterministic pre-push gate for the Assessment Platform.
# A non-zero exit ABORTS the push (wired as the git pre-push hook).
# Bypass is deliberate and discouraged: `git push --no-verify`.
#
# This is the scriptable half of the old "ship" routine — the objective gate.
# The judgment half (/code-review, roadmap update) stays in the `ship` skill.
#
# Playwright E2E is NOT run here by default: it is slow, needs browsers + three
# servers, and is already gated on every PR by .github/workflows/e2e.yml. Run it
# locally with RUN_E2E=1 when a change touches the candidate/invite flow.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "==> pytest";           uv run pytest -q
echo "==> ruff check";       uv run ruff check .
echo "==> mypy";             uv run mypy

echo "==> web: typecheck / lint / unit / build"
( cd web && npm run typecheck && npm run lint && npm run test && npm run build )

if [ "${RUN_E2E:-0}" = "1" ]; then
  echo "==> web: e2e (Playwright)"
  ( cd web && npm run test:e2e )
fi

echo "✅ checkpoints passed"
