# Assessment Platform — Web

React + Vite + TypeScript frontend for the Assessment Platform. This app talks to the
platform API entirely through the typed client in `src/api.ts`; no other module makes
network calls directly.

## Running locally

```bash
npm install
npm run dev
```

The app expects the API at `VITE_API_BASE_URL` (default `http://127.0.0.1:9000` if unset).
To point at a different backend, create a `.env.local` file:

```
VITE_API_BASE_URL=http://127.0.0.1:9000
```

The dev server does not require the backend to be running to load the UI, but every
page that fetches data (dashboard, question detail, candidate flow, etc.) needs a live
API to render real content.

## Scripts

- `npm run dev` — start the Vite dev server
- `npm run build` — type-check (`tsc -b`) and produce a production build
- `npm run typecheck` — `tsc -b --noEmit`
- `npm run lint` — ESLint
- `npm run test` — run the Vitest test suite once
- `npm run preview` — preview the production build locally

## Structure

```
src/
  api.ts                 typed API client (reads VITE_API_BASE_URL, attaches JWT)
  types.ts                shared request/response types matching the API contract
  auth/AuthContext.tsx     JWT auth state (localStorage-backed), login/logout, 401 handling
  components/              NavBar, AppLayout, ProtectedRoute
  pages/                   one component per route (see below)
  pages/__tests__/         component tests (mocked api client)
```

## Routes and the endpoints they use

Interviewer-facing (JWT stored in localStorage, sent as `Authorization: Bearer`;
any 401 from an authenticated call logs the user out and redirects to `/login`):

- `/login` — `POST /auth/login`, then `GET /auth/me`
- `/register` — `POST /auth/register`, then logs in
- `/dashboard` — `GET /questions`
- `/questions/new` — `POST /questions`
- `/questions/:id` — `GET /questions/:id`, `GET /questions/:id/invites`,
  `GET /questions/:id/submissions`, `POST /questions/:id/invites`

Candidate-facing (public, no auth):

- `/t/:token` — `GET /invite/:token` (fetched immediately to detect an invalid/expired
  link before showing the name/email gate), then `POST /invite/:token/submit`

## Testing

Tests use Vitest + React Testing Library. `src/api.ts` is mocked with `vi.mock` in each
test file so no network access happens; `@monaco-editor/react` is mocked to a plain
textarea in the candidate-flow test. Covered:

- `pages/__tests__/LoginPage.test.tsx` — successful login + navigation, error display
- `pages/__tests__/AddQuestionPage.test.tsx` — submits the full payload, add/remove test
  case rows
- `pages/__tests__/CandidatePage.test.tsx` — gate → editor → submitted flow, and the
  404/410 error states

## Assumptions / contract notes

- `required_complexity` (a field in the `POST /questions` body) isn't explicitly placed
  in the page spec's four sections; it's included in the "Constraints & grading" section
  of the add-question form as a free-text input.
- The candidate page fetches `GET /invite/:token` immediately on load (before showing the
  name/email gate) rather than after, so an invalid or expired link is surfaced before the
  candidate fills anything in. The gate itself is purely local UI state — no dedicated
  endpoint is called when it's submitted.
- Monaco's built-in language ids don't include a distinct highlighter for `c` (it shares
  `cpp`); this only affects syntax highlighting, not submission behavior.
- Question `id` is treated as an interviewer-supplied slug (per the add-question form
  spec) rather than a server-generated id.
- No refresh-token flow exists in the contract, so a `401` from any authenticated request
  simply clears the stored JWT and redirects to `/login`.
