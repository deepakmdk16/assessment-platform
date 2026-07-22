import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { badgeClass } from '../badges'
import { Pager } from '../components/Pager'
import type { SubmissionSummary } from '../types'

const PAGE_SIZE = 100
// Enough to title-map every question a normal workspace has; ids beyond this
// fall back to showing the raw question_id.
const QUESTION_FETCH_LIMIT = 200

export function SubmissionsPage() {
  const navigate = useNavigate()
  const [submissions, setSubmissions] = useState<SubmissionSummary[] | null>(null)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [titles, setTitles] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .listAllSubmissions(offset, PAGE_SIZE)
      .then((page) => {
        if (cancelled) return
        setSubmissions(page.items)
        setTotal(page.total)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load submissions')
      })
    return () => {
      cancelled = true
    }
  }, [offset])

  // Map question_id -> title once, so rows read as "Two Sum" rather than a slug.
  // Best-effort: a failure just leaves rows showing the id.
  useEffect(() => {
    let cancelled = false
    api
      .listQuestions(true, 0, QUESTION_FETCH_LIMIT)
      .then((page) => {
        if (cancelled) return
        setTitles(Object.fromEntries(page.items.map((q) => [q.id, q.title])))
      })
      .catch(() => {
        /* non-fatal: rows fall back to the question_id */
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>
            Submissions
            {total > 0 && <span className="count">{total}</span>}
          </h1>
          <div className="sub">Every graded attempt across your questions, newest first.</div>
        </div>
      </div>

      {error && <p className="form-error">{error}</p>}
      {!error && submissions === null && <p className="page-loading">Loading…</p>}

      {submissions?.length === 0 && (
        <p className="empty-state">
          No submissions yet. Share an invite link on any question to get started.
        </p>
      )}

      {submissions && submissions.length > 0 && (
        <div className="card">
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Question</th>
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
                    key={s.id}
                    className="clickable-row"
                    onClick={() => navigate(`/submissions/${s.id}`)}
                    title="View submission detail"
                  >
                    <td>
                      <div className="t-title">{s.candidate}</div>
                      {s.candidate_email && <div className="cellsub">{s.candidate_email}</div>}
                    </td>
                    <td>{titles[s.question_id] ?? s.question_id}</td>
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
                    <td>{new Date(s.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pager total={total} limit={PAGE_SIZE} offset={offset} onChange={setOffset} />
        </div>
      )}
    </div>
  )
}
