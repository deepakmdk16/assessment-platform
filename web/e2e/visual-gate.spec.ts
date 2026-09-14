/**
 * Gate G4: the app's routes, at two viewports, in both themes — no horizontal
 * overflow, no serious/critical accessibility violation.
 *
 * "The routes" means the ones ROUTES below lists. Two are missing and both need
 * a fixture this spec does not build: `/submissions/:id` needs a graded
 * submission, `/variant-sets/:id` a drafted set. Both are table-heavy interviewer
 * surfaces, which is the shape most likely to overflow — filed in STATUS.
 *
 * The 2026-09-14 audit found seven layout and theme defects (R2-143, R2-144,
 * R2-145, R2-146, R2-154, R2-159, R2-164) that no test could ever have caught,
 * because nothing rendered a route at a phone width or in dark mode. The unit
 * suite renders components; the other specs drive flows at one desktop size in
 * whatever theme the OS happens to report. Nobody looked at the pixels.
 *
 * This is deliberately shallow and wide: it visits pages rather than exercising
 * them, so adding a route costs one line. Depth stays in the flow specs.
 *
 * Known failures are listed in KNOWN_VIOLATIONS with the finding that owns them
 * and the session that closes it, strict in both directions: a new violation
 * fails immediately, and a listed one that stops happening fails too, so the list
 * shrinks and cannot rot.
 *
 * Screenshots land in `web/test-results/visual-gate/` for a human to look at.
 * They are NOT compared against baselines — a pixel baseline over 4 variants of
 * 18 routes is a full-time job to maintain and fails on font rendering. The
 * assertions here are the gate; the screenshots are evidence.
 */
import AxeBuilder from '@axe-core/playwright'
import { expect, test, type BrowserContext, type Page } from '@playwright/test'
import fs from 'node:fs/promises'
import path from 'node:path'
import { createInvite, createQuestion, registerInterviewer, uniqueSuffix } from './helpers'

const API = process.env.E2E_API_URL ?? `http://127.0.0.1:${process.env.E2E_PLATFORM_PORT ?? '9000'}`

type Audience = 'public' | 'interviewer' | 'candidate'

interface Route {
  path: string
  name: string
  audience: Audience
  /**
   * Where this route is EXPECTED to end up, when that is not `path` itself.
   * Declared, never inferred: the landing assertion exists to catch the silent
   * redirect to /login when a session fails, so "it redirected somewhere" can
   * never be an acceptable answer. A changed redirect target fails here too,
   * which is the point.
   */
  lands?: string
}

const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 800 },
  { name: 'phone', width: 390, height: 844 },
] as const

const THEMES = ['light', 'dark'] as const

type Theme = (typeof THEMES)[number]
type ViewportName = (typeof VIEWPORTS)[number]['name']

/**
 * The violations that exist today, each with the finding and the session that
 * closes it. Delete an entry in the same commit as its fix — the gate fails
 * while a listed violation no longer happens.
 *
 * Keys are deliberately COARSER than the matrix. An accessibility violation is a
 * property of a component's tokens or markup, not of a viewport or a theme, so
 * it is keyed `route | rule`: listing it four times would only add three ways for
 * the list to go stale when one contrast ratio lands the right side of 4.5:1 in
 * one theme. Overflow genuinely is viewport-specific — it is the whole point of
 * testing at 390 px — so it keeps the viewport: `route | viewport | overflow`.
 * Either way a NEW route, or a new KIND of violation on a known one, still fails.
 */
