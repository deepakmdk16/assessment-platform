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

**Sequence:** (1) deploy + ops (X20, P26, X11) · (2) the rest by priority.
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
  Evidence: docs/PRIVACY.md:73-81 lists who candidate data reaches — the employer,
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
  Evidence: platform config.py:145-167 and api.py:433,461,2480 key on client_ip;
  agent ratelimit.py per-IP and in-memory (A13). Why: an office behind one NAT
  shares one bucket; one tenant cannot be capped independently. Fix: key expensive
  buckets (draft, submit, invites) on org_id in addition to IP; agent limiting moved
  to the platform's DB backend.
  _Verified: cited lines read in this audit; source: saas._
- **X10 · P1 · M — Interviewer-facing gaps a first paying customer hits.**
  Evidence: no question import/bulk upload (only hand-form or AI
  draft, api.py:554); no candidate-facing feedback or score (CandidatePage.tsx:345);
  no re-invite/extend-deadline (STATUS.md:118-121); no custom domain/white-label
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
  `Interviewer.default_org_name`/`default_logo_url` are still per-person
  ("workspace"-level) in a product where the workspace is now a shared
  `Organization` with its own name, so two admins keep separate branding
  defaults. `GET /auth/me` carries no organisation, so its name appears in
  exactly one place in the SPA. Question/assessment/variant-set ids remain one
  global slug namespace, so an explicit-id create is an existence oracle across
  organisations. Several open items above still cite `api.py:NNNN` line numbers
  that X01 moved by ~800-1000 lines. Why: none of these is user-visible today;
  together they are the tail of the org migration. Fix: a read surface for
  accepted invitations, decide whether branding defaults move to the org, and
  re-anchor the stale citations.

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
  ("grader unavailable, try again"). Since agent A07 the same branches can also
  echo the agent's new infra_error for a toolchain the jail can't see ("runtime
  not installed: … not on the jail PATH: 'ruby'").
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
- **W13 · P2 · XS — The logo URL is rendered unvalidated in the candidate's
browser.**
  Evidence: NewAssessmentPage.tsx:207-208 live-previews whatever is typed;
  AssessmentFlow.tsx:288 renders it for candidates; check whether schemas.py
  validates logo_url (https only). Why: http:// logos trigger mixed content; the
  candidate's IP is sent to an arbitrary host. Fix: require https:// client- and
  server-side.
  _Verified: single-audit claim, not independently re-verified; source: frontend._
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
- **X18 · P2 · S — Nobody is warned before an allowance runs out.**
  Evidence: the only signal is the refusal itself — 402 at invite/draft
  (api.py `_check_invite_capacity`, `billing.consume`), 403 to the candidate at
  `_require_sitting_quota`; no threshold email, and no mail of our own when Stripe
  reports `past_due` (the banner is only visible to someone who opens Settings).
  Why: the first time an interviewer learns the plan is exhausted is while trying
  to invite a candidate they have already scheduled. Fix: an email at ~80% of any
  allowance and one on `past_due`, both once per period per organisation.
  _Verified: read in the X02 branch; source: X02 follow-up._
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
- **W21 · P3 · XS — The start gate cannot show the logo before identification.**
  Evidence: `GET /invite/{token}` now carries the title, organisation, question
  count, duration and languages, and the gate renders them (P2a, 2026-09-13);
  `logo_url` still arrives only in the /start payload. Fix: add `logo_url` to
  `InviteStatusOut` and render it on the gate — do it in P3b (logo upload),
  which changes where the logo lives.
  _Verified: cited lines read in this audit; source: frontend,saas._

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
- **The AI notice is hand-mirrored** between `AssessmentNotice` in
  `CandidatePage.tsx` and the "Automated assessment" section of
  `docs/PRIVACY.md`. When P2b puts a support address on the probe, both should
  render that one field instead of restating the contact sentence.

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
