/** Shared invite helpers.
 *
 *  Three screens create invites and each had grown its own recipient parser with
 *  different semantics — one split on whitespace/comma/semicolon and lower-cased
 *  and de-duplicated, the other two split on comma/newline only and did neither.
 *  So the same pasted list produced different invites depending on which page you
 *  were on, and pasting an address twice in two different cases sent that
 *  candidate two links. One parser, used everywhere.
 */

import type { Invite } from './types'

/** Split a pasted list into normalised, unique addresses, in the order given.
 *
 *  Accepts commas, semicolons and any whitespace (including newlines), because
 *  that is what people actually paste out of a spreadsheet or a mail client.
 *  Lower-cases, since an invite is matched to the address that opens it and
 *  `Priya@x.io` and `priya@x.io` are one candidate, not two. */
export function parseRecipients(raw: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const token of raw.split(/[\s,;]+/)) {
    const email = token.trim().toLowerCase()
    if (email && !seen.has(email)) {
      seen.add(email)
      out.push(email)
    }
  }
  return out
}

/** What a paste turned into, for the hint under the field. Silence here is how
 *  someone ends up wondering why they invited four people and got three. */
export function describeRecipients(raw: string): string | null {
  const parsed = parseRecipients(raw)
  if (parsed.length === 0) return null
  const rawCount = raw.split(/[\s,;]+/).filter((t) => t.trim()).length
  const dropped = rawCount - parsed.length
  const people = `${parsed.length} recipient${parsed.length === 1 ? '' : 's'}`
  return dropped > 0
    ? `${people} · ${dropped} duplicate${dropped === 1 ? '' : 's'} dropped · lower-cased`
    : `${people} · lower-cased`
}

/** Parse a datetime the API returned.
 *
 *  Every timestamp column is timezone-naive (STATUS P14), so the API serialises
 *  UTC instants with no offset — "2026-09-15T08:45:16". `new Date()` reads an
 *  offset-less string as LOCAL time, which silently shifts every comparison and
 *  every rendered time by the viewer's offset: in UTC+5:30 an invite reads as
 *  expired five and a half hours before it is, and Revoke disappears from a link
 *  the server still honours.
 *
 *  Appending 'Z' when there is no offset makes the client agree with the server.
 *  Harmless once P14 lands and the API starts emitting aware datetimes. */
export function parseServerDate(value: string): Date {
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : value + 'Z')
}

export type InviteState = 'active' | 'revoked' | 'expired'

/** The invite's effective state.
 *
 *  Derived rather than read straight off `status`: the server stores only
 *  `active` and `revoked` and computes expiry per request, so a link whose
 *  `expires_at` has passed still arrives here labelled `active`. Showing that
 *  verbatim would tell an interviewer a dead link is live. */
export function inviteState(invite: Invite, now: Date = new Date()): InviteState {
  if (invite.status === 'revoked') return 'revoked'
  if (invite.expires_at && parseServerDate(invite.expires_at).getTime() <= now.getTime())
    return 'expired'
  return 'active'
}

/** `datetime-local` wants `YYYY-MM-DDTHH:mm` in local time, and an ISO string
 *  from the API is UTC — so the naive `.slice(0, 16)` shifts the value by the
 *  viewer's offset. */
export function toLocalInputValue(date: Date): string {
  const offsetMs = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offsetMs).toISOString().slice(0, 16)
}

/** Presets for the expiry field. `null` means the link never expires, which is
 *  the current behaviour of every invite the product has ever sent. */
export const EXPIRY_PRESETS: { label: string; days: number | null }[] = [
  { label: 'Never', days: null },
  { label: '24 hours', days: 1 },
  { label: '7 days', days: 7 },
  { label: '30 days', days: 30 },
]

export function expiryFromDays(days: number, now: Date = new Date()): Date {
  return new Date(now.getTime() + days * 86_400_000)
}
