import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { TeamPage } from '../TeamPage'
import { api } from '../../api'
import type { Member, OrgInvite, Organization, User } from '../../types'

const authState = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../../auth/AuthContext', () => ({
  useAuth: () => ({ user: authState.user }),
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
      getOrg: vi.fn(),
      listMembers: vi.fn(),
      listOrgInvites: vi.fn(),
      renameOrg: vi.fn(),
      setMemberRole: vi.fn(),
      removeMember: vi.fn(),
      createOrg: vi.fn(),
      createOrgInvite: vi.fn(),
      revokeOrgInvite: vi.fn(),
    },
    ApiError,
  }
})

const ada: Member = {
  interviewer_id: 1,
  email: 'ada@acme.io',
  name: 'Ada Lovelace',
  role: 'admin',
  joined_at: '2026-09-04T09:00:00',
}
const sam: Member = {
  interviewer_id: 2,
  email: 'sam@acme.io',
  name: 'Sam Okafor',
  role: 'member',
  joined_at: '2026-09-06T09:00:00',
}

const org = (over: Partial<Organization> = {}): Organization => ({
  id: 1,
  name: 'Acme Corp',
  role: 'admin',
  member_count: 2,
  retention_days: null,
  ...over,
})

const pendingInvite = (over: Partial<OrgInvite> = {}): OrgInvite => ({
  id: 7,
  email: 'priya@acme.io',
  role: 'member',
  url: 'http://127.0.0.1:5173/join?token=abc',
  expires_at: '2026-09-15T09:14:00',
  accepted_at: null,
  sent: true,
  error: null,
  ...over,
})

function setUp(
  overrides: {
    org?: Organization
    members?: Member[]
    invites?: OrgInvite[]
    self?: number
  } = {},
) {
  authState.user = {
    id: String(overrides.self ?? 1),
    email: 'ada@acme.io',
    name: 'Ada Lovelace',
    default_org_name: null,
    default_logo_url: null,
    email_verified: true,
  }
  vi.mocked(api.getOrg).mockResolvedValue(overrides.org ?? org())
  vi.mocked(api.listMembers).mockResolvedValue(overrides.members ?? [ada, sam])
  vi.mocked(api.listOrgInvites).mockResolvedValue(overrides.invites ?? [])
}

