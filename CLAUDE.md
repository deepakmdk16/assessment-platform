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
  wizard's %), and re-raises the agent's 503 (offline) / 422 (unusable draft, dict
  detail flattened to a string) / 400 so the UI can show warnings (other transport
  errors → 502). New schemas `QuestionDraftIn`/`QuestionDraftOut`. Drafting is
  **synchronous** (LLM + reference execution), so it uses a dedicated
  `AGENT_DRAFT_TIMEOUT_S` (120s default), **not** the 10s trigger timeout — the live
  smoke caught complex drafts 502-ing on the short one.
- **FE** — a collapsible **"Draft with AI" panel** on the Basics step of
  [AddQuestionPage.tsx](web/src/pages/AddQuestionPage.tsx): brief + language + optional
  difficulty/target-complexity → `api.draftQuestion` pre-fills the wizard fields
  (interviewer edits, then Review → Create); warnings render as a `role="alert"`;
  reference solution shown read-only (**not stored** — no column for it).
- Verified offline: `pytest` 48 (draft happy/503/422/auth/timeout + pass_threshold
  guard), ruff+mypy clean; `web` typecheck/lint/unit (12) + build clean. E2E:
  new `e2e/draft-with-ai.spec.ts` (draft→review→save, mock agent answers
  `/questions/draft`) green; full suite **4/4**.
