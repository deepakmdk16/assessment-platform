/** One sitting, one tab (R2-041).
 *
 *  The same invite link opened twice used to give a candidate two live tabs on
 *  one sitting, and neither knew about the other. Both recorded integrity
 *  signals, so every switch between them was logged twice as the candidate
 *  "leaving" — the away total on the interviewer's panel was inflated by ordinary
 *  window management. Both also autosaved, so whichever tab typed last won and
 *  the other tab's work was silently overwritten.
 *
 *  The lock is a claim in `localStorage`, held by whichever tab claimed it first
 *  and refreshed on a heartbeat. A tab that finds a fresh claim belonging to
 *  someone else goes read-only: it records nothing and saves nothing. A claim
 *  that stops being refreshed goes stale, so closing or crashing the first tab
 *  hands the sitting to the next one within a few seconds rather than locking
 *  the candidate out of their own assessment.
 *
 *  **A deterrent against confusion, not against cheating.** `localStorage` is
 *  per-origin and per-profile, so a second browser, a private window or another
 *  device sees no lock at all — the same honest limit the rest of the integrity
 *  story has. What this buys is that the common accident (a duplicated tab)
 *  stops corrupting the record.
 */

import { useEffect, useState } from 'react'

const LOCK_PREFIX = 'assessment-sitting:'

/** How often the holder re-stamps its claim. */
const HEARTBEAT_MS = 2_000

/** A claim older than this is taken as abandoned. Three missed heartbeats, so a
 *  tab that is merely busy (a long paint, a backgrounded timer being throttled)
 *  does not lose its own sitting. */
const STALE_MS = 7_000

interface Claim {
  tab: string
  at: number
}

function read(key: string): Claim | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as Partial<Claim>
    if (typeof parsed.tab !== 'string' || typeof parsed.at !== 'number') return null
    return { tab: parsed.tab, at: parsed.at }
  } catch {
    return null
  }
}

function write(key: string, claim: Claim): void {
  try {
    localStorage.setItem(key, JSON.stringify(claim))
  } catch {
    // Private mode / quota. Treated as "no lock available", which the caller
    // resolves in the candidate's favour — see `useSittingLock`.
  }
}

function isStale(claim: Claim, now: number): boolean {
  // `now < claim.at` means the clock moved backwards (an NTP correction, a
  // candidate changing their system time). Treat that as stale rather than
  // waiting out a claim that may be hours in the "future".
  return now - claim.at > STALE_MS || now < claim.at
}

/** True when nothing else holds this sitting right now. A read, no claim. */
function isFree(key: string | null): boolean {
  if (!key) return true
  const claim = read(`${LOCK_PREFIX}${key}`)
  return claim === null || isStale(claim, Date.now())
}

/** Whether this tab owns the sitting. `null` key = nothing to lock yet (before
 *  the candidate has identified themselves), which owns it by default: the lock
 *  exists to arbitrate between tabs of the *same* sitting. */
export function useSittingLock(key: string | null): boolean {
  const [held, setHeld] = useState(true)
  const [lockedKey, setLockedKey] = useState<string | null>(null)

  // Re-derived during render whenever the sitting changes — which includes the
  // moment it first appears, when the candidate identifies themselves. Doing
  // this in an effect instead left a tab believing it held a sitting someone
  // else was already in until the first heartbeat, and it recorded and saved
  // for that whole window. React's documented way to adjust state when a prop
  // changes; the read below has no side effects.
  if (key !== lockedKey) {
    setLockedKey(key)
    setHeld(isFree(key))
  }

  useEffect(() => {
    if (!key) return
    const storageKey = `${LOCK_PREFIX}${key}`
    // Per mount, not per module: a duplicated tab starts a fresh instance, and
    // React's development double-mount must not look like a second tab.
    const tab = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`

    const claim = (): boolean => {
      const now = Date.now()
      const existing = read(storageKey)
      if (existing !== null && existing.tab !== tab && !isStale(existing, now)) return false
      write(storageKey, { tab, at: now })
      // Re-read after writing: two tabs that claim in the same instant both
      // wrote, and the one whose write landed second owns it. localStorage has
      // no compare-and-swap, so this is the arbitration.
      const settled = read(storageKey)
      return settled === null || settled.tab === tab
    }

    const release = () => {
      // Only if it is still ours: a tab that already lost the sitting must not
      // take the winner's claim away on its way out.
      const mine = read(storageKey)
      if (mine?.tab !== tab) return
      try {
        localStorage.removeItem(storageKey)
      } catch {
        // ignore — the claim goes stale on its own
      }
    }

    // Claim now (an external-system write, not a render input) and let the
    // heartbeat report the outcome — including the case where the tab that
    // claimed a microsecond later actually won.
    claim()
    const timer = setInterval(() => setHeld(claim()), HEARTBEAT_MS)
    // React's cleanup does not run when the page is navigated away or reloaded,
    // and without this a candidate who simply reloads comes back to their own
    // claim, still inside the staleness window, and is told their sitting is
    // open in another tab. `pagehide` is the one teardown event that fires for
    // a reload, a close and a bfcache suspend alike; a bfcache restore just
    // re-claims on the next heartbeat.
    window.addEventListener('pagehide', release)

    return () => {
      clearInterval(timer)
      window.removeEventListener('pagehide', release)
      release()
    }
  }, [key])

  return held
}
