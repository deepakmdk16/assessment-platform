import type { DifficultyVerdict } from './types'

/** Map a status/verdict string to a colour variant for the .chip component. */
export function badgeClass(value: string | null | undefined): string {
  const v = (value ?? '').toLowerCase()
  if (['active', 'done', 'pass'].includes(v)) return 'chip chip-good'
  if (['revoked', 'error', 'fail'].includes(v)) return 'chip chip-bad'
  // TLE is a failure the candidate can act on (too slow), not a wrong answer —
  // warn keeps it visually distinct from FAIL in the per-test table.
  // `expired` is derived client-side (see invites.ts): the server stores only
  // active/revoked, so an expired link arrives labelled active.
  if (['running', 'pending', 'tle', 'expired'].includes(v)) return 'chip chip-warn'
  return 'chip chip-neutral'
}

/** Map a difficulty label (easy/medium/hard) to its .chip colour variant. */
export function difficultyClass(value: string | null | undefined): string {
  const v = (value ?? '').toLowerCase()
  if (v === 'easy') return 'chip chip-easy'
  if (v === 'medium') return 'chip chip-medium'
  if (v === 'hard') return 'chip chip-hard'
  return 'chip chip-neutral'
}

/** A candidate's 1-5 rating of a sitting (P2b) as a .chip variant: the top of the
 *  scale reads good, the bottom reads warn — never bad, because a low rating is
 *  the candidate's opinion, not a failure of theirs. */
export function ratingClass(rating: number): string {
  if (rating >= 4) return 'chip chip-good'
  if (rating <= 2) return 'chip chip-warn'
  return 'chip chip-neutral'
}

/** The difficulty verdict in the words everyone reads — the candidate's own
 *  choices on the feedback form and the interviewer's label for what they chose,
 *  which must stay the same words. */
export const DIFFICULTY_LABELS: Record<DifficultyVerdict, string> = {
  too_easy: 'Too easy',
  fair: 'About right',
  too_hard: 'Too hard',
}

export function difficultyVerdictLabel(value: DifficultyVerdict): string {
  return DIFFICULTY_LABELS[value]
}
