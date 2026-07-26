import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { difficultyClass } from '../badges'
import { VariantSetInvitePanel } from '../components/VariantSetInvitePanel'
import type { VariantSetOut } from '../types'

export function VariantSetDetailPage() {
  const { id = '' } = useParams()
  const [set, setSet] = useState<VariantSetOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .getVariantSet(id)
      .then((s) => {
        if (!cancelled) setSet(s)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof ApiError ? err.message : 'Failed to load variant set')
      })
    return () => {
      cancelled = true
    }
  }, [id])

  if (error) return <p className="form-error">{error}</p>
  if (set === null) return <p className="page-loading">Loading…</p>

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>{set.title}</h1>
          <div className="sub">
            Variant set · {set.variants.length} variants · created{' '}
            {new Date(set.created_at).toLocaleDateString()}
          </div>
          <div className="chip-row">
            {set.difficulty && (
              <span className={difficultyClass(set.difficulty)}>{set.difficulty}</span>
            )}
            {set.target_complexity && (
              <span className="chip chip-neutral mono">{set.target_complexity}</span>
            )}
            <span className="chip chip-neutral">{set.language}</span>
          </div>
        </div>
      </div>

      <div className="card pad">
        <div className="card-title">Brief</div>
        <p className="prose">{set.brief}</p>
      </div>

      <h2 className="sect-title">Variants</h2>
      <div className="variant-list">
        {set.variants.map((v) => (
          <div key={v.id} className="variant-card">
            <div className="variant-hd">
              {v.variant_label && <span className="variant-badge">{v.variant_label}</span>}
              <Link to={`/questions/${v.id}`} className="variant-title">
                {v.title}
              </Link>
            </div>
            <div className="chip-row">
              {v.required_complexity && (
                <span className="chip chip-neutral mono">{v.required_complexity}</span>
              )}
              {v.constraints && <span className="chip chip-neutral">{v.constraints}</span>}
            </div>
          </div>
        ))}
      </div>

      <p className="detail-note">
        A variant is a full question — editing one won’t change any invite already sent, since each
        invite keeps the variant it was handed.
      </p>

      <h2 className="sect-title">Assign &amp; invite</h2>
      <VariantSetInvitePanel setId={set.id} variants={set.variants} />
    </div>
  )
}
