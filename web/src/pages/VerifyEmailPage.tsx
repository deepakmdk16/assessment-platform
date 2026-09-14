import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'
import { emailFromToken } from '../auth/tokenEmail'
import { PRODUCT_NAME } from '../branding'

const brand = (
  <div className="brand">
    <span className="brand-mark" aria-hidden="true" />
    <span className="brand-name">{PRODUCT_NAME}</span>
  </div>
)

/** Spends an emailed address link. Two kinds land here: the sign-up
 *  confirmation, and a change of sign-in address (U08) routed at
 *  `/confirm-email`. Same states, same failure handling — only which endpoint is
 *  called, which claim names the address, and the wording differ. */
export function VerifyEmailPage({ change = false }: { change?: boolean }) {
  const [searchParams, setSearchParams] = useSearchParams()
  // Read once so the link keeps working across a re-render; it is only removed
  // from the address bar after it has been spent (see confirm()).
  const [token] = useState(() => searchParams.get('token'))
  const { user, loading, refresh } = useAuth()
  // The token names the account being confirmed, which need not be the one
  // signed in on this browser.
  const email = token ? emailFromToken(token, change ? 'new' : 'email') : null
  const [status, setStatus] = useState<'pending' | 'confirmed' | 'bad' | 'failed'>(
    token ? 'pending' : 'bad',
  )
  const started = useRef(false)

  const confirm = useCallback(async () => {
    if (!token) return
    setStatus('pending')
    try {
      await (change ? api.confirmEmailChange(token) : api.verifyEmail(token))
      if (user) await refresh().catch(() => undefined)
      setStatus('confirmed')
    } catch (err) {
      // Only the server calling the link invalid means it is dead. A 500, an
      // offline browser or a CORS failure must not tell the user their link
      // expired — that one is retryable, so the token stays in the URL too.
      setStatus(err instanceof ApiError && err.status === 400 ? 'bad' : 'failed')
      return
    }
    // Spent: take it out of the address bar so it doesn't linger in history.
    setSearchParams({}, { replace: true })
  }, [token, user, refresh, setSearchParams, change])

  useEffect(() => {
    // Wait for the session to settle so a signed-in user is refreshed after confirming
    // (the banner keys off user.email_verified); the ref keeps StrictMode to one POST.
    if (!token || loading || started.current) return
    started.current = true
    void confirm()
  }, [token, loading, confirm])

  return (
    <div className="auth">
      <div className="auth-card">
        {brand}
        {status === 'pending' && <p className="auth-lead">Confirming…</p>}
        {status === 'confirmed' && (
          <>
            <div className="auth-mark good" aria-hidden="true">
              ✓
            </div>
            <h1>{change ? 'Email address changed' : 'Email confirmed'}</h1>
            <p className="auth-lead">
              {email ? (
                <>
                  <b>{email}</b> is
                </>
              ) : (
                'Your address is'
              )}{' '}
              {change
                ? 'now the address you sign in with.'
                : 'now confirmed for your account.'}
            </p>
            <Link to={user ? '/dashboard' : '/login'} className="btn block">
              {user ? 'Go to your workspace' : 'Log in'}
            </Link>
          </>
        )}
        {status === 'failed' && (
          <>
            <div className="auth-mark bad" aria-hidden="true">
              !
            </div>
            <h1>Couldn&rsquo;t confirm right now</h1>
            <p className="auth-lead">
              Something went wrong on our side. Your link is still good — try again.
            </p>
            <button type="button" className="btn block" onClick={() => void confirm()}>
              Try again
            </button>
          </>
        )}
        {status === 'bad' && (
          <>
            <div className="auth-mark bad" aria-hidden="true">
              !
            </div>
            <h1>This link doesn't work</h1>
            <p className="auth-lead">
              {change
                ? 'Address links expire after three days, and are void once the account’s address changes by any other route. Log in and ask for the change again from Settings.'
                : 'Confirmation links expire after three days. Log in and send yourself a new one from the banner or Settings.'}
            </p>
            <Link to="/login" className="btn block sec">
              Log in
            </Link>
          </>
        )}
      </div>
    </div>
  )
}
