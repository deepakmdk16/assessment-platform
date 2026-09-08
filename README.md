# Assessment Platform

The stateful **system of record** that complements the stateless [Assessment Agent](../AssesmentAgent).
It owns all durable data — coding **questions** (with their expected answers /
test cases), candidate **submissions**, and the **assessment results** the agent
returns — and orchestrates grading by handing jobs to the agent and storing what
comes back.

The platform **never grades**. The agent is the deterministic grader; the
platform stores the agent's verdict/score verbatim and never computes or
overrides them.

## How it fits together

```
client ──POST /submissions──▶ platform ──POST /assessments──▶ agent (stateless)
                                  ▲                                  │
                                  └──POST /assessments/callback──────┘
                                     (agent returns the full result)
```

`POST /submissions` stores the submission, builds the agent request (the stored
question inline + the candidate code + a `callback_url` pointing back at this
platform + a `job_id` the platform mints and commits **before** the call), POSTs
it to the agent, and flips the submission to `running` once the agent accepts.
The agent grades asynchronously and POSTs the full result to
`/assessments/callback`, which the platform persists (verbatim in `full_result`)
and uses to flip the submission to `done` / `error`. If the agent can't be
reached the submission stays `pending` — never a 502 — and a background reaper
re-triggers it (giving up, loudly, after a few attempts).

## Stack

