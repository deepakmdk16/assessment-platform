import { test, expect } from '@playwright/test'
import { registerInterviewer, createQuestion, createAssessmentInvite } from './helpers'

/** A 1x1 PNG. Small enough to inline, real enough for Pillow to decode. */
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==',
  'base64',
)

test('an uploaded logo reaches the candidate, and a bad file is refused', async ({
  page,
  browser,
}) => {
  const creds = await registerInterviewer(page)

  await page.goto('/settings/workspace')
  await expect(page.getByText('No logo')).toBeVisible()

  // The upload saves on pick — no second button to press.
  // The input is labelled by the button-styled <label> beside it.
  await page.getByLabel('Upload logo').setInputFiles({
    name: 'logo.png',
    mimeType: 'image/png',
    buffer: PNG,
  })
  await expect(page.getByRole('button', { name: 'Remove' })).toBeVisible()
  const preview = page.locator('img.ide-brand-logo').first()
  await expect(preview).toBeVisible()
  const src = await preview.getAttribute('src')
  expect(src).toMatch(/\/logos\/[0-9a-f]{64}$/)

  // Served with the headers a content-addressed asset earns.
  const served = await page.request.get(src as string)
  expect(served.status()).toBe(200)
  expect(served.headers()['cache-control']).toContain('immutable')

  // Anything that is not an image it will render is refused, with the reason.
  await page.getByLabel('Replace logo').setInputFiles({
    name: 'logo.svg',
    mimeType: 'image/svg+xml',
    buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"></svg>'),
  })
  await expect(page.getByRole('alert')).toContainText(/not a PNG, JPEG or WebP/i)

  // The candidate sees it — on the start gate, before they identify themselves,
  // because the gate already names the organisation either way.
  const question = await createQuestion(page)
  const inviteUrl = await createAssessmentInvite(page, creds, question.id, ['cand@example.com'])
  const context = await browser.newContext()
  const candidate = await context.newPage()
  await candidate.goto(inviteUrl)
  await expect(candidate.locator('img.gate-logo')).toHaveAttribute('src', /\/logos\/[0-9a-f]{64}$/)
  await context.close()
})
