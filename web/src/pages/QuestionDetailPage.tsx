import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { badgeClass } from '../badges'
import type { Invite, QuestionOut, SubmissionRow } from '../types'

export function QuestionDetailPage() {
  const navigate = useNavigate()
  const { id } = useParams<{ id: string }>()
  const [question, setQuestion] = useState<QuestionOut | null>(null)
  const [invites, setInvites] = useState<Invite[]>([])
  const [submissions, setSubmissions] = useState<SubmissionRow[]>([])
  const [error, setError] = useState<string | null>(null)

  const [recipients, setRecipients] = useState('')
  const [creatingInvite, setCreatingInvite] = useState(false)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null)
  const [revokingToken, setRevokingToken] = useState<string | null>(null)
  const [revokeError, setRevokeError] = useState<{ token: string; message: string } | null>(null)

  useEffect(() => {
    if (!id) return
    api.getQuestion(id).then(setQuestion).catch(() => setError('Failed to load question'))
    api.listInvites(id).then(setInvites).catch(() => setError('Failed to load invites'))
    api
      .listSubmissions(id)
      .then(setSubmissions)
      .catch(() => setError('Failed to load submissions'))
  }, [id])

  async function handleCreateInvite(e: FormEvent) {
    e.preventDefault()
    if (!id) return
    setInviteError(null)
    setCreatingInvite(true)
    try {
      const recipientList = recipients
        .split(/[,\n]/)
        .map((r) => r.trim())
        .filter(Boolean)
      const invite = await api.createInvite(id, {
        recipients: recipientList.length > 0 ? recipientList : undefined,
      })
      setInvites((prev) => [invite, ...prev])
      setRecipients('')
    } catch (err) {
      setInviteError(err instanceof ApiError ? err.message : 'Failed to generate invite')
    } finally {
      setCreatingInvite(false)
    }
  }

  async function handleRevoke(token: string) {
    if (!id) return
    if (!window.confirm('Revoke this invite? The candidate link will stop working.')) return
    setRevokeError(null)
    setRevokingToken(token)
    try {
      const updated = await api.revokeInvite(id, token)
      setInvites((prev) => prev.map((inv) => (inv.token === token ? updated : inv)))
    } catch (err) {
      setRevokeError({
        token,
        message: err instanceof ApiError ? err.message : 'Failed to revoke invite',
      })
    } finally {
      setRevokingToken(null)
    }
  }

  async function copyUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      setCopiedUrl(url)
      setTimeout(() => setCopiedUrl(null), 2000)
    } catch {
      // clipboard API unavailable; ignore
    }
  }

  if (error) return <p className="form-error">{error}</p>
  if (!question) return <p className="page-loading">Loading…</p>

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>{question.title}</h1>
          <div className="sub">Created {new Date(question.created_at).toLocaleDateString()}</div>
        </div>
      </div>

      <div className="detail-grid">
        <div>
          <section className="card pad prose">
            <h2>Prompt</h2>
            <p className="pre-text">{question.prompt}</p>
            <h2>Constraints</h2>
            <p className="pre-text">{question.constraints}</p>
            {(question.example_input || question.example_output) && (
              <>
                <h2>Example</h2>
                {question.example_input && (
                  <div className="io">
                    <span className="io-label">Input</span>
                    <pre className="code">{question.example_input}</pre>
                  </div>
                )}
                {question.example_output && (
                  <div className="io">
                    <span className="io-label">Output</span>
                    <pre className="code">{question.example_output}</pre>
                  </div>
                )}
              </>
            )}
          </section>

          {invites.length > 0 && (
            <>
              <h2 className="sect-title">Invites</h2>
              <div className="card tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Link</th>
                      <th>Recipients</th>
                      <th>Status</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {invites.map((invite) => (
                      <tr key={invite.token}>
                        <td className="invite-url">{invite.url}</td>
                        <td>{invite.recipients.join(', ') || '—'}</td>
                        <td>
                          <span className={badgeClass(invite.status)}>{invite.status}</span>
                        </td>
                        <td>
                          <div className="row-actions">
                            <button
                              type="button"
                              className="btn sec sm"
                              onClick={() => copyUrl(invite.url)}
                            >
                              {copiedUrl === invite.url ? 'Copied!' : 'Copy link'}
                            </button>
                            {invite.status === 'active' && (
                              <button
                                type="button"
                                className="btn danger sm"
                                onClick={() => handleRevoke(invite.token)}
                                disabled={revokingToken === invite.token}
                              >
                                {revokingToken === invite.token ? 'Revoking…' : 'Revoke'}
                              </button>
                            )}
                            {revokeError?.token === invite.token && (
                              <p role="alert" className="form-error">
                                {revokeError.message}
                              </p>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          <h2 className="sect-title">
            Submissions
            {submissions.length > 0 && <span className="count">{submissions.length}</span>}
          </h2>
          {submissions.length === 0 ? (
            <p className="empty-state">No submissions yet. Share an invite link to get started.</p>
          ) : (
            <div className="card tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Candidate</th>
                    <th>Language</th>
                    <th>Status</th>
                    <th>Verdict</th>
                    <th>Score</th>
                    <th>Submitted</th>
                  </tr>
                </thead>
                <tbody>
                  {submissions.map((s) => (
                    <tr
                      key={s.submission_id}
                      className="clickable-row"
                      onClick={() => navigate(`/submissions/${s.submission_id}`)}
                      title="View submission detail"
                    >
                      <td>
                        <div className="t-title">{s.candidate_name}</div>
                        <div className="cellsub">{s.candidate_email}</div>
                      </td>
                      <td>{s.language}</td>
                      <td>
                        <span className={badgeClass(s.status)}>{s.status}</span>
                      </td>
                      <td>
                        {s.verdict ? (
                          <span className={badgeClass(s.verdict)}>{s.verdict}</span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="score">{s.score_pct != null ? `${s.score_pct}%` : '—'}</td>
                      <td>{s.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <aside className="side">
          <div className="card pad">
            <h3>Invite a candidate</h3>
            <form className="stack" onSubmit={handleCreateInvite}>
              <div className="field">
                <label htmlFor="recipients">Candidate emails (optional)</label>
                <textarea
                  id="recipients"
                  value={recipients}
                  onChange={(e) => setRecipients(e.target.value)}
                  placeholder="candidate@example.com"
                />
              </div>
              {inviteError && (
                <p role="alert" className="form-error">
                  {inviteError}
                </p>
              )}
              <button type="submit" className="btn accent block" disabled={creatingInvite}>
                {creatingInvite ? 'Generating…' : 'Generate coding test'}
              </button>
            </form>
            <p className="invite-hint muted">
              The link is emailed to each candidate. You can also copy it from the table.
            </p>
          </div>

          <div className="card pad">
            <h3>Grading</h3>
            <div className="kv">
              <span className="k">Pass threshold</span>
              <span className="num">{Math.round(question.pass_threshold * 100)}%</span>
            </div>
            <div className="kv">
              <span className="k">Time limit</span>
              <span className="num">{question.time_limit_s}s</span>
            </div>
            <div className="kv">
              <span className="k">Test cases</span>
              <span className="num">{question.test_cases.length}</span>
            </div>
            {question.required_complexity && (
              <div className="kv">
                <span className="k">Complexity</span>
                <span className="mono">{question.required_complexity}</span>
              </div>
            )}
          </div>
        </aside>
      </div>
    </div>
  )
}
