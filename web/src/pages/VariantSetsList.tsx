import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { difficultyClass } from '../badges'
import { Pager } from '../components/Pager'
import type { VariantSetSummary } from '../types'

// 25, not 100: the pager below has always been rendered, but at 100 it only
// appeared for workspaces large enough that the silent truncation had
// already bitten. A page you can see the end of is a page you can trust.
const PAGE_SIZE = 25

/** The variant-set list, without a page head of its own — it is rendered as the
 *  "Variant sets" tab of the question library (U07), which supplies the title
 *  and the create button. */
export function VariantSetsList() {
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
                      <Link
                        to={`/variant-sets/${s.id}`}
                        className="t-title"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {s.title}
                      </Link>
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
