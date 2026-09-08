import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { emailFromToken } from '../auth/tokenEmail'

const brand = (
  <div className="brand">
    <span className="brand-mark" aria-hidden="true" />
    <span className="brand-name">assess.dev</span>
  </div>
)

export function ResetPasswordPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  // Read once so a re-render can't lose it; it is only removed from the address
  // bar after it has been spent, so reloading a half-filled form still works.
  const [token] = useState(() => searchParams.get('token'))
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [outcome, setOutcome] = useState<'updated' | 'bad' | null>(null)

  if (!token || outcome === 'bad') {
    return (
      <div className="auth">
        <div className="auth-card">
          {brand}
          <div className="auth-mark bad" aria-hidden="true">
            !
          </div>
          <h1>This link doesn't work</h1>
          <p className="auth-lead">
            Reset links work once and expire after an hour. If you already used this one, just log
            in; otherwise request a fresh link.
          </p>
          <Link to="/forgot-password" className="btn block sec">
            Request a new link
          </Link>
          <p className="auth-alt muted">
            <Link to="/login">Back to log in</Link>
          </p>
        </div>
      </div>
    )
  }

  if (outcome === 'updated') {
    return (
      <div className="auth">
        <div className="auth-card">
          {brand}
          <div className="auth-mark good" aria-hidden="true">
            ✓
          </div>
          <h1>Password updated</h1>
          <p className="auth-lead">
            Your address is confirmed too, since you opened the link we mailed. Log in with the new
            password.
          </p>
          <Link to="/login" className="btn block">
            Log in
          </Link>
        </div>
      </div>
    )
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    if (password !== confirm) {
      setError("Passwords don't match.")
      return
    }
    setSubmitting(true)
    try {
      await api.resetPassword(token, password)
      setOutcome('updated')
      // Spent: take it out of the address bar so it doesn't linger in history.
      setSearchParams({}, { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setOutcome('bad')
      } else {
        setError(err instanceof ApiError ? err.message : 'Request failed')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const email = emailFromToken(token)
  return (
    <div className="auth">
      <form className="auth-card" onSubmit={handleSubmit}>
        {brand}
        <h1>Choose a new password</h1>
        <p className="auth-lead">
          {email && (
            <>
              For <b>{email}</b>.{' '}
            </>
          )}
          Setting it signs you out on every other device.
        </p>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="stack">
          <div className="field">
            <label htmlFor="new-password">New password</label>
            <input
              id="new-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              minLength={12}
              required
            />
            <p className="field-hint">
              At least 12 characters. Passwords that appear in known breaches are refused.
            </p>
          </div>
          <div className="field">
            <label htmlFor="confirm-password">Confirm new password</label>
            <input
              id="confirm-password"
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
          </div>
          <button type="submit" className="btn block" disabled={submitting}>
            {submitting ? 'Setting…' : 'Set new password'}
          </button>
        </div>
      </form>
    </div>
  )
}
