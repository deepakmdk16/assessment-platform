import { test, expect } from '@playwright/test'
import { registerInterviewer } from './helpers'

/** P3a — Settings is one route per section. Sign-up makes every account the
 *  admin of its own organisation, so this interviewer sees all six. */
test('every settings section has its own route, and the rail moves between them', async ({
  page,
}) => {
  await registerInterviewer(page)

  // Bare /settings is not a page; it sends you to the first section.
  await page.goto('/settings')
  await expect(page).toHaveURL(/\/settings\/workspace$/)
  await expect(page.getByLabel('Organization name')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Workspace' })).toHaveAttribute(
    'aria-current',
    'page',
  )

  const sections: [string, RegExp][] = [
    ['Billing', /candidate sittings/i],
    ['Notifications', /send results to another system/i],
    ['Privacy', /data retention/i],
    ['Account', /signed in on this browser/i],
    ['Security', /change password/i],
  ]
  for (const [label, marker] of sections) {
    await page.getByRole('link', { name: label }).click()
    await expect(page).toHaveURL(new RegExp(`/settings/${label.toLowerCase()}$`))
    await expect(page.getByText(marker).first()).toBeVisible()
  }

  // Deep-linking works, which is the point of a route per section…
  await page.goto('/settings/privacy')
  await expect(page.getByText(/erase a candidate/i)).toBeVisible()
  // …and so does the back button, which one long scrolling page could not offer.
  await page.goBack()
  await expect(page).toHaveURL(/\/settings\/security$/)

  // A section that does not exist is not a blank panel.
  await page.goto('/settings/nonsense')
  await expect(page).toHaveURL(/\/settings\/workspace$/)
})
