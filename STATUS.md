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
- **HMAC body-signing (cross-repo, deferred).** Hardens the shared-secret
  agent↔platform auth. Must land on **both** sides in one coordinated slice (the
  Agent grows the verify counterpart) or the platform side is inert.
- **CI follow-ons.** Also run the offline gates (pytest/ruff/mypy + web
  build/typecheck/lint/unit) in CI — currently only Playwright E2E is gated — and
  make the E2E suite resilient to a stale local `e2e-platform.db`.
- **Candidate-feedback agent (cross-repo, not yet chosen).** Surface actionable
  feedback to candidates; spans both repos.
