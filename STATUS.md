# STATUS — Assessment Platform

**Open items only.** Anything already done is history and belongs in `git log`
(commits are per-slice and detailed; there is deliberately no changelog file).
Close an item by **deleting its lines** in the commit that closes the work
(pre-push checkpoint #5) — never by annotating it as DONE.

Durable architecture, boundary and invariants live in CLAUDE.md + CONVENTIONS.md.
Agent-side items live in `../AssesmentAgent/STATUS.md`.

Priority: **P0** blocks taking money or endangers customers · **P1** first paying
customers hit it · **P2** fix before scale · **P3** polish.
Effort: **XS** minutes · **S** self-contained · **M** multi-file · **L** data + API + UI.

**Order of work lives in one place: the plan file** (see the audit pointer
below), not here — a "sequence" line in this file is dead text the `/next` skill
never reads.

The stack is deployable — `docker-compose.yml` + `docs/DEPLOY.md` (X05) — and
now observable: `/metrics`, JSON logs carrying a request id that spans both
services, and DSN-gated Sentry (X08). It is still unbacked-up (X20), so that
comes before real candidates. The agent no longer runs privileged (A07), but it
still needs a VM that grants it `CAP_SYS_ADMIN` at start and, on Ubuntu 23.10+,
a host AppArmor profile — managed container platforms remain ruled out.
Privacy (X03, X04) is built; X19 is the legal review it still waits on before
anyone is charged. Result delivery (X06 + X23) is done end to end — email, a
signed per-org webhook, and the settings panel that configures it. X07's code
half is done too; what remains of it is a domain purchase and three DNS records,
so nothing here is waiting on it.

---

## Where the open work is listed (read this first)

Two working documents live **outside git**, in the parent directory, and are
deliberately untracked (`.git/info/exclude`). They are the current source of
order; this file remains the tracked record of individual open items.

- `../PRODUCT-AUDIT-2026-09-14.md` — a full re-audit at platform `f07f80b` /
  agent `878d265`, after U01–U11 merged: **164 findings** (2 P0, 14 P1, 59 P2,
  89 P3) in an `R2-nnn` namespace, none of them duplicating anything in this
  file. Raw per-area reports, 190 walkthrough screenshots and the accessibility
  dump are in `../audit-2026-09-14-reports/`.
- `../AUDIT-SESSIONS-2026-09-14.md` — those 164 bucketed into sessions **S00–S30**
  in the order to take them, plus the nine mechanical gates (G1–G9) that would
  have caught each class. **S00 installs the gates and comes first.**

Two P0s are live and both are reproduced: a submission whose question has a
performance input over 4 MB never receives its grade (the result callback
exceeds the body cap), and a question saved with blank constraints — the wizard's
default — is refused by the agent's validator, so every submission against it
ends as "error".

Working rule for any item, here or there: **make the feature work end to end,
then the UI, then scale** — open for extension, closed for modification.

---

## Installed gates (S00) — what a session must do when it closes a finding

The audit's nine failure classes get mechanical checks, installed **before** the
fixes so no new drift lands while the fixes are outstanding. Each gate records the
violations that exist today as a **strict** expected-failure or an explicit
allowlist naming the finding and the session that closes it — strict meaning the
gate fails if a listed violation starts *passing*, so the list cannot rot.

**When your session fixes a listed finding, delete its entry in the same commit**
— the gate will fail until you do.

- **G1 · `tests/test_agent_contract_parity.py`** — the platform may not store a
  question the agent refuses to grade, and may not build a result callback over
  its own body cap. Imports the agent from the sibling checkout (`../AssesmentAgent`
  locally, `./AssesmentAgent` in CI, which `checks.yml` now checks out) and skips
  with a notice when absent. Also asserts `question_rules.MIN_CORRECTNESS_CASES`
  equals the agent's, replacing the old "keep identical" comment.
  Listed today: 10 × R2-002 (→ S02), 1 × R2-001 (→ S01).
  The agent's `scripts/checkpoints.sh` runs this test too — the edit that breaks
  it is usually made on that side.
- **G8 · `tests/test_limiter_coverage.py`** — a route reachable without auth, one
  that verifies a password, or one that sends email must call `limiter.check`.
  Rate limiting is opt-IN per handler, so a new route is unlimited and silent
  about it. Listed today: R2-032 (→ S07), 2 × R2-066 (→ S06), 4 × R2-013 (→ S06/S07).
  `NO_LIMIT_NEEDED` holds the routes that must *not* consume quota, each with its
  reason; both lists fail if they name a route that no longer exists.
- **G8 · `scripts/check-schema-limits.py`** — every field of every request body the
  API accepts must be bounded (`str`/`list` → `max_length`, numbers → `gt`/`ge`/
  `lt`/`le`). Models are reached through FastAPI's own `body_field`, so responses
  are not touched. 99 unbounded fields today, listed in
  `scripts/schema-limits-baseline.txt`; the file only shrinks, and there is no
  regenerate flag. Bounding a stored test case's `stdin`/`expected` is what lets
  G1's size xfail be deleted.
- **G5 · `docs/GLOSSARY.md` + `web/scripts/check-copy.mjs`** — one word per concept.
  The lint reads PROSE only (JSX text and quoted strings containing a space), so
  `OrganizationOut` and `/auth/login` are untouched while the copy is held to
  British spelling and the canonical noun. 12 known drift sites today (R2-108,
  R2-111, R2-112, R2-118 → S10), keyed by file + fragment.
- **G2 · `docs/CLAIMS.md` + `web/scripts/check-claims.mjs`** — a sentence asserting
  behaviour ("recorded", "blocked", "autosaved", "monitored", "cannot be") must
  have a row naming the test that proves it. 17 claims registered; 5 of their rows
  say **owed**, which is the honest list of promises the product cannot currently
  back: fullscreen (R2-003 → S04), the devtools half of the consent screen (S04),
  "No consent recorded" (S04), multi-question autosave (R2-030 → S08), and the
  buzzer-failure notice (R2-029 → S08).

- **G4 · `web/e2e/visual-gate.spec.ts`** (S00b) — every route at 1280x800 and
  390x844, in light and dark: no horizontal overflow, no serious/critical axe
  violation, and a screenshot for a human. Runs in the `e2e` CI job and under
  `RUN_E2E=1`; screenshots upload as a failure artifact. 26 known violations
  (R2-145 contrast -> S17, R2-154/156/159 overflow -> S13, plus link-in-text-block
  which this gate found and the audit had missed). Keys are `route | rule` for
  accessibility and `route | viewport | horizontal-overflow` for layout —
  deliberately coarser than the 4-variant matrix, so one contrast ratio landing
  the right side of AA in one theme cannot make the list go stale four ways.
  **Moderate-impact axe rules are out of scope by the impact filter, so R2-164's
  missing landmarks and headings are NOT covered** — S17 should tighten the
  filter once it has fixed them.

Both lints run in `npm run lint`, so they gate CI and the pre-push hook; the
visual gate rides the `e2e` job.

**E2E ports are now overridable** (`E2E_PLATFORM_PORT` / `E2E_FRONTEND_PORT` /
`E2E_AGENT_PORT`, defaults unchanged), so the suite can run beside a live dev
stack instead of demanding :9000 be free. The platform server is handed a
matching `FRONTEND_BASE_URL` — without it, invite links point at whatever holds
the default port and every candidate spec walks into the wrong stack.

### S00 review leftovers — 2026-09-14

- **P2 · S — Platform CI now depends on the agent repo's live default branch.**
  `.github/workflows/checks.yml:38` checks out `deepakmdk16/AssesmentAgent` with
  no `ref`, so an agent-side change to `signing.py` or `validate_question` can
  turn every open platform PR red, including ones touching only CSS. That is
  arguably correct for a contract gate — the byte-parity checks already behave
  this way locally — but it couples unrelated work. If it becomes disruptive,
  either pin `ref` (and accept that the gate then tests against a stale agent) or
  move the cross-repo checks into their own non-blocking job.
- **P3 · XS — `web/scripts/check-copy.mjs:38` mixes case-sensitive and
  case-insensitive patterns.** `/\bProblem\b/` and `/\bLogin\b/` carry no `/i`,
  so "the problem statement" and "the login page" pass a gate that bans both
  words. The two `Organizations?` rows could also collapse into one `/i` row.
- **P3 · S — The two copy lints duplicate their prose extractor.**
  `PROSE_PATTERNS`, `CLASS_ATTRIBUTE`, `walk()` and the path-key normalisation are
  byte-identical in `web/scripts/check-copy.mjs` and `web/scripts/check-claims.mjs`,
  and each re-walks `web/src` in its own node process. Extract `web/scripts/prose.mjs`
  when either needs its next change — a fix to the extractor currently has to be
  made twice.

---

## Product walkthrough — 2026-09-14 (all ten closed; leftovers below)

Ten gaps the user hit driving the running stack, plus one spotted in the same
screenshots. All ten are closed. Where the code contradicted the report, the
entry below says so rather than repeating the symptom.

Closed: U01 (radio layout), U02 (mail preflight + the app password now set —
verified by a real reset leaving the server), U03 (confirm password), U04 (start
screen 1050px → 720px, Start 163px above a 909px fold), U05 (a tab switch is
acknowledged on return), U06 + U07 (analytics behind the numbers, one rail entry
for the library), U08 (`PATCH /auth/me` + the Account form), U09 (delivery
failure out of the cell, link truncated), U10 (the agent no longer writes the
example into the prompt body). Layout direction A, signed off against
https://claude.ai/code/artifact/6d348599-0df6-4e19-9acc-47375dceeffe

What remains is the leftovers below, plus:

- **U08b · P3 · S — A member cannot reach billing at all.**
  The reported gap (Settings cannot edit the person) is closed. **Billing was
  never missing** — `BillingPanel.tsx` already shows `Renews <date>`, the plan
  cards with prices and this month's usage against the allowance. What remains is
  that P3a hides admin-only sections outright, so a *member* who wants to upgrade
  sees no panel and no route to ask. Fix: decide whether a member sees billing
  read-only with an "ask an admin" line, or nothing at all — a product call, not
  a bug.
- **U10b · P3 · XS — Questions drafted before today still carry the duplicate.**
  The cause is fixed agent-side (`authoring.py:_to_loader_dict`). Rows already in
  the database still have the example baked into `prompt`. It is data, not code,
  and re-drafting clears it. Fix: leave it, or strip a trailing `Example:` block
  once as a one-off script. A platform-side strip on render is NOT the fix.
- **U11 · P2 · S — Drafted constraints hand the candidate the solution.** *(not
reported — visible in the same screenshot)*
  Evidence: a question's Constraints reads "1 <= N, M <= 1000, so an O(N^2 * K)
  solution would be too slow … An O(N^2 * log(max_value)) solution is required
  using binary search on the answer combined with Dijkstra's algorithm or 2D
  DP." Why: constraints are supposed to bound the input, not name the
  algorithm — this is the assessment telling the candidate what to write, which
  makes the question worthless as a signal. Fix: agent-side prompt + a draft
  gate that rejects a constraints field naming an algorithm or a complexity
  class. Fits P4a (draft verification gates) — add it there rather than as its
  own pass.

### Walkthrough leftovers — 2026-09-14

- **P2 · S — An unmonitored sitting sees nothing of a tab switch.** U05's
  acknowledgement rides on `useIntegrity`, which is `enabled` only when the invite
  is `proctored`. That is deliberate — nothing is recorded without the monitoring
  consent, so there is nothing to acknowledge — but it means an interviewer who
  turns proctoring off gets no tab-switch signal at all and may not realise it.
  Fix: say so where proctoring is turned off, not by tracking regardless.
- **P3 · XS — "Show archived" stayed a checkbox, not a third tab.** The signed-off
  mockup drew three tabs (All / Variant sets / Archived). Archived is an orthogonal
  filter — archived *variant sets* exist too — so a third tab would have made them
  unreachable from the sets view. `DashboardPage.tsx` list-toolbar. Revisit if the
  checkbox reads as clutter beside the tab strip.
- **P3 · XS — The analytics drawer still fetches on page load.** `AnalyticsPanel`
  fetches `listAssessments` + `analyticsAssessment` on mount even though the
  cross-candidate drawer is shut, which is what it did before U06. Gate both on
  the drawer opening once someone notices the two requests.
- **P3 · XS — `Invite.deliveries` errors are summarised from the FIRST failure.**
  `InviteTable.tsx` shows one reason per invite. Two recipients failing for
  different reasons (one 530, one bad address) shows only the first. Correct
  almost always — a delivery failure is one server-side cause — but not always.

---

## Launch audit — 2026-09-06

- **P03 · P1 · S — Assessment and variant-set invites cannot be revoked (no route);
archiving does not stop links.**
  Evidence: the only revoke route requires Invite.question_id == question_id
  (api.py:1992-2003); assessment invites have question_id=None (api.py:1437-1446);
  live: revoke via the question route → 404; _load_invite_or_error checks only
  invite status/expiry (api.py:2023-2026); the API's own 409 text says "Revoke its
  invites instead" (api.py:1067,1101). Why: a leaked assessment link stays live
  indefinitely, and expiry is now the only control an interviewer has over one.
  Fix: owner-scoped POST /assessments/{id}/invites/{token}/revoke (+ variant-set);
  the shared InviteTable already renders a revoke column when handed an
  `onRevoke`, so the web half is one prop once the routes exist.
  _Verified: live run in this audit; source: backend,frontend,live. Expiry and the
  status column landed 2026-09-08._
- **X24 · P2 · S — The results webhook's SSRF gate is TOCTOU.**
  Evidence: `notify.webhook_url_error` resolves the host and refuses private
  addresses, then `httpx.post` resolves it again independently — a name with a
  short TTL can answer publicly for the check and privately for the connection.
  Why: blind (only the status code is logged) but it is the whole defense the
  README describes. Fix: resolve once and connect to the pinned address (custom
  httpx transport, keep the SNI/Host so TLS still validates), or send through an
  egress proxy that enforces the policy.
  Second defect in the same gate: `socket.getaddrinfo` runs unbounded inside the
  synchronous PATCH /orgs/current handler, so a hostname served by a black-holed
  nameserver pins a threadpool slot for tens of seconds. Admin-only and
  self-inflicted per tenant, which is why it is P2 and not higher, but the
  resolver wants a timeout (resolve in a thread with a deadline) — and the
  pinning fix above has to touch this code anyway.
  _Verified: raised by /code-review when X06 and X23 landed; the double-check is
  in main._
- **X26 · P2 · S — Erasure and the results notification have never met.**
  Evidence: `privacy._erase` rewrites `Submission.candidate_email` to a tombstone
  and `candidate` to `[erased]` but leaves `status` alone, so a submission still
  grading when the erasure lands notifies normally on its callback — emailing the
  interviewer "[erased] has completed Backend Screen" and POSTing a
  `results.ready` for `erased-…@erased.invalid` to the customer's endpoint.
  Separately, erasure does not clear `results_notified_at`, which is probably
  right (clearing it would re-arm the notifier for an erased sitting) but is
  undocumented, and `notify.reopen_sitting` is the other writer of that column.
  Why: the notification is the one channel that PUSHES rather than stores, so a
  tombstone reaches a third-party ATS as a junk record. Nobody decided this; it
  is what falls out. Fix: decide it — either suppress the notification for an
  erased sitting, or state that an anonymous result is still owed — and comment
  the `results_notified_at` interaction either way.
  _Verified: traced by /integration-check on the X06/X23 branch._
- **X27 · P2 · XS — The privacy notice and DPA do not mention the results webhook.**
  Evidence: docs/`PRIVACY.md` §"Who it is shared with" lists who candidate data reaches — the employer,
  the named sub-processors, and "**Nobody else.**" The webhook (X06) sends
  candidate name and email to an address the customer nominates; docs/DPA.md:50-55
  has no row for a controller-configured egress. Why: likely fine in law (the
  controller receives their own data), but if they point it at a third-party ATS
  that vendor becomes THEIR sub-processor, and the notice as written does not
  admit the flow exists. Fix: fold into the X19 legal review — a sentence in
  PRIVACY.md and a line in the DPA saying a controller-configured destination is
  the controller's responsibility.
  _Verified: traced by /integration-check on the X06/X23 branch._
- **X25 · P3 · XS — A crash between claiming a notification and sending it loses it.**
  Evidence: `notify.claim_sitting` stamps `results_notified_at` inside the
  callback request; `deliver` runs after the response. A SIGTERM in between
  consumes the one-shot claim with nothing sent, and nothing re-examines a
  stamped-but-unsent attempt (grading has the reaper for exactly this). Why: a
  rare silently-missed notification; the dashboard is still the record. Fix:
  stamp `results_sent_at` separately after delivery and let a sweep retry the
  gap, or move delivery onto a durable queue when one exists.
  _Verified: raised by /code-review when X06 landed._
- **X07 · P1 · XS — Email needs a real sending domain. BLOCKED on a purchase.**
  The code half is done: HTML+text templates for all five messages
  (`email_templates.py`), per-invitation Reply-To, `SMTP_FROM_NAME`, and the boot
  preflight already refuses the no-reply@assessment.local placeholder. Every
  provider speaks SMTP, so switching is five env vars and no code (profiles for
  SES and Postmark are in .env.example).
  What is left is not code: (1) buy the domain, (2) pick the sender — SES is
  effectively free against the existing $120 of AWS credits at this volume, but
  starts in the sandbox; Brevo/Resend free tiers avoid that, (3) publish SPF,
  DKIM and DMARC for it and start DMARC at `p=none`. Until then Gmail SMTP with
  an app password works and is what .env.example ships.
  Why it still matters: mail from an unauthenticated domain lands in spam, and a
  candidate who never sees the invitation silently misses the interview.
  _Verified: templates and Reply-To landed with X07's code half; the rest is a
  purchase and three DNS records._
- **X31 · P2 · XS — The agent's scrape reuses its code-execution credential.**
  `docs/DEPLOY.md` §4 tells an operator to scrape the agent with
  `ASSESS_API_TOKEN` — the same secret that authorises `POST /assessments`. So a
  Prometheus configured as documented holds arbitrary-code-execution rights on
  the worker. The platform got a dedicated `METRICS_TOKEN` for exactly this
  separation and the agent did not. Fix: a read-only `ASSESS_METRICS_TOKEN` the
  `/metrics` dependency accepts alongside the main token, and update §4.
  _Verified: raised by X08's integration check; DEPLOY.md:183 reads the token._

- **X32 · P2 · XS — `platform_submissions_stalled` reads zero when the reaper's
grace is disabled, disarming the alert DEPLOY.md names first.**
  With `REAP_RUNNING_AFTER_S=0` or `TRIGGER_RETRY_AFTER_S=0` (a supported config —
  `<= 0` means "leave those rows alone") the gauge skips the same rows the reaper
  skips, so it reports healthy while submissions strand forever. It mirrors the
  reaper faithfully, which is the bug: the metric exists to say the reaper is not
  working. `platform_submissions{status=running}` still rises, so it is
  detectable, but the prescribed alert never fires and no doc says so. Fix: count
  stranded rows against a floor independent of the grace, or expose the disabled
  state as its own series.
  _Verified: raised by X08's integration check; api.py's `grace > 0` guard._

- **X33 · P2 · XS — A `/metrics` scrape during a DB outage files a Sentry event
per scrape.**
  `/health` catches the DB failure and raises a handled 503; `/metrics` lets it
  propagate to the new unhandled-exception handler, which logs at ERROR and (with
  a DSN set) reports. At a 15-second scrape interval that is an error storm and a
  quota burn at the exact moment the service is least healthy. Fix: catch the DB
  error in `metrics` and 503 the way `health` does.
  _Verified: raised by X08's integration check._

- **X30 · P2 · S — Nothing scrapes `/metrics`, and no alert fires off it.**
  Both services now expose Prometheus text exposition (X08), but the compose
  stack has no scraper and no alerting: the numbers exist and nobody is
  watching them, which is a smaller gap than X08 but the same shape. The agent
  is on the internal `grading` network with no published port, so a scraper has
  to live inside the stack or be given a path to it. Fix: a Prometheus (or
  equivalent) service in `docker-compose.yml` scraping both targets, and alerts
  on the three signals that mean results are being lost —
  `platform_submissions_stalled`, `platform_grade_giveups`, and
  `agent_callbacks_total{outcome="failed"}`. Until then an operator reads them
  by hand; `docs/DEPLOY.md` says how.
  _Verified: opened by X08, which built the exposition but deliberately stopped
  short of adding infrastructure nobody had asked for._
- **X09 · P1 · S — Rate limits are per-IP, never per-tenant, in both services.**
  Evidence: platform `config.py`'s rate-limit block and api.py:433,461,2480 key on client_ip;
  agent ratelimit.py per-IP and in-memory (A13). Why: an office behind one NAT
  shares one bucket; one tenant cannot be capped independently. Fix: key expensive
  buckets (draft, submit, invites) on org_id in addition to IP; agent limiting moved
  to the platform's DB backend.
  _Verified: cited lines read in this audit; source: saas._
- **X10 · P1 · M — Interviewer-facing gaps a first paying customer hits.**
  Evidence: no question import/bulk upload (only hand-form or AI
  draft, api.py:554); no candidate-facing feedback or score (CandidatePage.tsx:345);
  no re-invite/extend-deadline (the re-invite gap in X10); no custom domain/white-label
  beyond logo/org text (models.py:165-166).
  Why: procurement and onboarding stall on table-stakes features. Fix: import and
  re-invite are what is left here. (Team and self-serve org onboarding shipped
  with X01; results notification and the ATS webhook shipped with X06/X23.)
  _Verified: cited lines read in this audit; source: saas._
- **X19 · P1 · S — The privacy notice, terms and DPA are unreviewed templates.**
  Evidence: docs/PRIVACY.md, docs/TERMS.md and docs/DPA.md were written from the
  system's real data flows (X04) and are accurate about what is collected, but
  carry `[BRACKETED]` placeholders and a DRAFT banner; the liability section of
  the terms and the SCC/UK-addendum attachment of the DPA are explicitly left
  blank. Why: a customer's legal review reads the DPA most closely, and shipping
  a template as if it were reviewed is worse than having none. Fix: legal review;
  replace the placeholders; attach the official SCC texts; bump
  `PRIVACY_POLICY_VERSION` and re-consent when the wording changes.
  _Verified: opened by this change; source: saas._
- **X20 · P1 · M — No backups exist; only a specification for them.**
  Evidence: docs/BACKUPS.md (written for X03) states the target RPO 5 min / RTO
  4 h and says plainly that nothing implements it — the platform runs from a
  single database with whatever durability the host gives it, and the restore
  drill table is empty. Why: the agent is stateless, so this database is the
  entire product record; losing it is unrecoverable by any other means. Fix:
  managed Postgres with PITR at 30 days, an independent weekly dump to separate
  storage, alerting on backup failure (ties to X30), and one actual restore
  drill recorded in the table.
  _Verified: opened by this change; source: saas._
- **X22 · P2 · S — An interviewer's own submissions are outside erasure and
retention.**
  Evidence: `POST /submissions` stores `Submission.candidate` (a free-text name)
  with `candidate_email` NULL and no invite, so `privacy.erase_candidate` — which
  matches on the address — cannot reach those rows, and `purge_expired`, which
  walks `CandidateAttempt`, never sees them either. Why: they are normally an
  interviewer's own test runs, but nothing stops a real person's name and code
  being pasted in, and the Privacy panel would then be overstating what it
  destroys. Fix: either scope the route to non-candidate use explicitly (and say
  so), or give the row a nullable `candidate_email` and include it in both
  paths. Matching on the display name is not the fix — it would erase the wrong
  people.
  _Verified: opened by a code review of this change; source: backend._
- **X21 · P2 · S — Erasures are not recorded anywhere that survives a restore.**
  Evidence: `privacy.erase_candidate` logs and returns counts, but the only
  durable trace is the erased rows themselves; restoring a backup from before a
  request silently resurrects the data (docs/BACKUPS.md "Restoring", step 4).
  Why: a restore that undoes an erasure re-creates the breach the request
  closed, and nothing would flag it. Fix: an append-only erasure log (org, hashed
  address, timestamp, counts) kept outside the primary tables, and a restore step
  that replays it.
  _Verified: opened by this change; source: saas._
- **P06 · P2 · XS — POST /invite/{token}/events accepts any question_id.**
  Evidence: api.py:2572-2584; live: unknown id → 500 ForeignKeyViolation; another
  organisation's valid id is stored and then blocks that organisation's DELETE
  /questions/{id} via the IntegrityEvent guard. Why: an unauthenticated route can
  500 and write across a real tenant boundary — the boundary is genuine since X01,
  so this is no longer only a nuisance. The *title* echo it enabled is closed
  (`_integrity_report` resolves titles only within the caller's organisation); the
  unvalidated write is not. Fix: resolve through _resolve_question (must belong to
  the invite) or null it.
  _Verified: live run in this audit; source: backend,live._
- **P29 · P3 · S — X01 leftovers an integration check surfaced.**
  Evidence: `GET /orgs/current/invites` filters `accepted_at IS NULL`, so
  `OrgInviteOut.accepted_at` can never be non-null on any response and
  `Membership.invited_by` is written by `_join_org` and read by nothing — the
  audit trail the OrgInvite docstring says the rows are kept for has no reader.
  `GET /auth/me` carries no organisation, so its name appears in
  exactly one place in the SPA. Question/assessment/variant-set ids remain one
  global slug namespace, so an explicit-id create is an existence oracle across
  organisations. Several open items above still cite `api.py:NNNN` line numbers
  that X01 moved by ~800-1000 lines. Why: none of these is user-visible today;
  together they are the tail of the org migration. Fix: a read surface for
  accepted invitations, and re-anchor the stale citations. (The branding half is
  closed: P3b moved it to `Organization.name`/`logo_sha` and dropped the
  per-person columns along with `PATCH /auth/me`.)

- **P07 · P2 · XS — CSV export is vulnerable to formula injection.**
  Evidence: api.py:2872-2884 writes candidate-supplied candidate, candidate_email
  and titles raw. Why: a candidate name starting with = + - @ executes in Excel on
  the interviewer's machine. Fix: quote/prefix cells that start with those
  characters.
  _Verified: cited lines read in this audit; source: backend._
- **P08 · P2 · S — Candidate email plus the secret token land in access logs via the
draft GET query string.**
  Evidence: GET /invite/{token}/draft?candidate_email=
  (`api::candidate_get_drafts`, `web/src/api.ts::readDraft`); uvicorn logs the query string regardless of LOG_PII;
  test_logging_redaction.py covers only email_client. Why: PII + bearer-equivalent
  token in plain logs. Fix: carry the email in a header or POST body.
  Narrowed but NOT closed by X08: `observability.QueryStringFilter` now redacts
  the query string from this server's access lines unless `LOG_PII` is on, so the
  aggregator no longer ingests it. The token still travels in the URL, so it is
  still in nginx's access log, the browser's history and any Referer — which is
  what moving it out of the query string fixes.
  _Verified: cited lines read in this audit; source: backend._
- **P11 · P2 · M — N+1 and heavy list queries.**
  Evidence: list_questions lazy-loads test_cases per row and ships full test cases +
  reference solutions (api.py:194-204, 954); list_variant_sets per-row count
  (896-898); list_assessments per-slot VariantSet get + count + lazy aq.question
  (1134-1150); _assessment_attempt_rows per-invite session.get(Invite) (1621-1625);
  analytics_overview loads every Submission in the ORGANISATION including code;
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
  Evidence: `schemas::AssessmentUpdate.proctored` (defaults True); a client omitting the field on a settings edit silently
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
  ("grader unavailable, try again"). Since agent A07 the same branches can also
  echo the agent's new infra_error for a toolchain the jail can't see ("runtime
  not installed: … not on the jail PATH: 'ruby'").
  _Verified: cited lines read in this audit; source: quality._
- **P22 · P2 · M — api.py is a 5,718-line god-module with the split seams already
drawn.**
  Evidence: 86 route decorators, 183 top-level defs, 28 banner sections;
  maintainability index 0; `api::_assessment_attempt_rows` is 167 lines with
  cyclomatic complexity ~40; the load+404/403 helper is copied per resource
  (`_owned_question`, `_owned_assessment`, `_owned_variant_set`,
  `_owned_submission`); the archive/unarchive pairs are duplicated
  (`archive_question` ≡ `archive_assessment`); `create_invite` ≡
  `create_assessment_invite`; count+slice pagination ×8; 14 manual `updated_at`
  writes despite `models::_updated_at`'s `onupdate`; Questions CRUD sits under the
  "Variant sets" banner. Why: every feature touches one file; reviews collide; the 154-line
  function is where the next bug lands. Fix: APIRouter per banner into
  routes/{auth,questions,variant_sets,assessments,invites,analytics,candidate,submissions,callback}.py;
  serializers → mappers.py; one generic _owned(Model, id, current, session) +
  _page(stmt, limit, offset); drop manual updated_at.
  _Verified: cited lines read in this audit; source: quality,backend._
- **P26 · P2 · S — The cross-repo parity gates (signing.py, callback contract) never
run in CI.**
  Evidence: both `scripts/checkpoints.sh` files skip the
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
- **W09 · P2 · XS — A transient network failure on boot logs the interviewer out.**
  Evidence: auth/`AuthContext.tsx` boot effect clears the token on any me() rejection, not
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
- **W14 · P2 · S — Accessibility: the remaining three.**
  Evidence: every picker row has an identical "Add" (NewAssessmentPage.tsx); the
  ARIA tablist has no arrow-key handling (AssessmentFlow.tsx); the Monaco Tab-trap
  has no escape hint. Why: WCAG name/role/value failures on interviewer surfaces.
  Fix: name the Add buttons per row, arrow keys on the tablist, an escape hint;
  add jsx-a11y lint so these can't come back.
  _Verified: single-audit claim; source: frontend. The icon buttons, the
  per-recipient select, the unbound labels and the sidebar's aria-current were
  fixed 2026-09-08._
- **W16 · P2 · M — Duplicated candidate IDE and countdown.**
  Evidence: the candidate editor panel is ~130 duplicated lines between
  CandidatePage and AssessmentFlow, plus the countdown in both. Why: a fix to one
  silently misses the other. Fix: extract `CandidateIde` and `useCountdown`.
  _Verified: cited lines read in this audit; source: frontend. The three divergent
  recipient parsers and the duplicated invite table were extracted 2026-09-08._
- **W18 · P2 · S — Hand-written types.ts mirrors 66 pydantic schemas with no drift
gate.**
  Evidence: types.ts (850 lines, 61 exports) vs schemas.py (66 classes); no OpenAPI
  generation; api.ts:112 is an unchecked `as T`; looseness already exists:
  QuestionIn.required_complexity: string vs backend str | None (schemas.py:98),
  InviteStatus = string (`types.ts`). Why: a renamed/nullable backend field ships
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
- **X18 · P2 · S — Nobody is warned before an allowance runs out.**
  Evidence: the only signal is the refusal itself — 402 at invite/draft
  (api.py `_check_invite_capacity`, `billing.consume`), 403 to the candidate at
  `_require_sitting_quota`; no threshold email, and no mail of our own when Stripe
  reports `past_due` (the banner is only visible to someone who opens Settings).
  P3a narrowed this: a 402 now carries a link to `/settings/billing`
  (`web/src/errors.tsx`), so the refusal is actionable — but it is still the
  first warning anyone gets.
  Why: the first time an interviewer learns the plan is exhausted is while trying
  to invite a candidate they have already scheduled. Fix: an email at ~80% of any
  allowance and one on `past_due`, both once per period per organisation.
  _Verified: read in the X02 branch; source: X02 follow-up._
- **X11 · P2 · XS — No dependency vulnerability scanning or Dependabot.**
  Evidence: .github/ in both repos has only workflows/; checkpoints.sh secret scan
  is regex-only; no pip-audit/npm audit in CI. Why: CVEs in bookworm
  toolchains/node/react go unnoticed. Fix: Dependabot (pip, npm, docker, actions)
  + pip-audit/npm audit --audit-level=high in CI.
  The headers half is closed: P9a ships CSP, nosniff, Referrer-Policy and an
  opt-in HSTS in `web/nginx-security-headers.conf`, documented in DEPLOY.md §3.
  _Verified: cited lines read in this audit; source: saas._
- **X12 · P2 · M — Candidate identity is a claim; recipient enumeration via
/start.**
  Evidence: platform api.py:2030-2043: a forwarded link + a guessed invited email =
  impersonation; 403 vs 200 on /start reveals which emails were invited;
  README:109-113 documents the model. Why: a shared link can be sat by anyone who
  knows a recipient's address. Fix: per-recipient tokens (one Invite row per
  recipient) or an emailed OTP at start.
  _Verified: single-audit claim, not independently re-verified; source: saas._
- **X13 · P2 · S — No API versioning; the boot preflight covers mail but not secrets.**
  Evidence: no /v1 prefix on platform routes; agent app version "0.2.0", platform
  "0.1.0"; config.py generates an ephemeral JWT_SECRET with only a warning, and
  nothing refuses a production boot with CALLBACK_TOKEN unset — leaving
  POST /assessments/callback world-writable. `_require_email_configured` already
  runs in the lifespan and is the hook to extend. Why: customers integrating
  CSV/ATS/webhooks can't be evolved safely; a prod boot with a missing secret
  silently rotates every session. Fix: /v1 prefix on public routes; a second
  PLATFORM_ENV=production tier in the existing preflight refusing to boot without
  JWT_SECRET / ASSESS_API_TOKEN / CALLBACK_TOKEN, and warning on
  RATE_LIMIT_BACKEND=memory.
  _Verified: cited lines read in this audit; source: saas. Mail half closed 2026-09-08._
- **X14 · P2 · S — AGPL-3.0 + informal commercial offer will cause procurement
friction (not legal advice).**
  Evidence: both LICENSE files are AGPL-3.0 (switched 2026-09-05); README.md:302-313
  offers a commercial licence via a GitHub issue; no CLA, EULA or pricing. Why:
  enterprise legal teams often blocklist AGPL; any outside contribution without a
  CLA removes the right to relicense. Fix: keep AGPL for the community edition;
  publish a written commercial EULA + pricing; require a CLA.
  _Verified: cited lines read in this audit; source: saas._
- **X15 · P2 · XS — Authoring cost is not baselined and there is no per-tenant
rollup.**
  Evidence: authoring is bounded by max_tokens=8000 × up to 2 attempts ≈ $0.25-0.30
  worst case per draft, ×K≤8 for a variant set, against a judge cost near $0.011 per
  candidate — so drafting is the real spend and the only unmetered one. The judge is
  skipped entirely when code fails to execute. Why: pricing decisions need the
  expensive half measured, and per-org attribution is a prerequisite for X02.
  Fix: baseline draft cost; roll up judge_cost_usd/draft_cost_usd per org (X02).
  _Verified: single-audit claim. The misread cost figures it also cited were
  corrected in the agent STATUS on 2026-09-08._
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
  Evidence: `_owned_variant_set` vs `_owned_question` / `_owned_assessment`, which
  both 403; deliberate per test_slice_vs2.py:126-128. Why: inconsistent with every
  other org-scope helper. Fix: align to 403 or document the exception in
  CONVENTIONS.
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
  comments (`models::Organization.plan_status`, `OrgAsset.kind`, `Question.status`,
  `Invite.status`, `QuestionTestCase.category`) hence the `# type: ignore[arg-type]`
  in `api.py`; `models::CandidateDraft.updated_at` uses `_created_at()` so lacks
  onupdate, and the table has no created_at contrary to `models.py`'s own header
  comment and CONVENTIONS. Why: full scans on the hot paths as data grows; invalid states
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
- **W15 · P3 · XS — Dead client code: `api.deleteAssessment` has no caller.**
  Evidence: `DELETE /assessments/{id}` exists and is owner-scoped, and the client
  method is written, but AssessmentDetailPage offers only Edit. Why: unused
  surface, and the question flow now has the delete affordance the assessment
  flow still lacks. Fix: mirror the question delete dialog in the assessment edit
  dialog's danger row.
  _Verified: single-audit claim. `updateQuestion`/`deleteQuestion` were wired 2026-09-08._
- **W20 · P3 · XS — TS strict not pinned; eslint not type-checked; no jsx-a11y;
layout shift while analytics load.**
  Evidence: tsconfig.app.json does not set "strict": true (only true via the TS 6
  default; 7 errors appear with --strictNullChecks false); eslint uses
  tseslint.recommended (not recommendedTypeChecked); no jsx-a11y;
  AnalyticsPanel.tsx:83 returns null until the overview arrives (layout jumps). Why:
  strictness depends on a compiler default; a11y regressions are unlinted. Fix: pin
  strict; recommendedTypeChecked + jsx-a11y.
  _Verified: cited lines read in this audit; source: quality. The analytics layout
  shift was fixed with a reserved-height skeleton 2026-09-08._

---

## Deploy-time env

Moved to `docs/DEPLOY.md`, which now carries the full list: what compose sets
for you, what only the operator can supply (`REGISTRATION_CODE`, SMTP, Stripe),
and the two settings TLS changes (`COOKIE_SECURE`, `TRUST_PROXY_HEADERS`).

## P2a review leftovers — 2026-09-13

Minor findings from the P2a review round, deferred rather than fixed there.

- **Esc may also exit fullscreen while cancelling a confirmation.**
  `web/src/components/ConfirmDialog.tsx:19` is a native `<dialog>`; in element
  fullscreen some browsers treat Esc as "exit fullscreen" too, which would
  record an integrity exit for declining to submit. Browser-dependent — verify
  in Chrome and Firefox; if it happens, render the candidate confirmations with
  the scrim-div pattern the fullscreen prompt uses.
- **Leaving a sitting is client-only.** `web/src/pages/AssessmentFlow.tsx`
  (`leftEarly`) ends nothing on the server: `/start` re-admits the candidate and
  the interviewer cannot see that they stopped. A `CandidateAttempt.finished_at`
  set by `POST /invite/{token}/finish` would let `/start` lock the sitting and
  the dashboard show it.
- **Language ids are shown raw on the start screen** (`cpp`, `javascript`) by
  `GateFacts` in `web/src/pages/CandidatePage.tsx`, as the editor's language
  select already does. One label map would fix both.
- **"Submit and leave" posts answers one at a time** (`runSubmitAll` in
  `AssessmentFlow.tsx`): N answers cost N round-trips with the editor locked.
  Parallel posts would trip the per-IP submit limiter; a batch submit endpoint is
  the real fix.
- **Four gate-fill helpers in `web/src/pages/__tests__/CandidatePage.test.tsx`**
  (`reachEditor`, `startSitting`, `start`, `passGate`) encode the same steps;
  the older three could call the module-level `passGate`.
- **The AI notice still names no address.** `AssessmentNotice` in
  `CandidatePage.tsx` tells a candidate to "contact the interviewer who invited
  you" for a human review, while `docs/PRIVACY.md` § Automated assessment offers
  the privacy contact. P2b added `support_email` to both invite responses, so the
  notice could now render that field instead of restating a contact sentence —
  decide first whether a human-review request should reach the platform's
  support mailbox at all, or only the hiring team.

## P3b review leftovers — 2026-09-13

Minor findings from the P3b review round, deferred rather than fixed there.

- **The orphan sweep does not run on assessment deletion.**
  `_drop_unreferenced_logo` (`assessment_platform/api.py`) is called when the
  organisation's logo is replaced or removed. Deleting the assessment that
  snapshotted a superseded logo leaves the `OrgAsset` row behind, and
  `GET /logos/{sha}` keeps serving the old branding. Narrower than it sounds,
  and the integration check pinned why: `privacy.purge_expired` never deletes an
  `Assessment` row, and `DELETE /assessments/{id}` refuses while any invite
  points at it — so the only assessment that can trigger this is one no
  candidate was ever sent. Bytes, not a leak: the address is unguessable and it
  is the organisation's own image. Fix, if ever: a periodic pass over
  unreferenced assets rather than a second hand-rolled hook.
- **A dangling `logo_sha` draws a broken image rather than falling back.** Every
  branded header is `logo_sha ? <img> : <span className="ide-mark">`
  (`web/src/pages/CandidatePage.tsx`, `AssessmentFlow.tsx`,
  `AssessmentDetailPage.tsx`), with no `onError`. The *null* case has a clean
  fallback; the *dead address* case — reachable only via the race below — is the
  one that renders worst, on a candidate's screen, permanently. Fix: one shared
  logo component that hides itself on error.
- **The candidate's dead-end notices carry no logo.** `CandidateNotice.tsx`
  shows neither name nor image, on the screens someone lands on when a link is
  spent. `GET /logos/{sha}` is public and would work there. (The invitation
  email deliberately stays imageless — a remote image in a message works as a
  tracking pixel.)
- **A multipart body with no `Content-Length` is not bounded before it is
  parsed.** `_limit_body_size` (`assessment_platform/api.py`) checks a declared
  length, and the JSON routes have schema caps behind it; `PUT
  /orgs/current/logo` is the first route where neither applies, because
  Starlette spools the part before `await file.read(cap + 1)` runs. Admin-only
  and authenticated, so the attacker is a customer's own admin or a stolen
  token. Fix: a streamed read that aborts past the cap, or a parser-level limit.
- **An assessment created concurrently with a logo replacement can reference a
  just-deleted asset.** Under READ COMMITTED, `create_assessment` can read
  `organization.logo_sha = A` before `set_org_logo` moves it to B, sweeps A
  (seeing no reference yet) and commits — leaving the new assessment pointing at
  a 404 permanently, since its logo is frozen at creation. Needs a row lock on
  the organisation, or a foreign key from `assessment.logo_sha` to the asset.

## P3a review leftovers — 2026-09-13

Minor findings from the P3a review round, deferred rather than fixed there.

- **`GET /orgs/current` is fetched twice on three of the six sections.** The
  Settings shell reads it for the role (`web/src/pages/SettingsPage.tsx:32`) and
  `BillingPanel.tsx:172`, `NotificationsPanel.tsx:39` and `PrivacyPanel.tsx:39`
  each read it again for their own data. Harmless but wasteful, and the two
  copies can disagree. Fix: pass the `Organization` down from the shell, which
  also closes the next item.
- **A section heading can sit above an empty panel.** The shell renders
  `<h2>{label}</h2>` (`web/src/pages/SettingsPage.tsx:100`) whichever way the
  panel goes; if a panel's own `getOrg` rejects it returns `null`, so the
  section title stands over nothing. Only reachable when the shell's fetch
  succeeded and the panel's failed.
- **Two error helpers in TeamPage.** The local `message()`
  (`web/src/pages/TeamPage.tsx:8`) and the shared `apiMessage()` differ only in
  the 402 branch, and six of the seven call sites still use the local one — so
  the Billing link appears on the invite form and nowhere else on that page.
- **`apiMessage` returns JSX, not data.** `web/src/errors.tsx:19` is why six
  error states widened from `string` to `ErrorMessage`, which costs them
  logging, comparison and snapshotting; `describeDraftFailure` — a pure
  classifier — now needs a Router to test. A `{ text, action? }` shape rendered
  through one error component would keep the states as strings.
- **The 402 link can appear inside an open `<dialog>`.** On
  `web/src/pages/QuestionDetailPage.tsx` the invite refusal renders inside the
  modal opened with `showModal()`; following the link unmounts the page without
  calling `close()`. Browsers pop a removed element from the top layer, so this
  is a broken invariant rather than a visible bug.

## P2b review leftovers — 2026-09-13

Minor findings from the P2b review round, deferred rather than fixed there.

- **One invite token, several recipients: feedback can be written under someone
  else's name.** `_check_invited` (`assessment_platform/api.py`) is an identity
  *claim*, and every recipient of a multi-address invite holds the same token, so
  recipient A can POST feedback as recipient B once B has submitted — and the
  unique constraint then stops B from ever correcting it. The same weakness
  already lets A burn B's single submit attempt, so the root fix is per-recipient
  tokens (or a signed one-time feedback link in the results email), not a patch
  to this route. Until then the interviewer surfaces present feedback as
  candidate-asserted, which is what it is.
- **A quick-screen sitting is never asked for feedback** (`_feedback_accepted`,
  `api.py`): both surfaces that display it — the attempts grid and the assessment
  rollup — are reached through an `Assessment`, so a question-only or
  variant-set invite has nowhere to show it. Giving `SubmissionDetailPage` a
  feedback line would let the form open up to those sittings too.
- **The submissions CSV export has no feedback column**
  (`assessment_platform/api.py`, the export header + row loop). The export
  already denormalises sitting-level integrity facts onto per-submission rows, so
  feedback is the same shape; the one surface a customer takes offline into an
  ATS is currently the one that cannot see it.
- **`SubmissionDetailPage` shows no feedback.** Integrity signals get both a grid
  cell and a per-submission panel; feedback got the grid cell and the analytics
  rollup only, so an interviewer who reaches a candidate through Submissions →
  detail never sees the rating. Same page as the quick-screen item above.
- **Feedback is offered on one paint only.** The form mounts on the live
  `submitted` / `complete` render, so closing the tab and coming back (which
  lands on `already_submitted`) loses the chance — the server would still accept
  it. A second chance would need the 409 path to carry `feedback_enabled`, or a
  one-time link in the results email.
- **`CandidateFeedback.org_id` is denormalised** (`models.py`) where its siblings
  (`CandidateDraft`, `IntegrityEvent`) are reached through `invite_id`. It keeps
  `_purge_org`'s "every table with an org_id is in this list" rule true, and it
  costs the write path one org lookup; if the rule is relaxed, the column and its
  index can go.

## P9a review leftovers — 2026-09-14

- Nothing in CI builds the web image, so the nginx config and the CSP are
  covered only by the file invariants in `tests/test_security_headers.py`. A
  dependency that later needs a CDN, an inline style or a cross-origin fetch
  would pass every check here and fail in production. Fix: a CI job that builds
  `web/Dockerfile`, runs the container and curls `/`, `/assets/<file>` and
  `/.well-known/security.txt` — the checks this branch ran by hand.
- `security.txt` has no `Policy:` field. RFC 9116 wants an absolute URI and the
  page it would name (`/security`) does not exist yet — it ships with P9b, which
  should add the field in the same change.
- The `Source` link is absent from the candidate's dead-end notices
  (`CandidateNotice.tsx`) and from the interviewer auth screens, which render no
  shell. Both are AGPL §13 surfaces a strict reading would want; the start
  screen, the legal pages and the app shell cover the ordinary paths.

## Unscheduled ideas

Not planned work; kept so they aren't rediscovered from scratch.

- **I2 · Plagiarism / similarity detection** across submissions (token-fingerprint /
  MOSS-style, optionally against public solutions and AI-generated-code detection).
  Largely mooted by per-candidate variants. **L.**
- **Candidate-feedback agent** (cross-repo, not yet chosen) — actionable feedback to
  candidates; also parked in the agent STATUS.
- **Per-role rubric customization** — weight readability vs performance vs idiom.
- **Reference in the candidate's language** — generate the oracle in whatever
  language they submit (agent).
- **Difficulty auto-calibration** — feed real pass-rates back to label difficulty
  empirically (cross-repo).
- **ATS/webhook integration** (Greenhouse, Lever) · **question-bank UX** (tagging,
  search, clone) · **candidate practice mode** as a free funnel.

## Deliberately not building

Revisit only on the named trigger — these are decisions, not gaps.

- **Webcam / identity capture.** The cost isn't the capture, it's consent and
  compliance (GDPR/BIPA), storage, and false-positive risk. Revisit only when a
  specific enterprise deal requires it.
- **Question authoring inside the assessment builder.** The questions page authors,
  the builder assembles. Revisit only on real demand.
