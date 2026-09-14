import { useEffect, useId, useRef, type ReactNode } from 'react'

/** A right-hand sheet for the detail behind a summary number (U06).
 *
 *  A native <dialog> driven from state, exactly like ConfirmDialog — the browser
 *  supplies the focus trap, Esc and the backdrop, and the CSS only moves it to
 *  the edge. A drawer rather than a route because the thing it explains (the
 *  question list) stays on screen behind it, which is the whole point of opening
 *  one number at a time.
 */
export function Drawer({
  open,
  title,
  hint,
  children,
  onClose,
}: {
  open: boolean
  title: string
  /** The one-line qualifier the card heads already carry, e.g. "passed vs total". */
  hint?: string
  children: ReactNode
  onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const el = ref.current
    if (el && open && !el.open) el.showModal()
  }, [open])

  // Unmounted when shut, rather than hidden like ConfirmDialog: a closed
  // <dialog> still holds its subtree, so several of these on one page would all
  // mount their charts and tables at once — which is the cost U06 exists to
  // remove. Removing the element from the DOM is also what closes it.
  if (!open) return null

  return (
    <dialog ref={ref} className="drawer" aria-labelledby={titleId} onClose={onClose}>
      <div className="drawer-head">
        <div>
          <h2 id={titleId}>{title}</h2>
          {hint && <span className="hint">{hint}</span>}
        </div>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6 6 18M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div className="drawer-body">{children}</div>
    </dialog>
  )
}
