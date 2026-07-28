import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'
import { difficultyClass } from '../badges'
import type { QuestionOut, VariantSetSummary } from '../types'

// A slot is either a fixed question or a variant set (VS2); order is preserved.
type Slot = { kind: 'question' | 'set'; id: string }

export function NewAssessmentPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user } = useAuth()
  const [title, setTitle] = useState('')
  const [durationMinutes, setDurationMinutes] = useState(60)
  const [indefinite, setIndefinite] = useState(false)
  // Prefilled from the interviewer's workspace default branding (A12); still
  // editable per assessment, and only this assessment's value is stored.
  const [orgName, setOrgName] = useState(user?.default_org_name ?? '')
  const [logoUrl, setLogoUrl] = useState(user?.default_logo_url ?? '')
  // Integrity monitoring (I1) — on unless the interviewer deliberately relaxes
  // this sitting.
  const [proctored, setProctored] = useState(true)
  // Pre-populated from the questions page's "Build assessment" multi-select
  // (A8) — question slots. Any id not actually in the library (stale/archived/
  // deleted) is dropped below once the library loads.
  const [slots, setSlots] = useState<Slot[]>(
    () =>
      ((location.state as { preselected?: string[] } | null)?.preselected ?? []).map((id) => ({
        kind: 'question' as const,
        id,
      })),
  )
  const [library, setLibrary] = useState<QuestionOut[]>([])
  const [sets, setSets] = useState<VariantSetSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    let cancelled = false
    Promise.all([api.listQuestions(false, 0, 200), api.listVariantSets(false, 0, 200)])
      .then(([qPage, sPage]) => {
        if (cancelled) return
        setLibrary(qPage.items)
        setSets(sPage.items)
        // Drop any preselected slot whose thing isn't actually available (stale,
        // archived, or deleted) — otherwise it'd be silently included on create
        // despite never appearing in the "in this assessment" list.
        const qIds = new Set(qPage.items.map((q) => q.id))
        const sIds = new Set(sPage.items.map((s) => s.id))
        setSlots((cur) =>
          cur.filter((s) => (s.kind === 'question' ? qIds.has(s.id) : sIds.has(s.id))),
        )
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof ApiError ? err.message : 'Failed to load your library')
      })
    return () => {
      cancelled = true
    }
  }, [])

  const qById = new Map(library.map((q) => [q.id, q]))
  const setById = new Map(sets.map((s) => [s.id, s]))
  const has = (kind: Slot['kind'], id: string) =>
    slots.some((s) => s.kind === kind && s.id === id)
  const availableQuestions = library.filter((q) => !has('question', q.id))
  const availableSets = sets.filter((s) => !has('set', s.id))

  function add(kind: Slot['kind'], id: string) {
    setSlots((s) => [...s, { kind, id }])
  }
  function remove(i: number) {
    setSlots((s) => s.filter((_, idx) => idx !== i))
  }
  function move(i: number, delta: number) {
    setSlots((s) => {
      const j = i + delta
      if (j < 0 || j >= s.length) return s
      const next = [...s]
      ;[next[i], next[j]] = [next[j], next[i]]
      return next
    })
  }

  async function handleCreate() {
    if (!title.trim()) return setError('Title is required.')
    if (slots.length === 0) return setError('Add at least one question or variant set.')
    setError(null)
    setSubmitting(true)
    try {
      const created = await api.createAssessment({
        title,
        duration_minutes: indefinite ? null : durationMinutes,
        slots: slots.map((s) =>
          s.kind === 'question' ? { question_id: s.id } : { variant_set_id: s.id },
        ),
        org_name: orgName.trim() || null,
        logo_url: logoUrl.trim() || null,
        proctored,
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
          <div className="field">
            <label htmlFor="title">Title</label>
            <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
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
          <div className="field">
            <label htmlFor="proctored">Monitoring</label>
            <label className="check">
              <input
                id="proctored"
                type="checkbox"
                checked={proctored}
                onChange={(e) => setProctored(e.target.checked)}
              />
              Monitor this assessment
            </label>
            <p className="cellsub">
              Runs the sitting in fullscreen, blocks pastes from outside the page, and records tab
              switches for you to review. Candidates are told before they start. Turn it off for a
              deliberately relaxed sitting.
            </p>
          </div>
        </div>
      </div>

      <div className="card pad">
        <div className="card-title">Branding (optional)</div>
        <p className="draft-hint">
          Shown on the candidate&rsquo;s IDE header when they open the assessment. Leave blank for
          the generic &ldquo;Coding assessment&rdquo; header.
        </p>
        <div className="stack">
          <div className="grid2">
            <div className="field">
              <label htmlFor="org_name">Organization name</label>
              <input
                id="org_name"
                placeholder="e.g. Acme Corp"
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="logo_url">Logo URL</label>
              <input
                id="logo_url"
                placeholder="https://…"
                value={logoUrl}
                onChange={(e) => setLogoUrl(e.target.value)}
              />
            </div>
          </div>
          {(orgName.trim() || logoUrl.trim()) && (
            <div className="ide-title-preview">
              {logoUrl.trim() && (
                <img src={logoUrl.trim()} alt="" className="ide-brand-logo" />
              )}
              <span>
                {orgName.trim() && `${orgName.trim()} — `}
                {title.trim() || 'Assessment title'}
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="card pad">
        <div className="card-title">Questions &amp; variant sets</div>
        <p className="draft-hint">
          Add fixed questions or variant sets from your library; their order here is the order the
          candidate sees. A variant set hands each candidate a different variant of the same problem.
        </p>
        <div className="grid2">
          <div>
            <div className="picker-label">In this assessment ({slots.length})</div>
            {slots.length === 0 ? (
              <p className="empty-state">No questions or variant sets added yet.</p>
            ) : (
              slots.map((slot, i) => {
                const q = slot.kind === 'question' ? qById.get(slot.id) : undefined
                const vs = slot.kind === 'set' ? setById.get(slot.id) : undefined
                return (
                  <div className={`q-pick${vs ? ' set' : ''}`} key={`${slot.kind}:${slot.id}`}>
                    <span className="q-ord">{i + 1}</span>
                    <span className="q-pick-t">
                      <span className="title">{q?.title ?? vs?.title ?? slot.id}</span>
                      {vs && <span className="chip chip-accent">Variant set</span>}
                      {q?.difficulty && (
                        <span className={difficultyClass(q.difficulty)}>{q.difficulty}</span>
                      )}
                      {vs && (
                        <span className="cellsub">
                          Each candidate gets a random variant · {vs.variant_count} variant
                          {vs.variant_count === 1 ? '' : 's'}
                        </span>
                      )}
                    </span>
                    <button type="button" className="mini" title="Move up" onClick={() => move(i, -1)}>
                      ↑
                    </button>
                    <button type="button" className="mini" title="Move down" onClick={() => move(i, 1)}>
                      ↓
                    </button>
                    <button type="button" className="mini" title="Remove" onClick={() => remove(i)}>
                      ✕
                    </button>
                  </div>
                )
              })
            )}
          </div>
          <div>
            <div className="src-group">
              <div className="picker-label">Your question library</div>
              {availableQuestions.length === 0 ? (
                library.length === 0 ? (
                  <p className="empty-state">
                    You have no questions yet.{' '}
                    <Link to="/questions/new">Create your first question</Link>.
                  </p>
                ) : (
                  <p className="empty-state">All questions added.</p>
                )
              ) : (
                availableQuestions.map((q) => (
                  <div className="q-pick" key={q.id}>
                    <span className="q-pick-t">
                      <span className="title">{q.title}</span>
                      {q.difficulty && (
                        <span className={difficultyClass(q.difficulty)}>{q.difficulty}</span>
                      )}
                    </span>
                    <button type="button" className="btn sec sm" onClick={() => add('question', q.id)}>
                      Add
                    </button>
                  </div>
                ))
              )}
            </div>
            <div className="src-group">
              <div className="picker-label">Your variant sets</div>
              {sets.length === 0 ? (
                <p className="empty-state">
                  You have no variant sets yet.{' '}
                  <Link to="/variant-sets/new">Create one</Link>.
                </p>
              ) : availableSets.length === 0 ? (
                <p className="empty-state">All variant sets added.</p>
              ) : (
                availableSets.map((s) => (
                  <div className="q-pick set" key={s.id}>
                    <span className="q-pick-t">
                      <span className="title">{s.title}</span>
                      <span className="chip chip-accent">
                        {s.variant_count} variant{s.variant_count === 1 ? '' : 's'}
                      </span>
                      {s.difficulty && (
                        <span className={difficultyClass(s.difficulty)}>{s.difficulty}</span>
                      )}
                    </span>
                    <button type="button" className="btn sec sm" onClick={() => add('set', s.id)}>
                      Add
                    </button>
                  </div>
                ))
              )}
            </div>
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
