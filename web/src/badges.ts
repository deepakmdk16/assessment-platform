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
