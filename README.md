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
platform), POSTs it to the agent, records the returned `job_id`, and flips the
submission to `running`. The agent grades asynchronously and POSTs the full
result to `/assessments/callback`, which the platform persists (verbatim in
`full_result`) and uses to flip the submission to `done` / `error`.

## Stack

Python ≥ 3.10 · [uv](https://docs.astral.sh/uv/) · FastAPI · SQLModel
(SQLAlchemy + Pydantic) · SQLite (dev) · httpx.

## Run it

```bash
uv sync                 # install deps into .venv
uv run platform-api     # serve on http://127.0.0.1:9000
```

Tables are created on startup (`SQLModel.metadata.create_all`; no Alembic in v1).

### Configuration (env vars)

| Var                 | Default                        | Purpose                                              |
| ------------------- | ------------------------------ | ---------------------------------------------------- |
| `DATABASE_URL`      | `sqlite:///./platform.db`      | SQLAlchemy URL. Swap to a `postgresql+...` URL for prod — URL-only change. |
| `AGENT_BASE_URL`    | `http://127.0.0.1:8000`        | Base URL of the Assessment Agent.                    |
| `PLATFORM_BASE_URL` | `http://127.0.0.1:9000`        | This platform's public URL, used to build the callback URL handed to the agent. |
| `AGENT_TIMEOUT_S`   | `10.0`                         | Timeout for the outbound "trigger job" call (the agent 202s immediately). |
| `HOST` / `PORT`     | `127.0.0.1` / `9000`           | Bind address for `platform-api`.                     |

## Endpoints

| Method | Path                       | Purpose                                                        |
| ------ | -------------------------- | -------------------------------------------------------------- |
| GET    | `/health`                  | `{"status":"ok"}`                                              |
| POST   | `/questions`               | Create a question (with nested test cases).                   |
| GET    | `/questions`               | List questions.                                               |
| GET    | `/questions/{id}`          | Get one question.                                             |
| PUT    | `/questions/{id}`          | Full replace of a question's mutable fields + test-case set.  |
| DELETE | `/questions/{id}`          | Delete a question (cascades to its test cases).               |
| POST   | `/submissions`             | Create a submission and trigger an agent job (→ `running`).    |
| GET    | `/submissions`             | List submissions (each with its result if any).               |
| GET    | `/submissions/{id}`        | Get a submission + its result.                                |
| POST   | `/submissions/{id}/retry`  | Re-trigger the agent for a submission stuck in `error` (409 otherwise). |
| POST   | `/assessments/callback`    | Agent posts the full result here; persisted verbatim.         |

Interactive docs at `/docs` when running.

## Data model

- **Question** — `id` (PK), `title`, `prompt`, `constraints`, `time_limit_s`
  (2.0), `pass_threshold` (0.9), `required_complexity?`, `example_input?`,
  `example_output?`, `created_at`, `updated_at`, and a child list of
  **QuestionTestCase** (`name`, `stdin`, `expected`, `category`
  `correctness|performance`, `weight`).
- **Submission** — `id` (uuid), `question_id` (FK), `candidate`, `language`,
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
