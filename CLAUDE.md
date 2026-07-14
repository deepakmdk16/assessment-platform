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

1. `uv run pytest` passes; `uv run ruff check .` and `uv run mypy` clean.
2. If `web/` changed: `npm run build`, `typecheck`, `lint`, `test` all clean.
3. `/code-review` (or a self-review of the diff) has been run.
4. New endpoints have tests that run **offline** (mock the agent call; no network,
   no real LLM).
5. **`## Status & next steps` below is updated** to reflect what this slice
   shipped — mark the finished open item done (or narrow it to what remains) and
   record the new slice. The roadmap must never lag the code.

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

**Slice 2 done (backend security/hardening, 2026-07-14).** Closed the
gap-analysis findings on the backend, all offline-tested (`pytest` 40 passed,
ruff+mypy clean):
- **CORS** — `CORSMiddleware` with env-driven `CORS_ORIGINS` (default
  `FRONTEND_BASE_URL`); the SPA can now call the API cross-origin. Without this
  the browser flow was blocked — it had only ever been exercised by scripted
  requests, never a real browser.
- **`/submissions*` now auth'd + owner-scoped** (`POST`, `GET` list/detail,
  `retry`) via a new `_owned_submission` helper.
- **Invite lifecycle** — `Invite.status` is now enforced (revoked/inactive →
  410); new owner-scoped `POST /questions/{id}/invites/{token}/revoke`; and
  **one submission per email per invite** (case-insensitive; second attempt for
  the same email → 409). Different emails may each submit once.
- **Rate limiting** — dependency-free in-process limiter (`ratelimit.py`) on
  `/auth/login` (brute-force) and `POST /invite/{token}/submit` (spam → paid
  agent jobs); env-tunable (`LOGIN_RATE_LIMIT_MAX`, `SUBMIT_RATE_LIMIT_MAX`,
  `RATE_LIMIT_WINDOW_S`; set MAX=0 to disable). 429 on exceed.
- **Gated registration** — `REGISTRATION_CODE` env; when set, `/auth/register`
  requires a matching `registration_code` in the body (403 otherwise). Unset =>
  open sign-up (dev).
- **Invite emailing** — `email_client.send_invite_emails` (stdlib `smtplib`),
  best-effort on invite create; logs the link when SMTP is unconfigured (dev),
  mocked in tests. SMTP_* env config.
- **N+1 fix** — `_results_by_submission` batch-fetches results for the list +
  dashboard reads in one query.

**Slice 3 partial (frontend UX — Slice-2 surfacing, 2026-07-14).** Surfaced the
Slice-2 backend in `web/`, all offline-tested (`web` typecheck/lint/test clean,
build green):
- **Revoke button** on the question-detail invites table (`api.revokeInvite` →
  `POST …/revoke`); shown only on `active` invites, `confirm()`-guarded, flips
  the row to `revoked` on success.
- **Candidate error handling** — submit **409** (email already used) → dedicated
  "Already submitted" screen; **410**/**404** (invite revoked/expired or question
  deleted mid-session) → terminal "no longer active" screen; broadened the 410
  load message to cover revoked *and* expired.
- Tests: 409 case added to `CandidatePage.test.tsx`; new `QuestionDetailPage.test.tsx`
  (revoke happy-path + confirm-dismissed).

**Open items (pick up here — each its own session):**
1. **Frontend UX polish (`web/`)** — the Slice-2 surfacing (revoke, 409/410) is
   done (Slice 3 above). Remaining: the earlier **dashboard + multi-step
   add-question polish**, and a nit from review — revoke errors currently reuse
   the create-invite form's error slot (shows far from the table row). Run the
   `npm` build/typecheck/lint/test loop after.
2. **Prod hardening.** **Alembic** migrations (schema is `create_all` today — a
   fresh DB picks up new columns, but existing DBs need migrations); `EmailStr`
   validation (emails are plain `str` — adds the `email-validator` dep);
   **HMAC body-signing** to harden the shared-secret agent↔platform auth. NOTE:
   HMAC is **cross-repo** — the Agent (`../AssesmentAgent`) must implement the
   signing/verifying counterpart or the platform-side change is inert.
3. **Browser E2E for `web/`** — today the frontend is contract-aligned +
   unit-tested (vitest), not click-through-tested. Add Playwright (browser +
   dev-server infra). This is the test class that would have caught the CORS gap.
4. **Agentic (deferred).** The recommended first agentic feature is an
   AI **question-authoring assistant** on the add-question screen (drafts
   constraints + a reference solution + a validated test suite; human approves).
   See the agent repo's CLAUDE.md "agentic direction" note. Adversarial test-gen
   and a candidate-feedback agent follow from it. Spans both repos — a project,
   not a cleanup item.

## Companion repo

The **Assessment Agent** (`../AssesmentAgent`) is the stateless grader. It owns
code execution + the deterministic verdict + the Sonnet quality summary. Keep the
boundary: the platform never absorbs grading logic, and the agent never absorbs
question storage.
