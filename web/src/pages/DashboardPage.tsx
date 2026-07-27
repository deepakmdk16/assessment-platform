import { useEffect, useState, type MouseEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { formatDuration, score } from '../analytics/format'
import { badgeClass, difficultyClass } from '../badges'
import { AnalyticsPanel } from '../components/AnalyticsPanel'
import { Meter } from '../components/Meter'
import { Pager } from '../components/Pager'
import type { QuestionAnalytics, QuestionOut } from '../types'

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
  // Multi-select for "build an assessment from these" (A8) — plain component
  // state, so it naturally resets on navigation.
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  // Analytics (AR1): time window shared by the panel and the per-question
  // columns, plus the per-question stats keyed by id (windowed by `days`).
  const [days, setDays] = useState<number | undefined>(30)
  const [stats, setStats] = useState<Map<string, QuestionAnalytics>>(new Map())

  // Per-question stats for the table columns. Fetched wide (one page) and looked
  // up by id, so archived rows — absent from analytics — simply show no stats.
  useEffect(() => {
    let cancelled = false
    api
      .analyticsQuestions(days, 0, 200)
      .then((page) => {
        if (!cancelled) setStats(new Map(page.items.map((s) => [s.question_id, s])))
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [days, reloadKey])

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

  function toggleSelect(id: string) {
    setSelectedIds((s) => {
      const next = new Set(s)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function buildAssessment() {
    navigate('/assessments/new', { state: { preselected: [...selectedIds] } })
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

      <AnalyticsPanel days={days} onDaysChange={setDays} />

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
          {selectedIds.size > 0 && (
            <button type="button" className="btn sec sm" onClick={buildAssessment}>
              Build assessment ({selectedIds.size})
            </button>
          )}
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
                  <th></th>
                  <th>Problem</th>
                  <th>Difficulty</th>
                  <th>Pass rate</th>
                  <th className="th-num">Avg</th>
                  <th className="th-num">Median time</th>
                  <th className="num">Test cases</th>
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
                    <td onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`Select ${q.title}`}
                        checked={selectedIds.has(q.id)}
                        onChange={() => toggleSelect(q.id)}
                      />
                    </td>
                    <td>
                      <div className="t-title">{q.title}</div>
                    </td>
                    <td>
                      {q.difficulty ? (
                        <span className={difficultyClass(q.difficulty)}>{q.difficulty}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>
                      {stats.has(q.id) ? (
                        <Meter rate={stats.get(q.id)!.pass_rate} />
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="num">
                      {stats.has(q.id) ? score(stats.get(q.id)!.avg_score_pct, 0) : '—'}
                    </td>
                    <td className="num mono">
                      {stats.has(q.id) ? formatDuration(stats.get(q.id)!.median_time_to_solve_s) : '—'}
                    </td>
                    <td className="num">{q.test_cases.length}</td>
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