const KNOWN_VIOLATIONS: Record<string, string> = {
  // Horizontal overflow — S13 (mobile and overflow)
  'question-new | phone | horizontal-overflow': 'R2-159 — wizard stepper does not wrap, S13',
  'question-edit | phone | horizontal-overflow': 'R2-159 — same wizard, edit mode, S13',
  'question-detail | phone | horizontal-overflow': 'R2-154 — delivery aside does not wrap, S13',
  'candidate-start | phone | horizontal-overflow': 'R2-156 — start-screen card overflows, S13',

  // Contrast — R2-145: --color-faint is 2.80–3.85:1 in both themes, below AA.
  // One token, every surface that uses it for a subtitle or a label. S17.
  'dashboard | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'dashboard-sets | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'question-new | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'question-detail | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'question-edit | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'assessments | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'assessment-new | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'assessment-detail | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'submissions | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'settings | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'candidate-start | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'team | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'variant-set-new | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'privacy | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'terms | color-contrast': 'R2-145 — --color-faint below AA, S17',
  'dpa | color-contrast': 'R2-145 — --color-faint below AA, S17',

  // Links that are only distinguishable by colour. Not in the audit — this gate
  // found it — so it has no R2 number; it belongs with S17's accessibility work.
  'login | link-in-text-block': 'found by this gate — inline links need underlining, S17',
  'register | link-in-text-block': 'found by this gate — inline links need underlining, S17',
  'assessment-new | link-in-text-block': 'found by this gate — inline links need underlining, S17',
  'question-detail | link-in-text-block': 'found by this gate — inline links need underlining, S17',
  'candidate-start | link-in-text-block': 'found by this gate — consent links, S17',
  'privacy | link-in-text-block': 'found by this gate — inline links need underlining, S17',
  'terms | link-in-text-block': 'found by this gate — inline links need underlining, S17',
  'dpa | link-in-text-block': 'found by this gate — inline links need underlining, S17',

  // A scrollable region a keyboard user cannot reach or scroll. Also found by
  // this gate, and only once /team was added to the list.
  'team | scrollable-region-focusable': 'found by this gate — members table, S17',
}

const a11yKey = (route: string, rule: string) => `${route} | ${rule}`
const overflowKey = (route: string, viewport: ViewportName) =>
  `${route} | ${viewport} | horizontal-overflow`

// The theme is stamped on <html> from localStorage before React mounts
// (`src/theme/theme.ts`), so it has to be seeded before the first navigation —
// setting it afterwards would measure a re-render rather than a cold paint.
async function pinTheme(page: Page, theme: Theme): Promise<void> {
  await page.addInitScript((pref) => {
    window.localStorage.setItem('assessment-theme', pref as string)
  }, theme)
}

// Sub-pixel slack. Layout maths lands on fractions (a flex row measuring 390.4px
// at a 390px viewport), and a 1px "overflow" is a rounding artifact that varies
// with font and zoom. The detector and the culprit finder MUST share this number:
// when they disagreed, a 1px reading failed the gate while naming no element.
const TOLERANCE = 1

/** Horizontal overflow: the page must never scroll sideways. */
async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate((tolerance) => {
    const el = document.documentElement
    const overflow = el.scrollWidth - el.clientWidth
    return overflow > tolerance ? overflow : 0
  }, TOLERANCE)
}

/** The elements sticking out past the viewport, for a message worth reading. */
async function overflowingElements(page: Page): Promise<string[]> {
  return page.evaluate((TOLERANCE) => {
    const limit = document.documentElement.clientWidth
    const out: string[] = []
    // Only the OUTERMOST offenders: a wide child inside a wide parent is one bug,
    // and three views of it would fill the budget while the independent ones go
    // unreported. Tracked by node identity — comparing rendered strings does not
    // work, and silently matched nothing when this was first written.
    const reported: HTMLElement[] = []
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      const box = el.getBoundingClientRect()
      if (box.width === 0 || box.right <= limit + TOLERANCE) continue
      if (reported.some((parent) => parent.contains(el))) continue
      reported.push(el)
      const id = el.id ? `#${el.id}` : ''
      const cls =
        el.className && typeof el.className === 'string'
          ? `.${el.className.split(/\s+/).filter(Boolean).join('.')}`
          : ''
      out.push(`${el.tagName.toLowerCase()}${id}${cls} right=${Math.round(box.right)} > ${limit}`)
      if (out.length >= 3) break
    }
    return out
  }, TOLERANCE)
}

