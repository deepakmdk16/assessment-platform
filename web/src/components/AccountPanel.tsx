/** Settings → Account: who you are signed in as, and whether the address we
 *  have for you actually reaches you.
 *
 *  Lifted out of SettingsPage unchanged when Settings became one route per
 *  section (P3a).
 */

import { useState } from 'react'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'

export function AccountPanel() {
  const { user } = useAuth()
  const [resendSent, setResendSent] = useState(false)
  const [resendError, setResendError] = useState<string | null>(null)
  const [resending, setResending] = useState(false)

  async function handleResend() {
    setResendError(null)
    setResendSent(false)
    setResending(true)
    try {
      await api.resendVerification()
      setResendSent(true)
    } catch (err) {
      setResendError(err instanceof ApiError ? err.message : 'Failed to resend the link')
    } finally {
      setResending(false)
    }
  }

  if (!user) return null

  return (
    <div className="card pad">
      <dl className="account-kv">
        <dt>Name</dt>
        <dd>{user.name}</dd>
        <dt>Email</dt>
        <dd>
          {user.email}
          {user.email_verified ? (
            <span className="chip chip-good">Confirmed</span>
          ) : (
            <>
              <span className="chip chip-warn">Not confirmed</span>
              <button
                type="button"
                className="btn sec sm"
                onClick={handleResend}
                disabled={resending || resendSent}
              >
                Resend link
              </button>
            </>
          )}
        </dd>
        <dt>Sessions</dt>
        <dd className="muted">
          Signed in on this browser for up to 30 days. Changing your password signs out every other
          device.
        </dd>
      </dl>
      {resendError && (
        <p role="alert" className="form-error">
          {resendError}
        </p>
      )}
      {resendSent && <p className="form-success">Sent. Check {user.email} for the new link.</p>}
    </div>
  )
}
