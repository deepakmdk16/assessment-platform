import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PrivacyPanel } from '../PrivacyPanel'
import { api } from '../../api'
import type { CandidateErasure, Organization } from '../../types'

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    api: { getOrg: vi.fn(), setRetention: vi.fn(), eraseCandidate: vi.fn() },
    ApiError,
  }
})

function org(over: Partial<Organization> = {}): Organization {
  return { id: 1, name: 'Acme', role: 'admin', member_count: 2, retention_days: null, ...over }
}

function erasure(over: Partial<CandidateErasure> = {}): CandidateErasure {
  return {
    candidate_email: 'jane@example.com',
    erased: true,
    submissions: 3,
    results: 3,
    attempts: 1,
    slot_variants: 0,
    integrity_events: 7,
    drafts_deleted: 2,
    invites_amended: 1,
    ...over,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(api.getOrg).mockResolvedValue(org())
  vi.mocked(api.setRetention).mockResolvedValue(org())
  vi.mocked(api.eraseCandidate).mockResolvedValue(erasure())
})

describe('retention', () => {
  it('opens on "keep until deleted" when no window is configured', async () => {
    render(<PrivacyPanel />)
    const keep = await screen.findByLabelText(/keep until deleted/i)
    expect(keep).toBeChecked()
    // The days input only exists once a window is actually chosen.
    expect(screen.queryByLabelText(/retention period in days/i)).not.toBeInTheDocument()
  })

  it('shows the configured window when the organisation has one', async () => {
    vi.mocked(api.getOrg).mockResolvedValue(org({ retention_days: 90 }))
    render(<PrivacyPanel />)
    expect(await screen.findByLabelText(/retention period in days/i)).toHaveValue(90)
  })

  it('sends null to turn the policy off, not 0', async () => {
    vi.mocked(api.getOrg).mockResolvedValue(org({ retention_days: 90 }))
    render(<PrivacyPanel />)
    await userEvent.click(await screen.findByLabelText(/keep until deleted/i))
    await userEvent.click(screen.getByRole('button', { name: /save retention policy/i }))
    await waitFor(() => expect(api.setRetention).toHaveBeenCalledWith(null))
  })

  it('saves the chosen window', async () => {
    render(<PrivacyPanel />)
    await userEvent.click(await screen.findByLabelText(/delete automatically/i))
    const days = screen.getByLabelText(/retention period in days/i)
    await userEvent.clear(days)
    await userEvent.type(days, '30')
    await userEvent.click(screen.getByRole('button', { name: /save retention policy/i }))
    await waitFor(() => expect(api.setRetention).toHaveBeenCalledWith(30))
  })

  it('refuses a window of zero before the round trip', async () => {
    render(<PrivacyPanel />)
    await userEvent.click(await screen.findByLabelText(/delete automatically/i))
    const days = screen.getByLabelText(/retention period in days/i)
    await userEvent.clear(days)
    await userEvent.type(days, '0')
    await userEvent.click(screen.getByRole('button', { name: /save retention policy/i }))
    expect(await screen.findByRole('alert')).toHaveTextContent(/between 1 and 3650/i)
    expect(api.setRetention).not.toHaveBeenCalled()
  })

  it('warns that turning a window on reaches sittings already held', async () => {
    render(<PrivacyPanel />)
    await userEvent.click(await screen.findByLabelText(/delete automatically/i))
    expect(screen.getByRole('status')).toHaveTextContent(/sittings you already hold/i)
  })
})

describe('erasure', () => {
  it('takes two deliberate presses', async () => {
    render(<PrivacyPanel />)
    await userEvent.type(
      await screen.findByLabelText(/candidate email address/i),
      'jane@example.com',
    )
    await userEvent.click(screen.getByRole('button', { name: /erase candidate data/i }))
    // First press only arms it.
    expect(api.eraseCandidate).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent(/press again to confirm/i)

    await userEvent.click(screen.getByRole('button', { name: /yes, erase permanently/i }))
    await waitFor(() => expect(api.eraseCandidate).toHaveBeenCalledWith('jane@example.com'))
  })

  it('editing the address disarms the confirmation', async () => {
    render(<PrivacyPanel />)
    const field = await screen.findByLabelText(/candidate email address/i)
    await userEvent.type(field, 'jane@example.com')
    await userEvent.click(screen.getByRole('button', { name: /erase candidate data/i }))
    await userEvent.type(field, 'x')
    expect(screen.getByRole('button', { name: /erase candidate data/i })).toBeInTheDocument()
  })

  it('reports what was destroyed', async () => {
    render(<PrivacyPanel />)
    await userEvent.type(
      await screen.findByLabelText(/candidate email address/i),
      'jane@example.com',
    )
    await userEvent.click(screen.getByRole('button', { name: /erase candidate data/i }))
    await userEvent.click(screen.getByRole('button', { name: /yes, erase permanently/i }))

    const receipt = await screen.findByRole('status')
    expect(receipt).toHaveTextContent(/erased jane@example.com/i)
    expect(receipt).toHaveTextContent(/3\s*submissions/i)
    expect(receipt).toHaveTextContent(/7\s*integrity signals/i)
  })

  it('says plainly when an address held nothing', async () => {
    // The distinction the counts exist for: a silent success and "there was
    // nothing here" must not look the same to whoever answers the request.
    vi.mocked(api.eraseCandidate).mockResolvedValue(
      erasure({
        erased: false,
        submissions: 0,
        results: 0,
        attempts: 0,
        integrity_events: 0,
        drafts_deleted: 0,
        invites_amended: 0,
      }),
    )
    render(<PrivacyPanel />)
    await userEvent.type(
      await screen.findByLabelText(/candidate email address/i),
      'nobody@example.com',
    )
    await userEvent.click(screen.getByRole('button', { name: /erase candidate data/i }))
    await userEvent.click(screen.getByRole('button', { name: /yes, erase permanently/i }))
    expect(await screen.findByRole('status')).toHaveTextContent(/nothing was held/i)
  })
})

it('is hidden entirely from a plain member', async () => {
  vi.mocked(api.getOrg).mockResolvedValue(org({ role: 'member' }))
  const { container } = render(<PrivacyPanel />)
  await waitFor(() => expect(container).toBeEmptyDOMElement())
})
