import { useEffect, useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { badgeClass, difficultyClass } from '../badges'
import type { QuestionOut } from '../types'

export function DashboardPage() {
  const navigate = useNavigate()
  const [questions, setQuestions] = useState<QuestionOut[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [showArchived, setShowArchived] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)

  useEffect(() => {
    api
      .listQuestions(showArchived)
      .then(setQuestions)
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load questions'))
  }, [showArchived])

  // Archive/unarchive is a row action, so stop the click from also opening the
  // question. Splice the returned row back in — or drop it when the list is
  // hiding archived questions and this one just left the active set.
  async function toggleArchive(e: MouseEvent, q: QuestionOut) {
    e.stopPropagation()
    setBusyId(q.id)
    setError(null)
    try {
      const updated =
        q.status === 'archived' ? await api.unarchiveQuestion(q.id) : await api.archiveQuestion(q.id)
      setQuestions((prev) => {
        if (!prev) return prev
        if (!showArchived && updated.status === 'archived') {
          return prev.filter((x) => x.id !== q.id)
        }
        return prev.map((x) => (x.id === q.id ? updated : x))
      })
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
            {questions && questions.length > 0 && <span className="count">{questions.length}</span>}
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
      {questions?.length === 0 && (
        <p className="empty-state">
          {showArchived
            ? 'No questions yet. Create your first one to start inviting candidates.'
            : 'No active questions. Create one, or show archived questions below.'}
        </p>
      )}

      {questions && questions.length > 0 && (
        <>
          <div className="list-toolbar">
            <label className="check">
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(e) => setShowArchived(e.target.checked)}
              />
              Show archived
            </label>
          </div>
          <div className="card tbl-wrap">
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
        </>
      )}
    </div>
  )
}