Python ≥ 3.10 · [uv](https://docs.astral.sh/uv/) · FastAPI · SQLModel
(SQLAlchemy + Pydantic) · SQLite (dev) · httpx.

## Run it

```bash
uv sync                 # install deps into .venv
bash scripts/dev.sh     # migrate ./dev.db to head, then serve on :9000
```

`scripts/dev.sh` runs `alembic upgrade head` before starting, so an existing
`dev.db` picks up new migrations instead of 500-ing on a missing column; it pins
`DATABASE_URL` to `./dev.db` unless you export your own. To run the raw server
without the migrate step, use `uv run platform-api` (config default DB is
`./platform.db`).

Schema comes from Alembic (`uv run alembic upgrade head`). For a quick local
start you can instead set `AUTO_CREATE_TABLES=true` to have the tables created on
startup (`SQLModel.metadata.create_all`) — but that only creates a *fresh* DB, it
never ALTERs an existing one, so it defaults off and `scripts/dev.sh` is the
safe path for an evolving `dev.db`.

### Configuration (env vars)

| Var                 | Default                        | Purpose                                              |
| ------------------- | ------------------------------ | ---------------------------------------------------- |
| `DATABASE_URL`      | `sqlite:///./platform.db`      | SQLAlchemy URL. Swap to a `postgresql+...` URL for prod — URL-only change. |
| `AGENT_BASE_URL`    | `http://127.0.0.1:8000`        | Base URL of the Assessment Agent.                    |
| `PLATFORM_BASE_URL` | `http://127.0.0.1:9000`        | This platform's public URL, used to build the callback URL handed to the agent. |
| `AGENT_TIMEOUT_S`   | `10.0`                         | Timeout for the outbound "trigger job" call (the agent 202s immediately). |
| `AGENT_DRAFT_TIMEOUT_S` | `240.0`                    | Timeout for the synchronous "Draft with AI" call. Long: it runs an LLM + executes the reference inline, and the agent re-drafts internally if its first attempt is unusable. |
| `AGENT_RUN_TIMEOUT_S`   | `60.0`                     | Timeout for the candidate's synchronous Run / Run-against-tests calls (compile + execute, no LLM). |
| `HOST` / `PORT`     | `127.0.0.1` / `9000`           | Bind address for `platform-api`.                     |
| `JWT_SECRET`        | *(ephemeral if unset)*         | HMAC secret for interviewer JWTs. **Required in prod** — if unset, an ephemeral per-process secret is generated (tokens don't survive a restart) and a warning is logged. |
| `JWT_EXPIRE_MIN`    | `15`                           | Interviewer access-token lifetime (minutes). Short on purpose: the SPA holds it in memory only; sessions outlive it via the refresh cookie. |
| `REFRESH_EXPIRE_DAYS` | `30`                         | Refresh-token lifetime — an httpOnly cookie scoped to `/auth`; how long a browser stays signed in. Sliding. |
| `COOKIE_SECURE`     | *(on iff `PLATFORM_BASE_URL` is https)* | `Secure` flag on the refresh cookie. Browsers drop a Secure cookie set over plain http, so leave the default. |
| `COOKIE_SAMESITE`   | `lax`                          | `lax` when the SPA and API share a site (same host or subdomains of one domain); `none` (Secure required) only for unrelated domains. |
| `PASSWORD_BREACH_CHECK` | `true`                     | Check new passwords against Have I Been Pwned (k-anonymity; only a 5-char hash prefix leaves the server; fails open). Off under test. |
| `FRONTEND_BASE_URL` | `http://127.0.0.1:5173`        | Frontend origin; the candidate invite, verify-email and reset-password links are all built from it. Must be the **exact spelling** the dev server binds and you browse (`web/vite.config.ts` pins `127.0.0.1`) — `localhost` and `127.0.0.1` are different *sites*, so mixing them mints dead links and silently voids the refresh cookie. |
| `RUN_RATE_LIMIT_MAX` | `60`                          | Candidate Run / Run-against-tests per `RATE_LIMIT_WINDOW_S`. These are free agent compute, and run-tests is a pass/fail oracle — don't disable in prod. `0` disables. |

#### Where secrets live

Config is read from the environment, and a **`.env` at the repo root is loaded if
present** (real env vars take precedence, so deployments are unaffected). `.env` is
gitignored; [`.env.example`](.env.example) is the template:

```bash
cp .env.example .env   # then fill in — never commit .env
```

#### Sending invite emails (SMTP)

**SMTP is required to start the API.** All five of `SMTP_HOST`, `SMTP_PORT`,
`SMTP_USER`, `SMTP_PASSWORD` and `SMTP_FROM` must be set, and `SMTP_FROM` must be
changed from the `no-reply@assessment.local` placeholder — that domain has no MX,
so mail sent from it bounces. Otherwise the server refuses to boot and names the
variables it is missing. Every invite, address confirmation and password reset
leaves this way, so a half-configured mailer means accepting invites you then
silently never deliver.

For offline dev, start with `ALLOW_UNCONFIGURED_EMAIL=true`: the mailer logs the
link instead of sending it (add `LOG_PII=true` to log it verbatim). Never set it
in a deployment. Creating an invite returns a per-recipient `deliveries[]` saying
whether each address was actually mailed, and the UI warns when a send failed.

| Var             | Default                    | Purpose                                        |
| --------------- | -------------------------- | ---------------------------------------------- |
| `SMTP_HOST`     | *(required)*               | SMTP server hostname.                          |
| `SMTP_PORT`     | `587`                      | SMTP port (587 = STARTTLS).                    |
| `SMTP_USER`     | *(required)*               | Username the server authenticates.             |
| `SMTP_PASSWORD` | *(required)*               | Password / app password. **Never commit this.** |
| `SMTP_FROM`     | *(required)*               | From address. The `no-reply@assessment.local` placeholder counts as unset. |
| `SMTP_USE_TLS`  | `true`                     | STARTTLS. `false` only for a local test relay. |
| `SMTP_TIMEOUT_S` | `10`                      | Per socket operation (connect, TLS, login, send). |
| `SMTP_DEADLINE_S` | `30`                     | Ceiling on one whole multi-recipient send.     |
| `ALLOW_UNCONFIGURED_EMAIL` | `false`         | Offline dev only: boot without SMTP and log links instead. |

Gmail works for testing: enable 2-Step Verification, then create an **app password**
(Google Account → Security → App passwords) — your normal account password will not
work, and `SMTP_FROM` must equal `SMTP_USER` because Gmail rewrites `From` to the
authenticated account. It rate-limits and mail often lands in spam without SPF/DKIM
on your domain, so for real candidates use a transactional provider (SES, Postmark,
Resend) with a verified sending domain.

## Endpoints

Interviewer routes require a `Bearer` JWT and are organisation-scoped: every
resource belongs to an `Organization`, and everyone in it shares the library. `/auth/login`
returns a short-lived access token **and** sets an httpOnly `refresh_token`
cookie (path `/auth`); `POST /auth/refresh` trades the cookie for a new access
token, which is how the SPA resumes a session on page load. Every token carries
the account's `token_version`; a password change or reset bumps it, signing out
every device at once. Passwords: ≥ 12 characters, ≤ 72 bytes, and not in a
known breach. Emails are lower-cased on register and login. Candidate routes
are **public but token-gated** (no bearer) and never expose test cases /
expected outputs.

Candidate routes are additionally **bound to the invite's recipients**: the caller
must identify with an email the invite was sent to, and a candidate who already
submitted is turned away. Note this is an identity *claim*, not proof — someone
holding the link who knows an invited address could still type it. It stops a
forwarded link, not deliberate impersonation.

| Method | Path                              | Auth        | Purpose                                                        |
| ------ | --------------------------------- | ----------- | ------------------------------------------------------------- |
| GET    | `/health`                         | none        | `{"status":"ok"}`                                             |
| POST   | `/auth/register`                  | none        | Register an interviewer → `{id,email,name,email_verified}` (409 if email taken, 422 weak/breached password); emails a confirmation link. |
| POST   | `/auth/login`                     | none        | → `{access_token, token_type:"bearer"}` + refresh cookie (401 on bad creds). |
| POST   | `/auth/refresh`                   | cookie      | → a new `{access_token}` and re-issued cookie (401 = not signed in). |
| POST   | `/auth/logout`                    | none        | Clears this browser's refresh cookie (204).                   |
| GET    | `/auth/me`                        | bearer      | Current interviewer.                                          |
| PATCH  | `/auth/me`                        | bearer      | Update workspace defaults (branding).                         |
| DELETE | `/auth/me`                        | bearer      | Delete the account. Takes the organisation with it only if you are its last member; 409 if you are its only admin and others remain. Body `{password}` (403 wrong password). |
| POST   | `/auth/change-password`           | bearer      | `{current_password,new_password}` → fresh session; every other device is signed out. |
| POST   | `/auth/forgot-password`           | none        | `{email}` → 202 either way; emails a one-hour, single-use reset link if the address has an account. |
| POST   | `/auth/reset-password`            | none        | `{token,new_password}` → 204 (400 bad/used/expired link). Signs out every device. |
| POST   | `/auth/verify-email`              | none        | `{token}` from the emailed link → 204 (400 bad/expired).      |
| POST   | `/auth/resend-verification`       | bearer      | Re-send the confirmation link (202).                          |
| POST   | `/questions`                      | bearer      | Create a question (owned by caller).                         |
| POST   | `/questions/draft`                | bearer      | Draft a question from a brief via the agent. **Stores nothing** — the interviewer reviews/edits, then saves via `POST /questions`. |
| POST   | `/orgs`                           | bearer      | Found an organisation, for an account that belongs to none (409 if it already does). |
| GET    | `/orgs/current`                   | bearer      | The caller's organisation, their role in it, and its size.   |
| PATCH  | `/orgs/current`                   | bearer      | Rename it (admin only).                                      |
| GET    | `/orgs/current/members`           | bearer      | The roster (any member).                                     |
| PATCH  | `/orgs/current/members/{id}`      | bearer      | Change a role (admin only); **409** for the last admin.      |
| DELETE | `/orgs/current/members/{id}`      | bearer      | Remove someone (admin only); their work stays with the organisation. |
| GET    | `/orgs/current/invites`           | bearer      | Invitations sent but not yet accepted (admin only).          |
| POST   | `/orgs/current/invites`           | bearer      | Invite one address (admin only); emails the link and records whether it sent. |
| DELETE | `/orgs/current/invites/{id}`      | bearer      | Withdraw a pending invitation (admin only).                  |
| GET    | `/org-invites/{token}`            | public      | What the join page shows: organisation name, invited address, role. |
| POST   | `/org-invites/{token}/accept`     | bearer      | Accept as an existing account (403 wrong address; 409 if your current organisation has members or work). |
| GET    | `/questions`                      | bearer      | List the organisation's questions (active only; `?include_archived=true` to include archived). |
| GET    | `/questions/{id}`                 | bearer      | Get one (403 if another organisation's, 404 if missing).     |
| PUT    | `/questions/{id}`                 | bearer      | Full replace (the organisation's own).                       |
| POST   | `/questions/{id}/archive`         | bearer      | Retire a question: hidden from the default list, submissions kept. The path for a question with submissions (DELETE 409s on those). |
| POST   | `/questions/{id}/unarchive`       | bearer      | Restore an archived question to the active list.             |
| DELETE | `/questions/{id}`                 | bearer      | Delete (the organisation's own); **409** once it has submissions — archive it instead. |
| POST   | `/questions/{id}/invites`         | bearer      | Create a candidate invite link → `{token,url,deliveries[],...}`. **At least one recipient is required** — the link only works for those addresses. |
| GET    | `/questions/{id}/invites`         | bearer      | List invites for a question.                                 |
| POST   | `/questions/{id}/invites/{token}/revoke` | bearer | Deactivate an invite; its link then 410s.                 |
| GET    | `/questions/{id}/submissions`     | bearer      | Dashboard: submissions for that question (the organisation's own). |
| GET    | `/invite/{token}`                 | public      | **Liveness probe only** — `{"status":"active"}`. Carries no question data. 404 invalid / 410 revoked-or-expired. |
| POST   | `/invite/{token}/start`           | public      | Candidate identifies as an invited recipient → the question + languages. 403 if not invited, 409 if they already submitted. **This is the only route that hands out the question.** |
| POST   | `/invite/{token}/run`             | public      | Run their code against their own stdin → stdout/stderr/timing. Not a submission. |
| POST   | `/invite/{token}/run-tests`       | public      | Run the question's suite → **pass/fail per case only** (no inputs/expected). Not a submission. |
| POST   | `/invite/{token}/submit`          | public      | Candidate submits code → creates a submission + triggers the agent. |
| POST   | `/submissions`                    | none*       | Direct submission + trigger (internal path).                 |
| GET    | `/submissions` / `/submissions/{id}` | none*    | List / get a submission + its result.                        |
| POST   | `/submissions/{id}/retry`         | none*       | Re-trigger a submission stuck in `error` (409 otherwise).    |
| POST   | `/assessments/callback`           | agent token | Agent posts the full result here; persisted verbatim.        |

\* The pre-existing internal `/submissions*` routes are not yet behind interviewer
auth — see the security TODO.

The list endpoints (`GET /questions`, `GET /submissions`, `GET
/questions/{id}/submissions`) are paginated: `?limit` (default 100, max 200) +
`?offset`, returning an envelope `{ items, total, limit, offset }` where `total`
is the full count, so a client can render a pager in one request.

Interactive docs at `/docs` when running.

## Data model

- **Interviewer** — `id` (PK), `email` (unique), `password_hash` (bcrypt),
  `name`, `created_at`.
- **Organization** — `id` (PK), `name`. The tenant: what every owned row below
  is scoped to.
- **Membership** — `org_id`, `interviewer_id` (**unique** — one organisation per
  person, deliberately), `role` (`admin` | `member`), `invited_by`.
- **OrgInvite** — `org_id`, `token` (unique), `email`, `role`, `invited_by`,
  `expires_at`, `accepted_at`, `sent` / `send_error`. Kept after acceptance as
  the record of who joined, when, and at whose invitation.
- **Question** — `id` (PK), `org_id` (FK → Organization, the access scope),
  `owner_id` (FK → Interviewer, nullable — who authored it), `title`, `prompt`,
  `constraints`, `time_limit_s` (2.0), `pass_threshold` (0.9),
  `required_complexity?`, `example_input?`, `example_output?`, `created_at`,
  `updated_at`, and a child list of **QuestionTestCase** (`name`, `stdin`,
  `expected`, `category` `correctness|performance`, `weight`).
- **Invite** — `id` (PK), `token` (unique, url-safe random), `question_id` (FK),
  `created_by` (FK → Interviewer, nullable — who sent it), `recipients` (JSON list of emails),
  `expires_at?`, `status` (`active`), `created_at`.
- **Submission** — `id` (uuid), `question_id` (FK), `invite_id?` (FK, set for
  candidate submissions), `candidate` (name), `candidate_email?`, `language`,
  `code`, `status` `pending|running|done|error`, `agent_job_id?`, `created_at`.
- **AssessmentResult** — `id`, `submission_id` (FK, unique), `verdict`
  `PASS|FAIL|ERROR`, `score_pct`, `reason`, `full_result` (JSON — the agent's
  entire callback payload verbatim), `received_at`.

### Notes

- **Submissions are immutable.** A genuine re-run (new code, or grading a
  candidate again) creates a **new** submission. `POST /submissions/{id}/retry`
  is not a re-run — it only re-triggers a submission whose initial agent call
  failed (status `error`); any other status returns 409.
- **Postgres is the confirmed eventual production database.** The swap is
  URL-only: point `DATABASE_URL` at a `postgresql+...` URL — no code change (the
  SQLite-specific `check_same_thread` arg is applied only for SQLite URLs).

## Development

```bash
uv run pytest        # tests (fully offline — the agent call is mocked)
uv run ruff check .  # lint
uv run mypy          # type-check
```

## Auth (shared secret)

The platform ↔ agent link is protected by a shared-secret bearer token in the
`X-Assess-Token` header, matching the agent's contract exactly. **Set both in
production;** each check is enforced only when its env var is set (unset => no
auth, so dev and the test suite run token-free).

| Env var            | Direction | Effect                                                                                   |
| ------------------ | --------- | ---------------------------------------------------------------------------------------- |
| `CALLBACK_TOKEN`   | inbound   | The secret the **agent** sends to `POST /assessments/callback`. When set, callbacks without a matching `X-Assess-Token` header get **401** (checked before any job_id logic). |
| `ASSESS_API_TOKEN` | outbound  | The secret **we** send when triggering the agent's `POST /assessments`. When set, we add `X-Assess-Token: <ASSESS_API_TOKEN>` to that request; when unset, no header is sent. |

These two must agree with the agent's env: the agent requires `ASSESS_API_TOKEN`
on its inbound `/assessments` and sends `CALLBACK_TOKEN` on its outbound callback.

Still open before production:

- No auth on the inbound `POST /submissions` yet (who may submit) — add an API
  key / caller auth there.
- Candidate `code` is untrusted; the agent sandboxes execution, but treat stored
  code as untrusted data here too.

## License

Dual-licensed. Copyright (c) 2026 deepak madire.

- **Open source: [GNU AGPL-3.0](LICENSE).** Free to use, study, modify,
  extend and redistribute. If you distribute a modified version, or offer
  the software (or a derivative) to others over a network, you must release
  your complete source under the same license.
- **Commercial license.** If you want to monetize this software without
  releasing your own source, or need enterprise terms (warranty, support,
  no copyleft), a paid commercial license is available from the copyright
  holder. Open a GitHub issue on this repository to request one.
