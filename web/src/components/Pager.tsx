interface PagerProps {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
}

/** Table-footer pager. Renders nothing when everything fits on one page, so a
 *  short list looks exactly as it did before pagination existed. */
export function Pager({ total, limit, offset, onChange }: PagerProps) {
  if (total <= limit) return null

  const from = offset + 1
  const to = Math.min(offset + limit, total)
  const page = Math.floor(offset / limit) + 1
  const pages = Math.ceil(total / limit)

  return (
    <div className="pager">
      <div className="pager-range">
        Showing{' '}
        <b>
          {from}–{to}
        </b>{' '}
        of <b>{total}</b>
      </div>
      <div className="pager-controls">
        <button
          type="button"
          className="btn sec sm"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M15 18l-6-6 6-6" />
          </svg>
          Prev
        </button>
        <span className="pager-page">
          Page {page} of {pages}
        </span>
        <button
          type="button"
          className="btn sec sm"
          disabled={offset + limit >= total}
          onClick={() => onChange(offset + limit)}
        >
          Next
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <path d="M9 6l6 6-6 6" />
          </svg>
        </button>
      </div>
    </div>
  )
}
