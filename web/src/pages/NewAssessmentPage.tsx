import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { difficultyClass } from '../badges'
import type { QuestionOut } from '../types'

export function NewAssessmentPage() {
  const navigate = useNavigate()
  const [id, setId] = useState('')
  const [title, setTitle] = useState('')
  const [durationMinutes, setDurationMinutes] = useState(60)
  const [indefinite, setIndefinite] = useState(false)
  const [selectedIds, setSelectedIds] = useState<string[]>([])
  const [library, setLibrary] = useState<QuestionOut[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    api
      .listQuestions(false, 0, 200)
      .then((page) => {
        if (!cancelled) setLibrary(page.items)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load questions')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const byId = new Map(library.map((q) => [q.id, q]))
  const selected = selectedIds.map((qid) => byId.get(qid)).filter((q): q is QuestionOut => !!q)
  const available = library.filter((q) => !selectedIds.includes(q.id))

  function add(qid: string) {
    setSelectedIds((s) => [...s, qid])
  }
  function remove(qid: string) {
    setSelectedIds((s) => s.filter((x) => x !== qid))
  }
  function move(i: number, delta: number) {
    setSelectedIds((s) => {
      const j = i + delta
      if (j < 0 || j >= s.length) return s
      const next = [...s]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  async function handleCreate() {
    if (!id.trim()) return setError('Id is required.')
    if (!title.trim()) return setError('Title is required.')
    if (selectedIds.length === 0) return setError('Add at least one question.')
    setError(null)
    setSubmitting(true)
    try {
      const created = await api.createAssessment({
        id,
        title,
        duration_minutes: indefinite ? null : durationMinutes,
        question_ids: selectedIds,
      })
      navigate(`/assessments/${created.id}`, { state: { justCreated: true } })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create assessment')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="wizard">
      <div className="page-head">
        <div>
          <h1>New assessment</h1>
          <div className="sub">Bundle several of your questions into one timed sitting.</div>
        </div>
      </div>

      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}

      <div className="card pad">
        <div className="card-title">Basics</div>
        <div className="stack">
          <div className="grid2">
            <div className="field">
              <label htmlFor="id">Id (slug)</label>
              <input id="id" className="mono" value={id} onChange={(e) => setId(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="title">Title</label>
              <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
          </div>
          <div className="field">
            <label htmlFor="duration">Time allowed (whole assessment)</label>
            <div className="inline-field">
              <input
                id="duration"
                type="number"
                min={1}
                value={durationMinutes}
                disabled={indefinite}
                onChange={(e) => setDurationMinutes(Number(e.target.value))}
              />
              <span className="muted">minutes</span>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={indefinite}
                onChange={(e) => setIndefinite(e.target.checked)}
              />
              Indefinite (no timer)
            </label>
            <p className="cellsub">One shared budget the candidate spends across every question.</p>
          </div>
        </div>
      </div>

      <div className="card pad">
        <div className="card-title">Questions</div>
        <p className="draft-hint">
          Add questions from your library; their order here is the order the candidate sees.
        </p>
        <div className="grid2">
          <div>
            <div className="picker-label">In this assessment ({selected.length})</div>
            {selected.length === 0 ? (
              <p className="empty-state">No questions added yet.</p>
            ) : (
              selected.map((q, i) => (
                <div className="q-pick" key={q.id}>
                  <span className="q-ord">{i + 1}</span>
                  <span className="q-pick-t">
                    <span className="title">{q.title}</span>
                    {q.difficulty && (
                      <span className={difficultyClass(q.difficulty)}>{q.difficulty}</span>
                    )}
                  </span>
                  <button type="button" className="mini" title="Move up" onClick={() => move(i, -1)}>
                    ↑
                  </button>
                  <button
                    type="button"
                    className="mini"
                    title="Move down"
                    onClick={() => move(i, 1)}
                  >
                    ↓
                  </button>
                  <button type="button" className="mini" title="Remove" onClick={() => remove(q.id)}>
                    ✕
                  </button>
                </div>
              ))
            )}
          </div>
          <div>
            <div className="picker-label">Your question library</div>
            {available.length === 0 ? (
              <p className="empty-state">
                {library.length === 0 ? 'You have no questions yet.' : 'All questions added.'}
              </p>
            ) : (
              available.map((q) => (
                <div className="q-pick" key={q.id}>
                  <span className="q-pick-t">
                    <span className="title">{q.title}</span>
                    {q.difficulty && (
                      <span className={difficultyClass(q.difficulty)}>{q.difficulty}</span>
                    )}
                  </span>
                  <button type="button" className="btn sec sm" onClick={() => add(q.id)}>
                    Add
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      <div className="wizard-nav">
        <button type="button" className="btn accent" onClick={handleCreate} disabled={submitting}>
          {submitting ? 'Creating…' : 'Create assessment'}
        </button>
        <button type="button" className="btn sec" onClick={() => navigate('/assessments')}>
          Cancel
        </button>
      </div>
    </div>
  )
}
