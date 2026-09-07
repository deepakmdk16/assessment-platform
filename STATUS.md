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

- **VS1 · Variant members leak into the question library + assessment builder
  — DONE 2026-07-26.** Saving a variant set creates N `Question` rows tagged
  `variant_set_id`; `list_questions` didn't filter them, so all N siblings showed
  in the dashboard library **and** the New-Assessment question picker as separate,
  near-identical problems ("3 variations of one problem" as 3 unrelated questions).
  Fix: `list_questions` now excludes `variant_set_id`-tagged questions by default
  (opt-in `?include_variants=true`), so a set shows as one thing, not N look-alikes.
  Backend-only — both the dashboard and the picker call the same `listQuestions`,
  so no frontend change. Was the stopgap for VS2.
- **VS2 · Assessment-slot integration for variant sets — DONE 2026-07-26.** A
  slot of an assessment can now be a variant-set pool
  instead of a fixed question, and each candidate is handed a different variant
  (round-robin), so "one slot → each candidate gets a different variant" works
  inside a multi-question sitting. **Data model:** `AssessmentQuestion.variant_set_id`
  (nullable; a slot is a fixed `question_id` XOR a `variant_set_id`) +
  `CandidateSlotVariant` keyed by `(invite, candidate_email, slot)`, which freezes
  the per-candidate pick — decoupled from `CandidateAttempt` so resolving a variant
  never stamps the timer and the interviewer results path can read it without
  creating an attempt (migration `e5b3c9d7a2f1`, additive; `question_id` made
  nullable). **Resolution:** `_invite_questions(invite, session, email)` is now
  candidate-aware — a set-slot resolves (and freezes, get-or-create + round-robin so
  the pool stays evenly used) to that candidate's variant, whose `question_id` then
  flows through view/run/submit/results exactly like a fixed question (zero
  candidate-side change). The results view (`/assessments/{id}/attempts`) resolves
  each candidate's own variant per set-slot and shows it under the set's title +
  the variant label. **API:** create/update take ordered `slots` (question XOR
  variant set); the legacy flat `question_ids` still maps to all-fixed slots so
  pre-VS2 clients need no change; the A9 lock compares the full slot signature.
  **Builder UI:** `NewAssessmentPage` now builds an ordered list of *slots* — the
  question library and a new "Your variant sets" source group both feed it, a
  set-slot renders with a cobalt rail + "Variant set" chip + "each candidate gets
  a random variant · N variants". `AssessmentDetailPage` shows the set-slot in the
  questions table and, in the attempts grid, names each candidate's assigned
  variant in the chip tooltip (column stays keyed by the set so it aligns).
  Backend + migration + 11 offline pytest + web vitest (builder mixed-slot create,
  detail set-slot + per-candidate variant) all green; mockup was signed off before
  the `.tsx`. **Feature complete end-to-end.** Only follow-up deliberately left:
  *regenerate a drifting variant* instead of the current advisory parity warning
  (tracked agent-side).
- **A7 · Invite paths separated, not merged — DONE 2026-07-26.** Both paths were
  duplicative/confusing once assessments existed. Decision (product): **keep both,
  relabel to two distinct tools** rather than deprecate either. The per-question
  path is now a **"Quick screen"** (card, button, dialog, and results table on
  `QuestionDetailPage` all relabelled; copy says it screens on *just this question*
  and links to Assessments for a multi-question sitting); the per-assessment path
  is **"Invite to this assessment"** (whole assessment, one shared timer). No data
  model change — both routes (`/questions/{id}/invites`, `/assessments/{id}/invites`)
  are unchanged; this is UI/copy only. Frontend unit + E2E tests updated for the
  new "Send quick screen" label (the E2E `createInvite` helper drives this path).
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
- **A13 · Timed-out submissions are recorded + flagged late — DONE 2026-07-26.**
  Found while testing VS2: a timed sitting (Google Assessment, `duration_minutes`
  was 2) showed no submissions even though candidates took it — every `/submit`
  past `deadline + grace` was rejected with a **410 and discarded**, silently
  losing the candidate's work (and contradicting the client, which already
  auto-submits at the buzzer *"so time running out records work instead of losing
  it"*). Now the timer no longer discards: `_submit_is_late` (replacing the raising
  `_enforce_deadline`) returns a bool, and `candidate_submit` **stores + grades**
  the submission either way, setting `Submission.late` (migration `f6c4d0b9e3a2`,
  additive, default False). The invite's own lifecycle (revoked / expired via
  `_load_invite_or_error`) still hard-blocks a submit — only the per-candidate
  timer is relaxed. `late` is surfaced on **every** interviewer submission
  surface (traced by `/integration-check`): the attempts grid (amber-ring chip +
  "submitted late" tooltip, keyed per candidate/slot so it works for VS2 variants
  too), the submission detail header, the global submissions list, the
  per-question ("Quick screen") results table, and the CSV export (`late` column)
  — the pills are the `chip-late` amber style. Backend + web tests
  updated (the old "past-grace ⇒ 410" timer test now asserts 201 + `late=true`);
  full suites green. **Note (sharpened 2026-08-03 while wiring the edit
  dialog):** the deadline is each attempt's own `started_at` + the assessment's
  *current* duration, read live at submit — so editing the duration moves
  every existing attempt's deadline immediately, in both directions (a shorter
  limit will flag in-flight candidates' future submits late; a longer one even
  un-lates a not-yet-submitted expired attempt server-side). What an edit
  still can't do is restart a sitting: the candidate's client auto-submitted
  at the buzzer it fetched at `/start` (the countdown only re-reads on
  reload), so re-invite remains the way to give a fresh clock. The edit
  dialog's duration hint states these semantics.

---

## B. Near-term deploy / residual

- **Set `TRUST_PROXY_HEADERS=true` when deploying behind a proxy.** The rate
  limiters key on the caller's address; behind a proxy that is the *proxy* for
  every request, collapsing every bucket into one shared counter (the first few
  callers 429 everyone else). Support exists, defaults OFF — safe for direct dev,
  wrong the moment there's a load balancer in front. A deploy-time checklist item.
  Chained proxies (CDN → LB) need `client_ip()` revisited, as it trusts one hop.
  The second limiter deploy knob is `RATE_LIMIT_BACKEND=db` for any multi-worker
  deploy (SEC4, §C — done; with the default `memory`, N workers multiply every
  limit by N).
- **DB calls run on the event loop in the async agent routes (residual).** The six
  agent-calling routes `await` the agent over `httpx.AsyncClient`, so slow agent I/O
  no longer holds a pooled thread. But the DB is still synchronous SQLModel, so the
  small per-request queries there run on the event loop. Fine at this scale (indexed
  single-row ops, SQLite); if a slow Postgres query shows up on these paths, wrap the
  DB work in `run_in_threadpool` or move to an async engine. Not worth doing pre-emptively.
  The background grading reaper's tick (`api._reap_tick`) is on the same footing.
- **Claude Code tooling follow-ups (global, deferred — not platform code).** From the
  2026-07-17 setup audit, outside this repo: `~/.claude/CLAUDE.md` §8 and the "Use
  PROACTIVELY" agent descriptions contradict the harness's don't-auto-spawn rule;
  serena has no auto-activation (worked around by a CLAUDE.md note). All touch
  `~/.claude/`, shared with `../AssesmentAgent`.

---

## C. Backlog — table-stakes & hardening (open items moved from PRODUCT_BACKLOG)

