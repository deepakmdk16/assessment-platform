import { expect, type Browser, type BrowserContext, type Page } from '@playwright/test'

/** Suffix that keeps each test's interviewer/question distinct in the shared DB. */
export function uniqueSuffix(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 1e6)}`
}

/** Register a fresh interviewer through the UI; lands on the dashboard, logged in. */
export async function registerInterviewer(page: Page): Promise<{ email: string; password: string }> {
  const suffix = uniqueSuffix()
  const email = `interviewer-${suffix}@example.com`
  const password = 'sekret-password-123'

  await page.goto('/register')
  await page.getByLabel('Name').fill(`Interviewer ${suffix}`)
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Create account' }).click()

  await expect(page.getByRole('heading', { name: 'Questions' })).toBeVisible()
  return { email, password }
}

/** Create a minimal valid question; lands on its detail page. Returns id + title. */
export async function createQuestion(page: Page): Promise<{ id: string; title: string }> {
  const suffix = uniqueSuffix()
  const id = `q-${suffix}`
  const title = `Two Sum ${suffix}`

  // The add-question page is a wizard: Basics → Grading → Test cases → Example → Review.
  await page.goto('/questions/new')
  await page.getByLabel('Id (slug)').fill(id)
  await page.getByLabel('Title').fill(title)
  await page.getByLabel('Prompt').fill('Return indices of the two numbers that add up to target.')
  await page.getByRole('button', { name: 'Next' }).click() // → Grading
  await page.getByRole('button', { name: 'Next' }).click() // → Test cases
  // The A1 case-floor is enforced at creation: a question needs ≥4 correctness
  // cases AND ≥1 performance case or POST /questions 422s. Start from the one
  // empty row, add four more, and mark the last one performance.
  await page.getByLabel('Test case 1 name').fill('basic')
  for (let i = 2; i <= 5; i++) {
    await page.getByRole('button', { name: 'Add test case' }).click()
    await page.getByLabel(`Test case ${i} name`).fill(`case ${i}`)
  }
  await page.getByLabel('Test case 5 category').selectOption('performance')
  await page.getByRole('button', { name: 'Next' }).click() // → Example
  await page.getByRole('button', { name: 'Next' }).click() // → Review
  await page.getByRole('button', { name: 'Create question' }).click()

  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  return { id, title }
}

/**
 * Send an invite from the (already open) question detail page; returns its
 * candidate URL. `recipients` is required — the link is bound to those addresses,
 * and only they can start the assessment.
 *
 * The email field lives in a dialog. Arriving straight from the wizard it's
 * already open (the post-create nudge); otherwise click through to it.
 */
export async function createInvite(page: Page, recipients: string[]): Promise<string> {
  const dialog = page.getByRole('dialog')
  if (!(await dialog.isVisible())) {
    await page.getByRole('button', { name: 'Send invite' }).click()
  }
  await dialog.getByLabel('Candidate emails').fill(recipients.join(', '))
  await dialog.getByRole('button', { name: 'Send invite' }).click()
  await expect(dialog).toBeHidden()
  const urlCell = page.locator('td.invite-url').first()
  await expect(urlCell).toBeVisible()
  const url = (await urlCell.textContent())?.trim()
  if (!url) throw new Error('invite URL cell was empty')
  return url
}

/**
 * Open the invite link in a fresh (unauthenticated) context and submit the gate
 * form. Stops there — the caller asserts what the gate did (let them through, or
 * refused them). The caller owns the returned context and must close it.
 */
export async function startAsCandidate(
  browser: Browser,
  inviteUrl: string,
  candidate: { name: string; email: string },
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto(inviteUrl)

  await page.getByLabel('Name').fill(candidate.name)
  await page.getByLabel('Email').fill(candidate.email)
  await page.getByRole('button', { name: 'Start' }).click()
  return { context, page }
}

/**
 * Drive a candidate through gate → editor → submit. Assumes the gate lets this
 * candidate through (i.e. they're an invited recipient who hasn't submitted).
 * Code must be non-empty — the submit schema enforces `min_length=1`.
 */
export async function submitAsCandidate(
  browser: Browser,
  inviteUrl: string,
  candidate: { name: string; email: string },
): Promise<{ context: BrowserContext; page: Page }> {
  const { context, page } = await startAsCandidate(browser, inviteUrl, candidate)

  // Monaco's editable surface is an invisible EditContext div; click the visible
  // editor body to focus it, then type so `code` is non-empty (schema min_length=1).
  await page.locator('.monaco-editor .view-lines').click()
  await page.keyboard.type('print("solution")')

  await page.getByRole('button', { name: 'Submit' }).click()
  return { context, page }
}
