/** Candidate-facing integrity UI (I1): the disclosure on the start screen, and
 *  the two things enforcement puts on top of the editor — the fullscreen prompt
 *  and the blocked-paste message. Capture itself lives in `../integrity.ts`. */

import { useState } from 'react'
import type { IntegrityState } from '../integrity'
import { fullscreenSupported } from '../integrity'

/** Shown on the start gate, before the candidate identifies themselves — nothing
 *  is recorded until the sitting begins, and they read this first. */
export function IntegrityNotice() {
  return (
    <div className="integrity-notice" role="note">
      <span className="integrity-notice-title">This sitting is monitored</span>
      <ul>
        {fullscreenSupported() && (
          <li>It runs in fullscreen. Leaving fullscreen pauses you until you return.</li>
        )}
        <li>Pasting code from outside this page is blocked.</li>
        <li>Tab switches and developer-tools use are recorded and shared with the interviewer.</li>
      </ul>
    </div>
  )
}

/** The blocking fullscreen prompt + the blocked-paste message, rendered over the
 *  editor. Renders nothing when the sitting is unmonitored or nothing is wrong. */
export function IntegrityOverlay({
  integrity,
  remainingLabel,
  onSubmitAndLeave,
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
}) {
  const { mustReturnToFullscreen, pasteBlocked, dismissPasteBlock } = integrity
  if (!mustReturnToFullscreen && !pasteBlocked) return null

  return (
    <>
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
}: {
  integrity: IntegrityState
  remainingLabel?: string | null
  onSubmitAndLeave?: (() => void) | null
}) {
  const { fullscreenExits } = integrity
  const [leaving, setLeaving] = useState(false)

  return (
    <div
      className="modal-scrim"
      role="dialog"
      aria-modal="true"
      aria-labelledby={leaving ? 'leave-title' : 'fs-title'}
    >
      <div className="modal">
        {leaving ? (
          <>
            <h2 id="leave-title">Leave the assessment?</h2>
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
            <h2 id="fs-title">Return to fullscreen to continue</h2>
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
          </>
        )}
      </div>
    </div>
  )
}
