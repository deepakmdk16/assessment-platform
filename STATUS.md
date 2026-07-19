# STATUS — Assessment Platform

Pending / next work **only**. Feature *history* is `git log` (commits are
per-slice and detailed) — there is deliberately no changelog file. Update this
file in the same commit that opens or closes an item (pre-push checkpoint #5).
Durable architecture / boundary / invariants live in CLAUDE.md + CONVENTIONS.md.

## Open items

- **Question `difficulty` / `status` field — UI remaining.** Backend done (see `git
  log`): `Question.difficulty`/`status` columns + Alembic migration, `difficulty` on
  create/update, `status` returned, and archive/unarchive endpoints. Still to do,
  **mockup-first per CLAUDE.md:** a difficulty dropdown in the wizard and
  Difficulty/Status columns + an archive button on the dashboard.
- **Set `TRUST_PROXY_HEADERS=true` when deploying behind a proxy.** The rate
  limiters key on the caller's address; behind a proxy that is the *proxy* for
  every request, collapsing every bucket into one shared counter (the first few
  callers 429 everyone else). The support exists and defaults OFF — safe for the
  direct dev setup, wrong the moment there's a load balancer in front. Not code:
  a deploy-time checklist item. Chained proxies (CDN → LB) need `client_ip()`
  revisited, as it trusts exactly one hop.
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
