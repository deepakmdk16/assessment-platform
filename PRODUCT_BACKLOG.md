# Product Backlog — Assessment Platform + Agent

Consolidated, prioritized gap list built from walking the running app and auditing
both repos (`assessment-platform` = system of record + web UI; `../AssesmentAgent`
= stateless grader). Every item is verified against the code with a file/line.
This is the **backlog to draw from** — implementation is per-item, on explicit go.

For *how the system works*, see each repo's `CLAUDE.md` + `CONVENTIONS.md`. For
in-flight work, see `STATUS.md`. This file is the durable gap/feature list.

Effort key: **XS** (minutes) · **S** (self-contained) · **M** (multi-file) · **L** (data + API + UI).

---

## P0 — Bugs & broken flows

_None open. B1 (dashboard archive dead-end) and B2 (stable `JWT_SECRET`) are done — see `git log`._

## P1 — Finish what's half-built ("data exists, UI doesn't surface it")

| ID | Symptom | Root cause | Fix shape | Repo | Effort |
|----|---------|-----------|-----------|------|--------|
| F4 | A question can be saved with as few as 1 test case; "8 minimum" is only aspirational. | Prompt says ">=6 aim 8-10"; draft-eval floor is 4; the loader enforces only `min_length=1` (`AssesmentAgent/.../loader.py:52`). | Raise the loader/`validate_question` floor to a hard minimum of correctness cases (exempt the performance case); holds for AI **and** hand-authored paths. | agent | S |

_Done: F1 (reference solution persisted — `reference_solution`/`reference_language` columns + migration, shown collapsed on the question and submission pages), F2 (difficulty row on the question detail page), F3 (difficulty select moved above the "Draft with AI" action, defaults `medium`) — see `git log`._

## P2 — Table-stakes to compete with HackerRank

