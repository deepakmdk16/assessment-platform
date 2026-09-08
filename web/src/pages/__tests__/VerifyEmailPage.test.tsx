import { StrictMode } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { VerifyEmailPage } from '../VerifyEmailPage'
import { api, ApiError } from '../../api'
import type { User } from '../../types'

const refreshMock = vi.fn(async () => {})
const authState = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: authState.user, loading: false, refresh: refreshMock }),
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
    api: { verifyEmail: vi.fn() },
    ApiError,
    getToken: vi.fn(() => null),
    setToken: vi.fn(),
    clearToken: vi.fn(),
    setUnauthorizedHandler: vi.fn(),
    setNoOrganizationHandler: vi.fn(),
    tryRefresh: vi.fn(async () => false),
  }
})

// A link token carries the address it confirms (payload is display-only).
const token = `hdr.${btoa(JSON.stringify({ email: 'jane@acme.com', use: 'verify' }))}.sig`

// StrictMode double-invokes effects: the page must still post the token exactly once.
function renderPage(search = `?token=${token}`) {
  return render(
    <StrictMode>
      <MemoryRouter initialEntries={[`/verify-email${search}`]}>
        <VerifyEmailPage />
      </MemoryRouter>
    </StrictMode>,
  )
}

describe('VerifyEmailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = null
  })

  it('posts the token once and shows Confirmed with a Log in link when signed out', async () => {
    vi.mocked(api.verifyEmail).mockResolvedValue(undefined)
    renderPage()

    expect(screen.getByText('Confirming…')).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: /email confirmed/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /log in/i })).toHaveAttribute('href', '/login')
    expect(api.verifyEmail).toHaveBeenCalledTimes(1)
    expect(api.verifyEmail).toHaveBeenCalledWith(token)
    expect(refreshMock).not.toHaveBeenCalled()
    // The address comes from the link, so it shows even with no session.
    expect(screen.getByText('jane@acme.com')).toBeInTheDocument()
  })

  it('names the address from the link, not the signed-in account', async () => {
    authState.user = {
      id: '2',
      email: 'other@acme.com',
      name: 'Other',
      default_org_name: null,
      default_logo_url: null,
      email_verified: true,
    }
    vi.mocked(api.verifyEmail).mockResolvedValue(undefined)
    renderPage()

    expect(await screen.findByRole('heading', { name: /email confirmed/i })).toBeInTheDocument()
    expect(screen.getByText('jane@acme.com')).toBeInTheDocument()
    expect(screen.queryByText('other@acme.com')).not.toBeInTheDocument()
  })

  it('refreshes the session and links to the dashboard when signed in', async () => {
    authState.user = {
      id: '1',
      email: 'jane@acme.com',
      name: 'Jane',
      default_org_name: null,
      default_logo_url: null,
      email_verified: false,
    }
    vi.mocked(api.verifyEmail).mockResolvedValue(undefined)
    renderPage()

    expect(await screen.findByRole('heading', { name: /email confirmed/i })).toBeInTheDocument()
    expect(refreshMock).toHaveBeenCalledTimes(1)
    expect(screen.getByText('jane@acme.com')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /go to your workspace/i })).toHaveAttribute(
      'href',
      '/dashboard',
    )
  })

  it('shows the bad-link state on 400', async () => {
    vi.mocked(api.verifyEmail).mockRejectedValue(new ApiError(400, 'Invalid or expired token'))
    renderPage()

    expect(
      await screen.findByRole('heading', { name: /this link doesn't work/i }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /log in/i })).toHaveAttribute('href', '/login')
  })

  it('offers a retry instead of claiming the link expired when the server errors', async () => {
    vi.mocked(api.verifyEmail).mockRejectedValueOnce(new ApiError(500, 'boom'))
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByRole('heading', { name: /couldn.t confirm right now/i })).toBeInTheDocument()
    expect(screen.queryByText(/expire after three days/i)).not.toBeInTheDocument()

    vi.mocked(api.verifyEmail).mockResolvedValueOnce(undefined)
    await user.click(screen.getByRole('button', { name: /try again/i }))

    expect(await screen.findByRole('heading', { name: /email confirmed/i })).toBeInTheDocument()
    expect(api.verifyEmail).toHaveBeenCalledTimes(2)
  })

  it('shows the bad-link state without a token and never calls the API', () => {
    renderPage('')
    expect(screen.getByRole('heading', { name: /this link doesn't work/i })).toBeInTheDocument()
    expect(api.verifyEmail).not.toHaveBeenCalled()
  })
})
