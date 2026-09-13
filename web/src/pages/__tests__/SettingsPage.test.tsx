import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Navigate, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from '../SettingsPage'
import { api, setToken } from '../../api'
import type { Organization, User } from '../../types'

const refreshMock = vi.fn()
const logoutMock = vi.fn()
const authState = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: authState.user, refresh: refreshMock, logout: logoutMock }),
}))

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    api: {
      updateMe: vi.fn(),
      resendVerification: vi.fn(),
      changePassword: vi.fn(),
      deleteAccount: vi.fn(),
      // BillingPanel, NotificationsPanel and PrivacyPanel each load on mount.
      getBilling: vi.fn(() => new Promise(() => {})),
      getOrg: vi.fn(() => new Promise(() => {})),
    },
    ApiError,
    setToken: vi.fn(),
  }
})

const owner = (over: Partial<User> = {}): User => ({
  id: '1',
  email: 'o@test.io',
  name: 'Owner',
  default_org_name: null,
  default_logo_url: null,
  email_verified: true,
  ...over,
})

const org = (role: Organization['role']): Organization => ({
  id: 7,
  name: 'Acme Corp',
  role,
  member_count: 3,
  retention_days: null,
  results_webhook_url: null,
  results_webhook_secret: null,
})

/** The real route shape: `/settings` redirects, and every section is its own
 *  URL. The stand-in for `/team` is there so a redirect out of Settings would
 *  be visible rather than silently rendering nothing. */
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/settings" element={<Navigate to="/settings/workspace" replace />} />
        <Route path="/settings/:section" element={<SettingsPage />} />
        <Route path="/team" element={<div>Team page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

async function fillPasswordChange(user: ReturnType<typeof userEvent.setup>, confirm: string) {
  await user.type(screen.getByLabelText(/current password/i), 'old-password-123')
  await user.type(screen.getByLabelText(/^new password/i), 'new-password-456')
  await user.type(screen.getByLabelText(/confirm new password/i), confirm)
  await user.click(screen.getByRole('button', { name: /change password/i }))
}

beforeEach(() => {
  vi.clearAllMocks()
  authState.user = owner()
  vi.mocked(api.getOrg).mockResolvedValue(org('admin'))
})

describe('Settings sections (P3a)', () => {
  it('redirects /settings to the first section rather than showing nothing', async () => {
    renderAt('/settings')
    expect(await screen.findByRole('link', { name: 'Workspace' })).toHaveAttribute(
      'aria-current',
      'page',
    )
    expect(screen.getByLabelText(/organization name/i)).toBeInTheDocument()
  })

  it('renders only the section in the URL, not the whole page', async () => {
    renderAt('/settings/security')
    expect(await screen.findByLabelText(/current password/i)).toBeInTheDocument()
    // The other sections' controls are not merely scrolled away — they are absent.
    expect(screen.queryByLabelText(/organization name/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/signed in on this browser/i)).not.toBeInTheDocument()
  })

  it('marks the current section for assistive tech, and only that one', async () => {
    renderAt('/settings/account')
    const current = await screen.findByRole('link', { name: 'Account' })
    expect(current).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Workspace' })).not.toHaveAttribute('aria-current')
  })

  it('sends an unknown section back to the first one instead of a blank panel', async () => {
    renderAt('/settings/nonsense')
    expect(await screen.findByLabelText(/organization name/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Workspace' })).toHaveAttribute('aria-current', 'page')
  })

  it('navigates by section link', async () => {
    const user = userEvent.setup()
    renderAt('/settings/workspace')

    await user.click(await screen.findByRole('link', { name: 'Account' }))

    expect(await screen.findByText(/signed in on this browser/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/organization name/i)).not.toBeInTheDocument()
  })

  it('navigates by the select the rail collapses into on a narrow screen', async () => {
    const user = userEvent.setup()
    renderAt('/settings/workspace')

    await user.selectOptions(await screen.findByLabelText(/^section$/i), 'security')

    expect(await screen.findByLabelText(/current password/i)).toBeInTheDocument()
  })
})

describe('Settings sections — what a member may see (P3a)', () => {
  // A block body, not an expression: an arrow returning the mock hands vitest
  // a "teardown function" it calls and awaits after every test.
  beforeEach(() => {
    vi.mocked(api.getOrg).mockResolvedValue(org('member'))
  })

  it('offers a member no link to an admin-only section', async () => {
    renderAt('/settings/workspace')

    expect(await screen.findByRole('link', { name: 'Workspace' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Notifications' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Privacy' })).not.toBeInTheDocument()
    // Nor in the narrow-screen control, which is the same nav in another shape.
    expect(screen.queryByRole('option', { name: 'Privacy' })).not.toBeInTheDocument()
  })

  it('sends a member who types an admin route straight back', async () => {
    renderAt('/settings/privacy')

    expect(await screen.findByLabelText(/organization name/i)).toBeInTheDocument()
    expect(screen.queryByText(/data retention/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/erase a candidate/i)).not.toBeInTheDocument()
  })

  it('never renders an admin section while the role is still unknown', async () => {
    // A pending role must not read as "allowed": the panel would flash open for
    // someone the next tick is about to redirect.
    vi.mocked(api.getOrg).mockReturnValue(new Promise(() => {}))
    renderAt('/settings/privacy')

    await waitFor(() => expect(api.getOrg).toHaveBeenCalled())
    expect(screen.queryByText(/erase a candidate/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Privacy' })).not.toBeInTheDocument()
  })

  it('says so when the role cannot be loaded, rather than demoting an admin', async () => {
    // A failed lookup is not a "no". Treating it as one costs a real admin their
    // own sections for the rest of the session, and `replace` takes the URL they
    // were on with it — so the gated section says what happened and stays put.
    vi.mocked(api.getOrg).mockRejectedValue(new Error('network down'))
    renderAt('/settings/privacy')

    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn’t check what you’re allowed/i)
    expect(screen.queryByText(/erase a candidate/i)).not.toBeInTheDocument()
    // Still on the section they asked for: reloading is a fix, being moved is not.
    expect(screen.queryByLabelText(/organization name/i)).not.toBeInTheDocument()
  })

  it('keeps the sections a member is entitled to', async () => {
    renderAt('/settings/billing')
    expect(await screen.findByRole('link', { name: 'Billing' })).toHaveAttribute(
      'aria-current',
      'page',
    )
  })
})

describe('Settings — an admin sees every section', () => {
  it('lists the admin-only sections once the role is known', async () => {
    renderAt('/settings/workspace')
    expect(await screen.findByRole('link', { name: 'Notifications' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Privacy' })).toBeInTheDocument()
  })

  it('opens an admin section at its own route', async () => {
    renderAt('/settings/privacy')
    expect(await screen.findByText(/data retention/i)).toBeInTheDocument()
  })
})

describe('Settings → Workspace', () => {
  it('loads the current default branding into the form', async () => {
    authState.user = owner({ default_org_name: 'Acme Corp', default_logo_url: 'https://acme/l.png' })
    renderAt('/settings/workspace')
    expect(await screen.findByLabelText(/organization name/i)).toHaveValue('Acme Corp')
    expect(screen.getByLabelText(/logo url/i)).toHaveValue('https://acme/l.png')
  })

  it('saves trimmed values, nulling blanks, and refreshes the session', async () => {
    const user = userEvent.setup()
    vi.mocked(api.updateMe).mockResolvedValue(owner({ default_org_name: 'Acme Corp' }))
    renderAt('/settings/workspace')

    await user.type(await screen.findByLabelText(/organization name/i), '  Acme Corp  ')
    await user.click(screen.getByRole('button', { name: /save defaults/i }))

    await waitFor(() => expect(api.updateMe).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.updateMe).mock.calls[0][0]).toEqual({
      default_org_name: 'Acme Corp',
      default_logo_url: null,
    })
    expect(refreshMock).toHaveBeenCalled()
    expect(await screen.findByText(/saved/i)).toBeInTheDocument()
  })
})

describe('Settings → Account', () => {
  it('shows the Confirmed chip and no resend button for a verified address', async () => {
    renderAt('/settings/account')
    expect(await screen.findByText('Confirmed')).toBeInTheDocument()
    expect(screen.queryByText('Not confirmed')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resend link/i })).not.toBeInTheDocument()
  })

  it('offers to resend the link while the address is unconfirmed', async () => {
    const user = userEvent.setup()
    authState.user = owner({ email_verified: false })
    vi.mocked(api.resendVerification).mockResolvedValue({ detail: 'sent' })
    renderAt('/settings/account')

    expect(await screen.findByText('Not confirmed')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /resend link/i }))

    await waitFor(() => expect(api.resendVerification).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/check o@test.io for the new link/i)).toBeInTheDocument()
  })

  it('stops offering resend once the link has been sent', async () => {
    const user = userEvent.setup()
    authState.user = owner({ email_verified: false })
    vi.mocked(api.resendVerification).mockResolvedValue({ detail: 'sent' })
    renderAt('/settings/account')

    const resend = await screen.findByRole('button', { name: /resend link/i })
    await user.click(resend)

    // Re-sending shares a rate-limit bucket with password reset, so a spent
    // button must not stay clickable.
    await waitFor(() => expect(resend).toBeDisabled())
    expect(api.resendVerification).toHaveBeenCalledTimes(1)
  })
})

describe('Settings → Security', () => {
  it('changes the password, keeps this tab signed in, and confirms', async () => {
    const user = userEvent.setup()
    vi.mocked(api.changePassword).mockResolvedValue({
      access_token: 'tok-new',
      token_type: 'bearer',
    })
    renderAt('/settings/security')

    await waitFor(() => expect(screen.getByLabelText(/current password/i)).toBeInTheDocument())
    await fillPasswordChange(user, 'new-password-456')

    await waitFor(() =>
      expect(api.changePassword).toHaveBeenCalledWith('old-password-123', 'new-password-456'),
    )
    expect(setToken).toHaveBeenCalledWith('tok-new')
    expect(
      await screen.findByText(/password changed\. other devices have been signed out/i),
    ).toBeInTheDocument()
  })

  it('rejects a mismatched confirmation locally', async () => {
    const user = userEvent.setup()
    renderAt('/settings/security')

    await waitFor(() => expect(screen.getByLabelText(/current password/i)).toBeInTheDocument())
    await fillPasswordChange(user, 'something-else')

    expect(await screen.findByRole('alert')).toHaveTextContent("Passwords don't match.")
    expect(api.changePassword).not.toHaveBeenCalled()
  })

  it('shows the error when the current password is wrong', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.changePassword).mockRejectedValue(
      new ApiError(403, 'current password is incorrect.'),
    )
    renderAt('/settings/security')

    await waitFor(() => expect(screen.getByLabelText(/current password/i)).toBeInTheDocument())
    await fillPasswordChange(user, 'new-password-456')

    expect(await screen.findByRole('alert')).toHaveTextContent(/current password is incorrect/i)
    expect(setToken).not.toHaveBeenCalled()
  })

  it('shows a policy or breach refusal verbatim', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.changePassword).mockRejectedValue(
      new ApiError(422, 'that password appears in a known data breach; please choose another.'),
    )
    renderAt('/settings/security')

    await waitFor(() => expect(screen.getByLabelText(/current password/i)).toBeInTheDocument())
    await fillPasswordChange(user, 'new-password-456')

    expect(await screen.findByRole('alert')).toHaveTextContent(/known data breach/i)
    expect(setToken).not.toHaveBeenCalled()
  })

  it('deletes the account once the password is filled in, then logs out', async () => {
    const user = userEvent.setup()
    vi.mocked(api.deleteAccount).mockResolvedValue(undefined)
    renderAt('/settings/security')

    const deleteButton = await screen.findByRole('button', { name: /delete my account/i })
    expect(deleteButton).toBeDisabled()

    await user.type(screen.getByLabelText(/confirm with your password/i), 'hunter2hunter2')
    expect(deleteButton).toBeEnabled()
    await user.click(deleteButton)

    await waitFor(() => expect(api.deleteAccount).toHaveBeenCalledWith('hunter2hunter2'))
    await waitFor(() => expect(logoutMock).toHaveBeenCalled())
  })

  it('shows the error when the delete password is wrong', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.deleteAccount).mockRejectedValue(new ApiError(403, 'password is incorrect.'))
    renderAt('/settings/security')

    await user.type(
      await screen.findByLabelText(/confirm with your password/i),
      'wrong',
    )
    await user.click(screen.getByRole('button', { name: /delete my account/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/password is incorrect/i)
    expect(logoutMock).not.toHaveBeenCalled()
  })
})
