import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'
import { PRODUCT_NAME } from '../branding'
import type { OrgInvitePublic } from '../types'

/** What an organisation invitation link opens (X01).
 *
 *  Reachable signed in or signed out, because both are ordinary: a colleague
 *  who has never used the product, and one who registered separately last week
 *  and now wants the same library. The page names the organisation, the role and
 *  the address the invitation was sent to before asking for anything, because
 *  the invitation only works for that address and finding that out after
 *  creating an account is a wasted account.
 */
export function JoinPage() {
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const { user, loading } = useAuth()
  const navigate = useNavigate()

  const [invite, setInvite] = useState<OrgInvitePublic | null>(null)
  const [notFound, setNotFound] = useState(false)
  const [accepting, setAccepting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // A link with no token at all is dead in the same way a 404 is; derived
  // rather than stored, so the effect never sets state on its own body.
  const dead = notFound || !token

  useEffect(() => {
    if (!token) return
    let cancelled = false
    api
      .readOrgInvite(token)
      .then((found) => {
        if (!cancelled) setInvite(found)
      })
      .catch(() => {
        // Expired, already accepted and never-existed all answer 404 — one
        // message, saying nothing about which organisation it was for.
        if (!cancelled) setNotFound(true)
      })
    return () => {
      cancelled = true
    }
  }, [token])

  async function handleAccept() {
    setError(null)
    setAccepting(true)
    try {
      await api.acceptOrgInvite(token)
      navigate('/team')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to accept the invitation')
    } finally {
      setAccepting(false)
    }
  }

  const wrongAccount = user !== null && invite !== null && user.email !== invite.email

  return (
    <div className="auth">
      <div className="auth-card">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true" />
          <span className="brand-name">{PRODUCT_NAME}</span>
        </div>

        {dead && (
          <>
            <h1>This link no longer works</h1>
            <p className="auth-lead">
              An invitation expires after 7 days, and can only be accepted once. Ask whoever
              invited you to send a new one.
            </p>
            <div className="stack">
              <Link to="/login" className="btn sec block">
                Go to sign in
              </Link>
            </div>
          </>
        )}

        {!dead && invite === null && <p className="page-loading">Loading…</p>}

        {invite && (
          <>
            <h1>Join {invite.org_name}</h1>
            <p className="auth-lead">
              You&rsquo;ve been invited to <strong>{invite.org_name}</strong> as{' '}
              <strong>{invite.role === 'admin' ? 'an admin' : 'a member'}</strong>. Accepting gives
              you the organisation&rsquo;s question library, its assessments and its candidate
              submissions.
            </p>
            <dl className="account-kv">
              <dt>Invitation sent to</dt>
              <dd className="mono">{invite.email}</dd>
            </dl>

            {error && (
              <p role="alert" className="form-error">
                {error}
              </p>
            )}

            {loading ? (
              <p className="page-loading">Loading…</p>
            ) : wrongAccount ? (
              <>
                <p role="alert" className="form-error">
                  You&rsquo;re signed in as {user?.email}. This invitation only works for{' '}
                  {invite.email}.
                </p>
                <div className="stack">
                  <Link to="/dashboard" className="btn sec block">
                    Back to your workspace
                  </Link>
                </div>
              </>
            ) : user ? (
              <div className="stack">
                <button
                  type="button"
                  className="btn block"
                  disabled={accepting}
                  onClick={() => void handleAccept()}
                >
                  {accepting ? 'Joining…' : 'Accept invitation'}
                </button>
                <Link to="/dashboard" className="btn ghost block">
                  Not now
                </Link>
                <p className="field-hint">
                  You currently have an organisation of your own. Accepting gives it up — which is
                  refused if it holds any questions or assessments, or anyone else.
                </p>
              </div>
            ) : (
              <div className="stack">
                <Link to={`/register?invite=${encodeURIComponent(token)}`} className="btn block">
                  Create an account and join
                </Link>
                <Link
                  to={`/login?next=${encodeURIComponent(`/join?token=${token}`)}`}
                  className="btn sec block"
                >
                  I already have an account
                </Link>
                <p className="field-hint">
                  Sign in as {invite.email} — the invitation only works for that address.
                </p>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
