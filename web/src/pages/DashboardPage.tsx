import { useEffect, useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { badgeClass, difficultyClass } from '../badges'
import { Pager } from '../components/Pager'
import type { QuestionOut } from '../types'

const PAGE_SIZE = 100

export function DashboardPage() {
  const navigate = useNavigate()
  const [questions, setQuestions] = useState<QuestionOut[] | null>(null)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  // Bumped after an archive/unarchive so the current page + total refetch and
  // stay consistent (a row may have just left or joined the filtered set).
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    api
      .listQuestions(showArchived, offset, PAGE_SIZE)
      .then((page) => {
        if (cancelled) return
        setQuestions(page.items)
        setTotal(page.total)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load questions')
      })
    return () => {
      cancelled = true
    }
  }, [showArchived, offset, reloadKey])

  function toggleShowArchived(value: boolean) {
    setShowArchived(value)
    setOffset(0) // the filtered set changed size; start from the first page
  }

  // Archive/unarchive is a row action, so stop the click from also opening the
  // question, then refetch so the page and total reflect the change.
  async function toggleArchive(e: MouseEvent, q: QuestionOut) {
    e.stopPropagation()
    setBusyId(q.id)
    setError(null)
    try {
      if (q.status === 'archived') await api.unarchiveQuestion(q.id)
      else await api.archiveQuestion(q.id)
      setReloadKey((k) => k + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to update question')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>
            Questions
            {total > 0 && <span className="count">{total}</span>}
          </h1>
          <div className="sub">Author problems, invite candidates, and review graded submissions.</div>
        </div>
        <Link to="/questions/new" className="btn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New question
        </Link>
      </div>

      {error && <p className="form-error">{error}</p>}
      {!error && questions === null && <p className="page-loading">Loading…</p>}

      {/* The toolbar renders as soon as questions load (even when empty) so
          archiving your last question never hides the "Show archived" toggle. */}
      {questions !== null && (
        <div className="list-toolbar">
          <label className="check">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => toggleShowArchived(e.target.checked)}
            />
            Show archived
          </label>
        </div>
      )}

      {questions?.length === 0 && (
        <p className="empty-state">
          {showArchived
            ? 'No questions yet. Create your first one to start inviting candidates.'
            : 'No active questions. Create one, or use “Show archived” above to see archived questions.'}
        </p>
      )}

      {questions && questions.length > 0 && (
        <div className="card">
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Problem</th>
                  <th>Test cases</th>
                  <th>Difficulty</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {questions.map((q) => (
                  <tr
                    key={q.id}
                    className={`clickable-row${q.status === 'archived' ? ' row-archived' : ''}`}
                    onClick={() => navigate(`/questions/${q.id}`)}
                  >
                    <td>
                      <div className="t-title">{q.title}</div>
                    </td>
                    <td className="num">{q.test_cases.length}</td>
                    <td>
                      {q.difficulty ? (
                        <span className={difficultyClass(q.difficulty)}>{q.difficulty}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      <span className={badgeClass(q.status)}>{q.status}</span>
                    </td>
                    <td>{new Date(q.created_at).toLocaleDateString()}</td>
                    <td>
                      <button
                        type="button"
                        className="btn sec sm"
                        onClick={(e) => toggleArchive(e, q)}
                        disabled={busyId === q.id}
                      >
                        {busyId === q.id
                          ? '…'
                          : q.status === 'archived'
                            ? 'Unarchive'
                            : 'Archive'}
                      </button>
                    </td>
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