- **CX2 · Server-side draft persistence — DONE 2026-07-31.** In-progress
  candidate code used to live only in `localStorage` (lost on cleared storage,
  incognito, or a device switch). Now autosaved server-side too: `CandidateDraft`
  (migration `c8a4e6f2d190`, additive; one row per invite+candidate+question,
  upserted) behind `PUT /invite/{token}/draft` (same identity gates as /events —
  live link + invited recipient + a question the sitting serves; NOT gated on
  already-submitted, never starts a clock; own `draft_save` rate bucket, code
  capped at 100k chars) and `GET /invite/{token}/draft` (all of the sitting's
  drafts in one fetch; empty list, not 404, on a cold start). Client: both flows
  autosave debounced 2s fire-and-forget (localStorage keeps the 500ms fast path);
  restore prefers localStorage (freshest on the same browser), falling back to
  the server copy — `AssessmentFlow` seeds each question's editor from its own
  draft. No interviewer surface reads drafts — a draft is the candidate's own
  work-in-progress until submitted. No UI change beyond restored content (no
  mockup needed).
- **AR1 · Aggregate analytics — DONE 2026-07-27.** The dashboard was a bare
  question list with no stats/metrics route. **Backend:** a DB-free, unit-tested
  `analytics.py` (pass-rate, median/percentile, daily trend, time-to-solve,
  competition ranking) behind three owner-scoped endpoints —
  `GET /analytics/overview` (workspace totals + submission trend + score
  distribution), `GET /analytics/questions` (`Page`; per-question pass-rate,
  avg/median score, late count, avg/median time-to-solve; excludes archived +
  variant members), and `GET /analytics/assessments/{id}` (cross-candidate:
  per-candidate rank/percentile + whole-sitting time-to-solve, completion, score
  distribution; reuses the attempts assembly extracted into
  `_assessment_attempt_rows`). All three take an optional `?days=N` window (the
  submission-derived stats only; the question/library counts stay current). No
  migration — every field is computed or response-only. **Frontend (folded onto
  the dashboard, no new route):** an `AnalyticsPanel` above the question list —
  time-range toggle, KPI tiles, submission-trend + score-distribution charts
  (inline SVG, so no inline styles / raw colour), and a cross-candidate view per
  chosen assessment; the existing question table gained pass-rate/avg/median-time
  columns. Charts key off semantic tokens (good/warn/bad/accent). Full gate green
  (backend pytest, web vitest incl. new panel + format-helper tests, lint, types,
  build); mockup signed off before the `.tsx`. **Feature complete.**
