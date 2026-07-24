// Shared candidate-flow timer helpers (no JSX), used by both the single-question
// CandidatePage and the multi-question AssessmentFlow.

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
