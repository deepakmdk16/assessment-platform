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

## Pre-push checkpoints (in addition to the global §6 gates)

1. `uv run pytest` passes; `uv run ruff check .` and `uv run mypy` clean.
2. If `web/` changed: `npm run build`, `typecheck`, `lint`, `test` all clean.
3. `/code-review` (or a self-review of the diff) has been run.
4. New endpoints have tests that run **offline** (mock the agent call; no network,
   no real LLM).

## Status & next steps

**Current status (Slice 1 done + web UI, 2026-07-14).** Backend: interviewer
auth (bcrypt + stateless JWT), question ownership, invites (shareable link
tokens), the candidate-by-token flow (`GET /invite/{token}` answer-key-stripped
+ `POST /invite/{token}/submit`), owner-scoped dashboard reads, agent-callback
storage, shared-secret auth on the agent↔platform calls, and uniform
`created_at`/`updated_at` on every table. Frontend (`web/`, React+Vite+TS):
login/register, dashboard, add-question, question detail (invites + results),
and the candidate flow (Monaco editor). **Verified end-to-end** with a live
agent+platform integration run (register→invite→candidate submit→grade→callback→
dashboard PASS) and the full offline suite (`pytest` green, ruff+mypy clean;
`web` build/typecheck/lint/test clean).

**Open items (pick up here):**
1. **Slice 3 — invites + UX.** Actually *email* the invite link to recipients
   (they're stored but not sent). Polish the dashboard and the multi-step
   add-question form.
2. **Auth the internal `/submissions*` routes** — currently un-authed; put them
   behind interviewer auth.
3. **Browser E2E for `web/`** — today the frontend is contract-aligned +
   unit-tested (vitest), not click-through-tested. Add Playwright.
4. **Agentic (deferred).** The recommended first agentic feature is an
   AI **question-authoring assistant** on the add-question screen (drafts
   constraints + a reference solution + a validated test suite; human approves).
   See the agent repo's CLAUDE.md "agentic direction" note. Adversarial test-gen
   and a candidate-feedback agent follow from it.
5. **Prod hardening.** Alembic migrations (schema is `create_all` today — a fresh
   DB picks up new columns, but existing DBs need migrations); `EmailStr`
   validation (emails are plain `str`); **HMAC body-signing** to harden the
   shared-secret agent↔platform auth.

## Companion repo

The **Assessment Agent** (`../AssesmentAgent`) is the stateless grader. It owns
code execution + the deterministic verdict + the Sonnet quality summary. Keep the
boundary: the platform never absorbs grading logic, and the agent never absorbs
question storage.
