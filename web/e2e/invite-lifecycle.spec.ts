import { test, expect } from '@playwright/test'
import {
  registerInterviewer,
  createQuestion,
  createInvite,
  startAsCandidate,
  submitAsCandidate,
} from './helpers'

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
  await expect(page.getByRole('cell', { name: 'revoked' })).toBeVisible()

  // The candidate now hits the terminal "no longer active" screen.
  const context = await browser.newContext()
  const candidatePage = await context.newPage()
  await candidatePage.goto(inviteUrl)
  await expect(candidatePage.getByRole('heading', { name: 'No longer active' })).toBeVisible()
  await context.close()
})
