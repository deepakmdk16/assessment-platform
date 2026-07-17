# STATUS — Assessment Platform

Pending / next work **only**. Feature *history* is `git log` (commits are
per-slice and detailed) — there is deliberately no changelog file. Update this
file in the same commit that opens or closes an item (pre-push checkpoint #5).
Durable architecture / boundary / invariants live in CLAUDE.md + CONVENTIONS.md.

## Open items

- **Persist invite delivery status.** `deliveries[]` is returned on invite create
  but never stored → no audit trail of who was actually emailed. Needs a model
  (delivery rows or a JSON column on `Invite`) + an Alembic migration; surface
  per-recipient status in the invites table. Pairs with the difficulty/status item.
- **Question `difficulty` / `status` field.** The dashboard has no Difficulty/Status
  columns because the model/API has no such fields. Needs a model field + Alembic
  migration + wizard UI.
- **Set `TRUST_PROXY_HEADERS=true` when deploying behind a proxy.** The rate
  limiters key on the caller's address; behind a proxy that is the *proxy* for
  every request, collapsing every bucket into one shared counter (the first few
  callers 429 everyone else). The support exists and defaults OFF — safe for the
  direct dev setup, wrong the moment there's a load balancer in front. Not code:
  a deploy-time checklist item. Chained proxies (CDN → LB) need `client_ip()`
  revisited, as it trusts exactly one hop.
- **Archive (soft-delete) a question that has submissions.** `DELETE /questions/{id}`
  now 409s once anything has been submitted against it, because submissions are the
  record and must not be cascaded away — so an interviewer has no way to retire an
  old question. An `archived` status that hides it from the dashboard while keeping
  its submissions is the intended path; folds into the `difficulty`/`status` item
  above. (`api.deleteQuestion` exists in `web/src/api.ts` but has no call site, so
  no UI surfaces the 409 today.)
- **HMAC body-signing (cross-repo, deferred).** Hardens the shared-secret
  agent↔platform auth. Must land on **both** sides in one coordinated slice (the
  Agent grows the verify counterpart) or the platform side is inert.
- **E2E resilience.** Make the E2E suite resilient to a stale local
  `e2e-platform.db`. (The other half of this item — running the offline gates in
  CI — is done: `.github/workflows/checks.yml` invokes `scripts/checkpoints.sh`.)
- **Claude Code tooling follow-ups (global, deferred — not platform code).** Three
  gaps found in the 2026-07-17 setup audit that live outside this repo, so they
  were left alone: the `ship` skill re-implements `scripts/checkpoints.sh` instead
  of calling it (both then drift); `~/.claude/CLAUDE.md` §8 and the "Use
  PROACTIVELY" agent descriptions contradict the harness's don't-auto-spawn rule;
  serena has no auto-activation (worked around by a note in CLAUDE.md, not fixed).
  All touch `~/.claude/`, shared with `../AssesmentAgent`.
- **Candidate-feedback agent (cross-repo, not yet chosen).** Surface actionable
  feedback to candidates; spans both repos.

## From the 2026-07-17 audit — remaining, highest value first

A full read of the codebase on 2026-07-17 found these. Correctness (question-delete
orphans, the submit race) and security/cost (draft + register caps, proxy-aware
limits, constant-time compares) are **done** — see `git log`. What it found and we
have *not* fixed yet:

- **Submissions stick in `running` forever.** If the agent 202s and its callback
  never arrives (crash, dropped network, lost job) the status never changes — and
  `retry` only accepts `error`, so there is no recovery path at all: the interviewer
  can neither retry nor cancel, and the candidate's attempt is stranded. Needs a
  design call: stale-`running` reaper vs. grace-period retry vs. polling the agent
  for job state. Do with request correlation below — you need tracing to know what
  you are reaping.
- **No request correlation.** Nothing ties submission → agent job → callback. When a
  callback goes missing (above), the only breadcrumb is one `logger.warning` for an
  unknown `job_id`. The whole architecture is an async callback handoff, so this is
  the observability to add first.
- **`init_db()` runs on every startup, contradicting Alembic.** `api.py`'s
  `_lifespan` calls it unconditionally under a stale comment ("no Alembic yet") —
  Alembic is here. `create_all` no-ops on existing tables so nothing corrupts, but it
  **hides schema drift**: a model change works in dev without a migration, the
  migration never gets written, and a fresh prod DB then gets `create_all`'s schema
  rather than Alembic's. Gate behind `AUTO_CREATE_TABLES`, default off; delete the
  comment.
- **Tests are not offline locally** (violates CONVENTIONS.md → Tests). `config.py`
  calls `load_dotenv()`, so a developer's `.env` sets `SMTP_HOST` and
  `send_invite_emails` opens real Gmail connections during **pytest and Playwright**
  (visible as `invite email: failed to send to …`). Sending is best-effort so nothing
  fails — it just hits the network on every invite test and is likely much of
  pytest's ~155s. CI is unaffected (no `.env` there). Force SMTP off under test.
- **`/health` checks nothing.** Returns `{"status":"ok"}` without touching the DB, so
  a load balancer happily keeps routing to an instance whose database is gone.
- **Sync routes + blocking agent calls.** Every route is `def`, so FastAPI runs it in
  a ~40-thread pool, and `draft_question` blocks a thread for up to
  `AGENT_DRAFT_TIMEOUT_S` (240s) × 3 transport retries; run/run-tests up to 60s. ~40
  concurrent drafts wedge the entire API, `/health` included. The rate limits now cap
  the easy trigger, but the shape is unchanged.
- **No pagination.** `GET /questions`, `GET /submissions` and
  `/questions/{id}/submissions` return everything, and `SubmissionOut` embeds the full
  `code` blob *and* the entire `full_result` payload — 500 candidates is 500 code
  blobs plus 500 agent payloads in one response. The N+1 was avoided in
  `_results_by_submission`; the payload size was not.
- **Frontend: no `ErrorBoundary`.** Any render throw (Monaco failing to load, an
  unexpected `full_result` shape) is a white screen for a candidate mid-assessment
  with their code in the editor — the worst failure location in the product.
  Mockup-first per CLAUDE.md.
- **Frontend: no result polling.** No `setInterval` anywhere: after a submit the
  status reads `running` until someone presses F5, so the product's payoff moment
  needs a manual refresh. Poll `GET /submissions/{id}` while pending/running.
  Mockup-first per CLAUDE.md.
- **Small cleanup (one batch).** `expires_at` accepts a past datetime → an invite
  that 410s on arrival, silently, *after* emailing every recipient. `assert x is not
  None` is load-bearing control flow in register/login/create_question/create_invite
  (`python -O` strips asserts). CORS `allow_credentials=True` is unnecessary — the JWT
  rides in a header, not a cookie.
