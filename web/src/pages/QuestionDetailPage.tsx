import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import type { Invite, QuestionOut, SubmissionRow } from '../types'

export function QuestionDetailPage() {
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
    setInviteError(null)
    setRevokingToken(token)
    try {
      const updated = await api.revokeInvite(id, token)
      setInvites((prev) => prev.map((inv) => (inv.token === token ? updated : inv)))
    } catch (err) {
      setInviteError(err instanceof ApiError ? err.message : 'Failed to revoke invite')
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
  if (!question) return <p>Loading…</p>

  return (
    <div className="page">
      <h1>{question.title}</h1>
      <p className="question-id">{question.id}</p>

      <section className="question-detail">
        <h2>Prompt</h2>
        <p className="pre-text">{question.prompt}</p>
        <h2>Constraints</h2>
        <p className="pre-text">{question.constraints}</p>
        <h2>Example</h2>
        <pre>{question.example_input}</pre>
        <pre>{question.example_output}</pre>
      </section>

      <section>
        <h2>Generate coding test</h2>
        <form className="invite-form" onSubmit={handleCreateInvite}>
          <label htmlFor="recipients">Recipient emails (comma or newline separated, optional)</label>
          <textarea
            id="recipients"
            value={recipients}
            onChange={(e) => setRecipients(e.target.value)}
            placeholder="candidate@example.com"
          />
          {inviteError && (
            <p role="alert" className="form-error">
              {inviteError}
            </p>
          )}
          <button type="submit" disabled={creatingInvite}>
            {creatingInvite ? 'Generating…' : 'Generate coding test'}
          </button>
        </form>

        {invites.length > 0 && (
          <table className="data-table">
            <thead>
              <tr>
                <th>URL</th>
                <th>Recipients</th>
                <th>Status</th>
                <th>Expires</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {invites.map((invite) => (
                <tr key={invite.token}>
                  <td className="invite-url">{invite.url}</td>
                  <td>{invite.recipients.join(', ') || '—'}</td>
                  <td>{invite.status}</td>
                  <td>{invite.expires_at ?? 'never'}</td>
                  <td className="invite-actions">
                    <button type="button" onClick={() => copyUrl(invite.url)}>
                      {copiedUrl === invite.url ? 'Copied!' : 'Copy link'}
                    </button>
                    {invite.status === 'active' && (
                      <button
                        type="button"
                        className="danger"
                        onClick={() => handleRevoke(invite.token)}
                        disabled={revokingToken === invite.token}
                      >
                        {revokingToken === invite.token ? 'Revoking…' : 'Revoke'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Submissions</h2>
        {submissions.length === 0 ? (
          <p>No submissions yet.</p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Email</th>
                <th>Language</th>
                <th>Status</th>
                <th>Verdict</th>
                <th>Score</th>
                <th>Submitted</th>
              </tr>
            </thead>
            <tbody>
              {submissions.map((s) => (
                <tr key={s.submission_id}>
                  <td>{s.candidate_name}</td>
                  <td>{s.candidate_email}</td>
                  <td>{s.language}</td>
                  <td>{s.status}</td>
                  <td>{s.verdict ?? '—'}</td>
                  <td>{s.score_pct != null ? `${s.score_pct}%` : '—'}</td>
                  <td>{s.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
