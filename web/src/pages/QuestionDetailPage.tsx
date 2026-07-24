import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { badgeClass, difficultyClass } from '../badges'
import { Pager } from '../components/Pager'
import type { Invite, InviteDelivery, QuestionOut, SubmissionRow } from '../types'

const SUB_PAGE_SIZE = 100

export function QuestionDetailPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { id } = useParams<{ id: string }>()
  const [question, setQuestion] = useState<QuestionOut | null>(null)
  const [invites, setInvites] = useState<Invite[]>([])
  const [submissions, setSubmissions] = useState<SubmissionRow[]>([])
  const [subTotal, setSubTotal] = useState(0)
  const [subOffset, setSubOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)

  // Inviting is a deliberate action, so the email field lives in a dialog rather
  // than sitting on the page implying a question isn't finished without one.
  // Arriving straight from the wizard we open it once as a nudge — that's the
  // only time the dismiss button reads "Skip for now" instead of "Cancel".
  const justCreated = Boolean((location.state as { justCreated?: boolean } | null)?.justCreated)
  const [inviteOpen, setInviteOpen] = useState(justCreated)
  // The nudge is one-shot: once dismissed, re-opening the dialog by hand is a
  // deliberate act, so the dismiss button goes back to reading "Cancel".
  const [isNudge, setIsNudge] = useState(justCreated)
  const dialogRef = useRef<HTMLDialogElement>(null)

  const [recipients, setRecipients] = useState('')
  const [creatingInvite, setCreatingInvite] = useState(false)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [copiedUrl, setCopiedUrl] = useState<string | null>(null)
  const [revokingToken, setRevokingToken] = useState<string | null>(null)
  const [revokeError, setRevokeError] = useState<{ token: string; message: string } | null>(null)
  // Emailing is best-effort, so a created invite may still not have reached
  // anyone. Surface that rather than letting the interviewer assume delivery.
  const [undelivered, setUndelivered] = useState<InviteDelivery[]>([])
  const [sentTo, setSentTo] = useState<string[]>([])

  useEffect(() => {
    if (!id) return
    api.getQuestion(id).then(setQuestion).catch(() => setError('Failed to load question'))
    api.listInvites(id).then(setInvites).catch(() => setError('Failed to load invites'))
  }, [id])

  // Submissions are paged independently so stepping through them doesn't refetch
  // the question and invites.
  useEffect(() => {
    if (!id) return
    api
      .listSubmissions(id, subOffset, SUB_PAGE_SIZE)
      .then((page) => {
        setSubmissions(page.items)
        setSubTotal(page.total)
      })
      .catch(() => setError('Failed to load submissions'))
  }, [id, subOffset])

  // Consume the nudge: history state survives a reload, so without clearing it
  // the invite dialog would pop open again every time the page is refreshed.
  // The initial state above already captured it, so this only affects reloads.
  useEffect(() => {
    if (justCreated) navigate(location.pathname, { replace: true, state: null })
  }, [justCreated, navigate, location.pathname])

  // Drive the native <dialog> from state so we get focus trapping, Esc-to-close
  // and the backdrop without hand-rolling a modal. `question` is a dependency
  // because the dialog isn't mounted until it loads — without it the post-create
  // auto-open runs against a null ref and silently never opens.
  useEffect(() => {
    const el = dialogRef.current
    if (!el) return
    if (inviteOpen && !el.open) el.showModal()
    if (!inviteOpen && el.open) el.close()
  }, [inviteOpen, question])

  function closeInviteDialog() {
    setInviteOpen(false)
    setIsNudge(false)
    setInviteError(null)
    setRecipients('')
  }

  async function handleCreateInvite(e: FormEvent) {
    e.preventDefault()
    if (!id) return
    setInviteError(null)
    setUndelivered([])
    setSentTo([])
    // Accept the comma- or newline-separated list interviewers actually paste.
    const recipientList = recipients
      .split(/[,\n]/)
      .map((r) => r.trim())
      .filter(Boolean)
    if (recipientList.length === 0) {
      // No recipients means no link: it would be one nobody could open.
      setInviteError('Enter at least one candidate email — the link only works for these addresses.')
      return
    }
    setCreatingInvite(true)
    try {
      const invite = await api.createInvite(id, { recipients: recipientList })
      setInvites((prev) => [invite, ...prev])
      setUndelivered(invite.deliveries.filter((d) => !d.sent))
      setSentTo(invite.deliveries.filter((d) => d.sent).map((d) => d.recipient))
      closeInviteDialog()
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
            {question.reference_solution && (
              <details className="draft-reference">
                <summary>
                  Show reference solution
                  {question.reference_language ? ` (${question.reference_language})` : ''}
                </summary>
                <pre className="code">{question.reference_solution}</pre>
              </details>
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
                      <th>Recipients &amp; delivery</th>
                      <th>Status</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {invites.map((invite) => (
                      <tr key={invite.token}>
                        <td className="invite-url">{invite.url}</td>
                        <td>
                          {invite.deliveries.length > 0 ? (
                            <ul className="recip-list">
                              {invite.deliveries.map((d) => (
                                <li className="recip" key={d.recipient}>
                                  <span className={`recip-dot ${d.sent ? 'ok' : 'fail'}`} />
                                  <span className="recip-addr">{d.recipient}</span>
                                  {!d.sent && d.error && (
                                    <span className="recip-why">— {d.error}</span>
                                  )}
                                </li>
                              ))}
                            </ul>
                          ) : (
                            invite.recipients.join(', ') || '—'
                          )}
                        </td>
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
            {subTotal > 0 && <span className="count">{subTotal}</span>}
          </h2>
          {submissions.length === 0 ? (
            <p className="empty-state">No submissions yet. Share an invite link to get started.</p>
          ) : (
            <div className="card">
              <div className="tbl-wrap">
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
              <Pager
                total={subTotal}
                limit={SUB_PAGE_SIZE}
                offset={subOffset}
                onChange={setSubOffset}
              />
            </div>
          )}
        </div>

        <aside className="side">
          <div className="card pad">
            <h3>Invite a candidate</h3>
            {sentTo.length > 0 && (
              <p role="status" className="form-success">
                Invite sent to {sentTo.join(', ')}.
              </p>
            )}
            {undelivered.length > 0 && (
              <div role="alert" className="form-warning">
                <p>
                  The invite was created, but the email couldn’t be sent to{' '}
                  {undelivered.map((d) => d.recipient).join(', ')}. Copy the link from the table and
                  send it another way.
                </p>
                <p className="cellsub">{undelivered[0].error}</p>
              </div>
            )}
            <button type="button" className="btn accent block" onClick={() => setInviteOpen(true)}>
              Send invite
            </button>
            <p className="invite-hint muted">
              Each invite link is emailed to the candidates you name, and only works for those
              addresses. You can also copy it from the table.
            </p>
          </div>

          <div className="card pad">
            <h3>Grading</h3>
            {question.difficulty && (
              <div className="kv">
                <span className="k">Difficulty</span>
                <span className={difficultyClass(question.difficulty)}>{question.difficulty}</span>
              </div>
            )}
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

      <dialog
        ref={dialogRef}
        className="modal"
        aria-labelledby="invite-dialog-title"
        onClose={closeInviteDialog}
      >
        <form className="stack" onSubmit={handleCreateInvite}>
          <h2 id="invite-dialog-title">Send invite</h2>
          <p className="muted">
            The link is emailed to each address and only works for them — a candidate has to confirm
            their email to start.
          </p>
          <div className="field">
            <label htmlFor="recipients">Candidate emails</label>
            <textarea
              id="recipients"
              value={recipients}
              autoFocus
              onChange={(e) => setRecipients(e.target.value)}
              placeholder="alice@example.com, bob@example.com"
            />
            <p className="cellsub">Separate multiple addresses with a comma or a new line.</p>
          </div>
          {inviteError && (
            <p role="alert" className="form-error">
              {inviteError}
            </p>
          )}
          <div className="modal-actions">
            <button
              type="button"
              className="btn sec"
              onClick={closeInviteDialog}
              disabled={creatingInvite}
            >
              {isNudge ? 'Skip for now' : 'Cancel'}
            </button>
            <button type="submit" className="btn accent" disabled={creatingInvite}>
              {creatingInvite ? 'Sending…' : 'Send invite'}
            </button>
          </div>
        </form>
      </dialog>
    </div>
  )
}
