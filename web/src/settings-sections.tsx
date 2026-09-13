import type { ReactElement } from 'react'
import { AccountPanel } from './components/AccountPanel'
import { BillingPanel } from './components/BillingPanel'
import { NotificationsPanel } from './components/NotificationsPanel'
import { PrivacyPanel } from './components/PrivacyPanel'
import { SecurityPanel } from './components/SecurityPanel'
import { WorkspacePanel } from './components/WorkspacePanel'

export interface SettingsSection {
  /** The URL segment: /settings/<id>. */
  id: string
  label: string
  /** The line under the heading — what this section is for, in one sentence. */
  sub: string
  /** Admin-only sections are absent for a member, and their routes redirect.
   *  Hidden rather than disabled: a control someone cannot use is not an
   *  explanation, it is an invitation to ask. */
  admin?: boolean
  panel: () => ReactElement
}

/** One table, in rail order. The panel lives on the row rather than in a switch
 *  the rail has to be kept in step with by hand — a section is either complete
 *  here or it does not exist. */
export const SETTINGS_SECTIONS: SettingsSection[] = [
  {
    id: 'workspace',
    label: 'Workspace',
    sub: 'The branding every new assessment is pre-filled with.',
    panel: () => <WorkspacePanel />,
  },
  {
    id: 'billing',
    label: 'Billing',
    sub: 'This month’s usage and the plan it is measured against.',
    panel: () => <BillingPanel />,
  },
  {
    id: 'notifications',
    label: 'Notifications',
    sub: 'Where a finished sitting’s result is sent.',
    admin: true,
    panel: () => <NotificationsPanel />,
  },
  {
    id: 'privacy',
    label: 'Privacy',
    sub: 'How long candidate data is kept, and how to erase it on request.',
    admin: true,
    panel: () => <PrivacyPanel />,
  },
  {
    id: 'account',
    label: 'Account',
    sub: 'Your login and the address we reach you on.',
    panel: () => <AccountPanel />,
  },
  {
    id: 'security',
    label: 'Security',
    sub: 'Your password, and deleting your account.',
    panel: () => <SecurityPanel />,
  },
]

/** Where bare /settings goes, and where an unknown or forbidden section is sent.
 *  Derived as the first section nobody is gated out of: a redirect target that
 *  could itself be refused is an infinite loop, so the order cannot create one. */
export const DEFAULT_SECTION = SETTINGS_SECTIONS.filter((s) => !s.admin)[0].id
