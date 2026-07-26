import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { difficultyClass } from '../badges'
import { Pager } from '../components/Pager'
import type { VariantSetSummary } from '../types'

const PAGE_SIZE = 100

export function VariantSetsListPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<VariantSetSummary[] | null>(null)
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .listVariantSets(false, offset, PAGE_SIZE)
      .then((page) => {
        if (cancelled) return
        setItems(page.items)
        setTotal(page.total)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof ApiError ? err.message : 'Failed to load variant sets')
      })
    return () => {
      cancelled = true
    }
  }, [offset])

  return (
    <div>
      <div className="page-head">
        <div>
          <h1>
            Variant sets
            {total > 0 && <span className="count">{total}</span>}
          </h1>
          <div className="sub">
            Draft several interchangeable versions of one problem, so each candidate gets a
            different-but-equivalent question.
          </div>
        </div>
        <Link to="/variant-sets/new" className="btn">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New variant set
        </Link>
      </div>

      {error && <p className="form-error">{error}</p>}
      {!error && items === null && <p className="page-loading">Loading…</p>}

      {items?.length === 0 && (
        <p className="empty-state">
          No variant sets yet. Create one to hand different candidates different siblings of the
          same problem.
        </p>
      )}

      {items && items.length > 0 && (
        <div className="card">
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Title</th>
                  <th>Variants</th>
                  <th>Difficulty</th>
                  <th>Language</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {items.map((s) => (
                  <tr
                    key={s.id}
                    className="clickable-row"
                    onClick={() => navigate(`/variant-sets/${s.id}`)}
                  >
                    <td>
                      <div className="t-title">{s.title}</div>
                    </td>
                    <td className="num">{s.variant_count}</td>
                    <td>
                      {s.difficulty ? (
                        <span className={difficultyClass(s.difficulty)}>{s.difficulty}</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>{s.language}</td>
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
