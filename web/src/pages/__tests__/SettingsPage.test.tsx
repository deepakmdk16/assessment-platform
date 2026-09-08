import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from '../SettingsPage'
import { api, setToken } from '../../api'
import type { User } from '../../types'

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

async function fillPasswordChange(user: ReturnType<typeof userEvent.setup>, confirm: string) {
  await user.type(screen.getByLabelText(/current password/i), 'old-password-123')
  await user.type(screen.getByLabelText(/^new password/i), 'new-password-456')
  await user.type(screen.getByLabelText(/confirm new password/i), confirm)
  await user.click(screen.getByRole('button', { name: /change password/i }))
}

describe('SettingsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = owner()
  })

  it('loads the current default branding into the form', () => {
    authState.user = owner({ default_org_name: 'Acme Corp', default_logo_url: 'https://acme/l.png' })
    render(<SettingsPage />)
    expect(screen.getByLabelText(/organization name/i)).toHaveValue('Acme Corp')
    expect(screen.getByLabelText(/logo url/i)).toHaveValue('https://acme/l.png')
  })

  it('saves trimmed values, nulling blanks, and refreshes the session', async () => {
    const user = userEvent.setup()
    vi.mocked(api.updateMe).mockResolvedValue(owner({ default_org_name: 'Acme Corp' }))
    render(<SettingsPage />)

    await user.type(screen.getByLabelText(/organization name/i), '  Acme Corp  ')
    await user.click(screen.getByRole('button', { name: /save defaults/i }))

    await waitFor(() => expect(api.updateMe).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.updateMe).mock.calls[0][0]).toEqual({
      default_org_name: 'Acme Corp',
      default_logo_url: null,
    })
    expect(refreshMock).toHaveBeenCalled()
    expect(await screen.findByText(/saved/i)).toBeInTheDocument()
  })

  it('shows the Confirmed chip and no resend button for a verified address', () => {
    render(<SettingsPage />)
    expect(screen.getByText('Confirmed')).toBeInTheDocument()
    expect(screen.queryByText('Not confirmed')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resend link/i })).not.toBeInTheDocument()
  })

  it('offers to resend the link while the address is unconfirmed', async () => {
    const user = userEvent.setup()
    authState.user = owner({ email_verified: false })
    vi.mocked(api.resendVerification).mockResolvedValue({ detail: 'sent' })
    render(<SettingsPage />)

    expect(screen.getByText('Not confirmed')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /resend link/i }))

    await waitFor(() => expect(api.resendVerification).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/check o@test.io for the new link/i)).toBeInTheDocument()
  })

  it('stops offering resend once the link has been sent', async () => {
    const user = userEvent.setup()
    authState.user = owner({ email_verified: false })
    vi.mocked(api.resendVerification).mockResolvedValue({ detail: 'sent' })
    render(<SettingsPage />)

    const resend = screen.getByRole('button', { name: /resend link/i })
    await user.click(resend)

    // Re-sending shares a rate-limit bucket with password reset, so a spent
    // button must not stay clickable.
    await waitFor(() => expect(resend).toBeDisabled())
    expect(api.resendVerification).toHaveBeenCalledTimes(1)
  })

  it('changes the password, keeps this tab signed in, and confirms', async () => {
    const user = userEvent.setup()
    vi.mocked(api.changePassword).mockResolvedValue({ access_token: 'tok-new', token_type: 'bearer' })
    render(<SettingsPage />)

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
    render(<SettingsPage />)

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
    render(<SettingsPage />)

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
    render(<SettingsPage />)

    await fillPasswordChange(user, 'new-password-456')

    expect(await screen.findByRole('alert')).toHaveTextContent(/known data breach/i)
    expect(setToken).not.toHaveBeenCalled()
  })

  it('deletes the account once the password is filled in, then logs out', async () => {
    const user = userEvent.setup()
    vi.mocked(api.deleteAccount).mockResolvedValue(undefined)
    render(<SettingsPage />)

    const deleteButton = screen.getByRole('button', { name: /delete my account/i })
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
    render(<SettingsPage />)

    await user.type(screen.getByLabelText(/confirm with your password/i), 'wrong')
    await user.click(screen.getByRole('button', { name: /delete my account/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/password is incorrect/i)
    expect(logoutMock).not.toHaveBeenCalled()
  })
})
