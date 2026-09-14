import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const dir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(dir, '..')

// Ports. The defaults are the real ones and nothing below changes unless a port
// is explicitly overridden — but a developer running the dev stack (`scripts/dev.sh`
// on :9000 + vite on :5173) otherwise cannot run E2E at all, because the platform
// server here deliberately refuses to reuse an existing listener. Overriding lets
// the suite run beside a live dev stack on a spare set:
//   E2E_PLATFORM_PORT=9100 E2E_FRONTEND_PORT=5273 E2E_AGENT_PORT=8200 RUN_E2E=1 …
// `||`, not `??`: an unset shell variable expands to the EMPTY STRING, which `??`
// keeps — `http://127.0.0.1:` — while every truthiness test below takes the
// default branch, so the suite would start servers on the default ports and then
// poll an invalid URL until the timeout.
const OVERRIDDEN = Boolean(process.env.E2E_PLATFORM_PORT || process.env.E2E_FRONTEND_PORT)
const PLATFORM_PORT = process.env.E2E_PLATFORM_PORT || '9000'
const FRONTEND_PORT = process.env.E2E_FRONTEND_PORT || '5173'
// NOT :8000 — that's the real assess-agent's port. With reuseExistingServer on
// (local runs), a running agent container answering /health there would be
// silently reused as if it were the mock, and specs then hit a real grader.
const AGENT_PORT = process.env.E2E_AGENT_PORT || '8100'

const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`
const PLATFORM_URL = `http://127.0.0.1:${PLATFORM_PORT}`
const AGENT_URL = `http://127.0.0.1:${AGENT_PORT}`

// Each port set gets its own throwaway DB, so two suites can never share one file.
const E2E_DB = PLATFORM_PORT === '9000' ? 'e2e-platform.db' : `e2e-platform-${PLATFORM_PORT}.db`

// One shared backend + a single SQLite file back every spec, so the suite runs
// serially. Tests stay independent by minting unique interviewer emails and
// question ids per run (see e2e/helpers.ts) rather than resetting the DB.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  // One retry in CI so a genuine flake doesn't fail the run — and so the
  // trace/HTML report below actually capture something on the retry.
  retries: process.env.CI ? 1 : 0,
  // On CI also emit an HTML report (uploaded as a failure artifact); locally
  // the plain list output is enough.
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'node e2e/mock-agent.mjs',
      url: `${AGENT_URL}/health`,
      // Never reuse: whatever answers /health here gets treated as the mock,
      // so silently adopting an existing listener means testing against the
      // wrong server (this is how a real agent hijacked the suite). Starting
      // fresh is instant; a busy port now fails loudly instead.
      reuseExistingServer: false,
      stdout: 'pipe',
      env: { MOCK_AGENT_PORT: AGENT_PORT },
    },
    {
      // Wipe the SQLite file (and any -wal/-shm sidecars) BEFORE starting so the
      // DB is genuinely throwaway. AUTO_CREATE_TABLES only builds a *fresh* DB —
      // it never ALTERs an existing one — so a stale e2e-platform.db left by an
      // earlier run (from before a later migration) would 500 on a missing column.
      // CI is already clean via checkout; this makes local runs just as robust.
      command: `rm -f ${E2E_DB}* && uv run platform-api`,
      cwd: repoRoot,
      url: `${PLATFORM_URL}/health`,
      // Never reuse: a leftover dev server on :9000 runs old code against the
      // wrong DB and points at the real agent — reusing it made 5/9 specs fail
      // in ways that looked like product bugs. Only vite below keeps reuse
      // (it's the slow one, and a stale frontend is at least the right app).
      reuseExistingServer: false,
      stdout: 'pipe',
      env: {
        AGENT_BASE_URL: AGENT_URL,
        PLATFORM_BASE_URL: PLATFORM_URL,
        DATABASE_URL: `sqlite:///./${E2E_DB}`,
        // Test mode: force SMTP off so invites don't hit real Gmail during E2E.
        PLATFORM_TESTING: '1',
        // The E2E DB is wiped and recreated on the fly (see the command above), so
        // opt into startup table creation (production runs Alembic instead; OFF by
        // default).
        AUTO_CREATE_TABLES: 'true',
        // Exactly one spelling. vite.config.ts pins the dev server to 127.0.0.1,
        // so the browser Origin can only be FRONTEND_URL. Allowing localhost too
        // would re-hide the bug this suite now guards: if the bind ever drifts
        // back to Vite's "localhost" default, the run must fail here rather than
        // pass while the SameSite=lax refresh cookie is silently dropped.
        CORS_ORIGINS: FRONTEND_URL,
        // Candidate invite links are built server-side as
        // `{FRONTEND_BASE_URL}/t/{token}` and the specs navigate straight to
        // them. It defaults to :5173, so on an overridden port set every
        // candidate spec would walk out of this stack and into whatever is on
        // :5173 — a dev server with a different database, where the token does
        // not exist. Pin it to the frontend this suite actually started.
        FRONTEND_BASE_URL: FRONTEND_URL,
        // Disable rate limits so a run of many logins/submits can't flake. Every
        // bucket must be listed by name: a limiter added later defaults to ON, and
        // an E2E run does in one window what a human would spread over a day.
        LOGIN_RATE_LIMIT_MAX: '0',
        SUBMIT_RATE_LIMIT_MAX: '0',
        REGISTER_RATE_LIMIT_MAX: '0',
        DRAFT_RATE_LIMIT_MAX: '0',
        DRAFT_SAVE_RATE_LIMIT_MAX: '0',
        RUN_RATE_LIMIT_MAX: '0',
        HOST: '127.0.0.1',
        PORT: PLATFORM_PORT,
      },
    },
    {
      // No --port on the DEFAULT path: vite.config.ts owns the host and port, and
      // overriding them unconditionally would hide a regression in that file from
      // this suite. Only an explicit E2E_FRONTEND_PORT passes one through, which
      // is opt-in and never what CI runs.
      command: OVERRIDDEN
        ? `npm run dev -- --port ${FRONTEND_PORT} --strictPort`
        : 'npm run dev',
      url: FRONTEND_URL,
      // Reuse only on the default port. On an overridden set the whole point is a
      // private stack, and adopting a stray listener would point the app back at
      // :9000 — the dev server, with the dev database and the wrong CORS origin.
      reuseExistingServer: !process.env.CI && !OVERRIDDEN,
      stdout: 'pipe',
      // Only on an overridden set. src/api.ts defaults to :9000, and pinning this
      // unconditionally would hide a regression in that default from this suite —
      // the same reasoning that refuses an unconditional --port above. It would
      // also be asymmetric: the default path reuses an existing vite, which never
      // sees this env at all.
      ...(OVERRIDDEN ? { env: { VITE_API_BASE_URL: PLATFORM_URL } } : {}),
    },
  ],
})
