import { test, expect } from '@playwright/test'
import { registerInterviewer, createQuestion, createInvite } from './helpers'

/** R2-003, in a real browser.
 *
 *  The unit test for this drives the real page and the real hook, but jsdom has
 *  no Fullscreen API at all — it stubs the very call that was missing. The bug
 *  was a browser-shaped one (fullscreen is granted only from a user gesture, and
 *  the handler held a stale hook), so the proof belongs somewhere a real browser
 *  runs the real click.
 *
 *  Chromium will not actually grant fullscreen to a headless page reliably, so
 *  what is asserted is the call itself, counted by an instrumented
 *  `requestFullscreen` installed before any app code runs. Call count 0 is
 *  exactly what the audit measured live. */
test('the start click asks the browser for fullscreen', async ({ page, browser }) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page, ['fs@example.com'])

  const context = await browser.newContext()
  const candidate = await context.newPage()

  await candidate.addInitScript(() => {
    const w = window as unknown as { __fsCalls: number }
    w.__fsCalls = 0
    const real = Element.prototype.requestFullscreen
    Element.prototype.requestFullscreen = function patched(this: Element, ...args) {
      w.__fsCalls += 1
      // Still call through, so a browser that does grant it behaves normally and
      // the app's own fullscreenchange handling stays on the real path.
      return real.apply(this, args as never)
    }
  })

  await candidate.goto(inviteUrl)
  await candidate.getByLabel('Name').fill('Fullscreen Candidate')
  await candidate.getByLabel('Email').fill('fs@example.com')
  await candidate.getByLabel(/i agree to my assessment/i).check()
  await candidate.getByRole('button', { name: 'Start' }).click()

  // The editor is up...
  await expect(candidate.getByRole('button', { name: 'Submit' })).toBeVisible()
  // ...and the sitting asked to be in fullscreen on the way there, which is what
  // the consent screen told this candidate would happen.
  await expect.poll(() => candidate.evaluate(() => (window as never as { __fsCalls: number }).__fsCalls)).toBeGreaterThan(0)

  await context.close()
})
