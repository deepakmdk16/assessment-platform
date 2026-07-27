import { meterClass, pct } from '../analytics/format'

/** Inline pass-rate meter for the question table: an SVG track + fill (coloured
 *  by the rate) beside the percentage. `rate` is a fraction in [0, 1]; null
 *  renders an empty track and an em-dash (no data yet). */
export function Meter({ rate }: { rate: number | null }) {
  const width = rate == null ? 0 : Math.max(0, Math.min(1, rate)) * 100
  return (
    <div className="meter-cell">
      <svg className="meter" viewBox="0 0 100 6" preserveAspectRatio="none" aria-hidden="true">
        <rect className="meter-track" x={0} y={0} width={100} height={6} rx={3} />
        {rate != null && (
          <rect className={`meter-fill ${meterClass(rate)}`} x={0} y={0} width={width} height={6} rx={3} />
        )}
      </svg>
      <span className={rate == null ? 'meter-val muted' : 'meter-val'}>{pct(rate)}</span>
    </div>
  )
}
