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

## Development

```bash
uv run pytest        # tests (fully offline — the agent call is mocked)
uv run ruff check .  # lint
uv run mypy          # type-check
```

## Security TODO (required before production)

There is **no auth** in v1. Before exposing this publicly you must add, at
minimum:

- A shared secret / API key on the inbound `POST /submissions` (who may submit).
- A shared secret (or signature) on the inbound `POST /assessments/callback` so
  only the real agent can write results — the callback currently trusts any
  caller that knows a `job_id`.
- Candidate `code` is untrusted; the agent sandboxes execution, but treat stored
  code as untrusted data here too.
