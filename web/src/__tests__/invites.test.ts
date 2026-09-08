import { describe, expect, it } from 'vitest'
import { describeRecipients, inviteState, parseRecipients, toLocalInputValue } from '../invites'
import type { Invite } from '../types'

const invite = (overrides: Partial<Invite> = {}): Invite => ({
  token: 'tok',
  url: 'http://127.0.0.1:5173/t/tok',
  question_id: 'q',
  assessment_id: null,
  variant_set_id: null,
  variant_label: null,
  recipients: ['a@x.io'],
  expires_at: null,
  status: 'active',
  deliveries: [],
  ...overrides,
})

describe('parseRecipients', () => {
  it('accepts every separator people actually paste, and preserves order', () => {
    expect(parseRecipients('a@x.io, b@x.io;c@x.io\nd@x.io  e@x.io')).toEqual([
      'a@x.io',
      'b@x.io',
      'c@x.io',
      'd@x.io',
      'e@x.io',
    ])
  })

  it('lower-cases and de-duplicates, so one candidate never gets two links', () => {
    // Two of the three old parsers did neither, so the same paste behaved
    // differently depending on which screen you were on.
    expect(parseRecipients('Priya@Example.com, priya@example.com')).toEqual(['priya@example.com'])
  })

  it('is empty for whitespace, so an empty box never mints a link nobody can open', () => {
    expect(parseRecipients('  \n , ; ')).toEqual([])
  })
})

describe('describeRecipients', () => {
  it('says what a paste turned into, including what it dropped', () => {
    expect(describeRecipients('a@x.io, A@X.io, b@x.io')).toBe(
      '2 recipients · 1 duplicate dropped · lower-cased',
    )
  })

  it('is silent on an empty box rather than showing a zero', () => {
    expect(describeRecipients('')).toBeNull()
  })
})

describe('inviteState', () => {
  const now = new Date('2026-09-08T12:00:00Z')

  it('calls a past expiry expired, though the server still says active', () => {
    // The server stores only active/revoked and computes expiry per request, so
    // showing `status` verbatim would call a dead link live.
    const past = invite({ expires_at: '2026-09-01T00:00:00Z', status: 'active' })
    expect(inviteState(past, now)).toBe('expired')
  })

  it('keeps a future expiry active', () => {
    expect(inviteState(invite({ expires_at: '2026-10-01T00:00:00Z' }), now)).toBe('active')
  })

  it('lets revoked win over expiry — revoking is the deliberate act', () => {
    const both = invite({ status: 'revoked', expires_at: '2026-09-01T00:00:00Z' })
    expect(inviteState(both, now)).toBe('revoked')
  })

  it('treats a null expiry as never expiring', () => {
    expect(inviteState(invite(), now)).toBe('active')
  })
})

describe('toLocalInputValue', () => {
  it('renders local wall-clock time, not a UTC slice', () => {
    // `new Date(iso).toISOString().slice(0,16)` shifts the field by the viewer's
    // offset, so a 5pm expiry shows as something else east or west of UTC.
    const d = new Date('2026-09-08T15:30:00Z')
    const expected = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(
      d.getDate(),
    ).padStart(2, '0')}T${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(
      2,
      '0',
    )}`
    expect(toLocalInputValue(d)).toBe(expected)
  })
})
