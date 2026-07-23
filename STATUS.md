# STATUS — Assessment Platform

Pending / next work **only**. Feature *history* is `git log` (commits are
per-slice and detailed) — there is deliberately no changelog file. Update this
file in the same commit that opens or closes an item (pre-push checkpoint #5).
Durable architecture / boundary / invariants live in CLAUDE.md + CONVENTIONS.md.
The broader prioritized gap/feature list (interviewer UX, candidate experience,
security, analytics, moats) lives in [PRODUCT_BACKLOG.md](PRODUCT_BACKLOG.md) —
this file stays scoped to near-term pending work.

## Open items

- **T4 multi-question assessments — IN PROGRESS (slice 1 of 5 landed).** Approved
  design: first-class `Assessment` (ordered questions, per-assessment **total**
  timer), free candidate navigation. **Landed:** `Assessment` + `AssessmentQuestion`
  models, `Invite.assessment_id` (question_id now nullable — an invite points at
  EITHER a question or an assessment), migration `15556d728532`. **Remaining
  slices:** (2) assessment CRUD API; (3) rethread invite create + candidate
  start/submit + submissions to be per-(invite,candidate,question), and move the
  timer deadline to read `assessment.duration_minutes`; (4) interviewer
  assessment-builder UI (mockup-gated); (5) candidate free-nav multi-question UI
  (mockup-gated). See PRODUCT_BACKLOG.md → T4 for the full spec.
- **Set `TRUST_PROXY_HEADERS=true` when deploying behind a proxy.** The rate
  limiters key on the caller's address; behind a proxy that is the *proxy* for
  every request, collapsing every bucket into one shared counter (the first few
  callers 429 everyone else). The support exists and defaults OFF — safe for the
  direct dev setup, wrong the moment there's a load balancer in front. Not code:
  a deploy-time checklist item. Chained proxies (CDN → LB) need `client_ip()`
  revisited, as it trusts exactly one hop.
- **Claude Code tooling follow-ups (global, deferred — not platform code).** Gaps
  found in the 2026-07-17 setup audit that live outside this repo, so they were
  left alone: `~/.claude/CLAUDE.md` §8 and the "Use PROACTIVELY" agent descriptions
  contradict the harness's don't-auto-spawn rule; serena has no auto-activation
  (worked around by a note in CLAUDE.md, not fixed). All touch `~/.claude/`, shared
  with `../AssesmentAgent`. (The audit's third item — the `ship` skill re-implementing
  `scripts/checkpoints.sh` — is resolved: the skill now runs `checkpoints.sh` when
  present, 2026-07-20.)
- **Candidate-feedback agent (cross-repo, not yet chosen).** Surface actionable
  feedback to candidates; spans both repos.

## From the 2026-07-17 audit — remaining, highest value first

A full read of the codebase on 2026-07-17 found these. Correctness (question-delete
orphans, the submit race), security/cost (draft + register caps, proxy-aware
limits, constant-time compares), and the blocking agent calls are **done** — see
`git log`. What it found and we have *not* fully closed yet:

- **DB calls run on the event loop in the async agent routes (residual).** The six
  agent-calling routes are now `async def` and `await` the agent over
  `httpx.AsyncClient`, so slow agent I/O no longer holds a pooled thread — the
  thread-exhaustion bug is fixed. But the DB is still synchronous SQLModel, so the
  small per-request queries in those routes now run on the event loop rather than in
  the threadpool. Fine at this scale (indexed single-row ops, ms-scale) and on SQLite;
  if a slow Postgres query ever shows up on these paths, wrap the DB work in
  `fastapi.concurrency.run_in_threadpool` or move to an async engine. Not worth doing
  pre-emptively.
