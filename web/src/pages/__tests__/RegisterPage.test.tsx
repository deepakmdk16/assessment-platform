import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RegisterPage } from '../RegisterPage'
import { api, ApiError } from '../../api'

const navigateMock = vi.fn()
const loginMock = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ login: loginMock }),
}))

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return { api: { register: vi.fn() }, ApiError }
})

function renderRegisterPage() {
  return render(
    <MemoryRouter>
      <RegisterPage />
    </MemoryRouter>,
  )
}

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('shows the password rule under the field', () => {
    renderRegisterPage()
    expect(
      screen.getByText('At least 12 characters. Passwords that appear in known breaches are refused.'),
    ).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toHaveAttribute('minlength', '12')
  })

  it('registers, logs in and navigates to the dashboard', async () => {
    const user = userEvent.setup()
    vi.mocked(api.register).mockResolvedValue({ id: '1', email: 'a@b.com', name: 'Ada' })
    loginMock.mockResolvedValue(undefined)

    renderRegisterPage()

    await user.type(screen.getByLabelText(/name/i), 'Ada')
    await user.type(screen.getByLabelText(/email/i), 'a@b.com')
    await user.type(screen.getByLabelText(/password/i), 'correct-horse-battery')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    await waitFor(() => {
      expect(api.register).toHaveBeenCalledWith({
        name: 'Ada',
        email: 'a@b.com',
        password: 'correct-horse-battery',
      })
    })
    expect(loginMock).toHaveBeenCalledWith('a@b.com', 'correct-horse-battery')
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/dashboard'))
  })

  it('shows the API refusal verbatim', async () => {
    const user = userEvent.setup()
    vi.mocked(api.register).mockRejectedValue(
      new ApiError(422, 'that password appears in a known data breach; please choose another.'),
    )

    renderRegisterPage()

    await user.type(screen.getByLabelText(/name/i), 'Ada')
    await user.type(screen.getByLabelText(/email/i), 'a@b.com')
    await user.type(screen.getByLabelText(/password/i), 'password1234')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'that password appears in a known data breach; please choose another.',
    )
    expect(loginMock).not.toHaveBeenCalled()
    expect(navigateMock).not.toHaveBeenCalled()
  })
})
