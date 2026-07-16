/** Map a status/verdict string to a colour variant for the .chip component. */
export function badgeClass(value: string | null | undefined): string {
  const v = (value ?? '').toLowerCase()
  if (['active', 'done', 'pass'].includes(v)) return 'chip chip-good'
  if (['revoked', 'error', 'fail'].includes(v)) return 'chip chip-bad'
  if (['running', 'pending'].includes(v)) return 'chip chip-warn'
  return 'chip chip-neutral'
}
