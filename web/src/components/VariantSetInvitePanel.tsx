import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api'
import { ExpiryField } from './ExpiryField'
import { InviteTable } from './InviteTable'
import { describeRecipients, parseRecipients } from '../invites'
import type { Invite, VariantOut } from '../types'

const AUTO = '__auto__'

export function VariantSetInvitePanel({
  setId,
  variants,
}: {
  setId: string
  variants: VariantOut[]
}) {
  const [invites, setInvites] = useState<Invite[]>([])
  const [raw, setRaw] = useState('')
  const [expiresAt, setExpiresAt] = useState<string | null>(null)
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const recipients = useMemo(() => parseRecipients(raw), [raw])

  useEffect(() => {
    let cancelled = false
    api
      .listVariantSetInvites(setId)
      .then((list) => {
        if (!cancelled) setInvites(list)
      })
      .catch(() => {
        /* the panel still works for sending; a load failure just shows no history */
      })
    return () => {
      cancelled = true
    }
  }, [setId])

  async function send() {
    if (recipients.length === 0) {
      setError('Add at least one candidate email.')
      return
    }
    setError(null)
    setSending(true)
    try {
      const picked: Record<string, string> = {}
      for (const [email, variantId] of Object.entries(overrides)) {
        if (variantId && variantId !== AUTO && recipients.includes(email)) picked[email] = variantId
      }
      const created = await api.createVariantSetInvites(setId, {
        recipients,
        overrides: picked,
        expires_at: expiresAt,
      })
      setInvites((prev) => [...created, ...prev])
      setRaw('')
      setOverrides({})
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to send invites.')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="card pad">
      <div className="card-title">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M17 2l4 4-4 4M3 11v-1a4 4 0 014-4h14M7 22l-4-4 4-4M21 13v1a4 4 0 01-4 4H3" />
        </svg>
        Invite candidates
      </div>
      <p className="draft-hint">
        One invite per candidate. Variants are handed out round-robin; pin a specific variant per
        candidate below if you want.
      </p>

      {error && <p className="form-error">{error}</p>}

      <div className="field">
        <label htmlFor="recipients">Candidate emails</label>
        <textarea
          id="recipients"
          rows={2}
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          placeholder="priya@example.com, marcus@example.com"
        />
        {describeRecipients(raw) && <p className="field-hint">{describeRecipients(raw)}</p>}
      </div>

      <ExpiryField value={expiresAt} onChange={setExpiresAt} idPrefix="vs" />

      {recipients.length > 0 && (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Variant</th>
              </tr>
            </thead>
            <tbody>
              {recipients.map((email) => (
                <tr key={email}>
                  <td>{email}</td>
                  <td>
                    <select
                      // N identical selects in a column need distinguishing for
                      // a screen reader — and for anyone querying them by role.
                      aria-label={`Variant for ${email}`}
                      value={overrides[email] ?? AUTO}
                      onChange={(e) =>
                        setOverrides((prev) => ({ ...prev, [email]: e.target.value }))
                      }
                    >
                      <option value={AUTO}>Auto (round-robin)</option>
                      {variants.map((v) => (
                        <option key={v.id} value={v.id}>
                          {v.variant_label ? `${v.variant_label} · ` : ''}
                          {v.title}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="form-actions">
        <button type="button" className="btn" onClick={send} disabled={sending}>
          {sending ? 'Sending…' : `Send ${recipients.length || ''} invite${recipients.length === 1 ? '' : 's'}`}
        </button>
      </div>

      {invites.length > 0 && (
        <>
          <h3 className="sect-title">Sent</h3>
          {/* No onRevoke: there is no revoke route for variant-set invites yet
              (P03, backend). The column stays absent rather than offering a
              control that can't work. */}
          <InviteTable invites={invites} showVariant />
        </>
      )}
    </div>
  )
}
