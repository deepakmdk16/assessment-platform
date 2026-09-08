import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'
import { PRODUCT_NAME } from '../branding'
import type { OrgInvitePublic } from '../types'

/** Sign-up. Reached cold, or from an organisation invitation link (X01), in
 *  which case the address is fixed by the invitation and the new account lands
 *  in that organisation instead of founding one of its own. */
export function RegisterPage() {
  const [params] = useSearchParams()
  const inviteToken = params.get('invite') ?? ''
  const [invite, setInvite] = useState<OrgInvitePublic | null>(null)
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  useEffect(() => {
    if (!inviteToken) return
    let cancelled = false
    api
      .readOrgInvite(inviteToken)
      .then((found) => {
        if (cancelled) return
        setInvite(found)
        // Typing the address by hand is the one way to fail an invitation that
        // was otherwise going to work, so don't ask for it.
        setEmail(found.email)
      })
      .catch(() => {
        // A dead link shouldn't block an ordinary sign-up; it just stops being
        // an invited one, and the server refuses the token again if it is sent.
        if (!cancelled) setInvite(null)
      })
    return () => {
      cancelled = true
    }
  }, [inviteToken])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await api.register({
        name,
        email,
        password,
        ...(invite ? { org_invite_token: inviteToken } : {}),
      })
      await login(email, password)
      navigate(invite ? '/team' : '/dashboard')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Registration failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">{PRODUCT_NAME}</span>
        </div>
        <h1>Create your account</h1>
        {invite ? (
          <p className="auth-lead">
            Joining <strong>{invite.org_name}</strong> as{' '}
            <strong>{invite.role === 'admin' ? 'an admin' : 'a member'}</strong>. You&rsquo;ll share
            its question library, assessments and candidate submissions.
          </p>
        ) : (
          <p className="auth-lead">Author coding assessments and review graded submissions.</p>
        )}
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <div className="stack">
          <div className="field">
            <label htmlFor="name">Name</label>
            <input id="name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              readOnly={invite !== null}
              required
            />
            {invite && (
              <p className="field-hint">
                Fixed by the invitation — it only works for this address.
              </p>
            )}
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={12}
              required
            />
            <p className="field-hint">
              At least 12 characters. Passwords that appear in known breaches are refused.
            </p>
          </div>
          <button type="submit" className="btn block" disabled={submitting}>
            {submitting
              ? 'Creating account…'
              : invite
                ? 'Create account and join'
                : 'Create account'}
          </button>
        </div>
        <p className="auth-alt muted">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </form>
    </div>
  )
}
