import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api'

const brand = (
  <div className="brand">
    <span className="brand-mark" aria-hidden="true" />
    <span className="brand-name">assess.dev</span>
  </div>
)

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sentTo, setSentTo] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.forgotPassword(email)
      setSentTo(email)
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError('Too many attempts, try again in a minute.')
      } else {
        setError(err instanceof ApiError ? err.message : 'Request failed')
      }
    } finally {
      setSubmitting(false)
    }
  }

  if (sentTo) {
    return (
      <div className="auth">
        <div className="auth-card">
          {brand}
          <div className="auth-mark good" aria-hidden="true">
            ✓
          </div>
          <h1>Check your inbox</h1>
          <p className="auth-lead">
            If <b>{sentTo}</b> has an account, a reset link is on its way. It works once and
            expires in an hour.
          </p>
          <p className="field-hint">
            Nothing arrived? Check spam, or{' '}
            <button type="button" className="btn-link" onClick={() => setSentTo(null)}>
              try again
            </button>
            .
          </p>
          <p className="auth-alt muted">
            <Link to="/login">Back to log in</Link>
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={handleSubmit}>
        {brand}
        <h1>Reset your password</h1>
        <p className="auth-lead">
          Enter the address you registered with and we'll email you a link to set a new password.
        </p>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="stack">
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn block" disabled={submitting}>
            {submitting ? 'Sending…' : 'Email me a reset link'}
          </button>
        </div>
        <p className="auth-alt muted">
          <Link to="/login">Back to log in</Link>
        </p>
      </form>
    </div>
  )
}
