# Deploying the assessment system

Four containers: Postgres, the **agent** (runs untrusted candidate code), the
**platform** API (the system of record), and **nginx** serving the SPA and
fronting the API on one origin. `docker-compose.yml` in the repository root
wires them together; this file is the walkthrough.

> **Read the host requirement first.** The agent must run privileged
> (`--privileged --cgroupns=host`) so nsjail can build its jail. That rules out
> Cloud Run, Fly, Railway, Render and Fargate — this stack needs a VM you
> control, or a Kubernetes cluster that permits privileged pods. STATUS.md A07
> tracks narrowing that requirement; until it closes, plan for a VM.

## What runs where

| Service | Image | Exposed | Notes |
| --- | --- | --- | --- |
| `db` | `postgres:17-alpine` | internal | Volume `pgdata`; the entire product record |
| `agent` | built from `../AssesmentAgent` | internal | Privileged. Never expose it — it executes untrusted code |
| `platform` | built from `./Dockerfile` | internal | Runs `alembic upgrade head` at boot, then uvicorn on 9000 |
| `web` | built from `./web/Dockerfile` | `WEB_PORT` | Static SPA + `/api/` reverse proxy to `platform` |

Only `web` publishes a port. The API is reached through nginx at `/api/` rather
than on its own origin: the refresh cookie is `SameSite=lax`, and one origin for
both the app and the API is the only arrangement where a session survives a
reload without loosening it. It also makes `CORS_ORIGINS` irrelevant here.

## Prerequisites

- Docker Engine 25+ with Compose v2 (`cgroup: host` needs Compose ≥ 2.15).
- A host that allows privileged containers, with cgroup v2 (any current Linux).
- Both repositories checked out side by side. The agent's build context defaults
  to `../AssesmentAgent`; set `AGENT_CONTEXT` if yours differ.
- A DNS name for `PUBLIC_BASE_URL` and, in front of it, something terminating
  TLS. Nothing here terminates TLS itself.

## 1. Fill in `.env`

`.env` lives in this repository root, is gitignored, and is read both by Compose
(for `${...}` substitution) and by the `platform` container (`env_file:`).
Start from the template — every variable is documented there:

```bash
cp .env.example .env
```

Compose refuses to start until these are set. Generate each secret with
`openssl rand -hex 32`:

| Variable | Why |
| --- | --- |
| `POSTGRES_PASSWORD` | The `db` password, and what `DATABASE_URL` is built from |
| `ASSESS_API_TOKEN` | Platform → agent auth |
| `CALLBACK_TOKEN` | Agent → platform auth on the result callback |
| `ASSESS_SIGNING_SECRET` | HMAC over the request body, platform → agent |
| `CALLBACK_SIGNING_SECRET` | HMAC over the callback body, agent → platform |
| `PUBLIC_BASE_URL` | The origin candidates open; every invite link points here |

Also required by the application itself, and equally non-optional:

- **`JWT_SECRET`** — sessions are forgeable without it.
- **SMTP** — the API refuses to boot without a complete mailer, because a server
  that cannot send mail accepts invites it then silently never delivers. Note
  the preflight checks that the five variables are *present*, not that they
  work: `.env.example` ships the Gmail placeholders uncommented, so a
  straight `cp` boots a server whose every send then fails at the provider.
  Replace them, and send yourself one invite before trusting it.
  `ALLOW_UNCONFIGURED_EMAIL=true` is for offline dev only.
- **`REGISTRATION_CODE`** — unset leaves interviewer sign-up open to the world.
  It gates only *founding a new organisation*; joining an existing one goes
  through an org invite, which is its own credential.
- **`ANTHROPIC_API_KEY`** — without it the LLM judge and question drafting
  degrade; the agent reports quality as unavailable.
- **Stripe keys** if you are charging (`.env.example` → billing).

Nothing about observability is required, and everything is off until you set it
(§4 is what to do with it). Set these in `.env`; the agent's are the same
settings under its own `ASSESS_` names, because it reads only those:

