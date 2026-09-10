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

The values Compose hardcodes — `DATABASE_URL`, `AGENT_BASE_URL`,
`PLATFORM_BASE_URL`, `TRUST_PROXY_HEADERS`, `RATE_LIMIT_BACKEND`,
`AUTO_CREATE_TABLES` — override `.env`, because they are only correct inside
this network. Change them in `docker-compose.yml`, not in `.env`, or your edit
will appear to do nothing. `COOKIE_SECURE`, `WEB_PORT`, `TRUSTED_PROXY_CIDR`,
`VITE_PRODUCT_NAME` and `PUBLIC_BASE_URL` are the opposite — compose reads them
*from* `.env`, so set those there.

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
- **No metrics, tracing or error reporting** (X08). Failed callbacks, grading
  latency and error rates are visible only in `docker compose logs`.
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
