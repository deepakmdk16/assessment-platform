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

  await expect(page.getByRole('heading', { name: 'My questions' })).toBeVisible()
  return { email, password }
}

/** Create a minimal valid question; lands on its detail page. Returns id + title. */
export async function createQuestion(page: Page): Promise<{ id: string; title: string }> {
  const suffix = uniqueSuffix()
  const id = `q-${suffix}`
  const title = `Two Sum ${suffix}`

  await page.goto('/questions/new')
  await page.getByLabel('Id (slug)').fill(id)
  await page.getByLabel('Title').fill(title)
  await page.getByLabel('Prompt').fill('Return indices of the two numbers that add up to target.')
  await page.getByLabel('Test case 1 name').fill('basic')
  await page.getByRole('button', { name: 'Create question' }).click()

  await expect(page.getByRole('heading', { name: title })).toBeVisible()
  return { id, title }
}

/** Generate an invite from the (already open) question detail page; returns its candidate URL. */
export async function createInvite(page: Page): Promise<string> {
  await page.getByRole('button', { name: 'Generate coding test' }).click()
  const urlCell = page.locator('td.invite-url').first()
  await expect(urlCell).toBeVisible()
  const url = (await urlCell.textContent())?.trim()
  if (!url) throw new Error('invite URL cell was empty')
  return url
}

/**
 * Drive a candidate through gate → editor → submit in a fresh (unauthenticated)
 * context. The caller owns the returned context and must close it. Code must be
 * non-empty — the submit schema enforces `min_length=1`.
 */
export async function submitAsCandidate(
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

  // Monaco's editable surface is an invisible EditContext div; click the visible
  // editor body to focus it, then type so `code` is non-empty (schema min_length=1).
  await page.locator('.monaco-editor .view-lines').click()
  await page.keyboard.type('print("solution")')

  await page.getByRole('button', { name: 'Submit' }).click()
  return { context, page }
}
