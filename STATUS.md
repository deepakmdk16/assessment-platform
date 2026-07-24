# STATUS — Assessment Platform

The **single** pending / next-work list for this repo (the old `PRODUCT_BACKLOG.md`
was folded in here on 2026-07-24 and deleted — one list, not two). Feature
*history* is `git log` (commits are per-slice and detailed) — there is deliberately
no changelog file. Update this file in the same commit that opens or closes an item
(pre-push checkpoint #5). Durable architecture / boundary / invariants live in
CLAUDE.md + CONVENTIONS.md; cross-repo grader concerns live in `../AssesmentAgent/STATUS.md`.

Effort key: **XS** (minutes) · **S** (self-contained) · **M** (multi-file) · **L** (data + API + UI).

---

## A. Assessment-era gaps — found in manual testing 2026-07-24 (highest priority)

The T4 multi-question assessment epic shipped; driving it end-to-end surfaced these.
Several are "the single-question flow had it, the assessment flow doesn't yet."

- **A1 · Grading rejects pre-floor questions — P0 regression (cross-repo).** A
  candidate submission for `grid_path_minimize` (and any question with **< 4
  correctness cases**) fails grading entirely: `agent_job_id=None`, `status=error`,
  and the candidate gets a 502. Root cause: the agent's F4 floor
  (`MIN_CORRECTNESS_CASES = 4`) is enforced at *grade time* on every inline
  question (`../AssesmentAgent/.../loader.py:78` via `api.py:392`), so a question
  authored under the old floor now hard-fails every submission — the candidate is
  punished for the interviewer's question shape. The platform stored a 3-case
  question the agent now refuses; the two repos disagree on the floor.
  **Platform half of the fix:** enforce the same question invariants (case floor +
  ≥1 performance case) at *creation* (`POST /questions`, `PUT /questions/{id}` —
  today there is **no** case-count check, `api.py:375`), so you can't save a
  question that will later fail grading. **Agent half** (downgrade the floor to a
  warning on the grade path) is tracked in the agent's STATUS. See also **A2**
  (the general lesson). Immediate unblock for testing: add ≥1 correctness case to
  `grid_path_minimize`. **M.**
- **A2 · "Flag early / degrade gracefully" when tightening a shared invariant
  (process gap).** A2 is the *pattern* behind A1 and worth institutionalizing: F4
  made `validate_question` stricter (3→4 cases), which silently invalidated
  already-stored data. When we tighten a shared invariant we should (1) **flag**
  existing rows that would now fail (a check/migration that reports offending
  questions at deploy time) and (2) **degrade** rather than hard-fail on paths
  where the data owner can't act (a candidate can't fix the interviewer's
  question). Capture this as a standing rule in CONVENTIONS.md when A1 is picked up. **S** (doc) + informs A1.
- **A3 · Submissions list can't tell an assessment sitting from a standalone
  attempt.** Every row shows only `question_id`; assessment-group and individual
  submissions look identical (`SubmissionSummaryOut`, `schemas.py:193`). The link
  exists (submission → `invite.assessment_id` → assessment title) but isn't
  surfaced. Needs: an assessment column/grouping in the summary schema + list route
  + `SubmissionsPage`, **and** ideally an **assessment-level attempt view** (one
  candidate's whole sitting — all N questions + an aggregate — instead of N
  scattered rows). **M.**
- **A4 · "Email sent" is reported even when delivery failed.** `AssessmentDetailPage`
  shows "Invite created for …" unconditionally and never inspects the returned
  `deliveries[].sent`. Live deliveries are stored `sent:false` with a Gmail
  `530 Authentication Required` (dev has no `SMTP_USERNAME`/`SMTP_PASSWORD`), yet
  the UI reads as success. The invite *link* is valid — only the email failed. Fix:
  surface per-recipient delivery status (sent/failed + reason) in the invite UI;
  distinguish "invite created" from "email delivered". (Ops: set SMTP creds in any
  env expected to actually mail.) **S.**
