import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { JoinPage } from '../JoinPage'
import { api } from '../../api'
import type { OrgInvitePublic, User } from '../../types'

const navigateMock = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => navigateMock }
})

const authState = vi.hoisted(() => ({ user: null as User | null, loading: false }))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: authState.user, loading: authState.loading }),
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
    api: { readOrgInvite: vi.fn(), acceptOrgInvite: vi.fn() },
    ApiError,
  }
})

const invite: OrgInvitePublic = { org_name: 'Acme Corp', email: 'sam@acme.io', role: 'member' }

const signedInAs = (email: string): User => ({
  id: '2',
  email,
  name: 'Sam Okafor',
  default_org_name: null,
  default_logo_url: null,
  email_verified: true,
})

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <JoinPage />
    </MemoryRouter>,
  )
}

describe('JoinPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = null
    authState.loading = false
    vi.mocked(api.readOrgInvite).mockResolvedValue(invite)
  })

  it('names the organisation, the role and the invited address before asking for anything', async () => {
    // Finding out afterwards that the link was for another address is a wasted
    // account, so all three are on screen before any form is.
    renderAt('/join?token=abc')
    expect(await screen.findByRole('heading', { name: 'Join Acme Corp' })).toBeInTheDocument()
    expect(screen.getByText('a member')).toBeInTheDocument()
    expect(screen.getByText('sam@acme.io')).toBeInTheDocument()
  })

  it('sends a signed-out visitor to sign-up carrying the token', async () => {
    renderAt('/join?token=abc')
    const signUp = await screen.findByRole('link', { name: /create an account and join/i })
    expect(signUp).toHaveAttribute('href', '/register?invite=abc')
  })

  it('carries the token through sign-in for an account that already exists', async () => {
    // Without this the token is gone from the app entirely and the only way back
    // is finding the original email again.
    renderAt('/join?token=abc')
    const signIn = await screen.findByRole('link', { name: /already have an account/i })
    expect(signIn).toHaveAttribute('href', `/login?next=${encodeURIComponent('/join?token=abc')}`)
  })

  it('accepts for the right signed-in account and lands on the team', async () => {
    authState.user = signedInAs('sam@acme.io')
    const user = userEvent.setup()
    renderAt('/join?token=abc')

    await user.click(await screen.findByRole('button', { name: 'Accept invitation' }))
    await waitFor(() => expect(api.acceptOrgInvite).toHaveBeenCalledWith('abc'))
    expect(navigateMock).toHaveBeenCalledWith('/team')
  })

  it('refuses the wrong signed-in account instead of letting them try', async () => {
    authState.user = signedInAs('mallory@evil.io')
    renderAt('/join?token=abc')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /signed in as mallory@evil.io.*only works for sam@acme.io/i,
    )
    expect(screen.queryByRole('button', { name: 'Accept invitation' })).not.toBeInTheDocument()
  })

  it("shows the server's reason when accepting is refused", async () => {
    const { ApiError } = await import('../../api')
    authState.user = signedInAs('sam@acme.io')
    vi.mocked(api.acceptOrgInvite).mockRejectedValue(
      new ApiError(409, 'your current organisation still has questions or assessments;'),
    )
    const user = userEvent.setup()
    renderAt('/join?token=abc')

    await user.click(await screen.findByRole('button', { name: 'Accept invitation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/still has questions/)
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it('treats a dead link as one message, saying nothing about the organisation', async () => {
    const { ApiError } = await import('../../api')
    vi.mocked(api.readOrgInvite).mockRejectedValue(new ApiError(404, 'no longer valid.'))
    renderAt('/join?token=stale')

    expect(await screen.findByRole('heading', { name: /no longer works/i })).toBeInTheDocument()
    expect(screen.queryByText(/Acme/)).not.toBeInTheDocument()
  })

  it('treats a link with no token at all the same way', async () => {
    renderAt('/join')
    expect(await screen.findByRole('heading', { name: /no longer works/i })).toBeInTheDocument()
    expect(api.readOrgInvite).not.toHaveBeenCalled()
  })
})
