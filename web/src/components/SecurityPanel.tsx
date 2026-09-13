/** Settings → Security: change the password, or delete the account.
 *
 *  Lifted out of SettingsPage unchanged when Settings became one route per
 *  section (P3a). The two live together because both are confirmed with the
 *  current password and both sign devices out.
 */

import { useState, type FormEvent } from 'react'
import { api, ApiError, setToken } from '../api'
import { useAuth } from '../auth/AuthContext'

export function SecurityPanel() {
  const { logout } = useAuth()
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwError, setPwError] = useState<string | null>(null)
  const [pwChanged, setPwChanged] = useState(false)
  const [changing, setChanging] = useState(false)

  const [deletePw, setDeletePw] = useState('')
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

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

  return (
    <>
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
          Deletes your login. What happens to the work depends on who else is in your organisation:
          if you are its last member, the questions, variant sets, assessments, invites and every
          candidate submission and result go with you, and candidates&rsquo; links stop working
          immediately. If colleagues remain, all of that stays with the organisation and only your
          account and your name against it are removed &mdash; and if you are its only admin,
          promote someone else first or this will be refused. This can&rsquo;t be undone.
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
    </>
  )
}