- **A5 · No completion screen after time's up in the multi-question flow.** The
  single-question `CandidatePage` shows "Thanks, {name}! Your solution has been
  submitted and is being graded." (`CandidatePage.tsx:268`). `AssessmentFlow` has
  **no terminal state** — at zero it auto-submits with errors swallowed
  (`AssessmentFlow.tsx:104-126`) and leaves the locked IDE on "Time's up · 0/N
  submitted." Because A1's rejection makes the auto-submits fail, candidates land
  on a dead "0/N" screen with no acknowledgement. Needs an "assessment complete"
  screen + non-silent handling of auto-submit failures (retry/report). **M.**
- **A6 · Drop the user-facing slug ID.** Both `AddQuestionPage` and
  `NewAssessmentPage` make the user type an "Id (slug)" — but the id is an internal
  PK / URL key, not a user concept (the DB already has auto-gen ids like
  `q-1784204214377-831267`). Auto-generate `slugify(title) + short-random-suffix`
  server-side and remove the field from both forms; keep accepting an explicit id
  on the API for the agent/CLI authoring path. **S.**
- **A7 · Invites should be assessment-level, not (also) question-level.** Now that
  assessments exist, offering "send invite" on a single question is duplicative and
  confusing. Decide the model: either deprecate per-question invites in the UI in
  favour of assessment invites (a single question becomes a one-question
  assessment), or clearly separate "quick single-question screen" from "assessment".
  Today both paths exist (`/questions/{id}/invites` and `/assessments/{id}/invites`). **M.**
- **A8 · Authoring ↔ assessment connective tissue.** The builder already adds
  *existing* library questions; what's missing: (a) an "add to assessment" affordance
  from the questions page / a "build assessment from these" multi-select, and
  (b) — **lowest priority, explicitly deferred** — creating a *brand-new* question
  from inside the builder. Keep question creation simple and owned by the questions
  page; the builder assembles, it shouldn't grow a second authoring flow unless
  there's real demand. **M.**
- **A9 · Assessment editing has no guardrails.** `PUT /assessments/{id}` can reorder
  or swap questions after invites are sent / submissions exist, so two candidates in
  the "same" assessment could get different question sets. Lock the question set once
  an invite or submission references the assessment (or version it). **M.**
- **A10 · Candidate identity is re-entered per question.** Each `/submit` carries
  `candidate_name`/`candidate_email`; a typo on question 2 forks a different attempt.
  For an assessment sitting, fix identity once at `/start` and thread it, so all
  questions belong to one attempt. **M.**
- **A11 · No assessment-level score / verdict.** An assessment stores N independent
  per-question results; there's no composite (weighted score, "passed 2/3", overall
  verdict) for the sitting. Interviewers need an at-a-glance assessment outcome.
  Pairs with A3's attempt view. **M.**
- **A12 · Enterprise branding / uploadable logo.** The candidate IDE header hardcodes
  "Coding assessment" (`AssessmentFlow.tsx:201`) and doesn't even show the
  assessment's own title. Add **workspace-level branding** (logo + display name, e.g.
  "Amazon") stored on the interviewer/workspace, rendered as `{logo} {Org} —
  {assessment title}` with a small "Powered by assess.dev"; optional per-assessment
  override later. Store the logo as an asset/URL reference, not base64 in a row.
  Meaningful for selling white-labeled to enterprises. **L.**

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

- **AR3 · PDF report download — platform half DONE; agent half tracked in the agent
  STATUS (cross-repo).** The platform now proxies + serves the PDF:
  `agent_client.request_report()` POSTs to the agent's `POST /report` (signed like
  every other outbound call), `GET /submissions/{id}/report` streams the PDF back
  (409 ungraded / 404 unknown / 502 on agent error), and SubmissionDetailPage has a
  "Download PDF report" button. **Refined contract** (differs from the original
  wording — the serialized result alone couldn't render a report): the platform
  sends `{result, question, code, candidate?}` — the stored `full_result` plus the
  FULL question (same inline shape as the grade path) plus the candidate's submitted
  `code`, because `result_to_dict` keeps only the question's id/title and omits the
  source. The agent half (`POST /report` + `result_from_dict`) landed on the agent's
  `feat/report-endpoint` branch; merge/deploy the two together.
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
