import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { LANGUAGES } from '../types'
import type { Language, VariantDraftOut, VariantIn } from '../types'

export function NewVariantSetPage() {
  const navigate = useNavigate()

  // Draft inputs.
  const [brief, setBrief] = useState('')
  const [language, setLanguage] = useState<Language>('python')
  const [difficulty, setDifficulty] = useState('medium')
  const [targetComplexity, setTargetComplexity] = useState('')
  const [count, setCount] = useState(3)

  // Draft output (review step) — null until a set has been drafted.
  const [variants, setVariants] = useState<VariantDraftOut[] | null>(null)
  const [setWarnings, setSetWarnings] = useState<string[]>([])
  const [title, setTitle] = useState('')

  const [drafting, setDrafting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleDraft() {
    if (!brief.trim()) {
      setError('Enter a brief to draft from.')
      return
    }
    setError(null)
    setVariants(null)
    setSetWarnings([])
    setDrafting(true)
    try {
      const res = await api.draftVariantSet({
        brief,
        language,
        count,
        difficulty: difficulty.trim() || undefined,
        target_complexity: targetComplexity.trim() || undefined,
      })
      setVariants(res.variants)
      setSetWarnings(res.warnings)
      setTitle(res.variants[0]?.question.title ?? brief.slice(0, 60))
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : 'Couldn’t draft the variant set. Check your connection and try again.',
      )
    } finally {
      setDrafting(false)
    }
  }

  async function handleSave() {
    if (!variants || variants.length < 2) return
    if (!title.trim()) {
      setError('Give the set a title before saving.')
      return
    }
    setError(null)
    setSaving(true)
    try {
      const payload: VariantIn[] = variants.map((v) => ({
        ...v.question,
        label: v.label,
        reference_solution: v.reference_solution,
        reference_language: v.reference_language,
      }))
      const created = await api.createVariantSet({
        title: title.trim(),
        brief,
        language,
        difficulty: difficulty.trim() || undefined,
        target_complexity: targetComplexity.trim() || undefined,
        variants: payload,
      })
      navigate(`/variant-sets/${created.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save the variant set.')
      setSaving(false)
    }
  }

  return (
    <div className="wizard">
      <div className="page-head">
        <div>
          <h1>New variant set</h1>
          <div className="sub">
            One brief → several interchangeable questions, calibrated to the same difficulty.
          </div>
        </div>
      </div>

      {error && <p className="form-error">{error}</p>}

      <div className="draft-card">
        <div className="draft-hd">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 3v4M3 5h4M6 17v4M4 19h4M13 3l2.5 6.5L22 12l-6.5 2.5L13 21l-2.5-6.5L4 12l6.5-2.5z" />
          </svg>
          Draft with AI
        </div>
        <p className="draft-hint">
          Each variant is a full independent draft (2–8 per set). The variants re-state the same
          brief differently, so a leaked question doesn’t help.
        </p>

        <div className="field">
          <label htmlFor="brief">Brief</label>
          <textarea
            id="brief"
            rows={3}
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            placeholder="e.g. Given N integers, return the length of the longest strictly increasing contiguous run."
          />
        </div>

        <div className="grid3">
          <div className="field">
            <label htmlFor="language">Reference language</label>
            <select
              id="language"
              value={language}
              onChange={(e) => setLanguage(e.target.value as Language)}
            >
              {LANGUAGES.map((lang) => (
                <option key={lang} value={lang}>
                  {lang}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="difficulty">Difficulty</label>
            <select id="difficulty" value={difficulty} onChange={(e) => setDifficulty(e.target.value)}>
              <option value="easy">easy</option>
              <option value="medium">medium</option>
              <option value="hard">hard</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="count">Variants</label>
            <input
              id="count"
              type="number"
              min={2}
              max={8}
              value={count}
              onChange={(e) => setCount(Math.max(2, Math.min(8, Number(e.target.value) || 2)))}
            />
          </div>
        </div>

        <div className="field">
          <label htmlFor="tc">Target complexity (optional)</label>
          <input
            id="tc"
            value={targetComplexity}
            onChange={(e) => setTargetComplexity(e.target.value)}
            placeholder="e.g. O(n log n)"
          />
        </div>

        <button type="button" className="btn accent" onClick={handleDraft} disabled={drafting}>
          {drafting ? 'Drafting…' : `Draft ${count} variants`}
        </button>
      </div>

      {variants && (
        <div className="draft-body">
          {setWarnings.length > 0 ? (
            <div className="draft-warnings">
              <strong>Check these before saving</strong>
              <ul>
                {setWarnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="parity-ok">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 6L9 17l-5-5" />
              </svg>
              Parity checked — all {variants.length} variants sit in the same difficulty band.
            </div>
          )}

          <div className="field">
            <label htmlFor="title">Set title</label>
            <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>

          <div className="variant-list">
            {variants.map((v, i) => (
              <div key={i} className="variant-card">
                <div className="variant-hd">
                  {v.label && <span className="variant-badge">{v.label}</span>}
                  <span className="variant-title">{v.question.title}</span>
                </div>
                <div className="chip-row">
                  {v.question.required_complexity && (
                    <span className="chip chip-neutral mono">{v.question.required_complexity}</span>
                  )}
                  {v.question.constraints && (
                    <span className="chip chip-neutral">{v.question.constraints}</span>
                  )}
                  <span className="chip chip-neutral">
                    {v.question.test_cases.length} cases
                  </span>
                </div>
                {v.warnings.length > 0 && (
                  <ul className="variant-warnings">
                    {v.warnings.map((w, j) => (
                      <li key={j}>{w}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>

          <div className="form-actions">
            <button type="button" className="btn sec" onClick={handleDraft} disabled={drafting}>
              Re-draft
            </button>
            <button type="button" className="btn" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : 'Save variant set'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
