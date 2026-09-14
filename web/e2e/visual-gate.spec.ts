/**
 * Gate G4: every route, at two viewports, in both themes — no horizontal
 * overflow, no serious/critical accessibility violation.
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
import { expect, test, type Page } from '@playwright/test'
import { createInvite, createQuestion, registerInterviewer, uniqueSuffix } from './helpers'

const API = process.env.E2E_API_URL ?? `http://127.0.0.1:${process.env.E2E_PLATFORM_PORT ?? '9000'}`

type Audience = 'public' | 'interviewer' | 'candidate'

interface Route {
  path: string
  name: string
  audience: Audience
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

/** Horizontal overflow: the page must never scroll sideways. */
async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => {
    const el = document.documentElement
    return el.scrollWidth - el.clientWidth
  })
}

/** The elements sticking out past the viewport, for a message worth reading. */
async function overflowingElements(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const limit = document.documentElement.clientWidth
    const out: string[] = []
    for (const el of Array.from(document.querySelectorAll<HTMLElement>('body *'))) {
      const box = el.getBoundingClientRect()
      if (box.width === 0 || box.right <= limit + 1) continue
      // Only the outermost offender: a wide child inside a wide parent is one bug.
      if (out.length && el.parentElement && out.at(-1)?.includes(el.parentElement.tagName))
        continue
      const id = el.id ? `#${el.id}` : ''
      const cls = el.className && typeof el.className === 'string' ? `.${el.className.split(/\s+/).filter(Boolean).join('.')}` : ''
      out.push(`${el.tagName.toLowerCase()}${id}${cls} right=${Math.round(box.right)} > ${limit}`)
      if (out.length >= 3) break
    }
    return out
  })
}

test.describe('visual gate', () => {
  // Fixtures are built ONCE and every variant signs in as the same interviewer.
  // Registering per variant would not just be four times the work — every
  // interviewer route is organisation-scoped, so a fresh account would see an
  // empty dashboard and the gate would render the empty state four times while
  // reporting it had covered the real pages.
  let routes: Route[] = []
  let creds: { email: string; password: string }
  // A key is shared across variants now, so staleness can only be judged once
  // every variant has run — see the final test in this describe.
  const seenAcrossRun = new Set<string>()

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage()
    creds = await registerInterviewer(page)
    const question = await createQuestion(page)
    const candidateUrl = await createInvite(page, ['visual-gate@example.com'])
    const token = new URL(candidateUrl).pathname.split('/').pop() as string

    // An assessment, via the API so its id comes back — the UI helper returns
    // only the candidate link, and `/assessments/:id` is a page worth covering.
    const login = await page.request.post(`${API}/auth/login`, { data: creds })
    expect(login.ok()).toBeTruthy()
    const headers = { Authorization: `Bearer ${(await login.json()).access_token}` }
    const created = await page.request.post(`${API}/assessments`, {
      headers,
      data: { title: `Visual gate ${uniqueSuffix()}`, question_ids: [question.id] },
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
      { path: '/dashboard?view=sets', name: 'dashboard-sets', audience: 'interviewer' },
      { path: '/questions/new', name: 'question-new', audience: 'interviewer' },
      { path: `/questions/${question.id}`, name: 'question-detail', audience: 'interviewer' },
      { path: `/questions/${question.id}/edit`, name: 'question-edit', audience: 'interviewer' },
      { path: '/assessments', name: 'assessments', audience: 'interviewer' },
      { path: '/assessments/new', name: 'assessment-new', audience: 'interviewer' },
      { path: `/assessments/${assessmentId}`, name: 'assessment-detail', audience: 'interviewer' },
      { path: '/submissions', name: 'submissions', audience: 'interviewer' },
      { path: '/settings', name: 'settings', audience: 'interviewer' },
      { path: `/t/${token}`, name: 'candidate-start', audience: 'candidate' },
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
        test.slow() // one test walks every route; the per-route work is small
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          colorScheme: theme,
        })
        const page = await context.newPage()
        await pinTheme(page, theme)

        // Interviewer routes need a session on this context.
        await signIn(page)

        const failures: string[] = []
        const seen = new Set<string>()

        for (const route of routes) {
          await page.goto(route.path)
          // The app shell is client-rendered; wait for it rather than a fixed pause.
          await page.locator('body').waitFor({ state: 'visible' })
          await page.waitForLoadState('networkidle')
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
                  `\n      KNOWN_VIOLATIONS key: '${k}'`
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
                `\n      at ${where}\n      KNOWN_VIOLATIONS key: '${k}'`
            )
          }
        }

        for (const k of seen) seenAcrossRun.add(k)

        expect(
          failures.map((f) => `  ✗ ${f}`).join('\n'),
          `visual gate at ${viewport.width}×${viewport.height}, ${theme} theme`
        ).toBe('')

        await context.close()
      })
    }
  }

  // Runs last (Playwright preserves declaration order within a file, and the
  // config pins workers: 1), so every variant has contributed to seenAcrossRun.
  test('KNOWN_VIOLATIONS holds nothing that is already fixed', () => {
    const stale = Object.entries(KNOWN_VIOLATIONS)
      .filter(([k]) => !seenAcrossRun.has(k))
      .map(([k, owner]) => `  ✗ '${k}' — ${owner}`)
    expect(
      stale.join('\n'),
      'these violations no longer happen; delete their lines from KNOWN_VIOLATIONS'
    ).toBe('')
  })
})
