import { useEffect } from 'react'

/** Ask the browser to confirm before the page unloads while `active` (P2a) —
 *  while an editor is open with work not yet submitted. The browser shows its
 *  own generic "Leave site?" dialog; the wording cannot be customised, and most
 *  browsers only show it once the candidate has interacted with the page.
 *  Switching tab or app cannot be blocked at all, only detected — that is what
 *  `integrity.ts` records. */
export function useLeaveGuard(active: boolean): void {
  useEffect(() => {
    if (!active) return
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault()
      // Older browsers read this instead of the cancelled default.
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [active])
}
