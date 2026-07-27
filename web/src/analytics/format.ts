// Pure formatting helpers for the analytics dashboard (AR1). No JSX / no I/O so
// they're unit-testable. Rates are fractions in [0, 1]; scores are 0..100;
// durations are seconds. Every "no data" case renders as an em dash.

const DASH = '—'

const pad2 = (n: number) => String(n).padStart(2, '0')

/** A rate/percentage from a [0,1] fraction, e.g. 0.58 -> "58%". Null -> "—". */
export function pct(fraction: number | null | undefined, digits = 0): string {
  if (fraction == null) return DASH
  return `${(fraction * 100).toFixed(digits)}%`
}

/** A score (already 0..100) to one decimal, e.g. 71.4. Null -> "—". */
export function score(value: number | null | undefined, digits = 1): string {
  if (value == null) return DASH
  return value.toFixed(digits)
}

/** A duration in seconds as a compact "Hh MMm" / "Mm SSs" / "Ss". Null -> "—". */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return DASH
  const total = Math.round(seconds)
  if (total >= 3600) {
    const h = Math.floor(total / 3600)
    const m = Math.floor((total % 3600) / 60)
    return `${h}h ${pad2(m)}m`
  }
  if (total >= 60) {
    const m = Math.floor(total / 60)
    const s = total % 60
    return `${m}m ${pad2(s)}s`
  }
  return `${total}s`
}

/** The .meter-fill colour modifier for a pass rate: green (default, "") when
 *  healthy, amber when middling, red when poor. Empty for the base green. */
export function meterClass(rate: number | null | undefined): string {
  if (rate == null) return ''
  if (rate >= 0.7) return ''
  if (rate >= 0.4) return 'warn'
  return 'bad'
}

/** English ordinal for a whole number: 1 -> "1st", 22 -> "22nd", 13 -> "13th". */
export function ordinal(n: number): string {
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`
  switch (n % 10) {
    case 1:
      return `${n}st`
    case 2:
      return `${n}nd`
    case 3:
      return `${n}rd`
    default:
      return `${n}th`
  }
}

/** A percentile fraction as an ordinal label, e.g. 0.83 -> "83rd". Null -> "—". */
export function percentileLabel(fraction: number | null | undefined): string {
  if (fraction == null) return DASH
  return ordinal(Math.round(fraction * 100))
}

/** The histogram bar colour class for a bucket keyed by its lower edge:
 *  red below 40, amber 40–60, green at/above 60. */
export function bucketClass(low: number): string {
  if (low < 40) return 'lo'
  if (low < 60) return 'mid'
  return 'hi'
}
