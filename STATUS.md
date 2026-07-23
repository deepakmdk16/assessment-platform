# STATUS — Assessment Platform

Pending / next work **only**. Feature *history* is `git log` (commits are
per-slice and detailed) — there is deliberately no changelog file. Update this
file in the same commit that opens or closes an item (pre-push checkpoint #5).
Durable architecture / boundary / invariants live in CLAUDE.md + CONVENTIONS.md.
The broader prioritized gap/feature list (interviewer UX, candidate experience,
security, analytics, moats) lives in [PRODUCT_BACKLOG.md](PRODUCT_BACKLOG.md) —
this file stays scoped to near-term pending work.

## Open items

- **T4 multi-question assessments — IN PROGRESS (slices 1–2 of 5 landed).** Approved
  design: first-class `Assessment` (ordered questions, per-assessment **total**
  timer), free candidate navigation. **Landed:** (1) `Assessment` +
  `AssessmentQuestion` models, `Invite.assessment_id` (question_id now nullable —
  an invite points at EITHER a question or an assessment), migration `15556d728532`;
  (2) owner-scoped assessment CRUD API (`/assessments` create/list/get/update/
  archive/unarchive/delete; delete 409s if an invite points at it; questions
  validated as owned + no dupes); (3a) Submission unique constraint now includes
  `question_id` (migration `ad5e81ec2b2b`) + `POST/GET /assessments/{id}/invites`;
  (3b) candidate flow rethreaded — `/start` returns the ordered `questions` (each
  with a per-question `submitted` flag) + shared `deadline` (still exposes the
  legacy `question` = first, so the pre-T4 UI keeps working); `/run` `/run-tests`
  `/submit` take an optional `question_id` (None = the single question); one
  attempt per (invite, candidate, question); timer reads the invite's total
  duration (assessment or legacy question). **The whole T4 backend is done.**
  (5) candidate **free-navigation multi-question UI** built (`AssessmentFlow`):
  question switcher, per-question code/submit, per-question read-only after submit,
  one shared countdown that auto-submits every written-but-unsubmitted question at
  zero. CandidatePage delegates to it when an invite carries >1 question; the
  single-question flow is unchanged. Shared timer/console helpers extracted to
  `candidateTimer.ts` / `ConsoleResult.tsx`. **Remaining (UI only):** (4)
  interviewer
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
