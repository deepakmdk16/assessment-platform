import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ResetPasswordPage } from '../ResetPasswordPage'
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
    api: { resetPassword: vi.fn() },
    ApiError,
    getToken: vi.fn(() => null),
    setToken: vi.fn(),
    clearToken: vi.fn(),
    setUnauthorizedHandler: vi.fn(),
    tryRefresh: vi.fn(async () => false),
  }
})

// A JWT-shaped token whose payload carries the email claim the greeting decodes.
const token = `hdr.${btoa(JSON.stringify({ email: 'jane@acme.com', use: 'reset' }))}.sig`

function renderPage(search = `?token=${token}`) {
  return render(
    <MemoryRouter initialEntries={[`/reset-password${search}`]}>
      <ResetPasswordPage />
    </MemoryRouter>,
  )
}

async function submit(
  user: ReturnType<typeof userEvent.setup>,
  password: string,
  confirm = password,
) {
  await user.type(screen.getByLabelText('New password'), password)
  await user.type(screen.getByLabelText('Confirm new password'), confirm)
  await user.click(screen.getByRole('button', { name: /set new password/i }))
}

describe('ResetPasswordPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the bad-link state when there is no token', () => {
    renderPage('')
    expect(screen.getByRole('heading', { name: /this link doesn't work/i })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /request a new link/i })).toHaveAttribute(
      'href',
      '/forgot-password',
    )
  })

  it('drops a claim that is not an address (a crafted link cannot inject copy)', () => {
    const crafted = `hdr.${btoa(JSON.stringify({ email: 'call 555-0100 now to keep access' }))}.sig`
    renderPage(`?token=${crafted}`)
    expect(screen.getByRole('heading', { name: /choose a new password/i })).toBeInTheDocument()
    expect(screen.queryByText(/555-0100/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^For /)).not.toBeInTheDocument()
  })

  it('greets the address decoded from the token', () => {
    renderPage()
    expect(screen.getByText('jane@acme.com')).toBeInTheDocument()
  })

  it('blocks a mismatched confirmation locally without calling the API', async () => {
    const user = userEvent.setup()
    renderPage()

    await submit(user, 'correct-horse-battery', 'correct-horse-staple')

    expect(screen.getByRole('alert')).toHaveTextContent("Passwords don't match.")
    expect(api.resetPassword).not.toHaveBeenCalled()
  })

  it('shows the updated state on success', async () => {
    const user = userEvent.setup()
    vi.mocked(api.resetPassword).mockResolvedValue(undefined)
    renderPage()

    await submit(user, 'correct-horse-battery')

    expect(await screen.findByRole('heading', { name: /password updated/i })).toBeInTheDocument()
    expect(api.resetPassword).toHaveBeenCalledWith(token, 'correct-horse-battery')
    expect(screen.getByRole('link', { name: /log in/i })).toHaveAttribute('href', '/login')
  })

  it('shows the bad-link state on 400', async () => {
    const user = userEvent.setup()
    vi.mocked(api.resetPassword).mockRejectedValue(new ApiError(400, 'Invalid or expired token'))
    renderPage()

    await submit(user, 'correct-horse-battery')

    expect(
      await screen.findByRole('heading', { name: /this link doesn't work/i }),
    ).toBeInTheDocument()
  })

  it('shows the API message on 422 and keeps the form', async () => {
    const user = userEvent.setup()
    vi.mocked(api.resetPassword).mockRejectedValue(
      new ApiError(422, 'Password must be at least 12 characters'),
    )
    renderPage()

    await submit(user, 'short')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Password must be at least 12 characters',
    )
    expect(screen.getByLabelText('New password')).toBeInTheDocument()
  })
})
