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
  return { api: { register: vi.fn(), readOrgInvite: vi.fn() }, ApiError }
})

function renderRegisterPage(url = '/register') {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <RegisterPage />
    </MemoryRouter>,
  )
}

/** Fill both password fields with the same value — the pair the form compares
 *  before it posts anything (U03). Exact labels, since /password/i now matches
 *  two inputs. */
async function typePassword(user: ReturnType<typeof userEvent.setup>, pw: string) {
  await user.type(screen.getByLabelText('Password'), pw)
  await user.type(screen.getByLabelText('Confirm password'), pw)
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
    expect(screen.getByLabelText('Password')).toHaveAttribute('minlength', '12')
  })

  it('registers, logs in and navigates to the dashboard', async () => {
    const user = userEvent.setup()
    vi.mocked(api.register).mockResolvedValue({ id: '1', email: 'a@b.com', name: 'Ada' })
    loginMock.mockResolvedValue(undefined)

    renderRegisterPage()

    await user.type(screen.getByLabelText(/name/i), 'Ada')
    await user.type(screen.getByLabelText(/email/i), 'a@b.com')
    await typePassword(user, 'correct-horse-battery')
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

  it('refuses a mismatched confirmation without creating the account', async () => {
    // A typo here used to become the account's real password, and the reset
    // path is email — which is what a locked-out interviewer cannot reach.
    const user = userEvent.setup()
    renderRegisterPage()

    await user.type(screen.getByLabelText(/name/i), 'Ada')
    await user.type(screen.getByLabelText(/email/i), 'a@b.com')
    await user.type(screen.getByLabelText('Password'), 'correct-horse-battery')
    await user.type(screen.getByLabelText('Confirm password'), 'correct-horse-bettery')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent("Passwords don't match.")
    expect(api.register).not.toHaveBeenCalled()
    expect(loginMock).not.toHaveBeenCalled()
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it('shows the API refusal verbatim', async () => {
    const user = userEvent.setup()
    vi.mocked(api.register).mockRejectedValue(
      new ApiError(422, 'that password appears in a known data breach; please choose another.'),
    )

    renderRegisterPage()

    await user.type(screen.getByLabelText(/name/i), 'Ada')
    await user.type(screen.getByLabelText(/email/i), 'a@b.com')
    await typePassword(user, 'password1234')
    await user.click(screen.getByRole('button', { name: /create account/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'that password appears in a known data breach; please choose another.',
    )
    expect(loginMock).not.toHaveBeenCalled()
    expect(navigateMock).not.toHaveBeenCalled()
  })
})

describe('RegisterPage · from an organisation invitation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // clearAllMocks keeps implementations, and the suite above leaves `register`
    // rejecting — restore the happy path explicitly.
    vi.mocked(api.register).mockResolvedValue({
      id: '2',
      email: 'sam@acme.io',
      name: 'Sam Okafor',
    })
    vi.mocked(api.readOrgInvite).mockResolvedValue({
      org_name: 'Acme Corp',
      email: 'sam@acme.io',
      role: 'member',
    })
  })

  it('fixes the address and names the organisation being joined', async () => {
    // Typing the address by hand is the one way to fail an invitation that was
    // going to work, so the form doesn't offer the chance.
    renderRegisterPage('/register?invite=abc')
    await waitFor(() => expect(screen.getByLabelText('Email')).toHaveValue('sam@acme.io'))
    expect(screen.getByLabelText('Email')).toHaveAttribute('readonly')
    expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create account and join/i })).toBeInTheDocument()
  })

  it('sends the token with the sign-up and lands on the team', async () => {
    const user = userEvent.setup()
    renderRegisterPage('/register?invite=abc')
    await waitFor(() => expect(screen.getByLabelText('Email')).toHaveValue('sam@acme.io'))

    await user.type(screen.getByLabelText('Name'), 'Sam Okafor')
    await typePassword(user, 'pw-long-enough-12')
    await user.click(screen.getByRole('button', { name: /create account and join/i }))

    await waitFor(() =>
      expect(api.register).toHaveBeenCalledWith({
        name: 'Sam Okafor',
        email: 'sam@acme.io',
        password: 'pw-long-enough-12',
        org_invite_token: 'abc',
      }),
    )
    // The redirect lands after login resolves, so it needs its own wait — the
    // register assertion above is satisfied one await earlier.
    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/team'))
  })

  it('falls back to an ordinary sign-up when the link is dead', async () => {
    // A stale link shouldn't block someone from registering at all.
    vi.mocked(api.readOrgInvite).mockRejectedValue(new ApiError(404, 'no longer valid.'))
    renderRegisterPage('/register?invite=stale')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Create account' })).toBeInTheDocument(),
    )
    expect(screen.getByLabelText('Email')).not.toHaveAttribute('readonly')
  })
})
