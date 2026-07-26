import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsPage } from '../SettingsPage'
import { api } from '../../api'
import type { User } from '../../types'

const refreshMock = vi.fn()
const authState = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: authState.user, refresh: refreshMock }),
}))

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return { api: { updateMe: vi.fn() }, ApiError }
})

const owner = (over: Partial<User> = {}): User => ({
  id: '1',
  email: 'o@test.io',
  name: 'Owner',
  default_org_name: null,
  default_logo_url: null,
  ...over,
})

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
})
