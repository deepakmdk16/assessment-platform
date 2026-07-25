import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { badgeClass } from '../badges'
import type { AssessmentOut, Invite, InviteDelivery } from '../types'

export function AssessmentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [assessment, setAssessment] = useState<AssessmentOut | null>(null)
  const [invites, setInvites] = useState<Invite[]>([])
  const [recipients, setRecipients] = useState('')
  const [sending, setSending] = useState(false)
  const [sentTo, setSentTo] = useState<string[]>([])
  const [undelivered, setUndelivered] = useState<InviteDelivery[]>([])
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    Promise.all([api.getAssessment(id), api.listAssessmentInvites(id)])
      .then(([a, inv]) => {
        if (cancelled) return
        setAssessment(a)
        setInvites(inv)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load assessment')
      })
    return () => {
      cancelled = true
    }
  }, [id])

  async function handleSend() {
    if (!id) return
    const list = recipients
      .split(/[\n,]/)
      .map((r) => r.trim())
      .filter(Boolean)
    if (list.length === 0) return setError('Enter at least one candidate email.')
    setError(null)
    setSending(true)
    try {
      const invite = await api.createAssessmentInvite(id, { recipients: list })
      setInvites((prev) => [invite, ...prev])
      setSentTo(invite.deliveries.filter((d) => d.sent).map((d) => d.recipient))
      setUndelivered(invite.deliveries.filter((d) => !d.sent))
      setRecipients('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create invite')
    } finally {
      setSending(false)
    }
  }

  async function copyUrl(url: string) {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(url)
      setTimeout(() => setCopied(null), 1500)
    } catch {
      // clipboard blocked — the url is on screen to copy manually
    }
  }

  if (error && !assessment) return <p className="form-error">{error}</p>
  if (!assessment) return <p className="page-loading">Loading…</p>

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>{assessment.title}</h1>
          <div className="sub">
            {assessment.questions.length} question{assessment.questions.length === 1 ? '' : 's'} ·{' '}
            {assessment.duration_minutes != null
              ? `${assessment.duration_minutes} min total`
              : 'Untimed'}
          </div>
        </div>
      </div>

      {error && <p className="form-error">{error}</p>}

      <div className="detail-grid">
        <div>
          <section className="card pad">
            <h3>Questions (in order)</h3>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Question</th>
                  </tr>
                </thead>
                <tbody>
                  {assessment.questions.map((q) => (
                    <tr key={q.question_id}>
                      <td className="num">{q.position + 1}</td>
                      <td>
                        <div className="t-title">{q.title}</div>
                        <div className="t-id">{q.question_id}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
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
                    {invites.map((inv) => (
                      <tr key={inv.token}>
                        <td className="invite-url">{inv.url}</td>
                        <td>
                          {inv.deliveries.length > 0 ? (
                            <ul className="recip-list">
                              {inv.deliveries.map((d) => (
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
                            inv.recipients.join(', ') || '—'
                          )}
                        </td>
                        <td>
                          <span className={badgeClass(inv.status)}>{inv.status}</span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn sec sm"
                            onClick={() => copyUrl(inv.url)}
                          >
                            {copied === inv.url ? 'Copied!' : 'Copy link'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
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
            <div className="field">
              <label htmlFor="recipients">Candidate emails</label>
              <textarea
                id="recipients"
                value={recipients}
                placeholder="one per line, or comma-separated"
                onChange={(e) => setRecipients(e.target.value)}
              />
            </div>
            <button
              type="button"
              className="btn accent block"
              onClick={handleSend}
              disabled={sending}
            >
              {sending ? 'Sending…' : 'Send invite'}
            </button>
            <p className="invite-hint muted">
              The link opens the whole assessment — every question, one shared timer — and only
              works for the emails you list.
            </p>
          </div>
        </aside>
      </div>
    </div>
  )
}
