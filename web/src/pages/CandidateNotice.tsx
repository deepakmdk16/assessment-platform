import type { ReactNode } from 'react'

/** A candidate's dead end: the sitting is over, the link is spent, or something
 *  went wrong. `supportEmail` (P2b) is the platform's own address — never an
 *  interviewer's — and is omitted when the deploy configures none. `children` is
 *  the optional feedback form, passed in only from the two post-submit screens. */
export function CandidateNotice({
  title,
  body,
  supportEmail,
  children,
}: {
  title: string
  body: string
  supportEmail?: string | null
  children?: ReactNode
}) {
  return (
    <div className="auth">
      <div className="auth-card notice-card">
        <h1>{title}</h1>
        <p className="muted">{body}</p>
        {supportEmail && (
          <p className="support-line">
            Questions about this assessment? Email{' '}
            <a href={`mailto:${supportEmail}`}>{supportEmail}</a>.
          </p>
        )}
        {children}
      </div>
    </div>
  )
}