describe('TeamPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('shows the roster with each person and their role', async () => {
    setUp()
    render(<TeamPage />)
    expect(await screen.findByText('Ada Lovelace')).toBeInTheDocument()
    expect(screen.getByText('sam@acme.io')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Acme Corp')).toBeInTheDocument()
  })

  it('offers a member none of the admin controls', async () => {
    // Not offered-then-refused: a plain member gets a read-only page, so no
    // click can come back 403.
    setUp({ org: org({ role: 'member' }), self: 2 })
    render(<TeamPage />)
    await screen.findByText('Ada Lovelace')

    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    // And it never asks the server for the admin-only invitation list.
    expect(api.listOrgInvites).not.toHaveBeenCalled()
  })

  it('locks the only admin’s role control and says why', async () => {
    setUp({ members: [ada] })
    render(<TeamPage />)
    const select = await screen.findByLabelText('Role for Ada Lovelace')
    expect(select).toBeDisabled()
    expect(screen.getByText(/only admin/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
  })

  it('confirms before removing someone, and does nothing if declined', async () => {
    setUp()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    render(<TeamPage />)
    await screen.findByText('Sam Okafor')

    await user.click(screen.getByRole('button', { name: 'Remove' }))
    expect(window.confirm).toHaveBeenCalled()
    expect(api.removeMember).not.toHaveBeenCalled()
  })

  it('warns differently when the admin is removing themselves', async () => {
    setUp({ members: [ada, { ...sam, role: 'admin' }], self: 1 })
    const user = userEvent.setup()
    render(<TeamPage />)
    await screen.findByText('Ada Lovelace')

    const row = screen.getByText('ada@acme.io').closest('tr')
    await user.click(within(row as HTMLElement).getByRole('button', { name: 'Remove' }))
    expect(vi.mocked(window.confirm).mock.calls[0][0]).toMatch(/Remove yourself/)
    await waitFor(() => expect(api.removeMember).toHaveBeenCalledWith(1))
  })

  it('sends an invitation and shows it as pending', async () => {
    setUp()
    vi.mocked(api.createOrgInvite).mockResolvedValue(pendingInvite())
    const user = userEvent.setup()
    render(<TeamPage />)
    await screen.findByText('Sam Okafor')

    await user.type(screen.getByLabelText('Email'), 'priya@acme.io')
    await user.click(screen.getByRole('button', { name: 'Send invitation' }))

    await waitFor(() => expect(api.createOrgInvite).toHaveBeenCalledWith('priya@acme.io', 'member'))
    expect(await screen.findByText(/Invitation sent to priya@acme.io/)).toBeInTheDocument()
    expect(screen.getByText('http://127.0.0.1:5173/join?token=abc')).toBeInTheDocument()
  })

  it('says so when the invitation could not be emailed', async () => {
    // Silence here leaves an admin waiting for someone who was never written to.
    setUp()
    vi.mocked(api.createOrgInvite).mockResolvedValue(
      pendingInvite({ sent: false, error: 'mailbox unavailable' }),
    )
    const user = userEvent.setup()
    render(<TeamPage />)
    await screen.findByText('Sam Okafor')

    await user.type(screen.getByLabelText('Email'), 'priya@acme.io')
    await user.click(screen.getByRole('button', { name: 'Send invitation' }))

    const alert = await screen.findByText(/Couldn’t email priya@acme.io/)
    expect(alert).toHaveTextContent('mailbox unavailable')
    expect(alert).toHaveTextContent(/copy its link below/i)
  })

  it('surfaces a refused role change on the row it came from', async () => {
    // The client already withholds the one refusal it can predict (the last
    // admin), so what has to work here is the general case: whatever else the
    // server says lands on the row the click came from, not in a global banner
    // that leaves you guessing which person it was about.
    const { ApiError } = await import('../../api')
    setUp({ members: [ada, sam] })
    vi.mocked(api.setMemberRole).mockRejectedValue(new ApiError(409, 'no such member.'))
    const user = userEvent.setup()
    render(<TeamPage />)
    await screen.findByText('Sam Okafor')

    await user.selectOptions(screen.getByLabelText('Role for Sam Okafor'), 'admin')
    const samRow = screen.getByText('sam@acme.io').closest('tr') as HTMLElement
    expect(await within(samRow).findByRole('alert')).toHaveTextContent('no such member.')
    const adaRow = screen.getByText('ada@acme.io').closest('tr') as HTMLElement
    expect(within(adaRow).queryByRole('alert')).not.toBeInTheDocument()
  })

  it('offers a way back to an account that was removed from its organisation', async () => {
    // Reachable and otherwise a dead end: every scoped route answers 403, so
    // without this the page would only report the refusal.
    const { ApiError } = await import('../../api')
    setUp()
    vi.mocked(api.getOrg).mockRejectedValueOnce(
      new ApiError(403, 'account belongs to no organisation.'),
    )
    vi.mocked(api.createOrg).mockResolvedValue(org({ name: 'Sam Consulting', member_count: 1 }))
    const user = userEvent.setup()
    render(<TeamPage />)

    await screen.findByText(/don’t belong to an organisation/i)
    await user.type(screen.getByLabelText('Organisation name'), 'Sam Consulting')
    await user.click(screen.getByRole('button', { name: 'Create organisation' }))

    await waitFor(() => expect(api.createOrg).toHaveBeenCalledWith('Sam Consulting'))
    // Refetched, so the roster arrives with it rather than an empty organisation.
    await waitFor(() => expect(screen.getByText('Ada Lovelace')).toBeInTheDocument())
    expect(screen.queryByText(/don’t belong to an organisation/i)).not.toBeInTheDocument()
  })

  it('replaces the pending row when the same address is re-invited', async () => {
    // The server drops the superseded invitation, so leaving it on screen shows
    // two links for one seat — and the older one's Revoke 404s.
    setUp({ invites: [pendingInvite()] })
    vi.mocked(api.createOrgInvite).mockResolvedValue(
      pendingInvite({ id: 8, url: 'http://127.0.0.1:5173/join?token=xyz' }),
    )
    const user = userEvent.setup()
    render(<TeamPage />)
    await screen.findByText('priya@acme.io')

    await user.type(screen.getByLabelText('Email'), 'priya@acme.io')
    await user.click(screen.getByRole('button', { name: 'Send invitation' }))

    await waitFor(() =>
      expect(screen.getByText('http://127.0.0.1:5173/join?token=xyz')).toBeInTheDocument(),
    )
    expect(screen.queryByText('http://127.0.0.1:5173/join?token=abc')).not.toBeInTheDocument()
    expect(screen.getAllByText('priya@acme.io')).toHaveLength(1)
  })

  it('reseeds the rename field when a reload brings a different name', async () => {
    // Otherwise the input keeps its mount-time value and Save silently reverts
    // whatever rename arrived in between.
    setUp()
    const user = userEvent.setup()
    render(<TeamPage />)
    await screen.findByDisplayValue('Acme Corp')

    vi.mocked(api.getOrg).mockResolvedValue(org({ name: 'Acme Ltd' }))
    await user.click(screen.getByRole('button', { name: 'Remove' }))

    await waitFor(() => expect(screen.getByLabelText('Organisation name')).toHaveValue('Acme Ltd'))
  })

  it('revokes a pending invitation after confirming', async () => {
    setUp({ invites: [pendingInvite()] })
    const user = userEvent.setup()
    render(<TeamPage />)
    await screen.findByText('priya@acme.io')

    await user.click(screen.getByRole('button', { name: 'Revoke' }))
    await waitFor(() => expect(api.revokeOrgInvite).toHaveBeenCalledWith(7))
    await waitFor(() => expect(screen.queryByText('priya@acme.io')).not.toBeInTheDocument())
  })
})
