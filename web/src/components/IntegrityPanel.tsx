/** The interviewer's view of a sitting's integrity signals (I1): summary counts,
 *  then the timeline. Evidence for a human — it never touches the verdict. */

import type { IntegrityEvent, IntegrityReport } from '../types'

/** Offsets are from the candidate's own start, so they line up with the clock
 *  without any date arithmetic. */
function atLabel(ms: number): string {
  const total = Math.floor(ms / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `+${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
}

/** A duration in words — "3m 51s", "11s". */
function durationLabel(ms: number): string {
  const total = Math.round(ms / 1000)
  if (total < 60) return `${total}s`
  return `${Math.floor(total / 60)}m ${total % 60}s`
}

/** Severity drives the rail colour: a blocked paste is the one signal that is
 *  hard to explain innocently; leaving the tab or fullscreen is worth a look;
 *  an in-page paste or a browser that refused fullscreen is only context. */
function severity(e: IntegrityEvent): string {
  if (e.kind === 'paste_external') return 'sev-bad'
  if (e.kind === 'paste_internal' || e.kind === 'fullscreen_denied') return ''
  return 'sev-warn'
}

function label(e: IntegrityEvent): string {
  switch (e.kind) {
    case 'focus_loss':
      return 'Left the assessment tab'
    case 'fullscreen_exit':
      return 'Exited fullscreen'
    case 'fullscreen_denied':
      return 'Browser refused fullscreen'
    case 'paste_external':
      return 'Paste from outside the page'
    case 'paste_internal':
      return 'Pasted within the editor'
    case 'devtools':
      return 'Developer tools appear to have opened'
    default:
      return e.kind
  }
}

function detail(e: IntegrityEvent): string | null {
  const parts: string[] = []
  if (e.size != null) parts.push(`${e.size.toLocaleString()} characters`)
  if (e.duration_ms != null) {
    parts.push(
      e.kind === 'focus_loss'
        ? `away ${durationLabel(e.duration_ms)}`
        : `returned after ${durationLabel(e.duration_ms)}`,
    )
  }
  if (e.kind === 'paste_internal') parts.push('allowed — copied from this page')
  if (e.kind === 'fullscreen_denied') parts.push('sitting continued unlocked')
  if (e.question_title) parts.push(`on ${e.question_title}`)
  return parts.length > 0 ? parts.join(' · ') : null
}

export function IntegrityPanel({ report }: { report: IntegrityReport }) {
  const { monitored, summary, events } = report

  // Recorded signals always win over the monitored flag: if a sitting produced
  // events, showing them is never wrong, whereas suppressing them would hide
  // real evidence. Only a sitting with nothing recorded needs the disclaimer.
  if (!monitored && events.length === 0) {
    return (
      <div className="integrity">
        <h3>Integrity</h3>
        <p className="empty-state">
          This sitting ran unmonitored, so there is nothing to report — an empty timeline here says
          nothing either way.
        </p>
      </div>
    )
  }

  return (
    <div className="integrity">
      <h3>Integrity</h3>
      {summary.total === 0 ? (
        <p className="empty-state">
          <span className="chip chip-good">No signals</span>
          Stayed in fullscreen, no outside pastes, never left the tab.
        </p>
      ) : (
        <>
          <div className="integrity-summary">
            {summary.pastes_blocked > 0 && (
              <span className="chip chip-bad">
                {summary.pastes_blocked} paste{summary.pastes_blocked === 1 ? '' : 's'} blocked
              </span>
            )}
            {summary.focus_losses > 0 && (
              <span className="chip chip-warn">
                {summary.focus_losses} tab switch{summary.focus_losses === 1 ? '' : 'es'}
                {summary.away_ms > 0 ? ` · ${durationLabel(summary.away_ms)} away` : ''}
              </span>
            )}
            {summary.fullscreen_exits > 0 && (
              <span className="chip chip-warn">
                {summary.fullscreen_exits} fullscreen exit{summary.fullscreen_exits === 1 ? '' : 's'}
              </span>
            )}
            {summary.devtools_opens > 0 && <span className="chip chip-warn">devtools opened</span>}
          </div>
          <ul className="integrity-list">
            {events.map((e, i) => (
              <li className={`ev ${severity(e)}`} key={`${e.kind}-${e.offset_ms}-${i}`}>
                <span className="ev-at">{atLabel(e.offset_ms)}</span>
                <span className="ev-rail" aria-hidden="true" />
                <span className="ev-main">
                  <span className="ev-label">
                    {label(e)}
                    {e.kind === 'paste_external' && (
                      <span className="chip chip-bad">{e.blocked ? 'blocked' : 'not blocked'}</span>
                    )}
                  </span>
                  {detail(e) && <span className="ev-detail">{detail(e)}</span>}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

/** The header chip: how many signals, at a glance. Null when there are none, so
 *  a clean sitting stays visually quiet. */
export function IntegrityChip({ report }: { report: IntegrityReport }) {
  if (!report.monitored || report.summary.total === 0) return null
  const severe = report.summary.pastes_blocked > 0
  return (
    <span
      className={severe ? 'chip chip-bad' : 'chip chip-warn'}
      title="Integrity signals recorded during this sitting"
    >
      Integrity · {report.summary.total}
    </span>
  )
}

/** One candidate's signal count in the assessment attempts grid. Distinguishes
 *  three states that must not look alike: an unmonitored sitting (nothing to
 *  record), a monitored one with nothing recorded, and one with signals. */
export function IntegrityCell({
  signals,
  blocked,
}: {
  signals?: number | null
  blocked: number
}) {
  if (signals == null) return <span className="muted">Not monitored</span>
  if (signals === 0) return <span className="muted">—</span>
  return (
    <span
      className={blocked > 0 ? 'chip chip-bad' : 'chip chip-warn'}
      title={
        blocked > 0
          ? `${signals} signals, including ${blocked} blocked paste${blocked === 1 ? '' : 's'}`
          : `${signals} signal${signals === 1 ? '' : 's'} recorded during this sitting`
      }
    >
      {signals}
    </span>
  )
}
