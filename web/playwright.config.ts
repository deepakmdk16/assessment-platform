import { defineConfig, devices } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const dir = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(dir, '..')

const FRONTEND_URL = 'http://127.0.0.1:5173'
const PLATFORM_URL = 'http://127.0.0.1:9000'
const AGENT_URL = 'http://127.0.0.1:8000'

// One shared backend + a single SQLite file back every spec, so the suite runs
// serially. Tests stay independent by minting unique interviewer emails and
// question ids per run (see e2e/helpers.ts) rather than resetting the DB.
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: 'node e2e/mock-agent.mjs',
      url: `${AGENT_URL}/health`,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      env: { MOCK_AGENT_PORT: '8000' },
    },
    {
      command: 'uv run platform-api',
      cwd: repoRoot,
      url: `${PLATFORM_URL}/health`,
      reuseExistingServer: !process.env.CI,
      stdout: 'pipe',
      env: {
        AGENT_BASE_URL: AGENT_URL,
        PLATFORM_BASE_URL: PLATFORM_URL,
        DATABASE_URL: 'sqlite:///./e2e-platform.db',
        // Vite may report its Origin as either host; allow both.
        CORS_ORIGINS: `${FRONTEND_URL},http://localhost:5173`,
        // Disable rate limits so a run of many logins/submits can't flake.
        LOGIN_RATE_LIMIT_MAX: '0',
        SUBMIT_RATE_LIMIT_MAX: '0',
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
