import { useEffect, useId, useRef, type ReactNode } from 'react'

interface Props {
  open: boolean
  title: string
  /** The body: what is about to happen and what cannot be undone. */
  children: ReactNode
  confirmLabel: string
  onConfirm: () => void
  /** Cancel, Esc and the backdrop all end here. */
  onCancel: () => void
}

/** Asks the candidate to confirm an irreversible step (P2a). A native <dialog>
 *  driven from state, like the interviewer's edit dialogs: the browser supplies
 *  the focus trap, Esc and the backdrop. Focus lands on Cancel first, so a
 *  stray Enter cannot submit. */
export function ConfirmDialog({ open, title, children, confirmLabel, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  return (
    <dialog ref={ref} className="modal" aria-labelledby={titleId} onClose={onCancel}>
      <div className="stack">
        <h2 id={titleId}>{title}</h2>
        {children}
        <div className="modal-actions">
          <button type="button" className="btn sec" onClick={onCancel}>
            Cancel
          </button>
          <button type="button" className="btn submit" onClick={onConfirm}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </dialog>
  )
}
