import { useEffect, useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { badgeClass } from '../badges'
import { Pager } from '../components/Pager'
import type { AssessmentOut } from '../types'

const PAGE_SIZE = 100

export function AssessmentsListPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<AssessmentOut[] | null>(null)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [showArchived, setShowArchived] = useState(false)
  const [busyId, setBusyId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [reloadKey, setReloadKey] = useState(0)

  useEffect(() => {
    let cancelled = false
    api
      .listAssessments(showArchived, offset, PAGE_SIZE)
      .then((page) => {
        if (cancelled) return
        setItems(page.items)
        setTotal(page.total)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load assessments')
      })
    return () => {
      cancelled = true
    }
  }, [showArchived, offset, reloadKey])

  async function toggleArchive(e: MouseEvent, a: AssessmentOut) {
    e.stopPropagation()
    setBusyId(a.id)
    setError(null)
    try {
      if (a.status === 'archived') await api.unarchiveAssessment(a.id)
      else await api.archiveAssessment(a.id)
      setReloadKey((k) => k + 1)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to update assessment')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>
            Assessments
            {total > 0 && <span className="count">{total}</span>}
          </h1>
          <div className="sub">Bundle questions into one timed sitting and invite candidates.</div>
        </div>
        <Link to="/assessments/new" className="btn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New assessment
        </Link>
      </div>

      {error && <p className="form-error">{error}</p>}
      {!error && items === null && <p className="page-loading">Loading…</p>}

      {items !== null && (
        <div className="list-toolbar">
          <label className="check">
            <input
              type="checkbox"
              checked={showArchived}
              onChange={(e) => {
                setShowArchived(e.target.checked)
                setOffset(0)
              }}
            />
            Show archived
          </label>
        </div>
      )}

      {items?.length === 0 && (
        <p className="empty-state">
          {showArchived
            ? 'No assessments yet. Create one to bundle questions into a sitting.'
            : 'No active assessments. Create one, or use “Show archived” above.'}
        </p>
      )}

      {items && items.length > 0 && (
        <div className="card">
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Questions</th>
                  <th>Time allowed</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((a) => (
                  <tr
                    key={a.id}
                    className={`clickable-row${a.status === 'archived' ? ' row-archived' : ''}`}
                    onClick={() => navigate(`/assessments/${a.id}`)}
                  >
                    <td>
                      <div className="t-title">{a.title}</div>
                    </td>
                    <td className="num">{a.questions.length}</td>
                    <td>
                      {a.duration_minutes != null ? (
                        <span className="num">{a.duration_minutes} min</span>
                      ) : (
                        <span className="muted">Indefinite</span>
                      )}
                    </td>
                    <td>
                      <span className={badgeClass(a.status)}>{a.status}</span>
                    </td>
                    <td>{new Date(a.created_at).toLocaleDateString()}</td>
                    <td>
                      <button
                        type="button"
                        className="btn sec sm"
                        onClick={(e) => toggleArchive(e, a)}
                        disabled={busyId === a.id}
                      >
                        {busyId === a.id ? '…' : a.status === 'archived' ? 'Unarchive' : 'Archive'}
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
