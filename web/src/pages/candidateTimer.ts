// Shared candidate-flow timer helpers (no JSX), used by both the single-question
// CandidatePage and the multi-question AssessmentFlow.

import { parseServerDate } from '../invites'

/** How far this browser's clock sits from the server's, in ms (R2-028).
 *
 *  `server_now` comes back from /start; `receivedAtMs` is the browser's own clock
 *  at the moment the response landed. Add the result to `Date.now()` and you have
 *  the server's time, which is the only clock the deadline means anything on: a
 *  laptop three minutes fast auto-submitted the candidate three minutes early,
 *  and a slow one let them run past the deadline and be recorded `late`.
 *
 *  The measurement carries one network hop, so it is right to within the
 *  response's own latency — tens of milliseconds against a countdown in minutes.
 */
export function clockOffsetMs(serverNowIso: string, receivedAtMs: number = Date.now()): number {
  return parseServerDate(serverNowIso).getTime() - receivedAtMs
}

/** The server's clock, as this browser can best tell it. */
export function serverNow(offsetMs: number, nowMs: number = Date.now()): number {
  return nowMs + offsetMs
}

// Countdown urgency thresholds (ms): amber under 5 min, red under 1 min.
export const WARN_MS = 5 * 60 * 1000
export const CRIT_MS = 60 * 1000

/** Class for the timer chip given its remaining ms. */
export function timerClass(ms: number): string {
  return ms <= CRIT_MS ? 'timer crit' : ms <= WARN_MS ? 'timer warn' : 'timer'
}

/** Remaining time as m:ss (or h:mm:ss past an hour), floored at zero. */
export function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}
