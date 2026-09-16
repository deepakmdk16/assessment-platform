/** A way to ask for help without leaving the sitting (R2-039).
 *
 *  `support_email` used to reach the start gate and nowhere else, so the moment
 *  a candidate clicked Start they were in fullscreen with no address and no
 *  route back to one — and if the fullscreen prompt had them, nothing on screen
 *  but two buttons. The button lives in the sitting's top bar and opens the same
 *  right-hand `Drawer` the interviewer side uses; the fullscreen prompt carries
 *  its own one-line copy of the address, because the top bar is behind that
 *  dialog's backdrop.
 *
 *  Deliberately not a contact form: the finding is that the candidate has no
 *  address, and an address fixes it. A form would need a route, a store, and a
 *  surface for the interviewer to read it on.
 */

import { useState } from 'react'
import { Drawer } from './Drawer'
import { IntegrityRules } from './IntegrityGate'

/** The address, as a link, or nothing at all.
 *
 *  Absent rather than empty when the deploy configures no address — the same
 *  rule the start gate already follows. A dead `mailto:` is worse than no line:
 *  it looks like a way out and is not. */
function SupportAddress({ email }: { email: string }) {
  return (
    <a className="support-link" href={`mailto:${email}`}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="m3 7 9 6 9-6" />
      </svg>
      {email}
    </a>
  )
}

export function SittingHelp({
  supportEmail,
  proctored,
  remainingLabel,
}: {
  supportEmail?: string | null
  /** Monitored sittings get the rules block; an unmonitored one has no rules to
   *  re-read, and showing them would describe monitoring that isn't happening. */
  proctored: boolean
  /** e.g. "24:13 left", or null when untimed. The top bar's clock is behind the
   *  backdrop while this is open, so it is repeated at the foot. */
  remainingLabel?: string | null
}) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        className="icon-btn help"
        aria-haspopup="dialog"
        aria-label="Help"
        onClick={() => setOpen(true)}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="12" cy="12" r="9" />
          <path d="M9.2 9.2a2.8 2.8 0 1 1 3.6 2.7c-.6.2-.8.7-.8 1.3v.4" />
          <path d="M12 17.3h.01" />
        </svg>
        {/* Hidden below the narrow breakpoint by CSS; `aria-label` carries the
            name either way, exactly as the theme button does. */}
        <span className="icon-btn-label">Help</span>
      </button>

      <Drawer
        open={open}
        title="Help"
        hint="Your work stays open behind this."
        onClose={() => setOpen(false)}
      >
        <div className="stack">
          {supportEmail && (
            <div className="help-block">
              <h3>Something not working?</h3>
              <p>Write to the team running this assessment. Say which question you are on.</p>
              <SupportAddress email={supportEmail} />
            </div>
          )}
          {proctored && (
            <div className="help-block">
              <h3>What is recorded</h3>
              <IntegrityRules />
            </div>
          )}
          <div className="help-block">
            <h3>Finishing</h3>
            <p>Submit with the button under the editor. You can’t change your code after that.</p>
          </div>
          <p className="drawer-foot">
            {remainingLabel
              ? `${remainingLabel} on the clock — it keeps running while this is open.`
              : 'No time limit on this sitting.'}
          </p>
        </div>
      </Drawer>
    </>
  )
}

/** The same address on the fullscreen prompt, which covers the top bar and so
 *  hides the button above (R2-039). One line, not a second drawer: stacking a
 *  dialog on a dialog is how focus traps get broken, and S04 exists partly
 *  because this app's dialogs mismanaged focus. */
export function SittingHelpLine({ supportEmail }: { supportEmail?: string | null }) {
  if (!supportEmail) return null
  return (
    <p className="help-line">
      Stuck? <a href={`mailto:${supportEmail}`}>{supportEmail}</a>
    </p>
  )
}
