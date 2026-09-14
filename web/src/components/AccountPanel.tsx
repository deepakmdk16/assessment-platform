/** Settings → Account: who you are signed in as, whether the address we have for
 *  you actually reaches you, and — since U08 — the form that lets you correct
 *  either one.
 *
 *  Lifted out of SettingsPage unchanged when Settings became one route per
 *  section (P3a); the edit form is the part P3b left out.
 *
 *  The address is deliberately NOT applied on save: the server mails a link to
 *  the new mailbox and the account moves only when that link is opened. Sign-in
 *  is by address and the way back from a wrong one is a reset mail sent to it,
 *  so applying a typo here would lock the account out of itself.
 */

import { useState, type FormEvent } from 'react'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'

export function AccountPanel() {
  const { user, refresh } = useAuth()
  const [name, setName] = useState(user?.name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [password, setPassword] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const [pendingEmail, setPendingEmail] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const [resendSent, setResendSent] = useState(false)
  const [resendError, setResendError] = useState<string | null>(null)
  const [resending, setResending] = useState(false)

  // Asking for the password only when the address is actually moving keeps a
  // name correction a one-field edit, and matches what the server enforces.
  const emailChanged = user !== null && email.trim().toLowerCase() !== user.email.toLowerCase()

  async function handleSave(e: FormEvent) {
    e.preventDefault()
    if (!user) return
    setSaveError(null)
    setSaved(null)
    setPendingEmail(null)
    const nextName = name.trim()
    if (!nextName) {
      setSaveError('Name cannot be empty.')
      return
    }
    setSaving(true)
    try {
      await api.updateMe({
        ...(nextName !== user.name ? { name: nextName } : {}),
        ...(emailChanged ? { email: email.trim(), password } : {}),
      })
      await refresh().catch(() => undefined)
      setPassword('')
      if (emailChanged) setPendingEmail(email.trim())
      else setSaved('Saved.')
    } catch (err) {
      if (err instanceof ApiError) {
        setSaveError(err.status === 403 ? 'Password is incorrect.' : err.message)
      } else {
        setSaveError('Failed to save your details')
      }
    } finally {
      setSaving(false)
    }
  }

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
    <>
      <form className="card pad" onSubmit={handleSave}>
        <div className="card-title">Your details</div>
        {saveError && (
          <p role="alert" className="form-error">
            {saveError}
          </p>
        )}
        {saved && <p className="form-success">{saved}</p>}
        {pendingEmail && (
          <p className="form-success">
            Check <b>{pendingEmail}</b> for a confirmation link. Your address stays{' '}
            <b>{user.email}</b> until you open it.
          </p>
        )}
        <div className="stack">
          <div className="grid2">
            <div className="field">
              <label htmlFor="acct-name">Name</label>
              <input
                id="acct-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
                required
              />
            </div>
            <div className="field">
              <label htmlFor="acct-email">Email</label>
              <input
                id="acct-email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                required
              />
              <p className="field-hint">
                {user.email_verified ? 'Confirmed. ' : 'Not confirmed yet. '}
                This is how you sign in, so a new address has to be confirmed from its
                own inbox before it takes effect.
              </p>
            </div>
            {emailChanged && (
              <div className="field">
                <label htmlFor="acct-pw">Current password</label>
                <input
                  id="acct-pw"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                />
                <p className="field-hint">Confirms it&rsquo;s you before your sign-in moves.</p>
              </div>
            )}
          </div>
        </div>
        <div className="card-actions">
          <button type="submit" className="btn" disabled={saving}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </form>

      <div className="card pad">
        <dl className="account-kv">
          <dt>Email status</dt>
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
            Signed in on this browser for up to 30 days. Changing your password signs out every
            other device.
          </dd>
        </dl>
        {resendError && (
          <p role="alert" className="form-error">
            {resendError}
          </p>
        )}
        {resendSent && <p className="form-success">Sent. Check {user.email} for the new link.</p>}
      </div>
    </>
  )
}
