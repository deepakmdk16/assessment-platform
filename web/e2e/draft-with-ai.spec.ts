import { expect, test } from '@playwright/test'
import { registerInterviewer } from './helpers'

// "Draft with AI" happy path against the mock agent's /questions/draft:
// expand the panel → brief → Draft → fields pre-fill → review → Create → detail.
test('drafts a question with AI and saves it', async ({ page }) => {
  await registerInterviewer(page)

  await page.goto('/questions/new')

  // Expand the collapsed panel (only the toggle carries aria-expanded).
  await page.getByRole('button', { expanded: false }).click()
  await page.getByLabel('Brief').fill('Longest strictly increasing run in a list of integers.')
  await page.getByRole('button', { name: 'Draft with AI', exact: true }).click()

  // The mock agent fills the Basics fields; the id is minted server-side on save
  // (A6), so a reused E2E server's persisted DB never collides across runs.
  await expect(page.getByLabel('Title')).toHaveValue('Longest increasing run')

  // Walk the rest of the wizard and save.
  await page.getByRole('button', { name: 'Next' }).click() // → Grading
  await page.getByRole('button', { name: 'Next' }).click() // → Test cases
  await page.getByRole('button', { name: 'Next' }).click() // → Example
  await page.getByRole('button', { name: 'Next' }).click() // → Review
  await page.getByRole('button', { name: 'Create question' }).click()

  await expect(page.getByRole('heading', { name: 'Longest increasing run' })).toBeVisible()
})
