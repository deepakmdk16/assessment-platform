import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { InviteTable } from '../InviteTable'
import type { Invite } from '../../types'

const invite = (overrides: Partial<Invite> = {}): Invite => ({
  token: 'tok1',
  url: 'http://127.0.0.1:5173/t/tok1',
  question_id: 'q',
  assessment_id: null,
  variant_set_id: null,
  variant_label: null,
  recipients: ['priya@example.com'],
  expires_at: null,
  status: 'active',
  deliveries: [],
  ...overrides,
})

describe('InviteTable', () => {
  it('shows an expired link as expired even though the server says active', async () => {
    render(<InviteTable invites={[invite({ expires_at: '2020-01-01T00:00:00Z' })]} />)
    expect(screen.getByText('expired')).toBeInTheDocument()
    expect(screen.queryByText('active')).not.toBeInTheDocument()
  })

  it('offers no revoke on an expired or revoked link', () => {
    const onRevoke = vi.fn()
    render(
      <InviteTable invites={[invite({ status: 'revoked' })]} onRevoke={onRevoke} />,
    )
    expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument()
  })

  it('omits the revoke column entirely where there is no revoke route', () => {
    // Assessment and variant-set invites have none yet, so the column must be
    // absent rather than offering a control that cannot work.
    render(<InviteTable invites={[invite()]} />)
    expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument()
  })

  it('confirms a copy, and says so when the clipboard refuses', async () => {
    const user = userEvent.setup()
    const writeText = vi.fn().mockRejectedValue(new Error('denied'))
    // navigator.clipboard is getter-only in jsdom, so define rather than assign.
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })

    render(<InviteTable invites={[invite()]} />)
    await user.click(screen.getByRole('button', { name: /copy link/i }))

    // Silence here is what made the old button look dead.
    expect(await screen.findByRole('alert')).toHaveTextContent(/couldn.t copy/i)
  })

  it('keeps the per-recipient delivery detail when asked for it', () => {
    render(
      <InviteTable
        showDeliveries
        invites={[
          invite({
            deliveries: [
              { recipient: 'ok@x.io', sent: true, error: null },
              { recipient: 'bad@x.io', sent: false, error: 'mailbox full' },
            ],
          }),
        ]}
      />,
    )
    expect(screen.getByText('ok@x.io')).toBeInTheDocument()
    expect(screen.getByText(/mailbox full/)).toBeInTheDocument()
  })
})
