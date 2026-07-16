import { test, expect } from '@playwright/test'
import { registerInterviewer, createQuestion, createInvite, startAsCandidate } from './helpers'

test('candidate runs code against their own input, then against the test cases', async ({
  page,
  browser,
}) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page, ['runner@example.com'])

  const { context, page: candidate } = await startAsCandidate(browser, inviteUrl, {
    name: 'Runner Candidate',
    email: 'runner@example.com',
  })

  await candidate.locator('.monaco-editor .view-lines').click()
  await candidate.keyboard.type('print("solution")')

  // Run against custom stdin.
  await candidate.getByLabel('Your input (stdin)').fill('21')
  await candidate.getByRole('button', { name: 'Run', exact: true }).click()
  await expect(candidate.getByText(/mock-run-output for stdin: 21/)).toBeVisible()

  // Run against the real test suite: counts and statuses, no case contents.
  await candidate.getByRole('button', { name: 'Run against test cases' }).click()
  await expect(candidate.getByText(/1 of 2 test cases passed/i)).toBeVisible()
  await expect(candidate.getByText('Test 1')).toBeVisible()
  await expect(candidate.getByText('Test 2')).toBeVisible()
  // The interviewer's case names must never reach the candidate.
  await expect(candidate.getByText('basic')).toHaveCount(0)
  await expect(candidate.getByText('large')).toHaveCount(0)

  // Neither run recorded an attempt: Submit still works afterwards.
  await candidate.getByRole('button', { name: 'Submit' }).click()
  await expect(candidate.getByRole('heading', { name: 'Submitted' })).toBeVisible()
  await context.close()
})
