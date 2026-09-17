/** Candidate-facing integrity UI (I1): the disclosure on the start screen, and
 *  the two things enforcement puts on top of the editor — the fullscreen prompt
 *  and the blocked-paste message. Capture itself lives in `../integrity.ts`. */

import { useEffect, useId, useRef, useState } from 'react'
import type { IntegrityState } from '../integrity'
import { fullscreenSupported } from '../integrity'
import { SittingHelpLine } from './SittingHelp'

/** Shown on the start gate, before the candidate identifies themselves — nothing
 *  is recorded until the sitting begins, and they read this first.
 *
 *  A disclosure since U04: the three bullets plus the AI notice pushed the start
 *  button below the fold on a laptop, which is the last place to hide a control.
 *  What is being recorded stays in the visible summary — only the mechanics of
 *  each rule move behind the toggle, so nothing a candidate is consenting to is
 *  a click away. */
export function IntegrityNotice() {
  return (
    <details className="disclose warn" role="note">
      <summary>
        <b>This sitting is monitored</b>
        <span>
          {fullscreenSupported() ? 'Fullscreen, pasting blocked, ' : 'Pasting blocked, '}
          tab switches recorded.
        </span>
      </summary>
      <IntegrityRules />
    </details>
  )
}

/** What monitoring actually does, as the candidate is told it — on the start
 *  screen where they consent, and again in the sitting's help drawer, which is
 *  the only place they can re-read it without leaving (R2-039).
 *
 *  One component rather than two copies on purpose: every sentence here has a
 *  row in docs/CLAIMS.md naming the test that proves it, and a second copy
 *  somewhere else is a second thing to keep in step with the code.
 *
 *  The developer-tools line is deliberately narrower than it used to be
 *  (R2-040). The old wording promised that every use of developer tools was
 *  seen, which was not true: the heuristic notices a window/viewport gap opening
 *  during the sitting, so devtools undocked into their own window, or already
 *  open before the candidate started, pass unnoticed. It now says only what it
 *  can actually see. */
export function IntegrityRules() {
  return (
    <ul>
      {fullscreenSupported() && (
        <li>It runs in fullscreen. Leaving fullscreen pauses you until you return.</li>
      )}
      <li>Pasting code from outside this page is blocked.</li>
      <li>Tab switches are recorded and shared with the interviewer.</li>
      <li>Opening developer tools is recorded when the browser makes it visible to the page.</li>
    </ul>
  )
}

/** How long they were gone, in the words a person would use. */
function awayLabel(ms: number): string {
  const seconds = Math.round(ms / 1000)
  if (seconds < 60) return `${seconds} second${seconds === 1 ? '' : 's'}`
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return rest === 0
    ? `${minutes} minute${minutes === 1 ? '' : 's'}`
    : `${minutes}m ${rest}s`
}

/** The blocking fullscreen prompt, the blocked-paste message, and the
 *  acknowledgement that a tab switch was seen, rendered over the editor. Renders
 *  nothing when the sitting is unmonitored or nothing is wrong. */
export function IntegrityOverlay({
  integrity,
  remainingLabel,
  onSubmitAndLeave,
  supportEmail,
}: {
  integrity: IntegrityState
  /** e.g. "24:18 left" — the clock keeps running while they're out of fullscreen,
   *  and saying so is the point. Omitted for an untimed sitting. */
  remainingLabel?: string | null
  /** "Submit and leave" from the leave dialog (P2a). The parent decides what
   *  submitting means here — the one answer, or every written one — and asks
   *  for its own confirmation first. Null when nothing can be submitted, which
   *  disables the button rather than hiding the choice. */
  onSubmitAndLeave?: (() => void) | null
  /** Where to write for help. The prompt below covers the top bar, and with it
   *  the Help button, so this is the stuck candidate's only address (R2-039). */
  supportEmail?: string | null
}) {
  const { mustReturnToFullscreen, pasteBlocked, dismissPasteBlock, awayNotice, dismissAwayNotice } =
    integrity
  if (!mustReturnToFullscreen && !pasteBlocked && !awayNotice) return null

  return (
    <>
      {/* Welcome back, and yes — that was recorded (U05). A tab switch is the
          one thing a browser gives a page no way to block, so saying it was
          seen is the whole of what can be done about it; staying silent left
          the candidate believing nothing happened. Dismissible, not blocking:
          they consented to being monitored, not to being locked out. */}
      {awayNotice && (
        <div className="editor-hint away" role="status">
          <span>
            <strong>You left this tab for {awayLabel(awayNotice.durationMs)}.</strong> That was
            recorded and is shared with the interviewer, as the start screen said. The clock kept
            running.
          </span>
          <button type="button" className="btn-link" onClick={dismissAwayNotice}>
            Dismiss
          </button>
        </div>
      )}
      {pasteBlocked && (
        <div className="editor-hint blocked" role="alert">
          <span>
            <strong>Paste blocked.</strong> That text came from outside the assessment (
            {pasteBlocked.size.toLocaleString()} characters). Copying and pasting within the editor
            still works.
          </span>
          <button type="button" className="btn-link" onClick={dismissPasteBlock}>
            Dismiss
          </button>
        </div>
      )}
      {mustReturnToFullscreen && (
        <FullscreenPrompt
          integrity={integrity}
          remainingLabel={remainingLabel}
          onSubmitAndLeave={onSubmitAndLeave}
          supportEmail={supportEmail}
        />
      )}
    </>
  )
}

