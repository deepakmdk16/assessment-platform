import { test, expect } from '@playwright/test'
import { registerInterviewer, createQuestion, createInvite, submitAsCandidate } from './helpers'

test('interviewer opens a graded submission and sees the full report card', async ({
  page,
  browser,
}) => {
  await registerInterviewer(page)
  await createQuestion(page)
  const inviteUrl = await createInvite(page, ['reportee@example.com'])

  const { context, page: candidatePage } = await submitAsCandidate(browser, inviteUrl, {
    name: 'Reportee Candidate',
    email: 'reportee@example.com',
  })
  await expect(candidatePage.getByRole('heading', { name: 'Submitted' })).toBeVisible()
  await context.close()

  // Wait for the graded row, then click through to the report.
  await expect(async () => {
    await page.reload()
    await expect(page.getByRole('cell', { name: 'PASS', exact: true })).toBeVisible({
      timeout: 1500,
    })
  }).toPass({ timeout: 15000 })

  await page.getByRole('cell', { name: 'Reportee Candidate reportee@example.com' }).click()

  // The problem, the candidate's code, and the agent's verdict.
  await expect(page.getByText('Return indices of the two numbers')).toBeVisible()
  // Presence only: Monaco virtualizes its text, so its textContent is unreliable
  // to assert on. The unit test covers that the code reaches the editor.
  await expect(page.locator('.monaco-editor').first()).toBeVisible()
  await expect(page.getByText('mock agent: all tests passed')).toBeVisible()

  // The AI summary, strengths and weaknesses from the agent's quality block.
  await expect(page.getByText('Mock grade for E2E.')).toBeVisible()
  await expect(page.getByText('Mock strength: handles edge cases.')).toBeVisible()
  await expect(page.getByText('Mock weakness: no input validation.')).toBeVisible()

  // Per-test-case detail, including the inputs/expected the candidate never sees.
  await page.getByRole('button', { name: /test cases/i }).click()
  await expect(page.getByText('basic')).toBeVisible()
  await expect(page.getByText('large')).toBeVisible()
  await expect(page.getByText('mock-input-1')).toBeVisible()
  await expect(page.getByText('mock-input-2')).toBeVisible()
})
