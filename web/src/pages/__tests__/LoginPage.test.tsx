import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from '../LoginPage'
import { AuthProvider } from '../../auth/AuthContext'
import { api } from '../../api'

const navigateMock = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    api: { login: vi.fn(), me: vi.fn(), register: vi.fn(), logout: vi.fn() },
    ApiError,
    getToken: vi.fn(() => null),
    setToken: vi.fn(),
    clearToken: vi.fn(),
    setUnauthorizedHandler: vi.fn(),
    setNoOrganizationHandler: vi.fn(),
    // No live session on boot: the provider's refresh attempt resolves false.
    tryRefresh: vi.fn(async () => false),
  }
})

function renderLoginPage(url = '/login') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthProvider>
        <LoginPage />
      </AuthProvider>
    </MemoryRouter>,
  )
}

async function signIn() {
  const user = userEvent.setup()
  await user.type(screen.getByLabelText('Email'), 'sam@acme.io')
  await user.type(screen.getByLabelText('Password'), 'pw-long-enough-12')
  await user.click(screen.getByRole('button', { name: /log in/i }))
}

describe('LoginPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('logs in with valid credentials and navigates to the dashboard', async () => {
    const user = userEvent.setup()
    vi.mocked(api.login).mockResolvedValue({ access_token: 'tok123', token_type: 'bearer' })
    vi.mocked(api.me).mockResolvedValue({
      id: '1',
      email: 'a@b.com',
      name: 'Ada',
      default_org_name: null,
      default_logo_url: null,
      email_verified: true,
    })

    renderLoginPage()

    await user.type(screen.getByLabelText(/email/i), 'a@b.com')
    await user.type(screen.getByLabelText(/password/i), 'secret123')
    await user.click(screen.getByRole('button', { name: /log in/i }))

    await waitFor(() => {
      expect(api.login).toHaveBeenCalledWith({ email: 'a@b.com', password: 'secret123' })
    })
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/dashboard'))
  })

  it('shows an error message when login fails', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.login).mockRejectedValue(new ApiError(401, 'Invalid credentials'))

    renderLoginPage()

    await user.type(screen.getByLabelText(/email/i), 'a@b.com')
    await user.type(screen.getByLabelText(/password/i), 'wrong')
    await user.click(screen.getByRole('button', { name: /log in/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid credentials')
  })

  it('links to the forgot-password page', () => {
    renderLoginPage()
    expect(screen.getByRole('link', { name: /forgot password/i })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
  })
})

describe('LoginPage · returning to where you came from', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.login).mockResolvedValue({ access_token: 't', token_type: 'bearer' })
  })

  it('returns to the invitation an existing account arrived from', async () => {
    // The join page sends people here when they already have an account; without
    // carrying the token they land on the dashboard with the invitation lost.
    renderLoginPage(`/login?next=${encodeURIComponent('/join?token=abc')}`)
    await signIn()
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/join?token=abc'))
  })

  it('ignores an off-site destination', async () => {
    // `next` comes from the address bar, so anyone can set it — an absolute URL
    // here would turn sign-in into an open redirect.
    renderLoginPage('/login?next=https://evil.example/steal')
    await signIn()
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/dashboard'))
  })

  it('ignores a protocol-relative destination', async () => {
    renderLoginPage('/login?next=//evil.example/steal')
    await signIn()
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/dashboard'))
  })
})
