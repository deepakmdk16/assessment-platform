import { render, screen, within } from '@testing-library/react'
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
    // Per address: who, and whether it arrived.
    expect(screen.getByText('ok@x.io')).toBeInTheDocument()
    expect(screen.getByText('Sent')).toBeInTheDocument()
    expect(screen.getByText('Not sent')).toBeInTheDocument()
  })

  it('states a delivery failure once, under the invite, in words (U09)', () => {
    // The raw SMTP repr used to wrap inside the Recipients cell once per
    // recipient, squeezing Status/Expires/Link into strips and clipping the
    // Copy link button off the right edge.
    const raw =
      "(530, b'5.7.0 Authentication Required. For more information, go to https://support.google.com/mail/?p=WantAuthError g4-2002 - gsmtp', 'sender@gmail.com')"
    render(
      <InviteTable
        showDeliveries
        invites={[
          invite({
            deliveries: [
              { recipient: 'a@x.io', sent: false, error: raw },
              { recipient: 'b@x.io', sent: false, error: raw },
            ],
          }),
        ]}
      />,
    )

    expect(screen.getByText('2 of 2 not delivered')).toBeInTheDocument()
    expect(screen.getByText(/SMTP_PASSWORD is missing or wrong/)).toBeInTheDocument()
    // Said once for the invite, not once per recipient, and never raw.
    expect(screen.queryByText((t) => t.includes('WantAuthError'))).not.toBeInTheDocument()
    expect(screen.getByText(/still valid if you send it yourself/i)).toBeInTheDocument()
  })

  it('says nothing extra when every recipient got the mail', () => {
    render(
      <InviteTable
        showDeliveries
        invites={[invite({ deliveries: [{ recipient: 'ok@x.io', sent: true, error: null }] })]}
      />,
    )
    expect(screen.queryByText(/not delivered/i)).not.toBeInTheDocument()
  })

  it('leads the link cell with the action, so content cannot clip it', () => {
    render(<InviteTable invites={[invite({ url: 'http://127.0.0.1:5173/t/' + 'a'.repeat(64) })]} />)
    const cell = screen.getByRole('button', { name: /copy link/i }).closest('td')
    expect(cell).not.toBeNull()
    // The whole URL is still there to select and still readable on hover.
    expect(within(cell as HTMLElement).getByTitle(/\/t\/a+$/)).toBeInTheDocument()
  })
})
