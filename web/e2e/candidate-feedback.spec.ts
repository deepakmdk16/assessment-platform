import { test, expect } from '@playwright/test'
import {
  registerInterviewer,
  createQuestion,
  createAssessmentInvite,
  submitAsCandidate,
} from './helpers'

test('candidate leaves feedback on a finished sitting, and the interviewer sees it', async ({
  page,
  browser,
}) => {
  const creds = await registerInterviewer(page)
  const question = await createQuestion(page)
  const inviteUrl = await createAssessmentInvite(page, creds, question.id, ['fb@example.com'])

  const { context, page: candidate } = await submitAsCandidate(browser, inviteUrl, {
    name: 'Feedback Candidate',
    email: 'fb@example.com',
  })
  // One question, so this is the single-question flow's terminal screen — the
  // invite is still assessment-backed, which is what decides the form.
  await expect(candidate.getByRole('heading', { name: 'Submitted' })).toBeVisible()

  // Optional, and it sends nothing until a rating is chosen.
  await expect(candidate.getByRole('button', { name: 'Send feedback' })).toBeDisabled()
  await candidate.getByRole('radio', { name: '4' }).check()
  await candidate.getByRole('radio', { name: 'Too hard' }).check()
  await candidate.getByLabel('Anything you want the team to know?').fill('The editor was quick.')
  await candidate.getByRole('button', { name: 'Send feedback' }).click()
  await expect(candidate.getByText(/your feedback is with the hiring team/i)).toBeVisible()

  // Once per sitting: reloading the finished screen offers no second form.
  await candidate.reload()
  await expect(candidate.getByRole('button', { name: 'Send feedback' })).toHaveCount(0)
  await context.close()

  // The interviewer's attempts grid carries it, per sitting.
  await page.goto('/assessments')
  await page.getByRole('link', { name: /^Screen / }).first().click()
  await expect(page.getByText('4/5')).toBeVisible()
  await expect(page.getByText(/too hard · “the editor was quick/i)).toBeVisible()
})