| Variable | Agent's name | Default | What it does |
| --- | --- | --- | --- |
| `LOG_LEVEL` | `ASSESS_LOG_LEVEL` | `INFO` | Root level for the process. Uvicorn configures only its own loggers, so this is what makes the app's breadcrumbs print |
| `LOG_FORMAT` | `ASSESS_LOG_FORMAT` | `text` | `json` emits one JSON object per line for an aggregator |
| `SENTRY_DSN` | `ASSESS_SENTRY_DSN` | unset | Unset means no error reporting at all — the SDK is never even imported |
| `SENTRY_ENVIRONMENT` | `ASSESS_SENTRY_ENVIRONMENT` | `production` | The label every event is filed under |
| `SENTRY_RELEASE` | `ASSESS_SENTRY_RELEASE` | unset | Which build an error came from, typically the deployed git sha |
| `SENTRY_TRACES_SAMPLE_RATE` | `ASSESS_SENTRY_TRACES_SAMPLE_RATE` | `0` | Performance tracing, off by default: it is the costly half of Sentry and the half that samples request data |
| `METRICS_TOKEN` | — (uses `ASSESS_API_TOKEN`) | unset | Shared secret for `GET /metrics`. **Fail-closed:** unset means the route 503s, because it is the only one that reads across every organisation |
| `METRICS_AUTH_DISABLED` | — (agent: `ASSESS_AUTH_DISABLED`) | `false` | The explicit opt-out for a dev box that wants an unauthenticated scrape |
| `METRICS_WINDOW_S` | — | `86400` | How far back the platform's grade-latency histogram looks |
| `METRICS_MAX_SAMPLES` | — | `5000` | Ceiling on rows one scrape reads for that histogram. A busy deployment hits this before the window, so the histogram then covers less than `METRICS_WINDOW_S` |

The platform's names arrive through `env_file:`, so `.env` is enough for them.
The agent has **no** `env_file:` — every `ASSESS_`-prefixed name above reaches it
only because `docker-compose.yml` lists it explicitly in the agent service's
`environment:` block. Setting an unprefixed name for the worker does nothing.

The values Compose hardcodes — `DATABASE_URL`, `AGENT_BASE_URL`,
`PLATFORM_BASE_URL`, `TRUST_PROXY_HEADERS`, `RATE_LIMIT_BACKEND`,
`AUTO_CREATE_TABLES` — override `.env`, because they are only correct inside
this network. Change them in `docker-compose.yml`, not in `.env`, or your edit
will appear to do nothing. `COOKIE_SECURE`, `WEB_PORT`, `TRUSTED_PROXY_CIDR`,
`VITE_PRODUCT_NAME`, `PUBLIC_BASE_URL` and the observability variables above are
the opposite — compose reads them *from* `.env` (as `${VAR:-default}`, so an
existing `.env` upgrades unchanged), so set those there.

## 2. Bring it up

```bash
docker compose up -d --build
docker compose ps          # db, platform and web report (healthy)
docker compose logs -f platform
```

The first build takes a while: the agent compiles nsjail from source and
installs eight language toolchains. The agent shows `running` rather than
`(healthy)` — its image defines no health probe; the platform's own boot would
fail if the agent were unreachable.

`platform` waits for Postgres to pass `pg_isready`, then runs
`alembic upgrade head` before binding its port. A failed migration is a boot
failure you see in the logs, not a 500 in front of a candidate.

Verify, against whatever `WEB_PORT` publishes (`:80` by default):

```bash
curl -fsS http://127.0.0.1/api/health   # {"status":"ok"} — proxied to the API
curl -fsS http://127.0.0.1/ | head -1   # the SPA
```

## 3. Put TLS in front

Bind nginx to loopback and let a terminator (Caddy, a cloud load balancer, an
nginx on the host) hold the certificate:

```
WEB_PORT=127.0.0.1:8080
PUBLIC_BASE_URL=https://assess.example.com
```

Two settings depend on this and are wrong by default without it:

- **`COOKIE_SECURE`** defaults to `true` in `docker-compose.yml`. It is normally
  derived from `PLATFORM_BASE_URL`, which is internal `http` here, so the
  derivation would drop `Secure` from the session cookie. Set it to `false` only
  for a plain-`http` trial — a browser drops a `Secure` cookie sent over http,
  and the session then silently never persists.
- **`TRUSTED_PROXY_CIDR`** must name your terminator. `ratelimit.py` trusts the
  rightmost `X-Forwarded-For` entry, and nginx sets that entry to `$remote_addr`
  — which is the *terminator* until nginx is told to believe the terminator's
  own `X-Forwarded-For`. Leave it at the loopback default behind TLS and every
  caller in the deployment shares one rate-limit bucket, so the first few
  failed logins lock out everybody:

  ```
  TRUSTED_PROXY_CIDR=10.0.0.0/8      # or the terminator's exact address
  ```

  With a CDN in front of the terminator, list the chain — `real_ip_recursive`
  is on, so nginx walks left past every address you have declared trusted.

## 4. Monitoring

Both services expose Prometheus text at `/metrics`, both can emit JSON logs, and
both can report errors to Sentry (X08). None of it is on by default — pick what
you will actually look at, and read §1's table for the variables.

