import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const dir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(dir, '..')

const FRONTEND_URL = 'http://127.0.0.1:5173'
const PLATFORM_URL = 'http://127.0.0.1:9000'
// NOT :8000 — that's the real assess-agent's port. With reuseExistingServer on
// (local runs), a running agent container answering /health there would be
// silently reused as if it were the mock, and specs then hit a real grader.
const AGENT_URL = 'http://127.0.0.1:8100'

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
      env: { MOCK_AGENT_PORT: '8100' },
    },
    {
      // Wipe the SQLite file (and any -wal/-shm sidecars) BEFORE starting so the
      // DB is genuinely throwaway. AUTO_CREATE_TABLES only builds a *fresh* DB —
      // it never ALTERs an existing one — so a stale e2e-platform.db left by an
      // earlier run (from before a later migration) would 500 on a missing column.
      // CI is already clean via checkout; this makes local runs just as robust.
      command: 'rm -f e2e-platform.db* && uv run platform-api',
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
        DATABASE_URL: 'sqlite:///./e2e-platform.db',
        // Test mode: force SMTP off so invites don't hit real Gmail during E2E.
        PLATFORM_TESTING: '1',
        // The E2E DB is wiped and recreated on the fly (see the command above), so
        // opt into startup table creation (production runs Alembic instead; OFF by
        // default).
        AUTO_CREATE_TABLES: 'true',
        // Vite may report its Origin as either host; allow both.
        CORS_ORIGINS: `${FRONTEND_URL},http://localhost:5173`,
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
        PORT: '9000',
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 5173 --strictPort',
      url: FRONTEND_URL,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
    },
  ],
})