- **I1 · Integrity / proctoring suite (staged; scope agreed 2026-07-24).**
  All three active parts are DONE — browser telemetry (2026-07-28), structural
  anti-cheat (variant sets, see below), and the integrity report (2026-07-31).
  **Webcam/video stays DEFERRED.**
  - **Browser telemetry — DONE 2026-07-28.** `IntegrityEvent` (migration
    `a9d1f4c07b53`, additive) records six signal kinds per sitting, keyed like
    `CandidateAttempt` by `(invite, candidate_email)` because a tab switch belongs
    to the *sitting*, not one question (each event still names the question that
    was open). The candidate UI (`web/src/integrity.ts`, one hook owned by
    `CandidatePage` for both flows so a multi-question sitting can't double-record)
    batches them to `POST /invite/{token}/events` — the one candidate route
    deliberately NOT gated on "already submitted" (the last batch flushes with the
    submit) and one that never creates an attempt (recording a tab switch must not
    start anyone's clock). Client-reported offsets are clamped server-side to the
    elapsed window. **flag-vs-block settled:** fullscreen is *enforced* (leaving
    blocks the editor behind a modal until they return; a browser that refuses
    fullscreen records `fullscreen_denied` and continues unlocked rather than
    trapping the candidate), outside pastes are *blocked*, everything else is
    flag-only. "Outside" = clipboard text not matching anything copied in-page this
    sitting (whitespace-normalized), so the candidate's own scratch code still
    pastes. Candidates are told on the start gate before identifying themselves —
    `GET /invite/{token}` carries `proctored` for exactly that. Monitoring is
    per-assessment (`Assessment.proctored`, defaults ON, builder checkbox); a
    legacy single-question "Quick screen" invite has no Assessment and is always
    monitored. Interviewer surface: an Integrity tab + header chip on
    `SubmissionDetailPage` (summary counts, then the timeline at offsets from the
    candidate's own start). **The whole thing is a deterrent, not proof** — it runs
    in the candidate's browser, so no signals ≠ a clean sitting, and an unmonitored
    sitting reports as such rather than as clean. Signals never touch the verdict.
    16 backend pytest + 14 web vitest green; mockup signed off before the `.tsx`.
    **The sitting's monitoring state is frozen on the invite** (`Invite.proctored`,
    migration `b1e7f3a52c94`, backfilled from each invite's assessment) rather than
    re-read from `Assessment.proctored`. `/integration-check` caught the live-read
    version rewriting history in both directions: relaxing an assessment after the
    fact hid evidence that had already been recorded, and tightening it made a
    sitting that genuinely ran unmonitored report as a clean one — the exact
    false-clean reading the flag exists to prevent. The panel also renders recorded
    events whatever the flag says; suppressing real evidence is never the safer
    default. The **attempts grid** carries a per-candidate signal count (null =
    unmonitored, which is not zero), so an interviewer can triage a sitting without
    opening each submission — and, more importantly, so a candidate who tripped
    signals and **never submitted** is visible at all: they have an attempt row but
    no submission to hang a report off.
    **Deliberately NOT built:** a risk score / ranking (that's the integrity-report
    part below). **Gap-closure DONE 2026-07-31:** the global submissions list, the
    per-question "Quick screen" results table, and the CSV export now carry the
    sitting's signal count alongside `late` (`integrity_signals`/`integrity_blocked`
    on both list rows; `integrity_signals`/`integrity_blocked_pastes` CSV columns,
    blank — never 0 — for an unmonitored sitting), reusing the attempts-grid
    semantics via one batched `_integrity_by_submission` helper and the existing
    `IntegrityCell` chip. **Gap closed 2026-08-03:** assessment settings are
    now editable from the UI — an Edit dialog on `AssessmentDetailPage` (title,
    timer, monitoring, branding) calls `PUT /assessments/{id}`, always sending
    the current `proctored` explicitly (the endpoint is full-replace and
    defaults it true) and resending the slot list verbatim so the A9 lock never
    trips on a settings-only edit. The question set itself stays deliberately
    non-editable in the UI: post-invite the server 409s it, and pre-invite
    editing would mean rebuilding the builder on the detail page — not planned
    unless there's real demand (the dialog says to create a new assessment).
  - **Structural anti-cheat (our moat — prefer over surveillance):** per-candidate
    unique question variants (see D) makes a leaked bank useless and reduces the need
    for heavy proctoring at all.
  - **Integrity report — DONE 2026-07-31 (branch `feature/i1-integrity-report`).**
    Deterministic, DB-free scoring in `integrity.py` (score 0-100 + level
    none/low/elevated/high + the reasons that drove it; severe signals —
    blocked outside pastes, devtools — dominate, ambient focus flicker
    accumulates slowly under per-kind caps; the two context kinds
    `paste_internal`/`fullscreen_denied` never score). Surfaced as
    `IntegrityReportOut.risk` (recorded events are always scored, whatever the
    monitoring flag; null only for a quiet unmonitored sitting),
    `AssessmentAttemptOut.integrity_risk`, and `integrity_risk` on both list
    rows + the CSV (null/blank = unmonitored, matching the count column). UI
    (mockup signed off before the `.tsx`): a risk banner on the Integrity tab
    — level pill + score, reasons with point contributions, and an always-on
    "not proof, never part of the verdict" disclaimer — and the shared grid
    chip now colours by level (high → red, elevated → amber, low → neutral)
    on the attempts grid, submissions list, and quick-screen table. A triage
    hint, never proof, never part of a verdict.
  - **Identity / webcam — DEFERRED (do not build yet).** Start photo, periodic
    snapshots, optional continuous video. Held back deliberately: the cost isn't the
    capture, it's consent/compliance (GDPR/BIPA), storage, and bias/false-positive
    risk. Revisit only when a specific enterprise deal requires it. **M–L (the three
    active parts).**
- **I2 · Plagiarism / similarity detection** across submissions (token-fingerprint /
  MOSS-style; optionally match against public solutions + AI-generated-code detection).
  None present; largely mooted by per-candidate variants (see D). **L.**
- **Multi-question variant sets (cross-repo, per-candidate unique variants) —
  DONE end to end (agent, platform backend, frontend, assignment, and the
  assessment-slot integration).** The agent
  half shipped (orchestration + parity guard + `POST /questions/draft-set`, see
  `../AssesmentAgent/STATUS.md`). **Platform backend landed** (branch
  `feature/multi-question-set-ui`): a variant **is** a `Question` tagged with
  `variant_set_id`/`variant_label` (reuses all question infra — test cases, preview,
  grading, invites), grouped by a new `VariantSet` table (migration
  `c3f1a7b2e5d8`, additive/nullable). `agent_client.draft_set` calls the agent;
  `POST /variant-sets/draft` (rate-limited, stateless) returns the drafted variants
  + set-level parity/shortfall warnings; `POST /variant-sets` persists a reviewed
  set (each variant clears the same case-count floor); `GET /variant-sets[/{id}]`
  list + detail, owner-scoped. **Frontend DONE** — dedicated **"Variant sets"**
  section (rail entry + list + New draft→review→save + detail), built on the app's
  real tokens/components. **Assignment DONE 2026-07-26** — `Invite.variant_set_id`
  (migration `d4a2b8c6f1e0`); `POST /variant-sets/{id}/invites` mints **one invite
  per recipient**, handing out variants **round-robin** (the rotation continues
  across calls so the set stays evenly used) with a per-recipient **override** to
  pin a variant; `question_id` holds the assigned variant, so the candidate flow
  resolves it exactly like a single-question invite (zero candidate-side changes).
  `GET /variant-sets/{id}/invites` + a detail-page invite panel show who got which
  variant. Fully offline-tested (platform pytest + web vitest green). **Feature
  complete end-to-end.** The assessment-slot integration this entry used to defer
  (a variant pool as a slot *inside* a multi-question assessment) shipped as **VS2
  — see §A**, which owns the detail. The only follow-up still open is agent-side:
  regenerating a drifting variant instead of the advisory parity warning.
- **SEC1 · `REGISTRATION_CODE` unset by default → open interviewer sign-up.** Must be
  set in prod (`config.py:110`). Deploy-checklist item. **XS.**
- **SEC4 · Rate limiter shared store — DONE 2026-08-03.** `RATE_LIMIT_BACKEND`
  selects the backend: `memory` (default, the existing in-process sliding
  window — unchanged for dev/tests) or `db` — fixed-window counters in a new
  `RateLimitCounter` table (migration `a4f8c2d6e9b1`, additive; nothing reads
  it unless the backend is selected), shared by every worker/instance on the
  same database, so limits hold fleet-wide with no new infrastructure (works
  on SQLite and Postgres alike). The hot path is one conditional atomic
  `UPDATE … SET count = count + 1 WHERE count < max`, so concurrent workers
  can't jointly overshoot; the first-hit INSERT race falls back to the same
  increment; a 429'd request never consumes quota (matching the memory
  backend); dead windows are swept lazily with a 1-day grace. 9 offline unit
  tests, driven through two limiter instances wherever cross-process sharing
  is the claim. **Deploy-checklist item:** set `RATE_LIMIT_BACKEND=db`
  whenever the API runs more than one process — with `memory`, N workers
  silently multiply every limit by N (companion knob to
  `TRUST_PROXY_HEADERS`, §B).

---

## D. Net-new / future ideas (moved from PRODUCT_BACKLOG "good-to-have")

Not scheduled; the durable idea list to draw from.

- **Per-candidate unique question variants — DONE** (shipped as variant sets, §C, and
  the assessment-slot integration VS2, §A). The only follow-up is agent-side:
  regenerate a drifting variant instead of the advisory parity warning.
- **Candidate-feedback agent (cross-repo, not yet chosen).** Actionable feedback to
  candidates; spans both repos (also parked in the agent STATUS).
- **Per-role rubric customization** — weight readability vs performance vs idiom.
- **Reference in the candidate's language** — generate the oracle in whatever language
  they submit (agent).
- **Difficulty auto-calibration** — feed real candidate pass-rates back to label
  difficulty empirically (pairs with AR1; cross-repo).
- **Cross-candidate analytics — DONE 2026-07-27 as AR1** (§C).
- **ATS/webhook integration** (Greenhouse, Lever).
- **Question-bank UX** — tagging, search, clone/reuse.
- **Candidate practice mode** — a free funnel into the paid product.

---

## E. SaaS-launch audit — 2026-09-06 (open items, ordered P0 → P3)

**How this list was produced (2026-09-06).** Every DONE claim in both STATUS files was traced
to code and tests by five independent read-only audits (agent claims, platform backend,
web frontend, SaaS readiness, code quality), then the high-impact claims were checked
live: both `checkpoints.sh` gates green (agent 265 passed / 4 skipped, platform 266
passed + web 113 vitest + build), Playwright E2E 9/9, the real-wire cross-repo smoke
(`scripts/smoke_e2e.py`) PASS, the full platform API flow (register → question →
assessment → invite → start → draft/events/run → submit → callback → attempts/CSV/
analytics → archive/delete → cross-owner 403) against a real **Postgres 16** with all 19
migrations applied, the agent **Docker image built** and its nsjail sandbox exercised
under `--privileged` over HTTP (egress blocked, 1 GB alloc killed, forks capped at 63,
C compiles, env clean), and every P1 below re-read at the cited lines. **Not validated:**
the three LLM surfaces (judge / drafting / adversarial) — no `ANTHROPIC_API_KEY` on the
machine and the local Ollama install is broken (see A24), and the weekly keyed CI evals
have been red since 2026-07-27 (A23). An adversarial re-verification workflow was
started; 19 independent refuters ran before the account session limit stopped it and
all 19 confirmed their finding (tagged below) — the remaining VERIFY-status items carry
the tag "single-audit claim". Priorities: **P0** blocks taking money or endangers
customers · **P1** first paying customers hit it · **P2** fix before scale · **P3** polish.
Effort: XS minutes · S self-contained · M multi-file · L data + API + UI.

Platform backend (P), web (W) and cross-repo/SaaS (X) items (55: P0: 4, P1: 9, P2: 35, P3: 7).
Agent-only items (A) live in `../AssesmentAgent/STATUS.md`.

**Suggested sequence** (the cheap P0/P1 blockers — P01, P02, P04, A01, A03, P09, P19,
A32, W01, W02 — the grading-durability epic — A04 + P05 + P10 + P15 — and the
account-lifecycle backend — P13 — landed 2026-09-07): (1) organisation → billing
(X01 → X02), with the P13 web pages alongside; (2) privacy
(X03, X04) and email/notifications (X06, X07); (3) deploy + ops (X05, X08, A06, A07,
P26, X11); (4) everything else by priority. Close each item by deleting it here in
the same commit (checkpoint #5).

- **P13 · P1 (was P0) · S — Account-lifecycle web pages (backend landed 2026-09-07).**
  The API side is done: min-12/≤72-byte passwords + HIBP breach check, lower-cased
  emails (backfilled by migration `e3b9a7c1d052`), 15-min access token held in
  memory + 30-day httpOnly refresh cookie on `/auth`, `token_version` revocation,
  and `/auth/{refresh,logout,forgot-password,reset-password,change-password,
  verify-email,resend-verification}` + `DELETE /auth/me` (purges everything the
  account owns). The SPA resumes sessions via the cookie. Still missing: the
  pages that use the new routes — forgot/reset-password, verify-email landing,
  "Forgot password?" on login, a Security section in Settings (change password,
  delete account), and an unverified-email banner with resend. Mockup-first rule
  applies (CLAUDE.md); nothing is gated on verification yet.
  _Follow-up opened 2026-09-07 while closing the original P13._

- **X01 · P0 · L — No organisation/team model — one login per company.**
  Evidence: only Interviewer rows (platform models.py:43-55); every resource is
  owner_id-scoped (api.py:504-521); "workspace" means one interviewer's default
  branding (models.py:52-53); no membership/role/admin/audit-log tables (grep:
  none). Why: a second hiring manager sees nothing; no hand-off when someone leaves;
  blocks any team plan. Fix: Organization + Membership(role); move owner_id FKs to
  org_id; scope queries by membership; org invites replace REGISTRATION_CODE.
  _Verified: cited lines read in this audit; source: saas._
- **X02 · P0 · L — No billing, plans, quotas or usage metering; LLM spend is not
attributable per tenant.**
  Evidence: grep Stripe|plan|quota|usage in both packages: none; limits are per-IP
  buckets only (config.py:145-167); per-candidate judge cost is computed on the
  agent (pricing.py:12-44, judge.py:287-294) and shipped as judge_cost_usd inside
  the callback (agent.py:203) which the platform stores verbatim in
  AssessmentResult.full_result JSON and never aggregates; draft cost surfaces per
  draft only (api.py:686,770-792). Why: cannot take money; one interviewer can burn
  unlimited Sonnet drafts and compute. Fix: Stripe Checkout + plan on the org;
  monthly counters (assessments, drafts, candidates) enforced in draft/invite/submit
  routes; denormalise judge_cost_usd/draft_cost_usd into columns with a per-org
  rollup.
  _Verified: cited lines read in this audit; source: saas._
- **X03 · P0 · M — No PII erasure or retention path for candidate data.**
  Evidence: deletion is refused once activity exists (api.py:1062-1103); no
  candidate-scoped delete anywhere; PII stored in Submission (name/email/code),
  IntegrityEvent, CandidateDraft, CandidateAttempt; no retention job; no
  backup/restore doc. Why: GDPR/CCPA erasure requests cannot be honoured; a customer
  DPA will require it. Fix: org-scoped DELETE /candidates/{email} that anonymises
  the four tables; RETENTION_DAYS purge job; document backups/RPO/RTO.
  _Verified: cited lines read in this audit; source: saas._
- **X04 · P0 · S — No privacy policy, terms, DPA or recorded consent for
proctoring.**
  Evidence: web/src/components/IntegrityGate.tsx:10-22 is a notice, not a consent
  record; no policy/terms links anywhere in web/src; nothing stored on
  CandidateAttempt about consent. Why: selling monitored assessments to
  EU/UK/California candidates without a documented lawful basis is
  customer-blocking. Fix: explicit consent checkbox stored on CandidateAttempt;
  privacy-policy + terms links; a DPA template (legal review).
  _Verified: cited lines read in this audit; source: saas._
- **P03 · P1 · S — Assessment and variant-set invites cannot be revoked (no route,
no UI); archiving does not stop links.**
  Evidence: the only revoke route requires Invite.question_id == question_id
  (api.py:1992-2003); assessment invites have question_id=None (api.py:1437-1446);
  live: revoke via the question route → 404; _load_invite_or_error checks only
  invite status/expiry (api.py:2023-2026); the API's own 409 text says "Revoke its
  invites instead" (api.py:1067,1101); web has revoke only on QuestionDetailPage
  (api.ts:247-251) and never lets expires_at be set (api.ts:204,236). Why: a leaked
  assessment link stays live indefinitely. Fix: owner-scoped POST
  /assessments/{id}/invites/{token}/revoke (+ variant-set) and UI revoke/expiry
  controls on both surfaces.
  _Verified: live run in this audit; source: backend,frontend,live._
- **W03 · P1 · S — Every list row is mouse-only.**
  Evidence: <tr className="clickable-row" onClick=navigate> with no link/focusable
  target inside at pages/DashboardPage.tsx:170-174, AssessmentsListPage.tsx:113-117,
  VariantSetsListPage.tsx:81-86, SubmissionsPage.tsx:118-123,
  QuestionDetailPage.tsx:287-293 (attempts chips do it right:
  AssessmentDetailPage.tsx:238-243). Why: keyboard/screen-reader users cannot open a
  question, assessment, set or submission (WCAG 2.1.1). Fix: wrap the title cell in
  a <Link>; keep the row click as a convenience.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **X05 · P1 · M — No platform container, prod entrypoint, migration-on-start, or
compose; the agent needs a privileged host.**
  Evidence: only AssesmentAgent/Dockerfile exists; no Dockerfile for the platform or
  web, no compose/helm/fly/render/railway/Procfile; scripts/dev.sh:18 runs alembic
  upgrade head for dev only; the agent Dockerfile requires --privileged
  --cgroupns=host (Dockerfile:9-19). Why: first deploy is hand-assembled; a
  forgotten migration 500s; hosting choice is constrained. Fix: platform Dockerfile
  (uv + alembic upgrade head && uvicorn), static web build behind nginx,
  docker-compose wiring agent (privileged) + platform + Postgres; docs/DEPLOY.md.
  _Verified: cited lines read in this audit; source: saas._
- **X06 · P1 · S — Results never reach the interviewer proactively.**
  Evidence: agent_client.py:260 passes email_to=None; no notification or webhook
  code in the platform; the agent's Gmail mailer (mailer.py:29-30,103-106) is
  CLI/direct-API only. Why: interviewers must poll the dashboard to learn a
  candidate finished. Fix: "results ready" email from assessments_callback
  (api.py:3129) via email_client, plus a per-org webhook.
  _Verified: cited lines read in this audit; source: saas._
- **X07 · P1 · S — Email deliverability is not production-grade.**
  Evidence: invites go via smtplib STARTTLS (email_client.py:37-48) with SMTP_FROM
  default no-reply@assessment.local (config.py:130-135); plain text, no templates,
  no unsubscribe/consent footer; README:96-101 already warns Gmail is test-only.
  Why: invites land in spam; candidates miss interviews; the default from-address is
  invalid. Fix: Postmark/SES with a verified domain (SPF/DKIM/DMARC), HTML+text
  templates, per-org reply-to.
  _Verified: cited lines read in this audit; source: saas._
- **X08 · P1 · S — No metrics, tracing or error reporting in either service.**
  Evidence: grep Sentry|opentelemetry|prometheus|/metrics in both packages: none;
  agent /health is static; platform logging unconfigured (P19). Why: no way to see
  failed callbacks, grading latency or error rates. Fix: Sentry in both services;
  /metrics (job count, grade latency, callback failures); structured JSON logs with
  request ids.
  _Verified: cited lines read in this audit; source: saas._
- **X09 · P1 · S — Rate limits are per-IP, never per-tenant, in both services.**
  Evidence: platform config.py:145-167 and api.py:433,461,2480 key on client_ip;
  agent ratelimit.py per-IP and in-memory (A13). Why: an office behind one NAT
  shares one bucket; one tenant cannot be capped independently. Fix: key expensive
  buckets (draft, submit, invites) on org_id in addition to IP; agent limiting moved
  to the platform's DB backend.
  _Verified: cited lines read in this audit; source: saas._
- **X10 · P1 · M — Interviewer-facing gaps a first paying customer hits.**
  Evidence: no team (X01); no question import/bulk upload (only hand-form or AI
  draft, api.py:554); no candidate-facing feedback or score (CandidatePage.tsx:345);
  no re-invite/extend-deadline (STATUS.md:118-121); no custom domain/white-label
  beyond logo/org text (models.py:165-166); no ATS/webhook (STATUS.md:337); no
  self-serve org onboarding. Why: procurement and onboarding stall on table-stakes
  features. Fix: prioritise team, notifications, import, re-invite after the P0s.
  _Verified: cited lines read in this audit; source: saas._
- **P06 · P2 · XS — POST /invite/{token}/events accepts any question_id.**
  Evidence: api.py:2572-2584; live: unknown id → 500 ForeignKeyViolation; another
  tenant's valid id is stored and then blocks that tenant's DELETE /questions/{id}
  via the IntegrityEvent guard (api.py:1087-1093). Why: unauthenticated route can
  500 and cross-tenant-pollute. Fix: resolve through _resolve_question (must belong
  to the invite) or null it.
  _Verified: live run in this audit; source: backend,live._
- **P07 · P2 · XS — CSV export is vulnerable to formula injection.**
  Evidence: api.py:2872-2884 writes candidate-supplied candidate, candidate_email
  and titles raw. Why: a candidate name starting with = + - @ executes in Excel on
  the interviewer's machine. Fix: quote/prefix cells that start with those
  characters.
  _Verified: cited lines read in this audit; source: backend._
- **P08 · P2 · S — Candidate email plus the secret token land in access logs via the
draft GET query string.**
  Evidence: GET /invite/{token}/draft?candidate_email= (api.py:2641-2645,
  web/src/api.ts:322); uvicorn logs the query string regardless of LOG_PII;
  test_logging_redaction.py covers only email_client. Why: PII + bearer-equivalent
  token in plain logs. Fix: carry the email in a header or POST body.
  _Verified: cited lines read in this audit; source: backend._
- **P11 · P2 · M — N+1 and heavy list queries.**
  Evidence: list_questions lazy-loads test_cases per row and ships full test cases +
  reference solutions (api.py:194-204, 954); list_variant_sets per-row count
  (896-898); list_assessments per-slot VariantSet get + count + lazy aq.question
  (1134-1150); _assessment_attempt_rows per-invite session.get(Invite) (1621-1625);
  analytics_overview loads every owner Submission including code (1783-1788);
  analytics_assessment re-queries rows it already has (1938-1946). Why: latency
  grows linearly with library size; analytics pulls every candidate's source. Fix:
  selectinload, aggregate queries, defer(code), slim list schemas.
  _Verified: single-audit claim, not independently re-verified; source: backend._
- **P12 · P2 · S — No pagination on invite and attempts list routes while README
claims list endpoints paginate.**
  Evidence: api.py:1410 GET /questions/{id}/invites, 1462 /assessments/{id}/invites,
  1536 /variant-sets/{id}/invites, 1551 /assessments/{id}/attempts return unbounded
  lists; README:141. Why: large assessments return unbounded payloads. Fix: Page
  envelope + limit/offset like the other lists.
  _Verified: single-audit claim, not independently re-verified; source: backend._
- **P14 · P2 · S — Every timestamp column is timezone-naive; correctness on Postgres
depends on the session time zone.**
  Evidence: grep DateTime(timezone=True) in models.py: 0; sa.DateTime() in
  migrations: 26; models.py:24-31 as_utc relabels naive values as UTC; nothing pins
  TimeZone on connect (db.py:44-46); CSV created_at.isoformat() emits no offset on
  SQLite. Why: deadlines/expiry shift by the DB offset if the server or DB TZ isn't
  UTC. Fix: `SET TIME ZONE 'UTC'` on connect for Postgres (or migrate to
  DateTime(timezone=True)); emit offsets in CSV.
  _Verified: cited lines read in this audit; source: backend._
- **P16 · P2 · XS — AssessmentUpdate.proctored defaults True on PUT.**
  Evidence: schemas.py:176; a client omitting the field on a settings edit silently
  turns monitoring on for future invites. Why: silent behaviour change on a
  full-replace endpoint. Fix: make proctored required on PUT.
  _Verified: cited lines read in this audit; source: backend._
- **P18 · P2 · S — Integrity-event volume is unbounded per sitting and all candidate
buckets are per-IP.**
  Evidence: 50 events/batch × 20 batches/min/IP (api.py:2550-2552, schemas.py:814)
  with no per-sitting cap; a corporate NAT shares 20 starts/submits/batches per
  minute. Why: table bloat from one sitting; a whole office shares one bucket. Fix:
  per-sitting cap on stored events; key candidate buckets on (token, email) as well
  as IP.
  _Verified: single-audit claim, not independently re-verified; source: backend._
- **P20 · P2 · XS — The callback handler ignores the shared contract; malformed
payloads 500 or get stored.**
  Evidence: contract/callback_contract.py:validate_callback is imported only by
  tests/test_contract.py (no runtime use in either package); api.py:3153-3156
  coerces verdict = str(payload.get("verdict") or "ERROR") (stores "PASSED") and
  float(payload.get("score_pct") or 0.0) raises on non-numeric → 500 → agent retries
  4× then drops. Why: the byte-mirrored contract exists to gate this and doesn't.
  Fix: errors = validate_callback(payload); if errors: log + 400.
  _Verified: single-audit claim, not independently re-verified; source: quality._
- **P21 · P2 · XS — Candidate-facing 502s echo internal exception text.**
  Evidence: api.py:2394,2396 (/invite/{token}/run, /run-tests) and 2695 (/submit)
  return f"… failed: {exc}"; for httpx.HTTPStatusError that is "Server error '500 …'
  for url 'http://<agent-host>:8000/run'" to an unauthenticated candidate; 677/764
  do the same to interviewers; _agent_detail (602) sanitises only the 400 case. Why:
  leaks internal topology and agent status. Fix: log exc, return a fixed message
  ("grader unavailable, try again").
  _Verified: cited lines read in this audit; source: quality._
- **P22 · P2 · M — api.py is a 3,196-line god-module with the split seams already
drawn.**
  Evidence: 52 routes, 132 top-level defs, 13 banner sections (lines 160, 383, 399,
  500, 691, 1117, 1370, 1721, 2014, 2674, 3032, 3084); maintainability index 0;
  _assessment_attempt_rows 1567-1720 has cyclomatic complexity 40; four copies of
  the load+404/403 helper (504, 514, 699, 1121); archive/unarchive pairs duplicated
  (1007-1042 ≡ 1312-1343); create_invite ≡ create_assessment_invite (1375-1408 vs
  1424-1460); count+slice pagination ×8; manual updated_at writes ×9 despite
  onupdate=_utcnow (models.py:40); Questions CRUD (924-1115) sits under the "Variant
  sets" banner. Why: every feature touches one file; reviews collide; the 154-line
  function is where the next bug lands. Fix: APIRouter per banner into
  routes/{auth,questions,variant_sets,assessments,invites,analytics,candidate,submissions,callback}.py;
  serializers → mappers.py; one generic _owned(Model, id, current, session) +
  _page(stmt, limit, offset); drop manual updated_at.
  _Verified: cited lines read in this audit; source: quality,backend._
- **P23 · P2 · XS — The platform test suite is ~6× slower than the agent's because
every test pays bcrypt cost 12.**
  Evidence: tests/conftest.py:124-128 registers + logs in per test → auth.py:27
  bcrypt.gensalt() default rounds; --durations shows ~0.36 s setup per test; live:
  266 tests in 77.65 s vs agent 265 tests in 12.9 s including real subprocesses.
  Why: the pre-push gate and dev loop pay ~90 s for hashing. Fix: BCRYPT_ROUNDS env
  (default 12, tests 4) read in auth.py, or an autouse fixture monkeypatching
  gensalt.
  _Verified: live run in this audit; source: quality,live._
- **P26 · P2 · S — The cross-repo parity gates (signing.py, callback contract) never
run in CI.**
  Evidence: scripts/checkpoints.sh (agent :41,59; platform :70,88) skip the
  byte-parity checks when ../<companion> isn't checked out — always the case in CI
  (single-repo checkout); CLAUDE.md says "fails the push on divergence" but that
  holds only with the opt-in pre-push hook, bypassable with --no-verify. Why: a
  divergence 401s every signed request or lets one side bless a payload the other
  rejects. Fix: CI step that checks out the companion repo (actions/checkout with
  repository:/path:) before checkpoints, or a published checksum both CIs assert.
  _Verified: cited lines read in this audit; source: quality._
- **P28 · P2 · S — Docs drift bundle (platform): README, STATUS, CLAUDE.md,
docstrings and .env.example lag the code.**
  Evidence: README.md:137-140 "/submissions* routes are not yet behind interviewer
  auth" (they are: api.py:2745,2800,2895); README.md:115-136 route table omits PATCH
  /auth/me, /assessments*, /variant-sets*, /analytics/*,
  /invite/{token}/events|draft, /submissions/export|{id}/integrity|{id}/report, and
  says GET /invite/{token} returns only status; README.md:147-170 data model lists 5
  of 13 tables; README.md:141-144 "list endpoints are paginated" (four aren't);
  config.py:181 "submit later than deadline + grace is refused" (stale since A13);
  schemas.py:576-578 InvitePublicOut.proctored comment says it reads
  Assessment.proctored (reads the frozen Invite.proctored); models.py:9-10 "every
  table carries created_at/updated_at" (untrue for CandidateSlotVariant,
  IntegrityEvent, CandidateDraft, RateLimitCounter); models.py:262 deadline formula
  wrong for assessment invites; STATUS.md:237-245 edit-dialog claim (P02);
  STATUS.md:300 cites config.py:110 (is :116); api.py:1067,1101 "Revoke its invites
  instead" impossible for assessment invites; agent_client.py:4 "four calls" (six);
  .env.example omits RATE_LIMIT_BACKEND, SUBMIT_GRACE_SECONDS,
  DRAFT_SAVE_RATE_LIMIT_MAX; CLAUDE.md:29-42 architecture omits ratelimit.py,
  email_client.py, question_rules.py; STATUS.md §D first bullet "Per-candidate
  unique question variants (build this)" already shipped (§C variant sets + §A VS2)
  and "cross-candidate analytics (= AR1)" is done; STATUS §A carries only DONE
  entries against the pending-only rule; web/README.md routes/tests stale and says
  the candidate page calls /submit with no /start. Why: a new operator or agent
  inherits wrong facts; the docs-drift gate covers only module names. Fix: one docs
  pass; add a route-table drift check to checkpoints.sh; prune DONE entries from
  STATUS.md.
  _Verified: single-audit claim, not independently re-verified; source:
  backend,saas._
- **W04 · P2 · S — The localStorage draft is keyed by token only and always beats
the server copy.**
  Evidence: key DRAFT_PREFIX + token (CandidatePage.tsx:40,150); restore order
  loadDraft(token) ?? server (:198-199) ignores updated_at (types.ts:386) and
  candidate email, while invites are multi-recipient (types.ts:183). Why: on a
  shared machine candidate B inherits A's unsubmitted code; a stale local draft
  hides newer work saved from another device. Fix: key the local draft by token +
  email and compare timestamps before choosing.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W05 · P2 · XS — The fullscreen "block" does not lock the keyboard.**
  Evidence: .modal-scrim is a pointer overlay only (components.css:2536-2546);
  Monaco readOnly is timeUp (CandidatePage.tsx:534) / locked
  (AssessmentFlow.tsx:405) and never includes mustReturnToFullscreen; the dialog
  moves no focus (IntegrityGate.tsx:54); STATUS says leaving fullscreen "blocks the
  editor". Why: a candidate who exits fullscreen can keep typing behind the scrim.
  Fix: add || integrity.mustReturnToFullscreen to readOnly and focus the modal
  button on open.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W06 · P2 · XS — The Integrity tab shows "Loading…" forever when the report fetch
fails.**
  Evidence: SubmissionDetailPage.tsx:92-97 swallows the error and leaves integrity
  null, so :212-217 renders the loading text indefinitely. Why: interviewer can't
  tell failed from slow. Fix: track a failed state and show an error line.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W07 · P2 · XS — The header IntegrityChip hides recorded events for an
unmonitored sitting, contradicting the panel and tab.**
  Evidence: IntegrityPanel.tsx:172 `if (!report.monitored || report.summary.total
  === 0) return null` while the panel deliberately shows those events (:102-105) and
  the tab badge counts them (SubmissionDetailPage.tsx:206); STATUS principle:
  recorded evidence is never suppressed. Why: header and tab disagree on the same
  sitting. Fix: drop the !report.monitored guard in the chip.
  _Verified: cited lines read in this audit; source: frontend._
- **W08 · P2 · XS — Pydantic 422 validation errors surface as "[object Object]".**
  Evidence: api.ts:101 assigns data.detail (an array for validation errors) straight
  into the Error message; every page prints err.message; only AddQuestionPage:38
  handles the list form. Why: unactionable errors on any schema failure (e.g. the
  empty-code submit). Fix: normalise in request(): if detail is an array, join the
  msg fields.
  _Verified: cited lines read in this audit; source: frontend,quality._
- **W09 · P2 · XS — A transient network failure on boot logs the interviewer out.**
  Evidence: auth/AuthContext.tsx:35-39 clears the token on any me() rejection, not
  just 401. Why: flaky Wi-Fi forces a re-login. Fix: clearToken() only on ApiError
  401; otherwise keep the token and retry.
  _Verified: cited lines read in this audit; source: frontend._
- **W10 · P2 · M — Error handling is per-page ad hoc; no request timeout;
ErrorBoundary only logs; 401 redirect loses returnTo.**
  Evidence: global handling exists only for 401 (api.ts:93-95,333,352 → logout,
  AuthContext.tsx:21-25); 403/404/410/429/5xx/network fall through to ~19 copies of
  `err instanceof ApiError ? err.message : 'Failed to …'` (47 setError call sites);
  QuestionDetailPage.tsx:46-60 discards the server detail and blanks the page if any
  of three fetches fails (:147) with no cancelled guard; api.ts:87-91 has no
  AbortController/timeout; components/ErrorBoundary.tsx:24-27 only console.errors;
  api.ts itself has no unit test (12 files vi.mock the whole client). Why:
  inconsistent UX, hung requests hang the page, no error telemetry. Fix: central
  describeError(err) + toast; AbortController with timeout; wire an error reporter;
  one api.test.ts.
  _Verified: single-audit claim, not independently re-verified; source:
  frontend,quality._
- **W11 · P2 · XS — Integrity monitoring and the countdown keep running after a
multi-question sitting completes.**
  Evidence: enabled: stage === 'editor' && proctored (CandidatePage.tsx:125) and
  stage never leaves editor in the multi flow (AssessmentFlow.tsx:272-279 renders
  the completion notice internally). Why: post-completion tab switches are recorded
  against the sitting. Fix: AssessmentFlow calls an onComplete that flips stage.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W12 · P2 · S — Silent truncation at 100/200 rows.**
  Evidence: builder library NewAssessmentPage.tsx:42 (200, no pager); submissions
  title map SubmissionsPage.tsx:12; per-question stats DashboardPage.tsx:37;
  analytics assessment picker AnalyticsPanel.tsx:59 (default 100). Why: larger
  workspaces silently lose rows and stats. Fix: page or search these sources.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W13 · P2 · XS — The logo URL is rendered unvalidated in the candidate's
browser.**
  Evidence: NewAssessmentPage.tsx:207-208 live-previews whatever is typed;
  AssessmentFlow.tsx:288 renders it for candidates; check whether schemas.py
  validates logo_url (https only). Why: http:// logos trigger mixed content; the
  candidate's IP is sent to an arbitrary host. Fix: require https:// client- and
  server-side.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W14 · P2 · S — Accessibility details.**
  Evidence: builder reorder/remove buttons named "↑", "↓", "✕" and every picker row
  has an identical "Add" (NewAssessmentPage.tsx:250-258,285,313); per-recipient
  variant <select> has no label (VariantSetInvitePanel.tsx:118-131); bare <label>
  without htmlFor (AddQuestionPage.tsx:521,530); sidebar active link has no
  aria-current (Sidebar.tsx:35-74); ARIA tablist without arrow-key handling
  (AssessmentFlow.tsx:319-333); Monaco Tab-trap has no escape hint; positives:
  native <dialog> + autoFocus for invite/edit, role="alert"/"status" used
  consistently. Why: WCAG name/role/value failures on interviewer surfaces. Fix:
  accessible names/labels, aria-current, arrow keys on the tablist; add jsx-a11y
  lint.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W16 · P2 · M — Duplicated logic that should be shared.**
  Evidence: candidate IDE panel duplicated ~130 lines (CandidatePage.tsx:491-623 vs
  AssessmentFlow.tsx:368-495) plus countdown (:298-309 / :160-170), auto-submit and
  doRun; CandidatePage.tsx:433-436 re-inlines timerClass from
  candidateTimer.ts:9-11; three recipient parsers with different semantics
  (QuestionDetailPage.tsx:95-98, AssessmentDetailPage.tsx:54-57,
  VariantSetInvitePanel.tsx:7-18 — only the last lowercases/dedupes); invite table +
  delivery warning duplicated (QuestionDetailPage.tsx:193-262,348-357 vs
  AssessmentDetailPage.tsx:279-331,342-351); copyUrl ×3
  (VariantSetInvitePanel.tsx:173 has no feedback and an unhandled rejection);
  branding preview ×2 (NewAssessmentPage.tsx:204-215, SettingsPage.tsx:84-92);
  archive toggle ×2; three duration formatters (analytics/format.ts:22-36,
  IntegrityPanel.tsx:16-20, candidateTimer.ts:14-21); 15 pages hand-roll
  useEffect+cancelled+Promise.all. Why: divergent behaviour (recipient parsing) and
  double maintenance. Fix: shared CandidateIde + useCountdown + useAsync hooks; one
  parseRecipients; one InviteTable; one formatDuration.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W17 · P2 · XS — components.css carries raw colour literals against the token
rule; the hex guard scans only .tsx.**
  Evidence: 21 raw colour literals in styles/components.css (lines 36, 38, 45, 76,
  77, 82, 83, 156, 157, 164, 167, 196, 197, 368, 374, 548, 1009, 1227, 1321, 1330,
  1554); worst .editor-wrapper { background: #1e1e1e } (:1554) is Monaco-dark in the
  light theme; scripts/check-no-hex.mjs:8,15 scans only .tsx and only hex; the
  ESLint rule catches only JSX style. Why: a re-theme cannot be done in tokens.css
  alone as CONVENTIONS promises. Fix: move the literals to tokens; extend the guard
  to .ts and rgb()/hsl().
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W18 · P2 · S — Hand-written types.ts mirrors 66 pydantic schemas with no drift
gate.**
  Evidence: types.ts (627 lines, 61 exports) vs schemas.py (66 classes); no OpenAPI
  generation; api.ts:112 is an unchecked `as T`; looseness already exists:
  QuestionIn.required_complexity: string vs backend str | None (schemas.py:98),
  InviteStatus = string (types.ts:163). Why: a renamed/nullable backend field ships
  silently. Fix: openapi-typescript from /openapi.json → types.gen.ts with a CI diff
  step.
  _Verified: cited lines read in this audit; source: quality._
- **W19 · P2 · M — E2E covers only the single-question quick-screen path.**
  Evidence: five specs (interviewer-candidate-flow, invite-lifecycle, candidate-run,
  submission-report, draft-with-ai); e2e/mock-agent.mjs serves /questions/draft,
  /run, /run/tests, /assessments only (no /questions/draft-set); uncovered: login
  page, logout/401, assessment builder (mixed slots, A8 preselect), assessment
  detail (invite, attempts grid, edit dialog, A9 409), variant sets
  (draft/review/save/detail/round-robin/override), set-slot assessment +
  per-candidate variant, multi-question candidate flow, timer/auto-submit/late pill,
  integrity (gate, modal, paste block, events → tab, risk banner, chips), draft
  autosave, analytics, settings/branding, archive, pagination, CSV, PDF, expired
  invite, theme toggle, narrow layout; rate limits are off in E2E so 429 UX is
  untestable. Why: the multi-question, variant-set and integrity features that
  define the product have zero browser coverage. Fix: extend the mock agent
  (draft-set) and add specs for the highest-value flows (assessment
  build→invite→multi-question sitting→attempts grid; variant set → set-slot;
  integrity gate).
  _Verified: cited lines read in this audit; source: frontend._
- **X11 · P2 · XS — No dependency vulnerability scanning, Dependabot, security
headers or HTTPS enforcement docs.**
  Evidence: .github/ in both repos has only workflows/; checkpoints.sh secret scan
  is regex-only; no pip-audit/npm audit in CI; no security-headers middleware (rely
  on the proxy, undocumented). Why: CVEs in bookworm toolchains/node/react go
  unnoticed; headers depend on an undocumented proxy. Fix: Dependabot (pip, npm,
  docker, actions) + pip-audit/npm audit --audit-level=high in CI;
  HSTS/CSP/X-Frame-Options at the proxy, documented.
  _Verified: cited lines read in this audit; source: saas._
- **X12 · P2 · M — Candidate identity is a claim; recipient enumeration via
/start.**
  Evidence: platform api.py:2030-2043: a forwarded link + a guessed invited email =
  impersonation; 403 vs 200 on /start reveals which emails were invited;
  README:109-113 documents the model. Why: a shared link can be sat by anyone who
  knows a recipient's address. Fix: per-recipient tokens (one Invite row per
  recipient) or an emailed OTP at start.
  _Verified: single-audit claim, not independently re-verified; source: saas._
- **X13 · P2 · S — No API versioning; boot-time config validation missing.**
  Evidence: no /v1 prefix on platform routes; agent app version "0.2.0", platform
  "0.1.0" (api.py:69-71); config.py:91-97 generates an ephemeral JWT_SECRET with
  only a warning; no fail-fast for missing tokens/secrets in production. Why:
  customers integrating CSV/ATS/webhooks can't be evolved safely; a prod boot with a
  missing secret silently rotates every session. Fix: /v1 prefix on public platform
  routes; ENV=production check that refuses to boot without
  JWT_SECRET/ASSESS_API_TOKEN/CALLBACK_TOKEN.
  _Verified: cited lines read in this audit; source: saas._
- **X14 · P2 · S — AGPL-3.0 + informal commercial offer will cause procurement
friction (not legal advice).**
  Evidence: both LICENSE files are AGPL-3.0 (switched 2026-09-05); README.md:302-313
  offers a commercial licence via a GitHub issue; no CLA, EULA or pricing. Why:
  enterprise legal teams often blocklist AGPL; any outside contribution without a
  CLA removes the right to relicense. Fix: keep AGPL for the community edition;
  publish a written commercial EULA + pricing; require a CLA.
  _Verified: cited lines read in this audit; source: saas._
- **X15 · P2 · XS — Cost-per-candidate numbers in STATUS are misread; authoring cost
is not baselined; no per-tenant rollup.**
  Evidence: agent STATUS.md:190-193 reports 4,202 input / 3,153 output / 17,730
  cache-read tokens for a 7-candidate eval run (eval.py:133-138 prints totals then
  averages) ≈ $0.0109 per candidate on Sonnet ($3/$15 per M, cache read 0.1×,
  pricing.py:17,21-22); STATUS.md:175-176 treats the same figures as per-candidate;
  authoring bound: max_tokens=8000 (authoring.py:861) × up to 2 attempts ≈
  $0.25-0.30 worst case per draft, ×K≤8 per variant set; judge skipped entirely when
  code fails to execute (agent.py:93-95). Why: pricing decisions built on a 7×
  overstated cost; drafts are the real spend and unmetered. Fix: correct the STATUS
  numbers; baseline draft cost; roll up judge_cost_usd/draft_cost_usd per org (X02).
  _Verified: single-audit claim, not independently re-verified; source: saas._
- **X16 · P2 · XS — Proxy trust is single-hop and the agent limiter is in-memory
only.**
  Evidence: platform ratelimit.py:156-177 trusts one X-Forwarded-For hop; agent
  ratelimit.py:1-9 in-process. Why: CDN→LB chains mis-key the limiter; a second
  agent replica doubles agent-side limits. Fix: configurable trusted-hop depth; move
  agent limiting to the platform.
  _Verified: cited lines read in this audit; source: saas._
- **A30 · P3 · XS — Python versions differ per repo and none match production.**
  Evidence: agent CI pins 3.10, platform CI 3.12, both declare >=3.10, local venvs
  3.12, agent Dockerfile ships Debian bookworm python3 (3.11); no matrix. Why: a
  3.11-only failure in the image is invisible to CI. Fix: strategy.matrix.python:
  [3.10, 3.12] in both (add 3.11 for the agent).
  _Verified: cited lines read in this audit; source: quality._
- **P17 · P3 · XS — _owned_variant_set returns 404 for foreign resources while
CONVENTIONS mandates 403.**
  Evidence: api.py:699-705 vs CONVENTIONS.md:32; deliberate per
  test_slice_vs2.py:126-128. Why: inconsistent with every other owner helper. Fix:
  align to 403 or document the exception in CONVENTIONS.
  _Verified: cited lines read in this audit; source: backend._
- **P24 · P3 · XS — Round-robin assignment and id generation are check-then-insert;
explicit id collisions 500 instead of 409.**
  Evidence: api.py:1494-1510 and 2098-2103 compute cursor = count(...) then insert
  (two concurrent calls hand out the same variant; correctness preserved by
  uq_candidate_slot_variant + re-read at 2113-2121); explicit ids (565, 1216) and
  _generate_id (539) collide into an uncaught IntegrityError. Why: 500 on a
  duplicate id; rotation skews under concurrency. Fix: catch IntegrityError → 409 in
  create routes; accept skew or select the least-used variant.
  _Verified: single-audit claim, not independently re-verified; source: quality._
- **P25 · P3 · S — Missing indexes and free-text enum columns; CandidateDraft
timestamps wrong.**
  Evidence: no index on Submission.created_at (ordering, analytics cutoffs;
  Submission.status got its index with the grading-durability change), Invite.status,
  AssessmentResult.verdict; IntegrityEvent has only single-column indexes for
  (invite_id, candidate_email) reads; status/verdict/category/kind are bare str with
  comments (models.py:89, 141, 249, 419, 434) hence `# type: ignore[arg-type]` at
  api.py:200; CandidateDraft.updated_at uses _created_at() (models.py:387) so lacks
  onupdate, and the table has no created_at contrary to models.py:9-10 and
  CONVENTIONS. Why: full scans on the hot paths as data grows; invalid states
  representable. Fix: one migration adding the indexes; sa.Enum(native_enum=False)
  or CHECK constraints; fix the draft timestamps.
  _Verified: single-audit claim, not independently re-verified; source: quality._
- **P27 · P3 · XS — No pre-commit config or gitleaks on the platform; 7 unused noqa;
mypy strict gap; tests unchecked.**
  Evidence: no .pre-commit-config.yaml in the platform tree (agent has the two-tier
  config); secret scan is 4 grep patterns in checkpoints.sh; RUF100 reports all 7 `#
  noqa` unused; mypy --strict = 22 errors (21 bare dict/list, 13 in
  agent_client.py); tests excluded from mypy. Why: weaker pre-commit backstop than
  the companion repo. Fix: copy the agent's two-tier pre-commit config; delete dead
  noqa; type the dicts.
  _Verified: cited lines read in this audit; source: quality._
- **W15 · P3 · XS — Dead client code.**
  Evidence: api.updateQuestion, deleteQuestion, deleteAssessment
  (api.ts:150-155,198-200) have zero non-test callers. Why: unused surface. Fix:
  delete or wire (question edit/delete exist server-side).
  _Verified: single-audit claim, not independently re-verified; source: frontend._
- **W20 · P3 · XS — TS strict not pinned; eslint not type-checked; no jsx-a11y;
layout shift while analytics load.**
  Evidence: tsconfig.app.json does not set "strict": true (only true via the TS 6
  default; 7 errors appear with --strictNullChecks false); eslint uses
  tseslint.recommended (not recommendedTypeChecked); no jsx-a11y;
  AnalyticsPanel.tsx:83 returns null until the overview arrives (layout jumps). Why:
  strictness depends on a compiler default; a11y regressions are unlinted. Fix: pin
  strict; recommendedTypeChecked + jsx-a11y; fixed-height skeleton.
  _Verified: cited lines read in this audit; source: quality._
- **W21 · P3 · XS — Product name "assess.dev" is hardcoded in the candidate header;
start gate cannot show branding before identification.**
  Evidence: AssessmentFlow.tsx:293 "Powered by assess.dev"; live: GET
  /invite/{token} pre-start returns only status + proctored, branding arrives in the
  /start payload. Why: product naming/white-label is baked into a component;
  candidates see a generic gate for a branded assessment. Fix: brand constant from
  config/env; carry title/org/logo in the pre-start public view.
  _Verified: cited lines read in this audit; source: frontend,saas._
