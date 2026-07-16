import { test, expect } from '@playwright/test'
import { registerInterviewer, createQuestion, createInvite, submitAsCandidate } from './helpers'

test('interviewer → invite → candidate submit → result grades PASS', async ({ page, browser }) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page, ['casey@example.com'])

  // Candidate uses a fresh, unauthenticated context (public invite link).
  const { context, page: candidatePage } = await submitAsCandidate(browser, inviteUrl, {
    name: 'Casey Candidate',
    email: 'casey@example.com',
  })
  await expect(candidatePage.getByRole('heading', { name: 'Submitted' })).toBeVisible()
  await context.close()

  // Back on the interviewer's question page: poll (reload) until the graded row lands.
  await expect(async () => {
    await page.reload()
    await expect(page.getByRole('cell', { name: 'PASS', exact: true })).toBeVisible({ timeout: 1500 })
  }).toPass({ timeout: 15000 })
  await expect(page.getByRole('cell', { name: '100%' })).toBeVisible()
  // Scope to the submission row: the invite's recipients cell holds this address too.
  await expect(page.getByRole('cell', { name: 'Casey Candidate casey@example.com' })).toBeVisible()
})
