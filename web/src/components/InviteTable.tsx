import { useState } from 'react'
import { badgeClass } from '../badges'
import { inviteState, parseServerDate } from '../invites'
import type { Invite } from '../types'

/** One invite table for all three surfaces.
 *
 *  Question, assessment and variant-set invites had drifted into three tables
 *  with different columns — only the question one showed Status, none showed
 *  Expires, and only the variant-set one had a Variant column — so the same
 *  object told a different story depending on where you looked at it. */
export function InviteTable({
  invites,
  showVariant = false,
  showDeliveries = false,
  onRevoke,
  revokingToken,
  revokeError,
}: {
  invites: Invite[]
  /** Variant-set invites only: which variant this candidate was handed. */
  showVariant?: boolean
  /** Per-recipient delivery outcome (A4). Only the question invite flow returns
   *  `deliveries`, and losing it to unify the tables would be a regression, so
   *  the column is carried here rather than left behind. */
  showDeliveries?: boolean
  /** Omitted where the backend has no revoke route for this invite kind yet
   *  (assessment and variant-set invites) — the column simply doesn't render. */
  onRevoke?: (token: string) => void
  revokingToken?: string | null
  revokeError?: { token: string; message: string } | null
}) {
  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>{showDeliveries ? 'Recipients & delivery' : 'Candidate'}</th>
            {showVariant && <th>Variant</th>}
            <th>Status</th>
            <th>Expires</th>
            <th>Link</th>
            {onRevoke && <th />}
          </tr>
        </thead>
        <tbody>
          {invites.map((invite) => (
            <InviteRow
              key={invite.token}
              invite={invite}
              showVariant={showVariant}
              showDeliveries={showDeliveries}
              onRevoke={onRevoke}
              revoking={revokingToken === invite.token}
              error={revokeError?.token === invite.token ? revokeError.message : null}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function InviteRow({
  invite,
  showVariant,
  showDeliveries,
  onRevoke,
  revoking,
  error,
}: {
  invite: Invite
  showVariant: boolean
  showDeliveries: boolean
  onRevoke?: (token: string) => void
  revoking: boolean
  error: string | null
}) {
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const state = inviteState(invite)

  async function copy() {
    setCopyFailed(false)
    try {
      await navigator.clipboard.writeText(invite.url)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard access is denied outside a secure context and in some
      // browsers' permission states. Silence here looks like a dead button.
      setCopyFailed(true)
    }
  }

  return (
    <tr>
      <td>
        {showDeliveries && invite.deliveries.length > 0 ? (
          <ul className="recip-list">
            {invite.deliveries.map((d) => (
              <li className="recip" key={d.recipient}>
                <span className={`recip-dot ${d.sent ? 'ok' : 'fail'}`} />
                <span>{d.recipient}</span>
                {!d.sent && d.error && <span className="recip-why">— {d.error}</span>}
              </li>
            ))}
          </ul>
        ) : (
          invite.recipients.join(', ') || '—'
        )}
      </td>
      {showVariant && (
        <td>
          {invite.variant_label ? (
            <span className="chip chip-neutral">{invite.variant_label}</span>
          ) : (
            <span className="muted">—</span>
          )}
        </td>
      )}
      <td>
        <span className={badgeClass(state)}>{state}</span>
      </td>
      <td>
        {invite.expires_at ? (
          parseServerDate(invite.expires_at).toLocaleString()
        ) : (
          <span className="muted">Never</span>
        )}
      </td>
      {/* The URL stays visible and selectable, not just copyable: a clipboard
          write can be blocked, and an interviewer sometimes wants to read the
          link rather than paste it. */}
      <td className="invite-url">
        <div className="row-actions">
          <span className="mono">{invite.url}</span>
          <button type="button" className="btn sec sm" onClick={() => void copy()}>
            {copied ? 'Copied!' : 'Copy link'}
          </button>
          {copyFailed && (
            <p role="alert" className="form-error">
              Couldn’t copy — select the link and copy it by hand.
            </p>
          )}
        </div>
      </td>
      {onRevoke && (
        <td>
          <div className="row-actions">
            {state === 'active' && (
              <button
                type="button"
                className="btn danger sm"
                onClick={() => onRevoke(invite.token)}
                disabled={revoking}
              >
                {revoking ? 'Revoking…' : 'Revoke'}
              </button>
            )}
            {error && (
              <p role="alert" className="form-error">
                {error}
              </p>
            )}
          </div>
        </td>
      )}
    </tr>
  )
}
