# CONVENTIONS.md — Assessment Platform

Concrete, checkable rules. The global `~/.claude/CLAUDE.md` covers general
behavior; this covers what a reviewer can verify in a diff.

## Python / backend

- **Clean gates.** `uv run ruff check .`, `uv run mypy`, and `uv run pytest` must
  all pass before commit. No new lint/type suppressions without a reason.
- **Typed.** Public functions and route handlers are type-annotated. Use
  `response_model=` on every route so the response shape is enforced.
- **Deps via `uv add`** — don't hand-edit `pyproject.toml` deps. Keep them lean.

## Data & schemas

- **Two layers, kept separate:** persistence in `models.py` (SQLModel tables),
  API shapes in `schemas.py`. Don't return ORM rows whose fields would leak.
- **The candidate view is answer-key-free by construction.** Anything served at
  `GET /invite/{token}` goes through `InvitePublicOut`, which has no
  `test_cases`/`expected`. Never widen it. The absence test must stay green.
- **Timestamps:** every table carries `created_at`; mutable rows also carry
  `updated_at` (bump it on write). Use timezone-aware UTC (`_utcnow`).

## Auth & security

- Interviewer routes: `Depends(get_current_interviewer)` **and** an ownership
  check (403 if the resource isn't the caller's). 401 for missing/invalid token.
- Candidate routes: public, but resolve the invite token (404 unknown / 410
  expired) before doing anything.
- Secrets (`JWT_SECRET`, `ASSESS_API_TOKEN`, `CALLBACK_TOKEN`, SMTP) come from the
  environment only and are never logged or committed.
- The platform **never** derives a verdict/score — it persists the agent's
  callback payload as-is.

## Tests

- Every new endpoint gets a test. Tests run **offline**: mock the outbound agent
  call (`agent_client`), use a temp/in-memory SQLite DB, no network, no real LLM.
- Cover the unhappy paths too: 401/403/404/410/409 where they apply.

## Frontend (`web/`)

- One typed API client (`src/api.ts`) is the only place that talks to the
  backend; it reads `VITE_API_BASE_URL` and attaches the JWT. Components don't
  fetch directly.
- `npm run build`, `typecheck`, `lint`, and `test` must all pass.
- Keep dependencies lean; prefer hand-rolled styling over a heavy UI kit.
- The candidate UI must never expect fields the public API doesn't send
  (no test cases / expected outputs).
