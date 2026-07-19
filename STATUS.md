# STATUS — Assessment Platform

Pending / next work **only**. Feature *history* is `git log` (commits are
per-slice and detailed) — there is deliberately no changelog file. Update this
file in the same commit that opens or closes an item (pre-push checkpoint #5).
Durable architecture / boundary / invariants live in CLAUDE.md + CONVENTIONS.md.

## Open items

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
- **Pagination — bounded now, pager UI deferred.** Done (see `git log`): all three
  list endpoints (`GET /questions`, `GET /submissions`, `/questions/{id}/submissions`)
  take `limit` (default 100, cap 200) + `offset` with deterministic ordering (newest
  first, id tiebreaker), so no response can be forced to serialize the whole table;
  and `GET /submissions` rows are now the lean `SubmissionSummaryOut` — no `code` /
  `full_result` (fetch the full `SubmissionOut` per-id for detail). Still to do: a real
  **pager UI** (Prev/Next + a total count) — the dashboard currently shows only the
  first 100 rows, silently. Needs a totals envelope or a count endpoint plus pager
  controls, **mockup-first per CLAUDE.md.**