test.describe('visual gate', () => {
  // Fixtures are built ONCE and every variant signs in as the same interviewer.
  // Registering per variant would not just be four times the work — every
  // interviewer route is organisation-scoped, so a fresh account would see an
  // empty dashboard and the gate would render the empty state four times while
  // reporting it had covered the real pages.
  let routes: Route[] = []
  let creds: { email: string; password: string }
  // A key is shared across variants, so staleness can only be judged once every
  // variant has run — see the final test in this describe. It goes to DISK, not
  // to a module-level Set: Playwright discards the worker process after a test
  // fails and re-evaluates the module in a fresh one, so in-memory state is
  // empty exactly when a variant has failed. The stale check would then report
  // all 26 known violations as fixed and tell someone to delete them.
  const SEEN_DIR = path.join(process.cwd(), 'test-results', 'visual-gate-seen')

  test.beforeAll(async ({ browser }) => {
    // Clear last run's keys: a variant that no longer runs must not keep voting.
    await fs.rm(SEEN_DIR, { recursive: true, force: true })
    const page = await browser.newPage()
    creds = await registerInterviewer(page)
    const question = await createQuestion(page)
    const candidateUrl = await createInvite(page, ['visual-gate@example.com'])
    const token = new URL(candidateUrl).pathname.split('/').pop() as string

    // An assessment, via the API so its id comes back — the UI helper returns
    // only the candidate link, and `/assessments/:id` is a page worth covering.
    const login = await page.request.post(`${API}/auth/login`, { data: creds })
    expect(login.ok()).toBeTruthy()
    const headers = {
      Authorization: `Bearer ${(await login.json()).access_token}`,
    }
    const created = await page.request.post(`${API}/assessments`, {
      headers,
      data: {
        title: `Visual gate ${uniqueSuffix()}`,
        question_ids: [question.id],
      },
    })
    expect(created.ok()).toBeTruthy()
    const assessmentId = (await created.json()).id

    routes = [
      { path: '/login', name: 'login', audience: 'public' },
      { path: '/register', name: 'register', audience: 'public' },
      { path: '/forgot-password', name: 'forgot-password', audience: 'public' },
      { path: '/privacy', name: 'privacy', audience: 'public' },
      { path: '/terms', name: 'terms', audience: 'public' },
      { path: '/dpa', name: 'dpa', audience: 'public' },
      { path: '/dashboard', name: 'dashboard', audience: 'interviewer' },
      {
        path: '/dashboard?view=sets',
        name: 'dashboard-sets',
        audience: 'interviewer',
      },
      { path: '/questions/new', name: 'question-new', audience: 'interviewer' },
      {
        path: `/questions/${question.id}`,
        name: 'question-detail',
        audience: 'interviewer',
      },
      {
        path: `/questions/${question.id}/edit`,
        name: 'question-edit',
        audience: 'interviewer',
      },
      { path: '/assessments', name: 'assessments', audience: 'interviewer' },
      {
        path: '/assessments/new',
        name: 'assessment-new',
        audience: 'interviewer',
      },
      {
        path: `/assessments/${assessmentId}`,
        name: 'assessment-detail',
        audience: 'interviewer',
      },
      { path: '/submissions', name: 'submissions', audience: 'interviewer' },
      // /settings redirects into its first section (the P3a sub-nav).
      { path: '/settings', name: 'settings', audience: 'interviewer', lands: '/settings/workspace' },
      { path: '/team', name: 'team', audience: 'interviewer' },
      { path: '/variant-sets/new', name: 'variant-set-new', audience: 'interviewer' },
      { path: `/t/${token}`, name: 'candidate-start', audience: 'candidate' },
      // Dead-end shells. They render without a valid token — which is the state
      // worth rendering, since it is the one a real user lands on by accident.
      { path: '/join', name: 'join-no-token', audience: 'public' },
      { path: '/reset-password', name: 'reset-password', audience: 'public' },
      { path: '/verify-email', name: 'verify-email', audience: 'public' },
      { path: '/no-such-page', name: 'not-found', audience: 'public' },
    ]
    await page.close()
  })

  /** Sign in as the fixture interviewer through the real form. */
  async function signIn(page: Page): Promise<void> {
    await page.goto('/login')
    await page.getByLabel('Email').fill(creds.email)
    await page.getByLabel('Password', { exact: true }).fill(creds.password)
    await page.getByRole('button', { name: /sign in|log in/i }).click()
    await expect(page.getByRole('heading', { name: 'Questions' })).toBeVisible()
  }

  for (const viewport of VIEWPORTS) {
    for (const theme of THEMES) {
      test(`${viewport.name} · ${theme}`, async ({ browser }) => {
        // One test walks every route: goto + networkidle + a settle + a fullPage
        // screenshot + an axe pass, each ~1-3s, and the first variant also pays
        // Vite's on-demand transform per route. test.slow()'s 90s does not cover
        // that on a cold CI runner, and the failure is a bare timeout with no
        // diagnostic — so the budget is explicit and generous.
        test.setTimeout(6 * 60 * 1000)
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          colorScheme: theme,
        })
        try {
          await runVariant(context, viewport, theme)
        } finally {
          await context.close()
        }
      })
    }
  }

  /** The body of one variant, so the context above can be closed in a `finally`. */
  async function runVariant(
    context: BrowserContext,
    viewport: (typeof VIEWPORTS)[number],
    theme: Theme,
  ): Promise<void> {
    const page = await context.newPage()
    await pinTheme(page, theme)

    // Interviewer routes need a session on this context.
    await signIn(page)

    const failures: string[] = []
    const seen = new Set<string>()

    for (const route of routes) {
      await page.goto(route.path)
      await page.waitForLoadState('networkidle')

      // Assert we are ON the route. The access token lives in memory only, so
      // every goto is a cold load that depends on the refresh-cookie round
      // trip; if that breaks, all ten interviewer routes silently redirect to
      // /login and the gate measures the sign-in page ten times per variant,
      // passing. Measuring the wrong page is worse than not measuring.
      const landed = new URL(page.url()).pathname
      const wanted = new URL(route.lands ?? route.path, 'http://x').pathname
      expect(landed, `${route.path} did not render — landed on ${landed}`).toBe(wanted)
      // Past every CSS transition (.btn is 140ms) — a screenshot taken mid
      // transition produced false "invisible button" findings in the audit.
      await page.waitForTimeout(250)

      await page.screenshot({
        path: `test-results/visual-gate/${viewport.name}-${theme}-${route.name}.png`,
        fullPage: true,
      })

      const overflow = await horizontalOverflow(page)
      if (overflow > 0) {
        const k = overflowKey(route.name, viewport.name)
        seen.add(k)
        if (!(k in KNOWN_VIOLATIONS)) {
          const culprits = await overflowingElements(page)
          failures.push(
            `${route.path} scrolls ${overflow}px sideways at ${viewport.width}px` +
              (culprits.length ? `\n      ${culprits.join('\n      ')}` : '') +
              `\n      KNOWN_VIOLATIONS key: '${k}'`,
          )
        }
      }

      const axe = await new AxeBuilder({ page })
        .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
        .analyze()
      for (const violation of axe.violations) {
        if (violation.impact !== 'serious' && violation.impact !== 'critical') continue
        const k = a11yKey(route.name, violation.id)
        seen.add(k)
        if (k in KNOWN_VIOLATIONS) continue
        const where = violation.nodes
          .slice(0, 2)
          .map((n) => n.target.join(' '))
          .join(', ')
        failures.push(
          `${route.path} — ${violation.impact} a11y: ${violation.id} (${violation.help})` +
            `\n      at ${where}\n      KNOWN_VIOLATIONS key: '${k}'`,
        )
      }
    }

    await fs.mkdir(SEEN_DIR, { recursive: true })
    await fs.writeFile(
      path.join(SEEN_DIR, `${viewport.name}-${theme}.json`),
      JSON.stringify([...seen]),
    )

    expect(
      failures.map((f) => `  ✗ ${f}`).join('\n'),
      `visual gate at ${viewport.width}×${viewport.height}, ${theme} theme`,
    ).toBe('')
  }

  // Runs last (Playwright preserves declaration order within a file, and the
  // config pins workers: 1), reading what every variant wrote to disk.
  test('KNOWN_VIOLATIONS holds nothing that is already fixed', async () => {
    const files = await fs.readdir(SEEN_DIR).catch(() => [] as string[])
    const expected = VIEWPORTS.length * THEMES.length
    // Only judge staleness on a COMPLETE run. If a variant failed or was skipped
    // its keys are missing, and every entry it owns would look fixed.
    test.skip(
      files.length < expected,
      `only ${files.length}/${expected} variants reported; staleness is not decidable`,
    )

    const seen = new Set<string>()
    for (const file of files)
      for (const k of JSON.parse(await fs.readFile(path.join(SEEN_DIR, file), 'utf8')))
        seen.add(k as string)

    const stale = Object.entries(KNOWN_VIOLATIONS)
      .filter(([k]) => !seen.has(k))
      .map(([k, owner]) => `  ✗ '${k}' — ${owner}`)
    expect(
      stale.join('\n'),
      'these violations no longer happen; delete their lines from KNOWN_VIOLATIONS',
    ).toBe('')
  })
})
