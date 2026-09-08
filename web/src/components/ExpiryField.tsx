import { useState } from 'react'
import { EXPIRY_PRESETS, expiryFromDays, toLocalInputValue } from '../invites'

/** The expiry control shared by all three invite dialogs.
 *
 *  `InviteCreate.expires_at` has been accepted by every invite route, returned
 *  on every invite and typed in the SPA since it shipped, and no screen ever set
 *  it. That matters more than it sounds: assessment and variant-set invites
 *  cannot be revoked at all, so a self-expiring link is the only control an
 *  interviewer has over a link that has escaped.
 *
 *  `value` is an ISO string or null (never expires), which is what the API takes.
 *
 *  The chosen preset and the past-expiry flag are state rather than derived at
 *  render time: working them out would mean reading the clock during render,
 *  which is impure and lint-enforced against. */
export function ExpiryField({
  value,
  onChange,
  idPrefix,
}: {
  value: string | null
  onChange: (next: string | null) => void
  /** Dialogs can be mounted alongside each other, so ids must not collide. */
  idPrefix: string
}) {
  const [choice, setChoice] = useState<string>(EXPIRY_PRESETS[0].label)
  const [inPast, setInPast] = useState(false)
  const selectId = `${idPrefix}-expiry`
  const customId = `${idPrefix}-expiry-custom`
  const isCustom = choice === 'custom'

  return (
    <div className="field">
      <label htmlFor={selectId}>Link expires</label>
      <select
        id={selectId}
        value={choice}
        onChange={(e) => {
          const next = e.target.value
          setChoice(next)
          setInPast(false)
          if (next === 'custom') {
            // Seed the custom picker with a week out rather than an empty field.
            onChange(expiryFromDays(7).toISOString())
            return
          }
          const preset = EXPIRY_PRESETS.find((p) => p.label === next)
          onChange(preset?.days == null ? null : expiryFromDays(preset.days).toISOString())
        }}
      >
        {EXPIRY_PRESETS.map((p) => (
          <option key={p.label} value={p.label}>
            {p.label}
          </option>
        ))}
        <option value="custom">Custom…</option>
      </select>
      {isCustom && (
        <>
          <label htmlFor={customId} className="field-hint">
            Expires at
          </label>
          <input
            id={customId}
            type="datetime-local"
            value={value ? toLocalInputValue(new Date(value)) : ''}
            onChange={(e) => {
              if (!e.target.value) {
                onChange(null)
                setInPast(false)
                return
              }
              const picked = new Date(e.target.value)
              // Say so here rather than letting the server teach it with a 422.
              setInPast(picked.getTime() <= Date.now())
              onChange(picked.toISOString())
            }}
          />
        </>
      )}
      {inPast ? (
        <p role="alert" className="form-error">
          Pick a time in the future — the server refuses an expiry that has already passed.
        </p>
      ) : (
        <p className="field-hint">
          {value
            ? `The link stops working at ${new Date(value).toLocaleString()}.`
            : 'The link works until it is revoked — and assessment and variant-set invites have no revoke yet.'}
        </p>
      )}
    </div>
  )
}
