import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AppLayout } from '../AppLayout'
import { ThemeProvider } from '../../theme/ThemeContext'
import { api } from '../../api'
import type { User } from '../../types'

const authState = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: authState.user, logout: vi.fn() }),
}))

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return { api: { resendVerification: vi.fn() }, ApiError }
})

const owner = (over: Partial<User> = {}): User => ({
  id: '1',
  email: 'jane@acme.com',
  name: 'Jane Okafor',
  default_org_name: null,
  default_logo_url: null,
  email_verified: false,
  ...over,
})

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <ThemeProvider>
        <AppLayout>
          <p>page content</p>
        </AppLayout>
      </ThemeProvider>
    </MemoryRouter>,
  )
}

describe('AppLayout', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = owner()
  })

  it('shows the confirm-email banner while the address is unconfirmed', () => {
    renderLayout()
    expect(screen.getByRole('status')).toHaveTextContent(
      'Confirm your email. We sent a link to jane@acme.com.',
    )
    expect(screen.getByText('page content')).toBeInTheDocument()
  })

  it('renders no banner once the address is confirmed', () => {
    authState.user = owner({ email_verified: true })
    renderLayout()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('swaps to the sent state after resending the link', async () => {
    const user = userEvent.setup()
    vi.mocked(api.resendVerification).mockResolvedValue({ detail: 'sent' })
    renderLayout()

    await user.click(screen.getByRole('button', { name: /resend link/i }))

    await waitFor(() => expect(api.resendVerification).toHaveBeenCalledTimes(1))
    expect(await screen.findByText(/check jane@acme.com for the new link/i)).toBeInTheDocument()
    expect(screen.queryByText(/confirm your email/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /resend link/i })).not.toBeInTheDocument()
  })

  it('keeps the warning and shows the API message when resending fails', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.resendVerification).mockRejectedValue(new ApiError(429, 'Too many requests.'))
    renderLayout()

    await user.click(screen.getByRole('button', { name: /resend link/i }))

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent(/couldn.t resend: Too many requests\./i),
    )
    expect(screen.getByRole('status')).toHaveTextContent(/confirm your email/i)
    expect(screen.getByRole('button', { name: /resend link/i })).toBeEnabled()
  })

  it('hides the sent state too', async () => {
    const user = userEvent.setup()
    vi.mocked(api.resendVerification).mockResolvedValue({ detail: 'sent' })
    renderLayout()

    await user.click(screen.getByRole('button', { name: /resend link/i }))
    await user.click(await screen.findByRole('button', { name: 'Hide' }))

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('dismisses the banner until the next page load', async () => {
    const user = userEvent.setup()
    renderLayout()

    await user.click(screen.getByRole('button', { name: /hide for now/i }))

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
