# CLAUDE.md — Assessment Platform

Project-specific guidance. Merge with the global `~/.claude/CLAUDE.md`; where
this file is silent, the global rules apply. See [CONVENTIONS.md](CONVENTIONS.md)
for the concrete, checkable design rules.

## What this is

The **stateful system of record** for coding assessments — the companion to the
stateless **Assessment Agent** (separate repo, `../AssesmentAgent`). Interviewers
author questions here; candidates submit via a shareable invite link; the
platform triggers the agent to grade, receives the result on a callback, and
**stores** it. It never computes or overrides a verdict — the agent owns the
deterministic grade.

- **Backend:** `assessment_platform/` — FastAPI + SQLModel (SQLite dev,
  Postgres-ready via `DATABASE_URL`).
- **Frontend:** `web/` — React + Vite + TypeScript (interviewer + candidate UIs).
  Styling is **token-driven**: all appearance lives in `web/src/styles/` (a restyle
  edits CSS, never `.tsx`). No inline `style=` / hex in components — enforced by
  `npm run lint`. See CONVENTIONS.md → "Styling".

## Stack & how to run

- Backend: Python ≥ 3.10, `uv`. Run the API: `uv run platform-api` (`:9000`).
- Tests: `uv run pytest`. Lint/types: `uv run ruff check .`, `uv run mypy`.
- Frontend: `cd web && npm install && npm run dev` (`VITE_API_BASE_URL` →
  `http://127.0.0.1:9000`). Checks: `npm run build`, `npm run typecheck`,
  `npm run lint`, `npm run test`.
- The agent must be running (`../AssesmentAgent`: `uv run assess-api`, `:8000`)
  for submissions to actually grade end-to-end.

## Architecture (where things live)

- `models.py` — SQLModel tables (the durable state).
- `schemas.py` — API request/response models. **`InvitePublicOut` is the
  candidate-facing view and must never expose `test_cases`/`expected`.**
- `api.py` — FastAPI routes.
- `auth.py` — interviewer auth: bcrypt hashing + stateless JWT bearer.
- `agent_client.py` — the outbound call that triggers the agent (the mock
  boundary in tests).
- `config.py` — env-driven config. `db.py` — engine + session.

## The agent contract

- **Trigger:** the platform POSTs the full question **inline** + code to
  `{AGENT_BASE_URL}/assessments`, with `callback_url` pointing back to
  `/assessments/callback`. Auth: `X-Assess-Token: $ASSESS_API_TOKEN` (sent when
  set).
- **Callback:** the agent POSTs the full result to `/assessments/callback`,
  authenticated with `X-Assess-Token: $CALLBACK_TOKEN` (required when set). The
  payload is stored verbatim in `AssessmentResult.full_result`.

## Key principles (do not violate)

- **The platform stores; it never grades.** `AssessmentResult` is a faithful
  record of the agent's callback. No verdict/score logic lives here.
- **Never leak the answer key.** The candidate view (`GET /invite/{token}`)
  returns only prompt/constraints/public example — never test cases or expected
  outputs. There is a test that asserts their absence; keep it.
- **Auth enforced when configured.** Bearer/shared-secret checks activate only
  when their env var is set (dev/tests run without). Interviewer routes are
  bearer-guarded **and owner-scoped**; candidate routes are public but
  token-gated; the agent callback is shared-secret-guarded.
- **Secrets from env only** — `JWT_SECRET`, `ASSESS_API_TOKEN`, `CALLBACK_TOKEN`,
  SMTP creds. Never commit them.

## Git hygiene (branch flow)

**Always start new work from an up-to-date `main`.** Before cutting a branch:

```bash
git checkout main
git pull            # get the latest merged main (e.g. the PR just merged)
git checkout -b <slice-name>
```

Never branch off a stale local `main` or off another feature branch. Each unit
of work is its own branch → push → PR → the user merges to `main`. Do not merge
or push to `main` directly, and don't push a branch until the pre-push
checkpoints below pass. After the user merges, pull `main` again before the next
branch.

## Pre-push checkpoints (in addition to the global §6 gates)

Gates 1–2 are the deterministic `scripts/checkpoints.sh`, wired as the git
`pre-push` hook (run `bash scripts/install-hooks.sh` once per clone) — a failure
aborts the push; E2E stays opt-in via `RUN_E2E=1` (CI already gates it). Gates
3–5 are judgment; the `ship` skill walks them.

1. `uv run pytest` passes; `uv run ruff check .` and `uv run mypy` clean.
2. If `web/` changed: `npm run build`, `typecheck`, `lint`, `test` all clean.
3. `/code-review` (or a self-review of the diff) has been run.
4. New endpoints have tests that run **offline** (mock the agent call; no network,
   no real LLM).
5. **[ROADMAP.md](ROADMAP.md) is updated** to reflect what this slice shipped —
   mark the finished open item done (or narrow it to what remains) and record the
   new slice. The roadmap must never lag the code.

## Status & roadmap

Current status, the slice-by-slice changelog, and the open-items backlog live in
[ROADMAP.md](ROADMAP.md) — moved out of this file so CLAUDE.md stays lean and
loads cheaply every session. **Pre-push checkpoint #5 applies to ROADMAP.md:**
update it in the same commit that shifts the work; trim merged slices to one line
(git history holds the detail).

## Companion repo

The **Assessment Agent** (`../AssesmentAgent`) is the stateless grader. It owns
code execution + the deterministic verdict + the Sonnet quality summary. Keep the
boundary: the platform never absorbs grading logic, and the agent never absorbs
question storage.
