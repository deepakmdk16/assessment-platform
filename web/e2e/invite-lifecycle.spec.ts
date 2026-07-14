import { test, expect } from '@playwright/test'
import { registerInterviewer, createQuestion, createInvite, submitAsCandidate } from './helpers'

test('a second submission with the same email is rejected (409)', async ({ page, browser }) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page)

  const first = await submitAsCandidate(browser, inviteUrl, { name: 'Dup Candidate', email: 'dup@example.com' })
  await expect(first.page.getByRole('heading', { name: 'Submitted' })).toBeVisible()
  await first.context.close()

  const second = await submitAsCandidate(browser, inviteUrl, { name: 'Dup Candidate', email: 'dup@example.com' })
  await expect(second.page.getByRole('heading', { name: 'Already submitted' })).toBeVisible()
  await second.context.close()
})

test('revoking an invite blocks the candidate link (410)', async ({ page, browser }) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page)

  // Revoke via the invites table (the confirm() dialog auto-accepts).
  page.on('dialog', (dialog) => dialog.accept())
  await page.getByRole('button', { name: 'Revoke' }).click()
  await expect(page.getByRole('cell', { name: 'revoked' })).toBeVisible()

  // The candidate now hits the terminal "no longer active" screen.
  const context = await browser.newContext()
  const candidatePage = await context.newPage()
  await candidatePage.goto(inviteUrl)
  await expect(candidatePage.getByText('no longer active')).toBeVisible()
  await context.close()
})