| ID | Symptom | Root cause / note | Fix shape | Repo | Effort |
|----|---------|-------------------|-----------|------|--------|
| T3 | Difficulty barely changes the generated question. | Prompt injects a bare `DIFFICULTY: hard` label (`authoring.py:507`); `question_draft.md` has no difficulty semantics. | Prompt section tying easy/medium/hard to concrete levers (constraint sizes → complexity, algorithmic depth, edge-case count). Re-baseline draft eval (checkpoint #4). | agent | M |
| T4 | One question per assessment; no multi-question tests/sections. | `Invite.question_id` is singular. | Model an assessment as an ordered set of questions; thread through invite, candidate flow, results. | platform | L |

_Done: T1 (assessment timer — nullable `Question.duration_minutes` defaulting from difficulty in the wizard; server-authoritative `started_at` stamped once per candidate on `/start` via a `CandidateAttempt` row; `/start` returns a stable deadline; `/submit` enforces deadline + grace; candidate countdown with warn/critical states that auto-submits at zero), T2 (global Submissions page + route + sidebar link; rows link to the submission detail; question titles mapped from id; `candidate_email` added to the lean list row) — see `git log`._
| AR3 | The agent renders a PDF report but the platform never lets you download it. | `AssesmentAgent/.../report.py` exists; `SubmissionDetailPage` "report" tab is an on-screen card, not the PDF. | Add a platform endpoint that fetches/serves the agent PDF; a download button on the submission page. | platform (+web) | S–M |

## P3 — Polish, UX parity & candidate experience

| ID | Symptom | Root cause | Fix shape | Repo | Effort |
|----|---------|-----------|-----------|------|--------|
| U1 | No in-app light/dark toggle (mockups had one). | Dark exists only via `@media (prefers-color-scheme: dark)` (`tokens.css:70`); Monaco hardcoded `theme="vs-dark"` (`CandidatePage.tsx:347`, `SubmissionDetailPage.tsx:146`). | Toggle writing `data-theme` on `:root`, overriding the media query, persisted to `localStorage` (light/dark/follow-OS); Monaco reacts. | platform/web | M |
| U2 | Submission panes (question/code/AI summary) are fixed proportions. | `.ide-split` is static CSS grid/flex; no resize lib in `package.json`. | Resizable panels (e.g. `react-resizable-panels`) with persisted sizes. | platform/web | M–L |
| CX1 | The app is barely responsive — breaks on smaller/varied screens. | Only **2 `@media` rules** in the entire `components.css`. Candidates take assessments on many devices. | A responsive pass on the candidate flow first (the split IDE), then interviewer pages. | platform/web | M |
| CX2 | A candidate's in-progress code lives only in `localStorage`. | Autosave is debounced 500ms to `localStorage` (`CandidatePage.tsx:37,95`) — lost if storage is cleared, incognito, or a different device. | Optional server-side draft persistence keyed by invite token, so work survives a device/browser switch. | platform | M |

## P4 — Integrity & scale-hardening

| ID | Item | Evidence / note | Repo | Effort |
|----|------|-----------------|------|--------|
| I1 | Proctoring signals — tab-blur / paste / fullscreen-exit. | None present. | platform/web | M |
| I2 | Plagiarism / similarity detection across submissions. | None present. (Largely mooted by per-candidate variants — see below.) | platform | L |
| SEC4 | Rate limiter is per-process, won't hold across workers/instances. | In-process fixed-window (`ratelimit.py`). Fine for single-process dev. | platform | M |

---

## Security & secrets — a relative **strength** (audit summary)

Not a gap-heavy area. What's already in place:
- **bcrypt** password hashing; **stateless JWT** bearer (`auth.py`).
- **HMAC-SHA256 body signing** between platform and agent, mirrored verbatim and
  gate-enforced identical (`signing.py`, `checkpoints.sh`).
- **SSRF guard** on the agent: rejects non-http(s) and literal internal IPs —
  loopback / private / link-local / reserved / unspecified (`AssesmentAgent/.../api.py:101`).
- **Configurable in-process rate limits** on login / submit / register / draft,
  each disable-able (`config.py:135-146`).
- **Env-driven CORS** and an optional **registration-code gate**.

Open hardening items (ops, not vulnerabilities):
- **SEC1** — `REGISTRATION_CODE` is unset by default → open interviewer sign-up.
  Must be set in prod (`config.py:110`). *Deploy-checklist item, XS.*
- **SEC2** — `JWT_SECRET` ephemeral when unset (= **B2**).
- **SEC3** — invite links + recipient emails are logged at INFO when SMTP is
  unconfigured, and SMTP failures log recipient lists (`email_client.py:59,72`).
  Candidate PII in app logs; redact for prod log aggregation. *S.*
- **SEC4** — distributed rate limiting for horizontal scale (see P4).

---

## Analytics & reporting — mostly greenfield (audit summary)

- **No aggregate endpoints** — no `@app.get` for stats/metrics/summary; the
  dashboard is a question list only. No cross-candidate comparison, pass-rate,
  percentile, or time-to-solve. → **AR1** (L).
- **No export** (CSV/JSON) of submissions or results. → **AR2** (S–M).
- **PDF report exists but isn't surfaced** → **AR3** (in P2 above).

---

## Moats we already have (durable differentiators)

1. **Determinism boundary** — the verdict is score-based and reproducible; the LLM
   quality read is *reported but never gates it* (CONVENTIONS.md §1). LeetCode/
   HackerRank are hidden-test pass/fail with no place for an honest, non-gating
   quality signal.
2. **AI authoring with an executed-oracle guarantee** — questions are generated
   from a brief, expected outputs come from *running* a reference, and that
   reference is cross-checked against an independent brute force. Generate-and-
   verify vs a static bank.
3. **Local/offline model path** — candidate code never leaves the machine, $0 per
   call. A hard wedge for enterprises that won't ship code to a third-party grader.
4. **Adversarial edge-case probe** — actively tries to break a correct-looking
   solution beyond the fixed suite.
5. **Self-hostable nsjail sandbox** — network egress blocked, cgroup memory/pids
   ceilings; you own execution.

Moats 1–3 are architectural, not features a competitor bolts on.

---

## Good-to-have features (net-new, beyond the backlog)

- **Per-candidate unique question variants (build this — it compounds moats 2+3).**
  Hand each candidate a slightly different generated question from the same brief.
  Structurally defeats the leaked-question-bank problem that plagues LeetCode/
  HackerRank and doubles as anti-cheat (reduces the need for I2). No competitor
  can do this cheaply.
- **Candidate-feedback agent** (parked in agent `STATUS.md`) — actionable feedback.
- **Per-role rubric customization** — weight readability vs performance vs idiom.
- **Reference in the candidate's language** — generate the oracle in whatever
  language they submit.
- **Difficulty auto-calibration** — feed real candidate pass-rates back to label
  difficulty empirically (pairs with AR1).
- **Cross-candidate analytics** — percentile, time-to-solve distribution,
  per-question discrimination (AR1).
- **ATS/webhook integration** (Greenhouse, Lever).
- **Question bank UX** — tagging, search, clone/reuse.
- **Candidate practice mode** — a free funnel into the paid product.

---

## Suggested sequencing

1. ~~**Quick-win batch** (one branch): **B1, F2, F3** + **B2** (env).~~ **Done.**
2. ~~**F1** (reference persistence) — needs a migration.~~ **Done.**
3. ~~**T2** (Submissions tab) — web-only now that the endpoint's confirmed present.~~ **Done.**
4. ~~**T1** (timer) — first heavy item; the loudest table-stakes gap.~~ **Done.**

**Process note:** `CLAUDE.md` requires **mockup-first sign-off for non-trivial
visual changes** (copy/one-liners exempt). B1/F2/F3 reuse existing components;
U1/U2/CX1 and any new page (T2) are genuine visual work → mockup before `.tsx`.

## Verification per bucket

- **Web:** `cd web && npm run build && npm run typecheck && npm run lint && npm run test`; exercise the flow in the running app.
- **Backend:** `uv run pytest`, `ruff check .`, `mypy`; new endpoints need offline tests that mock the agent call. A migration needs `alembic upgrade head` on a copy of `dev.db`.
- **Agent:** `uv run pytest`; re-baseline `assess-draft-eval` after prompt changes (offline it SKIPs, so pytest alone isn't proof).
- **E2E:** the Docker stack (web :5173 → platform :9000 → agent :8000 → ollama): draft → invite → candidate submit → callback → stored.
