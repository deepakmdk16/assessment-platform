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
  full suites green. **Note:** editing an existing assessment's duration does *not*
  rescue already-expired attempts (deadline = each attempt's own `started_at` +
  duration); re-invite to give a fresh clock.

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
