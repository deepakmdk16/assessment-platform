import { test, expect } from '@playwright/test'
import {
  registerInterviewer,
  createQuestion,
  createInvite,
  startAsCandidate,
  submitAsCandidate,
} from './helpers'

test('creating a question needs no invite — the nudge can be skipped', async ({ page }) => {
  await registerInterviewer(page)
  await createQuestion(page)

  // Landing from the wizard, the invite dialog offers itself but never blocks.
  const dialog = page.getByRole('dialog')
  await expect(dialog).toBeVisible()
  await dialog.getByRole('button', { name: 'Skip for now' }).click()
  await expect(dialog).toBeHidden()

  // The question exists with no invite, and the email field is out of the way.
  await expect(page.getByRole('heading', { name: 'Submissions' })).toBeVisible()
  await expect(page.getByLabel('Candidate emails')).toBeHidden()

  // It's still one click away when they want it, and cancelling creates nothing.
  await page.getByRole('button', { name: 'Send invite' }).click()
  await expect(dialog.getByLabel('Candidate emails')).toBeVisible()
  await dialog.getByRole('button', { name: 'Cancel' }).click()
  await expect(dialog).toBeHidden()
  await expect(page.locator('td.invite-url')).toHaveCount(0)
})

test('an invite is not created without an email address', async ({ page }) => {
  await registerInterviewer(page)
  await createQuestion(page)

  const dialog = page.getByRole('dialog')
  await dialog.getByRole('button', { name: 'Send invite' }).click()

  await expect(dialog.getByRole('alert')).toContainText('at least one candidate email')
  await expect(dialog).toBeVisible() // still open, nothing created
  await expect(page.locator('td.invite-url')).toHaveCount(0)
})

test('a candidate who already submitted is turned away at the gate', async ({ page, browser }) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page, ['dup@example.com'])

  const first = await submitAsCandidate(browser, inviteUrl, {
    name: 'Dup Candidate',
    email: 'dup@example.com',
  })
  await expect(first.page.getByRole('heading', { name: 'Submitted' })).toBeVisible()
  await first.context.close()

  // Second visit: refused at Start, before the editor is ever shown.
  const second = await startAsCandidate(browser, inviteUrl, {
    name: 'Dup Candidate',
    email: 'dup@example.com',
  })
  await expect(
    second.page.getByRole('heading', { name: 'Assessment already recorded' }),
  ).toBeVisible()
  await expect(second.page.locator('.monaco-editor')).toHaveCount(0)
  await second.context.close()
})

test('the link only works for the invited email', async ({ page, browser }) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page, ['invited@example.com'])

  // Someone the link was forwarded to cannot get in — and never sees the problem.
  const outsider = await startAsCandidate(browser, inviteUrl, {
    name: 'Mallory',
    email: 'not-invited@example.com',
  })
  await expect(outsider.page.getByRole('alert')).toContainText('wasn’t sent to that email')
  await expect(outsider.page.locator('.monaco-editor')).toHaveCount(0)
  await outsider.context.close()

  // The invited candidate still gets through on the same link.
  const invited = await startAsCandidate(browser, inviteUrl, {
    name: 'Ingrid',
    email: 'invited@example.com',
  })
  await expect(invited.page.locator('.monaco-editor')).toBeVisible()
  await invited.context.close()
})

test('revoking an invite blocks the candidate link (410)', async ({ page, browser }) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page, ['revoked@example.com'])

  // Revoke via the invites table (the confirm() dialog auto-accepts).
  page.on('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Revoke' }).click()
  // `exact` matters: getByRole matches the accessible name by SUBSTRING, and this
  // invite's recipient cell reads "revoked@example.com". Without it the assertion
  // is satisfied by the recipient cell the moment the row renders — so it passes
  // without the status ever changing, and then breaks with a strict-mode violation
  // once the status cell says "revoked" too and both match.
  await expect(page.getByRole('cell', { name: 'revoked', exact: true })).toBeVisible()

  // The candidate now hits the terminal "no longer active" screen.
  const context = await browser.newContext()
  const candidatePage = await context.newPage()
  await candidatePage.goto(inviteUrl)
  await expect(candidatePage.getByRole('heading', { name: 'No longer active' })).toBeVisible()
  await context.close()
})