- **E2E stale-DB flake root-caused & fixed** (was open item #3's follow-on). The
  real `e2e-platform.db` lives at the **repo root** (platform-api's cwd) and
  persists across runs; the mock agent reset its job counter each start, so
  `mock-job-N` ids collided with old rows and the callback (`.first()` match)
  graded a stale submission, leaving the current one stuck `running`. Fixed by
  minting per-process-unique ids in `e2e/mock-agent.mjs`; verified the suite passes
  twice in a row on an accumulated DB (0 collisions).
- **Live cross-repo smoke DONE (real agent + `ANTHROPIC_API_KEY`, 2026-07-15)** —
  drove the platform against a real `../AssesmentAgent`: (a) **full draft
  round-trip** brief → real Sonnet draft (200, ~$0.012, 11 cases) → platform
  reshape → save → **grade the drafted question with its own reference → PASS
  100%**; (b) grade path with a hand-authored question → PASS; (c) confirmed the
  agent's SSRF guard rejects `127.0.0.1` callbacks (use a hostname). Reconfirmed
  the pre-existing pass_threshold 0–100 vs 0–1 mismatch (out of scope) — a wizard-
  saved question stores the ×100 percent; the smoke divided back to a fraction to
  grade. CI still can't run a live LLM, so the mock E2E remains the CI gate.

**Flows tested in Slice 7 (for context).** _Live_ (real agent + real platform, real
`ANTHROPIC_API_KEY`, callbacks via the `*.local` hostname to dodge the agent's
`127.0.0.1` SSRF guard): (1) agent draft direct → 200; (2) draft **through the
platform** → reshaped `QuestionDraftOut`; (3) save drafted question → 201; (4) grade
drafted question w/ its own reference → **PASS 100%** (threshold corrected to a
fraction); (5) grade a hand-authored question end-to-end → **PASS 100%**; (6) draft
503 (no key) surfaced; (7) **raw wizard path** (save drafted question with
`pass_threshold` left as the wizard's percent) → **agent 400, submission `error`**
(see the bug below). _Offline pytest_: draft happy/503/422/auth/timeout. _vitest_:
draft panel pre-fills wizard + warning. _Playwright (mock)_ 4/4: draft→review→save,
invite→submit→grade PASS, revoke→410, duplicate→409.

**`pass_threshold` unit mismatch — FIXED (Slice 7, 2026-07-15).** The smoke's raw
path surfaced a grade-breaking, pre-existing bug: the wizard held/sent
`pass_threshold` as a **0–100 percent** while the DB/API/agent use a **0–1
fraction**, so the agent 400'd at trigger time (`pass_threshold must be in (0, 1]`)
and every UI-created question ended `status: error` — hidden by the mock (which
doesn't validate the threshold). **Fix:** convert at the FE boundary —
[AddQuestionPage.tsx](web/src/pages/AddQuestionPage.tsx) sends `passThreshold / 100`
on save and scales `×100` when populating from a draft; the draft route now returns
the agent's **fraction** as-is (no more `×100`); and `QuestionCreate`/`QuestionUpdate`
gained a `pass_threshold: Field(gt=0, le=1)` guard so a percent is rejected with a
**422** at creation instead of failing silently at grade. Verified: new pytest
guard (percent→422), updated draft/vitest assertions, and a **live re-run of the raw
path → PASS 100%**.

**Slice 8 done (full UI redesign — frontend only, 2026-07-16).** Ground-up visual
overhaul to a "developer console" look (dark left rail, graphite primary buttons,
one cobalt accent, green Submit, semantic chips), signed off from an HTML mockup
first. **No backend/agent changes.**
- **Token-driven CSS architecture** — all appearance in `web/src/styles/`
  (`tokens.css` = the re-theme file; `base.css`; `components.css`); `index.css` only
  `@import`s them. A restyle edits CSS, never `.tsx`. Enforced by `npm run lint`
  (ESLint bans inline `style=`; `scripts/check-no-hex.mjs` bans hex in `.tsx`).
  Documented in [CONVENTIONS.md](CONVENTIONS.md) → "Styling" (+ CLAUDE.md pointer).
- **App shell** — dark left rail (`components/Sidebar.tsx`) + topbar breadcrumb/logout
  (`AppLayout.tsx`); interviewer pages use it, candidate/auth stay full-screen.
- **Pages** — dashboard → **problem-list table**; question detail → **two-column**
  (problem + invite/grading side panel); add-question → **stepper + Draft-with-AI
  card + roomier test-case cards** (Input/Expected side-by-side); candidate →
  **LeetCode-style IDE** (Run coming-soon, green Submit); **new**
  `SubmissionDetailPage` (clickable rows → problem + candidate code + AI summary +
  best-effort per-test table, via the existing `GET /submissions/{id}`);
  login/register/gate → auth cards. Light + dark themes.
- **UX cleanups** — hid the internal slug id (dashboard + detail); candidate gate no
  longer reveals the question title before Start; new `web/src/badges.ts` chip helper.
- Removed orphaned `NavBar.tsx`. Verified: `pytest` untouched; `web`
  typecheck/lint(+guards)/unit (12) + build clean; **E2E 4/4** (helper + one spec
  assertion updated for new heading/notice text). On branch `slice8-ui-overhaul`.
- **Known limits / follow-ups (all needed BACKEND):** dashboard table has no
  Difficulty/Status/invite-count columns (no such fields/counts in the API yet) —
  **still open, now open item #7**; submission-detail per-test-case table was a
  placeholder — **fixed in Slice 10**; the candidate **Run** button was UI-only —
  **fixed in Slice 11**.

**Slice 9–12 done (invite binding, report card, candidate Run, draft robustness,
2026-07-16).** One branch, `slice9-assessment-workflow`, plus its cross-repo half on
the Agent's `slice11-run-endpoints`. Closes open item #0 (a) and (b), and the draft
robustness the user flagged.

- **Slice 9 — invite links are bound to their recipients.** The link was effectively
  a bearer token for the question: anyone it was forwarded to could open it, read the
  problem and submit; and a repeat candidate only learned they couldn't retake it
  *after* writing a solution. Now: invites **require ≥1 recipient** (422 otherwise);
  new **`POST /invite/{token}/start`** takes the candidate's email, 403s an uninvited
  address, 409s one who already submitted, and only then returns the question;
  **`GET /invite/{token}` is a liveness probe carrying no question data** — moving the
  question behind `/start` is what makes the check real, since otherwise a link holder
  could read the problem off the probe. `/submit` re-checks both gates (the gate is
  only UI). **Caveat, by decision:** this is an identity *claim*, not proof — someone
  who knows an invited address can still type it. Per-recipient tokens or an emailed
  OTP are the stronger form; chosen deliberately for speed.
- **Slice 9 — inviting is a deliberate, optional action (user call, 2026-07-16).**
  Creating a question never required an invite, but the email box sat on the page
  implying otherwise. It now lives in a **dialog** behind "Send invite": arriving from
  the wizard opens it once as a nudge (dismiss reads **"Skip for now"**, one-shot —
  re-opening by hand reads "Cancel"), emails are comma- or newline-separated, and a
  successful send closes the dialog and confirms who it went to. **No email → no
  invite link** (the 422 stands): a link naming nobody is one nobody could open, so
  the binding holds everywhere. Secrets now load from a gitignored **`.env`**
  (`.env.example` is the template; real env vars still win).
- **Slice 9 — invite email actually reports itself.** `send_invite_emails` now sends
  per recipient (one bad address no longer costs the others their invite) and returns
  a `Delivery` each; `InviteOut.deliveries[]` carries it on create and the UI warns
  when a send failed. Sending stays best-effort (a dead mail server must not undo an
  invite that exists), but silent non-delivery is gone. **Live-verified against Gmail
  SMTP (2026-07-16)** — see the live-verification note below. Setup: README → "Sending
  invite emails (SMTP)". **Known gap:** `deliveries[]` is returned on create but **not
  stored**, so after a reload there's no record of who was actually emailed (see open
  item #6).
- **Slice 10 — the interviewer report card renders.** The per-test table never worked:
  `extractCases()` probed `full_result` for `test_results`/`tests`/`results`/`cases`/
  `checks`, but the agent's key is **`test_cases`** — so it always fell to the "not
  wired yet" placeholder. The data had been stored verbatim since Slice 1; nothing
  read it. Now typed (`AgentFullResult`/`ResultTestCase`/`ResultQuality`) and rendered:
  verdict, points, threshold, compile/infra errors, AI summary + strengths/weaknesses/
  criteria, and every case's input/expected/actual/status/timing. **No backend change
  was needed.** The E2E mock agent's callback was thinner than the real one — that
  drift is what let a broken card pass CI — so it now mirrors `result_to_dict`.
- **Slice 11 — candidate Run + Run against test cases** (cross-repo). Agent Phase A:
  **`POST /run`** (execute once against caller stdin) and **`POST /run/tests`** (suite;
  **pass/fail only**, no I/O). Platform Phase B: `POST /invite/{token}/run` and
  `.../run-tests`, gated exactly like `/start` (else the link is free agent compute),
  rate-limited on their own bucket (`RUN_RATE_LIMIT_MAX`; run-tests is a pass/fail
  oracle for reverse-engineering the suite), and redacting further — **case names are
  dropped** (a name like `handles_duplicates` is itself a hint); cases are positional,
  "Test 1", like HackerRank. Neither route creates a Submission or spends the one
  attempt. UI: a **custom-input box** (what LeetCode/HackerRank actually do — an
  interactive terminal would need a persistent container + PTY per session, which this
  architecture doesn't have), output console, and a pass/fail strip.
- **Slice 12 — draft failures degrade gracefully.** Two retries, deliberately distinct:
  the **agent** re-drafts when its own output is unusable (`ASSESS_DRAFT_ATTEMPTS`=2 —
  the model is stochastic, so a reference that won't compile is usually a one-off); the
  **platform** retries only what a retry could fix (agent unreachable / 429 / 5xx) and
  **fails fast on 503 (no API key), 422 (already re-drafted) and 400** — retrying those
  just makes the interviewer wait for the same error. `AGENT_DRAFT_TIMEOUT_S` raised
  120→240s to cover the agent's internal attempts. UI gives a **Try again** button and
  a message that says whether retrying can help.
- **The C++ `.hpp` failure is fixed at its source** (agent): the runner compiles exactly
  one translation unit (`g++ main.cpp`), so a reference split across a header could
  never build — nothing had told the model that. The drafting prompt now states the
  single-file rule.
- Verified offline: `pytest` **87**, ruff+mypy clean; agent `pytest` **115**, ruff+mypy
  clean; `web` typecheck/lint/unit **30** + build clean; **Playwright 9/9**.
- **LIVE browser verification DONE (user-driven, 2026-07-16)** — real Gmail SMTP (app
  password), real agent, both feature branches, since merged (platform PR #9 → `main`
  `dcfdfae`; agent PR #7 → `main` `9b9451e`). Confirmed by hand: (1) invite email
  **received** by a single recipient, and only the named email can open the link;
  (2) **multi-recipient** comma-separated invite delivered to both; (3) candidate
  **Run** with custom stdin and **Run against test cases** both work in the editor;
  (4) a candidate who already submitted is refused at **Start**; (5) **Cancel** after
  an accidental "Send invite" creates nothing. One reported "multi-recipient email not
  received" was **not a bug** — the DB showed the invite was addressed to
  `deepakmadire@…` (the SMTP sender account) rather than the intended `deepakmdk16@…`,
  i.e. a typo; the comma-split had stored two clean, correct entries. That episode is
  what surfaced open item #6: a mistyped-but-valid address reports `sent: true`
  truthfully, and with no stored delivery record there was no way to audit it after.
- **Local-dev hazard worth knowing:** Playwright's `reuseExistingServer` is on locally,
  so a **stale `platform-api` on :9000 or a real `assess-api` on :8000 from an earlier
  session gets silently reused** — the suite then runs against old code / the real agent
  and fails confusingly. `lsof -ti:8000,9000,5173 | xargs kill -9` before a local run.

**Open items (pick up here — each its own session):**
0. **Backend work — DONE (Slices 9–12, merged 2026-07-16).** (a) invite email —
   **done and live-verified**: candidates receive the link over real Gmail SMTP,
   single and multi-recipient (setup: README → "Sending invite emails (SMTP)"; the
   sender's app password lives in a gitignored `.env` / shell export, never in the
   repo). (b) new features/APIs — **done**: real per-test-case results on the report
   card (Slice 10) and the Run endpoints (Slice 11). (c) more robust tests — done for
   the new surface (+62 tests across both repos). **What's left is now items #6 and #7
   below** (both need a model + Alembic migration, and pair naturally).
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
     screen; offline-tested (pytest + vitest) and an offline Playwright spec.
     **Live cross-repo smoke DONE** (see the Slice 7 entry): full brief→draft→save→
     grade→PASS round-trip against the real agent.
   - Follow-ons: adversarial test-gen (agent #4a, already built) and a
     candidate-feedback agent. Spans both repos — a project, not a cleanup item.
5. **`pass_threshold` unit mismatch — DONE (Slice 7, 2026-07-15).** Fixed at the FE
   boundary (`÷100` on save, `×100` on load) + a `gt=0, le=1` schema guard (percent →
   422) + live re-verify. See the "`pass_threshold` unit mismatch — FIXED" note in
   the Slice 7 status above. (No edit page exists yet; when one is added it must do
   the same `×100`/`÷100` conversion.)
6. **Persist invite delivery status (NEXT, 2026-07-16).** `deliveries[]` is returned
   on the create response only — nothing stores it — so a reload loses it and there is
   **no audit trail of who was actually emailed**. Surfaced during a live
   investigation: the DB could say who an invite was *addressed to*, but not whether
   the send *succeeded*. Matters for real hiring use, because a mistyped-but-valid
   address reports `sent: true` truthfully and is otherwise indistinguishable from
   success. Needs a model (delivery rows or a JSON column on `Invite`) + an Alembic
   migration, and the invites table should show per-recipient status. Pairs with #7.
7. **Question `difficulty` / `status` field (NEXT).** The dashboard table has no
   Difficulty/Status columns because no such fields exist in the model/API (the
   Slice-8 UI left the columns out for this reason). Needs a model field + Alembic
   migration + wizard UI. The last item from the original Slice-8 follow-up list.

## Companion repo

The **Assessment Agent** (`../AssesmentAgent`) is the stateless grader. It owns
code execution + the deterministic verdict + the Sonnet quality summary. Keep the
boundary: the platform never absorbs grading logic, and the agent never absorbs
question storage.
