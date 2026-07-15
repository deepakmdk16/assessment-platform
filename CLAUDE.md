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

**Slice 4 done (Playwright browser E2E, 2026-07-14).** Added the browser E2E
harness for `web/` (open item #3), all offline/deterministic:
- **`web/playwright.config.ts`** auto-starts three servers: a **mock agent**
  (`web/e2e/mock-agent.mjs`, a Node stand-in for `../AssesmentAgent` that accepts
  `POST /assessments` and posts a `PASS` callback), `uv run platform-api` (pointed
  at the mock, a throwaway `e2e-platform.db`, rate limits off), and the Vite dev
  server. No live agent / LLM key needed.
- **Specs** (`web/e2e/`): the full happy path (register → add-question → create
  invite → candidate submit → graded `PASS` on the dashboard) plus revoke → `410`
  and duplicate-email → `409`. Tests mint unique interviewer/question data per run
  (no DB reset); vitest `include` is scoped to `src/` so it ignores `e2e/`.
- Run: `npm run test:e2e` (first run: `npx playwright install chromium`). Verified
  3/3 green; `pytest` 40, ruff+mypy clean; `web` typecheck/lint/unit/build clean.

**Slice 5 done (E2E in CI, 2026-07-14).** Wired the Slice-4 Playwright harness
into GitHub Actions (open item #3):
- **`.github/workflows/e2e.yml`** runs on every PR + pushes to `main`. Provisions
  the toolchains only (`astral-sh/setup-uv` → `uv sync`; `actions/setup-node` 22 →
  `npm ci`; `npx playwright install --with-deps chromium`) then `npm run test:e2e`
  — the Playwright config auto-starts the three servers itself, so no live agent /
  LLM key is needed. `concurrency` cancels superseded runs; the HTML report uploads
  as a failure artifact.
- **`web/playwright.config.ts`** now, **only under `CI`**, emits an HTML report
  (`[['list'],['html']]`) and retries once (so `trace: on-first-retry` captures a
  trace). Local behaviour is unchanged (`list`, no retries).
- CI always starts from a fresh DB (`e2e-platform.db` is gitignored → not checked
  out, ephemeral runner). Verified green with `CI=true npm run test:e2e` on a fresh
  DB (3/3); `pytest` 40, ruff+mypy clean; `web` build/typecheck/lint/unit clean.
  NOTE: the suite is *not* resilient to a **stale** local `e2e-platform.db` (state
  accumulates → the PASS-grading spec can time out); `rm e2e-platform.db` before a
  local run if it flakes. Doesn't affect CI.

**Slice 6 done (FE UX polish + prod hardening, 2026-07-14).** Closed open items
#1 (fully) and #2 (except the deliberately-deferred HMAC), all offline-tested:
- **Add-question wizard** — [AddQuestionPage.tsx](web/src/pages/AddQuestionPage.tsx)
  is now a 5-step wizard (Basics → Grading → Test cases → Example → Review) with
  per-step validation + a Review summary; Enter/submit advances rather than
  creating until the last step.
- **Dashboard polish** — count badge, richer empty state, and per-question meta
  (test-case count + created date) on [DashboardPage.tsx](web/src/pages/DashboardPage.tsx).
- **Revoke-error nit fixed** — revoke failures now render a per-row `role="alert"`
  in the invite's actions cell instead of the create-invite form's error slot.
- **EmailStr validation** — request schemas (`RegisterIn`, `LoginIn`,
  `InviteCreate.recipients`, `CandidateSubmitIn`) now use `EmailStr` (adds
  `email-validator`); invalid emails → 422. Output schemas + DB models left as
  `str` (they store already-validated data). Tests added (register + invite).
- **Alembic** — `alembic/` + initial autogenerated migration (`cae37faa2bff`),
  `env.py` reads the URL from `config.DATABASE_URL` and targets `SQLModel.metadata`.
  Dev/tests still use `create_all` (kept at parity with the migration). Prod:
  `DATABASE_URL=... uv run alembic upgrade head`. `alembic/versions` is
  ruff-excluded (generated code).
- Verified: `pytest` 42, ruff+mypy clean; `web` typecheck/lint/unit (11) + build
  clean; E2E green (wizard flow updated in `e2e/helpers.ts`).

**Slice 7 done (question-authoring assistant — Phase B, 2026-07-15).** Consumed the
Agent's Phase-A `POST /questions/draft` (shipped & live-verified in `../AssesmentAgent`
on 2026-07-15) — open item #4, Phase B. The platform calls the agent to draft, shows
the draft for human review/edit, and stores the approved question via the normal
`POST /questions` path (it never grades, executes, or stores an unvalidated question):
- **Agent call** — new `agent_client.draft_question(brief, language, difficulty,
  target_complexity)` (auth reuses `X-Assess-Token: $ASSESS_API_TOKEN`), the 3rd
  agent↔platform call alongside trigger + callback.
- **Route** — `POST /questions/draft` (bearer-guarded, interviewer-only, **stores
  nothing**): calls the agent, maps its `question` dict into the create-form shape
  (flatten `example`→`example_input/output`, scale `pass_threshold` ×100 to the
  wizard's %), and re-raises the agent's 503 (offline) / 422 (unusable draft) / 400
  so the UI can show warnings (other transport errors → 502). New schemas
  `QuestionDraftIn`/`QuestionDraftOut`.
- **FE** — a collapsible **"Draft with AI" panel** on the Basics step of
  [AddQuestionPage.tsx](web/src/pages/AddQuestionPage.tsx): brief + language + optional
  difficulty/target-complexity → `api.draftQuestion` pre-fills the wizard fields
  (interviewer edits, then Review → Create); warnings render as a `role="alert"`;
  reference solution shown read-only (**not stored** — no column for it).
- Verified: `pytest` 46 (+4 draft: happy/503/422/auth), ruff+mypy clean; `web`
  typecheck/lint/unit (12, +1 draft) + build clean. E2E: new `e2e/draft-with-ai.spec.ts`
  (draft→review→save, mock agent answers `/questions/draft`) green. NOTE: the
  pre-existing `interviewer-candidate-flow` PASS-grading spec fails on this machine
  **independent of this change** (reproduced with the diff stashed) — the timing-
  sensitive spec flagged in the Slice-5 note; belongs to open item #3's follow-on.
- Live cross-repo E2E (real agent + `ANTHROPIC_API_KEY`) remains a **manual** step
  (CI can't run a live LLM).

**Open items (pick up here — each its own session):**
1. **Frontend UX polish** — **done (Slice 6):** add-question wizard, dashboard
   polish, and the revoke-error placement nit all shipped.
2. **Prod hardening.** EmailStr + Alembic **done (Slice 6).** Remaining:
   **HMAC body-signing** to harden the shared-secret agent↔platform auth —
   **deferred deliberately** because it's **cross-repo**: the Agent
   (`../AssesmentAgent`) must implement the signing/verifying counterpart in the
   same change, or the platform side is inert (and would break grading if made
   mandatory). Do it as a coordinated platform+Agent slice.
3. **CI for the E2E suite** — **done (Slice 5).** GitHub Actions runs the
   Playwright suite on every PR + push to `main`. Follow-ons if wanted: also run
   the offline gates (`pytest`/ruff/mypy + `web` build/typecheck/lint/unit) in CI
   (currently no workflow covers them), and make the E2E suite resilient to a
   stale local DB (reset `e2e-platform.db` on start instead of relying on unique
   per-run data).
4. **Question-authoring assistant (cross-repo project, 2026-07-14).** An AI
   assistant on the add-question screen that drafts a full question from an
   interviewer's brief (prompt, constraints, a reference solution, and a validated
   test suite) which the interviewer approves/edits before saving.
   **Decision: the Agent owns the whole draft** (execution lives in the agent; the
   platform has no executor and never grows one — platform stores, agent
   grades/executes). The platform calls the stateless agent endpoint
   `POST /questions/draft`, shows the draft for human approval/edit, and **stores**
   the approved result like any other question.
   - **Phase A — done** (agent, 2026-07-15): `POST /questions/draft` built &
     live-verified in `../AssesmentAgent`.
   - **Phase B — done (Slice 7, 2026-07-15):** platform `agent_client.draft_question`
     + `POST /questions/draft` route + the "Draft with AI" panel on the add-question
     screen; offline-tested (pytest + vitest) and an offline Playwright spec. See the
     Slice 7 entry above. **Remaining:** one **live** cross-repo E2E (real agent +
     `ANTHROPIC_API_KEY`) — deliberately manual, CI can't run a live LLM.
   - Follow-ons: adversarial test-gen (agent #4a, already built) and a
     candidate-feedback agent. Spans both repos — a project, not a cleanup item.

## Companion repo

The **Assessment Agent** (`../AssesmentAgent`) is the stateless grader. It owns
code execution + the deterministic verdict + the Sonnet quality summary. Keep the
boundary: the platform never absorbs grading logic, and the agent never absorbs
question storage.