### Scraping

Neither endpoint is internet-facing, deliberately. nginx returns 404 for
`/api/metrics` (`web/nginx.conf.template`), and the agent publishes no port at
all — it is on the internal `grading` network because it executes untrusted
code. So a scrape happens from inside the compose network:

The `platform` container is the one place that can reach both, and it already
holds both tokens in its own environment. It has no `curl` — like the image's
HEALTHCHECK, use the interpreter that is already there:

```bash
docker compose exec -T platform python - <<'EOF'
import os, urllib.request as u
for url, token in (
    ("http://platform:9000/metrics", os.environ.get("METRICS_TOKEN", "")),
    ("http://agent:8000/metrics", os.environ.get("ASSESS_API_TOKEN", "")),
):
    req = u.Request(url, headers={"X-Assess-Token": token})
    print(u.urlopen(req, timeout=5).read().decode())
EOF
```

Note the two tokens differ: the platform's scrape is guarded by `METRICS_TOKEN`
and *only when it is set*; the agent's is guarded by `ASSESS_API_TOKEN`, the same
secret the platform authenticates with, and is fail-closed — the agent answers
503 rather than opening up if that variable is missing. A real Prometheus belongs
on the `grading` network, which is the one network that reaches both services.

### What the numbers mean

The platform's are **derived by query** from rows it already stores, so a restart
does not reset them and a second API replica does not halve them:

| Metric | Meaning |
| --- | --- |
| `platform_submissions{status=pending\|running\|done\|error}` | Every submission by grading status |
| `platform_submissions_stalled{state=pending\|running}` | Past their re-trigger grace, waiting on the reaper |
| `platform_grade_giveups` | Abandoned after `MAX_TRIGGER_ATTEMPTS`; each one needs a human |
| `platform_results{verdict=PASS\|FAIL\|ERROR}` | Stored agent results by verdict |
| `platform_grade_latency_seconds` | Histogram: submit → stored result, over `METRICS_WINDOW_S` |

The agent's are **in-process counters**, and that difference matters when you
read them: they start at zero on every restart, and if you run more than one
worker each reports only its own share (sum by instance, which is what a scraper
does anyway). The platform's durable view of the same jobs is the other half of
the picture.

| Metric | Meaning |
| --- | --- |
| `agent_jobs_total{outcome=accepted\|done\|error}` | Grading jobs since this worker started |
| `agent_jobs_inflight` | Accepted jobs whose result has not been delivered yet |
| `agent_callbacks_total{outcome=delivered\|rejected\|failed\|requeued}` | Result deliveries. `failed` is a grade thrown away; `requeued` is the shutdown flush giving up, which the platform's reaper retries — a normal deploy, not an incident |
| `agent_grade_latency_seconds` | Histogram: wall-clock seconds to grade one submission |

**Alert on the three that mean results are being lost**, not on the pretty ones:

- `platform_submissions_stalled` — persistently above zero means the callback
  path (or the reaper itself) is broken. It is the first number to look at.
- `platform_grade_giveups` — rising means submissions have exhausted their
  retries and are sitting in `error` for a human to retry by hand.
- `agent_callbacks_total{outcome="failed"}` — the agent graded a submission and
  could not deliver the result. That grade is gone; the platform still shows the
  submission as `running`, so the reaper re-triggers it and the work is done
  twice, or the retries run out and it becomes a give-up.

Grade latency is a health signal rather than an alert: the platform's histogram
measures submit → stored result (queueing, the agent, and the callback), the
agent's measures grading alone, and a gap opening between them is the callback
or the queue, not the grader.

### Logs

`LOG_FORMAT=json` (and `ASSESS_LOG_FORMAT=json`) switches each process to one
JSON object per line — `ts`, `level`, `logger`, `request_id`, `msg`, plus `exc`
on a traceback — which is what an aggregator wants. Leave it at `text` if the
reader is a human tailing `docker compose logs`.

Two things to know before you turn it on:

- The uvicorn access line has its query string **redacted** unless `LOG_PII=true`,
  because invite tokens and candidate email addresses travel in query strings.
  Turning `LOG_PII` on to debug something also ships that to your aggregator.
- JSON lines are several times larger than the text lines they replace, and
  `docker-compose.yml` caps the json-file driver at 10 MB × 5 files per
  container. The same cap therefore holds noticeably less history — raise
  `max-size` or ship the lines off the box before you need them.

### Following one request through