/** The prompt while the candidate is out of fullscreen, and the leave dialog it
 *  opens (P2a). Mounted only while the prompt is up, so re-entering fullscreen
 *  discards a half-open leave dialog and the next exit starts from the prompt. */
function FullscreenPrompt({
  integrity,
  remainingLabel,
  onSubmitAndLeave,
  supportEmail,
}: {
  integrity: IntegrityState
  remainingLabel?: string | null
  onSubmitAndLeave?: (() => void) | null
  supportEmail?: string | null
}) {
  const { fullscreenExits } = integrity
  const [leaving, setLeaving] = useState(false)
  const ref = useRef<HTMLDialogElement>(null)
  const promptId = useId()
  const leaveId = useId()

  // A native <dialog>, opened modally, like every other dialog in the app
  // (R2-038): the browser then owns the focus trap, so Tab cannot walk into the
  // editor behind the scrim. It used to be a plain div wearing role="dialog",
  // which announces a trap to a screen reader without providing one.
  useEffect(() => {
    const el = ref.current
    if (el && !el.open) el.showModal()
  }, [])

  return (
    <dialog
      ref={ref}
      className="modal"
      aria-labelledby={leaving ? leaveId : promptId}
      // Escape must not dismiss this one. It is the gate that stops the sitting
      // while the candidate is out of fullscreen, and the editor behind it is
      // read-only: dismissing it would leave them staring at a frozen page with
      // nothing to act on.
      onCancel={(e) => e.preventDefault()}
    >
      <div className="stack">
        {leaving ? (
          <>
            <h2 id={leaveId}>Leave the assessment?</h2>
            <ul className="modal-facts">
              <li>Your work so far is autosaved.</li>
              <li>
                {remainingLabel ? `The clock keeps running: ${remainingLabel}.` : 'There’s no time limit.'}
              </li>
              <li>
                {remainingLabel
                  ? 'This link works until time runs out, so you can come back and continue.'
                  : 'This link stays open until you submit, so you can come back and continue.'}
              </li>
            </ul>
            <div className="modal-actions">
              <button
                type="button"
                className="btn"
                onClick={() => {
                  setLeaving(false)
                  void integrity.enterFullscreen()
                }}
              >
                Return to fullscreen
              </button>
              {/* Stays on this dialog: the parent asks for confirmation on top of
                  it, and a Cancel there lands back here, not on the prompt. */}
              <button
                type="button"
                className="btn sec"
                disabled={!onSubmitAndLeave}
                onClick={() => onSubmitAndLeave?.()}
              >
                Submit and leave
              </button>
            </div>
          </>
        ) : (
          <>
            <h2 id={promptId}>Return to fullscreen to continue</h2>
            <p>
              Your assessment must run in fullscreen.
              {remainingLabel ? ` The clock is still running — ${remainingLabel}.` : ''} The
              interviewer sees each time you leave.
            </p>
            <div className="modal-actions">
              <button
                type="button"
                className="btn submit"
                onClick={() => void integrity.enterFullscreen()}
              >
                Re-enter fullscreen
              </button>
              <button type="button" className="btn sec" onClick={() => setLeaving(true)}>
                Leave assessment
              </button>
              <span className="chip chip-warn">
                {fullscreenExits} {fullscreenExits === 1 ? 'exit' : 'exits'} recorded
              </span>
            </div>
            <SittingHelpLine supportEmail={supportEmail} />
          </>
        )}
      </div>
    </dialog>
  )
}
