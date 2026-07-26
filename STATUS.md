# STATUS — Assessment Platform

The **single** pending / next-work list for this repo (the old `PRODUCT_BACKLOG.md`
was folded in here on 2026-07-24 and deleted — one list, not two). Feature
*history* is `git log` (commits are per-slice and detailed) — there is deliberately
no changelog file. Update this file in the same commit that opens or closes an item
(pre-push checkpoint #5). Durable architecture / boundary / invariants live in
CLAUDE.md + CONVENTIONS.md; cross-repo grader concerns live in `../AssesmentAgent/STATUS.md`.

Effort key: **XS** (minutes) · **S** (self-contained) · **M** (multi-file) · **L** (data + API + UI).

---

## A. Assessment-era gaps — found in manual testing 2026-07-24, updated 2026-07-26 (highest priority)

The T4 multi-question assessment epic shipped; driving it end-to-end surfaced these.
Several are "the single-question flow had it, the assessment flow doesn't yet."

- **A7 · Invite paths separated, not merged — DONE 2026-07-26.** Both paths were
  duplicative/confusing once assessments existed. Decision (product): **keep both,
  relabel to two distinct tools** rather than deprecate either. The per-question
  path is now a **"Quick screen"** (card, button, dialog, and results table on
  `QuestionDetailPage` all relabelled; copy says it screens on *just this question*
  and links to Assessments for a multi-question sitting); the per-assessment path
  is **"Invite to this assessment"** (whole assessment, one shared timer). No data
  model change — both routes (`/questions/{id}/invites`, `/assessments/{id}/invites`)
  are unchanged; this is UI/copy only. Frontend tests updated for the new labels.
- **A8 · Authoring ↔ assessment connective tissue — (a) DONE 2026-07-26.**
  `DashboardPage.tsx` now has a per-row checkbox multi-select and a "Build
  assessment (N)" button that navigates to `/assessments/new` with `state:
  {preselected}`; `NewAssessmentPage.tsx` pre-populates its selection from that
  state, silently dropping any id not actually in the library (stale/archived/
  deleted) rather than leaving it invisibly included in the create payload.
  **(b) — lowest priority, explicitly deferred, unchanged:** creating a
  *brand-new* question from inside the builder. Keep question creation simple
  and owned by the questions page; the builder assembles, it shouldn't grow a
  second authoring flow unless there's real demand.
- **A12 · Enterprise branding — DONE 2026-07-26 (per-assessment + workspace
  default).** `Assessment.org_name`/`logo_url` (migration `0ae2d36aff72`,
  additive/nullable) are set on `NewAssessmentPage` (with a live preview) and
  shown read-only on `AssessmentDetailPage`; `InvitePublicOut` carries
  `assessment_title`/`org_name`/`logo_url` to the candidate, and `AssessmentFlow`'s
  IDE header renders `{logo} {org} — {title}` plus a small "Powered by
  assess.dev" when set, falling back to the generic "Coding assessment" header
  otherwise (a legacy single-question invite has no `Assessment` to brand from, so
  it's always unbranded). The logo is stored as a URL reference, never base64.
  **Workspace default added:** `Interviewer.default_org_name`/`default_logo_url`
  (migration `b7e2c1a4d9f0`, additive/nullable) set on a new **Settings → Workspace**
  page via `PATCH /auth/me` (partial update; blank normalises to null); it
  **pre-fills** a new assessment's branding (`NewAssessmentPage` seeds its org/logo
  from the current interviewer, still editable per assessment) — a snapshot, never
  applied retroactively, so changing the default leaves existing assessments
  untouched.

---

## B. Near-term deploy / residual

- **Set `TRUST_PROXY_HEADERS=true` when deploying behind a proxy.** The rate
  limiters key on the caller's address; behind a proxy that is the *proxy* for
  every request, collapsing every bucket into one shared counter (the first few
  callers 429 everyone else). Support exists, defaults OFF — safe for direct dev,
  wrong the moment there's a load balancer in front. A deploy-time checklist item.
  Chained proxies (CDN → LB) need `client_ip()` revisited, as it trusts one hop.
- **DB calls run on the event loop in the async agent routes (residual).** The six
  agent-calling routes `await` the agent over `httpx.AsyncClient`, so slow agent I/O
  no longer holds a pooled thread. But the DB is still synchronous SQLModel, so the
  small per-request queries there run on the event loop. Fine at this scale (indexed
  single-row ops, SQLite); if a slow Postgres query shows up on these paths, wrap the
  DB work in `run_in_threadpool` or move to an async engine. Not worth doing pre-emptively.
- **Claude Code tooling follow-ups (global, deferred — not platform code).** From the
  2026-07-17 setup audit, outside this repo: `~/.claude/CLAUDE.md` §8 and the "Use
  PROACTIVELY" agent descriptions contradict the harness's don't-auto-spawn rule;
  serena has no auto-activation (worked around by a CLAUDE.md note). All touch
  `~/.claude/`, shared with `../AssesmentAgent`.

---

## C. Backlog — table-stakes & hardening (open items moved from PRODUCT_BACKLOG)

- **CX2 · In-progress candidate code lives only in `localStorage`.** Autosave is
  debounced to `localStorage` (`CandidatePage.tsx:37,95`) — lost on cleared storage,
  incognito, or a device switch. Optional server-side draft persistence keyed by
  invite token so work survives a browser/device change. **M.**
- **AR1 · No aggregate analytics endpoints.** No stats/metrics/summary route; the
  dashboard is a question list. No cross-candidate comparison, pass-rate, percentile,
  or time-to-solve. **L.**
- **I1 · Integrity / proctoring suite (staged; scope agreed 2026-07-24).** Nothing
  present today. Build the first three; **webcam/video is DEFERRED.**
  - **Browser telemetry (do first, cheap):** tab/window blur + focus-loss timeline,
    fullscreen enforce + exit detection, paste events into the editor (size + whether
    it originated outside the page — flag a 200-line paste vs organic typing),
    devtools/right-click signals. Decide flag-vs-block per signal.
  - **Structural anti-cheat (our moat — prefer over surveillance):** per-candidate
    unique question variants (see D) makes a leaked bank useless and reduces the need
    for heavy proctoring at all.
  - **Integrity report:** per-attempt risk score + flagged-event timeline for the
    interviewer, so signals are actionable rather than raw logs.
  - **Identity / webcam — DEFERRED (do not build yet).** Start photo, periodic
    snapshots, optional continuous video. Held back deliberately: the cost isn't the
    capture, it's consent/compliance (GDPR/BIPA), storage, and bias/false-positive
    risk. Revisit only when a specific enterprise deal requires it. **M–L (the three
    active parts).**
- **I2 · Plagiarism / similarity detection** across submissions (token-fingerprint /
  MOSS-style; optionally match against public solutions + AI-generated-code detection).
  None present; largely mooted by per-candidate variants (see D). **L.**
- **Multi-question AI generation (cross-repo, enables per-candidate variants).**
  Today the drafter is one question per call. Add orchestration that produces a **set
  of K variants** for one brief + difficulty — do it by running the existing
  single-question drafter K times (each still executed-oracle-validated), **not** by
  asking one prompt for K questions (that dilutes each and worsens quality parity).
  Pin `difficulty` + `target_complexity` across the set so they're calibrated to the
  same band, and add a parity check (constraint sizes / `required_complexity` must
  match across the set) to catch "one variant harder than another". This is the
  natural feeder for per-candidate variants + assessment jumbling. Agent half (set
  orchestration + parity guard) also noted in the agent STATUS. **M.**
- **SEC1 · `REGISTRATION_CODE` unset by default → open interviewer sign-up.** Must be
  set in prod (`config.py:110`). Deploy-checklist item. **XS.**
- **SEC4 · Rate limiter is per-process**, won't hold across workers/instances
  (`ratelimit.py`). Fine for single-process dev; needs a shared store for horizontal
  scale. **M.**

---

## D. Net-new / future ideas (moved from PRODUCT_BACKLOG "good-to-have")

Not scheduled; the durable idea list to draw from.

- **Per-candidate unique question variants (build this — compounds the AI-authoring
  moat).** Hand each candidate a slightly different generated question from the same
  brief. Structurally defeats leaked-bank cheating and doubles as anti-cheat (reduces
  the need for I2). Cross-repo. 
- **Candidate-feedback agent (cross-repo, not yet chosen).** Actionable feedback to
  candidates; spans both repos (also parked in the agent STATUS).
- **Per-role rubric customization** — weight readability vs performance vs idiom.
- **Reference in the candidate's language** — generate the oracle in whatever language
  they submit (agent).
- **Difficulty auto-calibration** — feed real candidate pass-rates back to label
  difficulty empirically (pairs with AR1; cross-repo).
- **Cross-candidate analytics** — percentile, time-to-solve, per-question
  discrimination (= AR1).
- **ATS/webhook integration** (Greenhouse, Lever).
- **Question-bank UX** — tagging, search, clone/reuse.
- **Candidate practice mode** — a free funnel into the paid product.
