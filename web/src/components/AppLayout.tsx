import { useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'

function crumbFor(pathname: string): string {
  if (pathname === '/dashboard') return 'Questions'
  if (pathname === '/questions/new') return 'New question'
  if (pathname.startsWith('/questions/')) return 'Question'
  if (pathname === '/assessments/new') return 'New assessment'
  if (pathname === '/assessments') return 'Assessments'
  if (pathname.startsWith('/assessments/')) return 'Assessment'
  if (pathname === '/variant-sets/new') return 'New variant set'
  if (pathname === '/variant-sets') return 'Variant sets'
  if (pathname.startsWith('/variant-sets/')) return 'Variant set'
  if (pathname === '/team') return 'Team'
  return ''
}

export function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth()
  const { pathname } = useLocation()
  // The unverified-email banner: hidden until the next page load once dismissed.
  const [dismissed, setDismissed] = useState(false)
  const [sent, setSent] = useState(false)
  const [resending, setResending] = useState(false)
  const [resendError, setResendError] = useState<string | null>(null)

  async function handleResend() {
    setResendError(null)
    setResending(true)
    try {
      await api.resendVerification()
      setSent(true)
    } catch (err) {
      setResendError(err instanceof ApiError ? err.message : 'Failed to resend the link')
    } finally {
      setResending(false)
    }
  }

  const showNotice = user && !user.email_verified && !dismissed

  return (
    <div className="app">
      <Sidebar />
      <div className="main">
        <header className="topbar">
          <div className="crumb">
            Workspace <span>/</span> <b>{crumbFor(pathname)}</b>
          </div>
          <div className="topbar-user">
            <button type="button" className="btn ghost sm" onClick={logout}>
              Log out
            </button>
          </div>
        </header>
        {showNotice &&
          (sent ? (
            <div className="notice sent" role="status">
              <span>
                <b>Sent.</b> Check {user.email} for the new link.
              </span>
              <span className="spacer" />
              <button
                type="button"
                className="btn ghost sm"
                aria-label="Hide"
                onClick={() => setDismissed(true)}
              >
                ✕
              </button>
            </div>
          ) : (
            <div className="notice" role="status">
              <span>
                <b>Confirm your email.</b> We sent a link to {user.email}. Until then, password
                resets can&rsquo;t reach you.
                {resendError && <> Couldn&rsquo;t resend: {resendError}</>}
              </span>
              <span className="spacer" />
              <button
                type="button"
                className="btn sec sm"
                onClick={handleResend}
                disabled={resending}
              >
                Resend link
              </button>
              <button
                type="button"
                className="btn ghost sm"
                aria-label="Hide for now"
                onClick={() => setDismissed(true)}
              >
                ✕
              </button>
            </div>
          ))}
        <div className="content">{children}</div>
      </div>
    </div>
  )
}
