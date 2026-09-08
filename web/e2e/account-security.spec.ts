import { test, expect } from '@playwright/test'
import { registerInterviewer, uniqueSuffix } from './helpers'

test('changing the password signs the old one out and the new one in', async ({ page }) => {
  const { email, password } = await registerInterviewer(page)
  const newPassword = `changed-password-${uniqueSuffix()}`

  // A fresh account is unconfirmed: the banner nags on every interviewer page.
  await expect(page.getByRole('status').filter({ hasText: 'Confirm your email.' })).toBeVisible()

  await page.goto('/settings')
  await expect(page.getByText('Not confirmed')).toBeVisible()

  await page.getByLabel('Current password').fill(password)
  await page.getByLabel('New password', { exact: true }).fill(newPassword)
  await page.getByLabel('Confirm new password').fill(newPassword)
  await page.getByRole('button', { name: 'Change password' }).click()
  await expect(
    page.getByText('Password changed. Other devices have been signed out.'),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Log out' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()

  // The old password is refused…
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('alert')).toContainText('invalid email or password')

  // …and the new one lands on the dashboard.
  await page.getByLabel('Password').fill(newPassword)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.getByRole('heading', { name: 'Questions' })).toBeVisible()
})
