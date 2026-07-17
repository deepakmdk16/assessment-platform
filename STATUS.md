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
