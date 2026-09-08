import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ForgotPasswordPage } from '../ForgotPasswordPage'
import { api, ApiError } from '../../api'

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    api: { forgotPassword: vi.fn() },
    ApiError,
    getToken: vi.fn(() => null),
    setToken: vi.fn(),
    clearToken: vi.fn(),
    setUnauthorizedHandler: vi.fn(),
    setNoOrganizationHandler: vi.fn(),
    tryRefresh: vi.fn(async () => false),
  }
})

function renderPage() {
  return render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>,
  )
}

async function submit(user: ReturnType<typeof userEvent.setup>, email: string) {
  await user.type(screen.getByLabelText(/email/i), email)
  await user.click(screen.getByRole('button', { name: /email me a reset link/i }))
}

describe('ForgotPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the sent state with the address; try again returns to the form', async () => {
    const user = userEvent.setup()
    vi.mocked(api.forgotPassword).mockResolvedValue({ detail: 'ok' })
    renderPage()

    await submit(user, 'jane@acme.com')

    expect(await screen.findByRole('heading', { name: /check your inbox/i })).toBeInTheDocument()
    expect(screen.getByText('jane@acme.com')).toBeInTheDocument()
    expect(api.forgotPassword).toHaveBeenCalledWith('jane@acme.com')

    await user.click(screen.getByRole('button', { name: /try again/i }))
    expect(screen.getByRole('heading', { name: /reset your password/i })).toBeInTheDocument()
  })

  it('shows the rate-limit copy on 429', async () => {
    const user = userEvent.setup()
    vi.mocked(api.forgotPassword).mockRejectedValue(new ApiError(429, 'Too Many Requests'))
    renderPage()

    await submit(user, 'jane@acme.com')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Too many attempts, try again in a minute.',
    )
    expect(screen.queryByRole('heading', { name: /check your inbox/i })).not.toBeInTheDocument()
  })
})
