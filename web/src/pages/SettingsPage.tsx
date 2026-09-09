import { useState, type FormEvent } from 'react'
import { api, ApiError, setToken } from '../api'
import { useAuth } from '../auth/AuthContext'
import { BillingPanel } from '../components/BillingPanel'
import { PrivacyPanel } from '../components/PrivacyPanel'

export function SettingsPage() {
  const { user, refresh, logout } = useAuth()
  const [orgName, setOrgName] = useState(user?.default_org_name ?? '')
  const [logoUrl, setLogoUrl] = useState(user?.default_logo_url ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)

  const [resendSent, setResendSent] = useState(false)
  const [resendError, setResendError] = useState<string | null>(null)
  const [resending, setResending] = useState(false)

  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)
  const [pwChanged, setPwChanged] = useState(false)
  const [changing, setChanging] = useState(false)

  const [deletePw, setDeletePw] = useState('')
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  async function handleSave() {
    setError(null)
    setSaved(false)
    setSaving(true)
    try {
      await api.updateMe({
        default_org_name: orgName.trim() || null,
        default_logo_url: logoUrl.trim() || null,
      })
      await refresh()
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save settings')
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

  async function handleChangePassword(e: FormEvent) {
    e.preventDefault()
    setPwError(null)
    setPwChanged(false)
    if (newPw !== confirmPw) {
      setPwError("Passwords don't match.")
      return
    }
    setChanging(true)
    try {
      const result = await api.changePassword(currentPw, newPw)
      // The new token keeps this tab signed in; every other device is signed out.
      setToken(result.access_token)
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
      setPwChanged(true)
    } catch (err) {
      if (err instanceof ApiError) {
        setPwError(err.status === 403 ? 'Current password is incorrect.' : err.message)
      } else {
        setPwError('Failed to change password')
      }
    } finally {
      setChanging(false)
    }
  }

  async function handleDelete(e: FormEvent) {
    e.preventDefault()
    setDeleteError(null)
    setDeleting(true)
    try {
      await api.deleteAccount(deletePw)
      logout()
    } catch (err) {
      if (err instanceof ApiError) {
        setDeleteError(err.status === 403 ? 'Password is incorrect.' : err.message)
      } else {
        setDeleteError('Failed to delete account')
      }
      setDeleting(false)
    }
  }

  if (!user) return null

  return (
    <div className="wizard">
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <div className="sub">Your workspace defaults, plan and account security.</div>
        </div>
      </div>

      <h2 className="section-title">Workspace</h2>
      <div className="card pad">
        <div className="card-title">Default branding</div>
        <p className="draft-hint">
          Pre-fills the branding on every new assessment so you don&rsquo;t re-enter it each time.
          Candidates see it on their IDE header when they open the assessment. Leave blank to default
          to the generic &ldquo;Coding assessment&rdquo; header.
        </p>
        <div className="stack">
          <div className="grid2">
            <div className="field">
              <label htmlFor="default_org_name">Organization name</label>
              <input
                id="default_org_name"
                placeholder="e.g. Acme Corp"
                value={orgName}
                onChange={(e) => {
                  setOrgName(e.target.value)
                  setSaved(false)
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="default_logo_url">Logo URL</label>
              <input
                id="default_logo_url"
                placeholder="https://…"
                value={logoUrl}
                onChange={(e) => {
                  setLogoUrl(e.target.value)
                  setSaved(false)
                }}
              />
            </div>
          </div>
          {(orgName.trim() || logoUrl.trim()) && (
            <div className="ide-title-preview">
              {logoUrl.trim() && <img src={logoUrl.trim()} alt="" className="ide-brand-logo" />}
              <span>
                {orgName.trim() && `${orgName.trim()} — `}
                Coding assessment
              </span>
            </div>
          )}
        </div>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        {saved && <p className="form-success">Saved.</p>}
        <div className="card-actions">
          <button type="button" className="btn accent" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save defaults'}
          </button>
        </div>
      </div>

      <h2 className="section-title">Billing</h2>
      <BillingPanel />

      <PrivacyPanel />

      <h2 className="section-title">Account</h2>
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

      <h2 className="section-title">Security</h2>
      <form className="card pad" onSubmit={handleChangePassword}>
        <div className="card-title">Change password</div>
        {pwError && (
          <p role="alert" className="form-error">
            {pwError}
          </p>
        )}
        {pwChanged && (
          <p className="form-success">Password changed. Other devices have been signed out.</p>
        )}
        <div className="stack">
          <div className="grid2">
            <div className="field">
              <label htmlFor="cp-cur">Current password</label>
              <input
                id="cp-cur"
                type="password"
                value={currentPw}
                onChange={(e) => setCurrentPw(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            <div />
            <div className="field">
              <label htmlFor="cp-new">New password</label>
              <input
                id="cp-new"
                type="password"
                value={newPw}
                onChange={(e) => setNewPw(e.target.value)}
                autoComplete="new-password"
                minLength={12}
                required
              />
              <p className="field-hint">
                At least 12 characters. Passwords that appear in known breaches are refused.
              </p>
            </div>
            <div className="field">
              <label htmlFor="cp-new2">Confirm new password</label>
              <input
                id="cp-new2"
                type="password"
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                autoComplete="new-password"
                required
              />
            </div>
          </div>
        </div>
        <div className="card-actions">
          <button type="submit" className="btn" disabled={changing}>
            Change password
          </button>
          <span className="field-hint">Every other device is signed out.</span>
        </div>
      </form>

      <form className="card pad danger" onSubmit={handleDelete}>
        <div className="card-title">Delete account</div>
        {deleteError && (
          <p role="alert" className="form-error">
            {deleteError}
          </p>
        )}
        <p className="draft-hint">
          Deletes your login. What happens to the work depends on who else is in your
          organisation: if you are its last member, the questions, variant sets, assessments,
          invites and every candidate submission and result go with you, and candidates&rsquo;
          links stop working immediately. If colleagues remain, all of that stays with the
          organisation and only your account and your name against it are removed &mdash; and if
          you are its only admin, promote someone else first or this will be refused. This
          can&rsquo;t be undone.
        </p>
        <div className="grid2">
          <div className="field">
            <label htmlFor="del-pw">Confirm with your password</label>
            <input
              id="del-pw"
              type="password"
              value={deletePw}
              onChange={(e) => setDeletePw(e.target.value)}
              autoComplete="current-password"
              required
            />
          </div>
        </div>
        <div className="card-actions">
          <button type="submit" className="btn danger" disabled={!deletePw || deleting}>
            Delete my account
          </button>
          <span className="field-hint">Enabled once the password is filled in.</span>
        </div>
      </form>
    </div>
  )
}
