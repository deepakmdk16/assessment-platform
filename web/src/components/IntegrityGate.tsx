/** Candidate-facing integrity UI (I1): the disclosure on the start screen, and
 *  the two things enforcement puts on top of the editor — the fullscreen prompt
 *  and the blocked-paste message. Capture itself lives in `../integrity.ts`. */

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
}: {
  integrity: IntegrityState
  /** e.g. "24:18 left" — the clock keeps running while they're out of fullscreen,
   *  and saying so is the point. Omitted for an untimed sitting. */
  remainingLabel?: string | null
}) {
  const { mustReturnToFullscreen, fullscreenExits, pasteBlocked, dismissPasteBlock } = integrity
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
        <div className="modal-scrim" role="dialog" aria-modal="true" aria-labelledby="fs-title">
          <div className="modal">
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
              <span className="chip chip-warn">
                {fullscreenExits} {fullscreenExits === 1 ? 'exit' : 'exits'} recorded
              </span>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
