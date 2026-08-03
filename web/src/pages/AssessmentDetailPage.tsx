import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { badgeClass } from '../badges'
import { IntegrityCell } from '../components/IntegrityPanel'
import type { AssessmentAttempt, AssessmentOut, Invite, InviteDelivery } from '../types'

export function AssessmentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [assessment, setAssessment] = useState<AssessmentOut | null>(null)
  const [invites, setInvites] = useState<Invite[]>([])
  const [attempts, setAttempts] = useState<AssessmentAttempt[]>([])
  const [recipients, setRecipients] = useState('')
  const [sending, setSending] = useState(false)
  const [sentTo, setSentTo] = useState<string[]>([])
  const [undelivered, setUndelivered] = useState<InviteDelivery[]>([])
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  // Edit dialog (settings only — title/timer/monitoring/branding). The question
  // set is deliberately not editable here: post-invite the server locks it (A9),
  // and pre-invite it would mean rebuilding the whole builder on this page.
  const [editOpen, setEditOpen] = useState(false)
  const editDialogRef = useRef<HTMLDialogElement>(null)
  const [editTitle, setEditTitle] = useState('')
  const [editDuration, setEditDuration] = useState(60)
  const [editIndefinite, setEditIndefinite] = useState(false)
  const [editOrgName, setEditOrgName] = useState('')
  const [editLogoUrl, setEditLogoUrl] = useState('')
  const [editProctored, setEditProctored] = useState(true)
  const [editError, setEditError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!id) return
    let cancelled = false
    Promise.all([api.getAssessment(id), api.listAssessmentInvites(id), api.listAssessmentAttempts(id)])
      .then(([a, inv, att]) => {
        if (cancelled) return
        setAssessment(a)
        setInvites(inv)
        setAttempts(att)
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

  // Drive the native <dialog> from state (same pattern as the Quick-screen
  // dialog): focus trapping, Esc-to-close, and the backdrop come for free.
  useEffect(() => {
    const el = editDialogRef.current
    if (!el) return
    if (editOpen && !el.open) el.showModal()
    if (!editOpen && el.open) el.close()
  }, [editOpen, assessment])

  function openEdit() {
    if (!assessment) return
    setEditTitle(assessment.title)
    setEditIndefinite(assessment.duration_minutes == null)
    setEditDuration(assessment.duration_minutes ?? 60)
    setEditOrgName(assessment.org_name ?? '')
    setEditLogoUrl(assessment.logo_url ?? '')
    setEditProctored(assessment.proctored)
    setEditError(null)
    setEditOpen(true)
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault()
    if (!id || !assessment) return
    setEditError(null)
    setSaving(true)
    try {
      const updated = await api.updateAssessment(id, {
        title: editTitle,
        duration_minutes: editIndefinite ? null : editDuration,
        // The PUT is full-replace: resend the current slots verbatim (an
        // unchanged slot signature never trips the A9 post-invite lock) and
        // always send `proctored` explicitly — omitted, the server would
        // silently reset it to true.
        slots: assessment.questions.map((q) =>
          q.variant_set_id
            ? { variant_set_id: q.variant_set_id }
            : { question_id: q.question_id ?? undefined },
        ),
        org_name: editOrgName.trim() || null,
        logo_url: editLogoUrl.trim() || null,
        proctored: editProctored,
      })
      setAssessment(updated)
      setEditOpen(false)
    } catch (err) {
      setEditError(err instanceof ApiError ? err.message : 'Failed to save changes')
    } finally {
      setSaving(false)
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
            {assessment.org_name && <> · Branded for {assessment.org_name}</>}
            {/* I1: an unmonitored sitting is the exception, so only that is
                called out — a monitored one is the default and stays quiet. */}
            {!assessment.proctored && <> · Not monitored</>}
          </div>
        </div>
        <div className="head-actions">
          {assessment.logo_url && (
            <img src={assessment.logo_url} alt="" className="ide-brand-logo" />
          )}
          <button type="button" className="btn sec sm" onClick={openEdit}>
            Edit
          </button>
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
                    <tr key={q.variant_set_id ?? q.question_id ?? q.position}>
                      <td className="num">{q.position + 1}</td>
                      <td>
                        <div className="t-title">
                          {q.title}
                          {q.variant_set_id && (
                            <span className="chip chip-accent">
                              Variant set · {q.variant_count} variant
                              {q.variant_count === 1 ? '' : 's'}
                            </span>
                          )}
                        </div>
                        <div className="t-id">{q.variant_set_id ?? q.question_id}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {attempts.length > 0 && (
            <>
              <h2 className="sect-title">Attempts</h2>
              <div className="card tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Candidate</th>
                      <th>Progress</th>
                      <th>Passed</th>
                      <th>Avg score</th>
                      <th>Integrity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attempts.map((att) => (
                      <tr key={att.candidate_email}>
                        <td>
                          <div className="t-title">{att.candidate_name}</div>
                          <div className="cellsub">{att.candidate_email}</div>
                        </td>
                        <td>
                          <div className="attempt-progress">
                            {att.questions.map((q, i) => {
                              // For a variant-set slot, name the variant this
                              // candidate was handed so the interviewer can see who
                              // got which variant.
                              const base = q.variant_label
                                ? `${q.title} (variant ${q.variant_label})`
                                : q.title
                              const label = q.late ? `${base} · submitted late` : base
                              return q.submission_id ? (
                                <span
                                  key={i}
                                  className={`${badgeClass(q.verdict)} clickable${q.late ? ' late' : ''}`}
                                  title={`${label}: ${q.verdict ?? 'grading…'}`}
                                  role="link"
                                  tabIndex={0}
                                  onClick={() => navigate(`/submissions/${q.submission_id}`)}
                                  onKeyDown={(e) => {
                                    if (e.key === 'Enter') navigate(`/submissions/${q.submission_id}`)
                                  }}
                                >
                                  {i + 1}
                                </span>
                              ) : (
                                <span key={i} className="chip chip-neutral" title={`${label}: not submitted`}>
                                  {i + 1}
                                </span>
                              )
                            })}
                          </div>
                        </td>
                        <td className="num">
                          {att.passed_count} / {att.total_count}
                        </td>
                        <td className="score">
                          {att.avg_score_pct != null ? `${att.avg_score_pct.toFixed(0)}%` : '—'}
                        </td>
                        {/* I1: signals belong to the sitting, so this shows even
                            for a candidate who started and never submitted —
                            the case with no submission to open a report from. */}
                        <td>
                          <IntegrityCell
                            signals={att.integrity_signals}
                            blocked={att.integrity_blocked ?? 0}
                            risk={att.integrity_risk}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

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
            <h3>Invite to this assessment</h3>
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

      <dialog
        ref={editDialogRef}
        className="modal"
        aria-labelledby="edit-dialog-title"
        onClose={() => setEditOpen(false)}
      >
        <form className="stack" onSubmit={handleSave}>
          <h2 id="edit-dialog-title">Edit assessment</h2>
          <div className="field">
            <label htmlFor="edit-title">Title</label>
            <input
              id="edit-title"
              value={editTitle}
              required
              autoFocus
              onChange={(e) => setEditTitle(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="edit-duration">Time allowed (whole assessment)</label>
            <div className="inline-field">
              <input
                id="edit-duration"
                type="number"
                min={1}
                value={editDuration}
                disabled={editIndefinite}
                onChange={(e) => setEditDuration(Number(e.target.value))}
              />
              <span className="muted">minutes</span>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={editIndefinite}
                onChange={(e) => setEditIndefinite(e.target.checked)}
              />
              Indefinite (no timer)
            </label>
            <p className="cellsub">
              A changed time limit only applies to attempts that start after you save — it can’t
              revive an attempt whose clock has already run out. Re-invite to give a fresh clock.
            </p>
          </div>
          <div className="field">
            <label htmlFor="edit-proctored">Monitoring</label>
            <label className="check">
              <input
                id="edit-proctored"
                type="checkbox"
                checked={editProctored}
                onChange={(e) => setEditProctored(e.target.checked)}
              />
              Monitor this assessment
            </label>
            <p className="cellsub">
              Applies to invites sent after you save. Invites already sent keep the monitoring
              setting they went out with.
            </p>
          </div>
          <div className="field">
            <label htmlFor="edit-org">Organization name</label>
            <input
              id="edit-org"
              placeholder="e.g. Acme Corp"
              value={editOrgName}
              onChange={(e) => setEditOrgName(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="edit-logo">Logo URL</label>
            <input
              id="edit-logo"
              placeholder="https://…"
              value={editLogoUrl}
              onChange={(e) => setEditLogoUrl(e.target.value)}
            />
          </div>
          <p className="cellsub">
            To change the questions, create a new assessment — the question set is fixed once
            candidates have been invited.
          </p>
          {editError && (
            <p role="alert" className="form-error">
              {editError}
            </p>
          )}
          <div className="modal-actions">
            <button
              type="button"
              className="btn sec"
              onClick={() => setEditOpen(false)}
              disabled={saving}
            >
              Cancel
            </button>
            <button type="submit" className="btn" disabled={saving}>
              {saving ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </form>
      </dialog>
    </div>
  )
}