nginx mints an `X-Request-Id` per request and passes it upstream; the platform
adopts an inbound id when it is well formed rather than minting its own, puts it
on every log line, forwards it to the agent on the trigger, gets it back on the
result callback, and echoes it on the response (CORS exposes the header too, for
a browser talking to the API directly rather than through nginx). The SPA reads
it back and shows it as
`(ref: <id>)` on a 5xx, which makes an interviewer's "it broke" reproducible:

```bash
docker compose logs platform | grep 1a2b3c4d5e6f7081
```

That one id spans submit → trigger → grade → callback across both containers.
Add `$request_id` to nginx's `log_format` if you want nginx's own access log to
join the trace; the stock `combined` format omits it. Sentry events carry the
same id as a `request_id` tag, so a crash report searches straight back to its
log lines — and both are reachable from the `ref:` an interviewer read off the
screen.

### Sentry

With no DSN nothing is initialised, nothing is imported and nothing is sent — it
is inert, not merely quiet, and it stays off in the test suite whatever `.env`
holds. When a DSN is set, every event is scrubbed before it leaves the box: the
request body, cookies, query string and the user block are dropped and headers
are cut to a safe allowlist, so candidate source code and candidate email
addresses are not shipped to a third party. Performance tracing is off
(`SENTRY_TRACES_SAMPLE_RATE=0`) because it samples request data on every route,
which is both the expensive half of the bill and the larger PII surface.

## Upgrading

```bash
git pull && docker compose up -d --build
```

The platform container migrates on every start, and Alembic is a no-op at head.
Take a database backup first: migrations are not reversible in practice.

**More than one API replica:** two containers racing `alembic upgrade head` can
deadlock on the same DDL. Run the migration once as a release step and start the
replicas without it:

```bash
docker compose run --rm --entrypoint alembic platform upgrade head
```

and give the replicas a command that skips the boot migration:

```yaml
command: ["--no-migrate", "platform-api"]
```

## Operational gaps to know about

These are open items, not surprises — they are in STATUS.md, and a deploy is
where they bite:

- **No backups exist** (X20). The agent is stateless, so this database is the
  entire product record. `docs/BACKUPS.md` states the target; nothing implements
  it. Use managed Postgres with PITR, or schedule `pg_dump` off the host,
  *before* real candidates exist.
- **Observability is opt-in, and there is still no tracing** (X08 landed the
  rest). Metrics, JSON logs and Sentry all exist now (§4), but every one of them
  is off until you configure it, so a stack brought up from a bare `.env` still
  shows failed callbacks and grading latency only in `docker compose logs`. The
  agent's counters are per-process and reset on restart; the platform's are
  DB-derived and survive one. There are no distributed traces — the
  `X-Request-Id` on every log line is what stitches a request together instead.
- **Timestamps are timezone-naive** (P14), and nothing pins the session time
  zone. This compose stack is correct only because both images happen to default
  to UTC (verified: `SHOW timezone` = UTC in `db`, `time.tzname` = UTC in
  `platform`). Point `DATABASE_URL` at a managed Postgres in another zone, or set
  `TZ` on either container, and every deadline and expiry shifts by that offset
  with nothing to catch it. Until P14 closes, keep both on UTC.
- **Rate limits are per-IP, not per-tenant** (X09). An office behind one NAT
  shares a bucket.
- **The agent's LLM provider is pinned to `anthropic`** in `docker-compose.yml`.
  Left unset, the agent auto-selects Ollama whenever `ANTHROPIC_API_KEY` is
  absent and then fails every call in a container with no Ollama (A02).
- **The privacy notice, terms and DPA are unreviewed templates** (X19), and
  email needs a real sending domain with SPF/DKIM/DMARC (X07).

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `platform` exits at boot with an email error | The mailer preflight. Fill in the five SMTP variables |
| Agent runs fail with a sandbox error | The container is not privileged, or the host lacks cgroup v2 |
| Invite links point at the wrong host | `PUBLIC_BASE_URL` — it is baked into every minted link |
| Signed requests 401 between the services | The four shared secrets differ between the two containers |
| Login succeeds but the session drops on reload | `COOKIE_SECURE=true` served over plain http |
| A UI change did not appear | `VITE_*` values are baked at build time; rebuild `web` |
| `/api/metrics` returns 404 from outside | By design — nginx refuses it. Scrape from inside the network (§4) |
| The metrics scrape 401s | `METRICS_TOKEN` (platform) or `ASSESS_API_TOKEN` (agent) does not match the header sent |
| The metrics scrape 503s | No token is configured. Both services are fail-closed here: set `METRICS_TOKEN` / `ASSESS_API_TOKEN`, or `METRICS_AUTH_DISABLED=true` on a dev box |
