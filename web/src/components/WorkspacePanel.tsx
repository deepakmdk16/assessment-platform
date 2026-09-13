/** Settings → Workspace: the branding candidates see, and that every new
 *  assessment is created with (P3b).
 *
 *  It belongs to the *organisation*, not to whoever is looking at it, so only an
 *  admin can change it. A member is shown the result — the header preview — and
 *  none of the controls: an option someone cannot use is not an explanation.
 *
 *  The logo saves the moment it is chosen rather than waiting for the name's
 *  Save button. An upload is not a form field: it has one obvious outcome, and
 *  a picked file sitting unsaved behind a button is how people end up with a
 *  logo they think they set.
 */

import { useEffect, useId, useRef, useState } from 'react'
import { ApiError, api, logoSrc } from '../api'
import type { Organization } from '../types'

const MAX_KB = 256

export function WorkspacePanel() {
  const fileId = useId()
  const nameId = useId()
  const fileInput = useRef<HTMLInputElement>(null)
  const [org, setOrg] = useState<Organization | null>(null)
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void api
      .getOrg()
      .then((next) => {
        if (cancelled) return
        setOrg(next)
        setName(next.name)
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Couldn’t load the workspace.')
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSaveName() {
    setError(null)
    setSaved(false)
    setSaving(true)
    try {
      setOrg(await api.renameOrg(name.trim()))
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Couldn’t save the name.')
    } finally {
      setSaving(false)
    }
  }

  async function handlePick(file: File | undefined) {
    if (!file) return
    setError(null)
    // Checked here as well as on the server, because the failure a 5 MB phone
    // photo would otherwise produce is the body-size middleware's: a different
    // number from the hint above, phrased in bytes, after uploading all 5 MB of
    // it to find out.
    if (file.size > MAX_KB * 1024) {
      setError(`That file is ${Math.round(file.size / 1024)} KB. Logos are limited to ${MAX_KB} KB.`)
      if (fileInput.current) fileInput.current.value = ''
      return
    }
    setBusy(true)
    try {
      setOrg(await api.setOrgLogo(file))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Couldn’t upload that logo.')
    } finally {
      setBusy(false)
      // Clear the input, or choosing the same file twice fires no change event.
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function handleRemove() {
    setError(null)
    setBusy(true)
    try {
      setOrg(await api.clearOrgLogo())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Couldn’t remove the logo.')
    } finally {
      setBusy(false)
    }
  }

  if (!org) {
    return (
      <div className="card pad muted">{error ? <span role="alert">{error}</span> : 'Loading…'}</div>
    )
  }

  const isAdmin = org.role === 'admin'
  const logo = org.logo_sha ? logoSrc(org.logo_sha) : null
  // What the candidate will see, from the saved name — not the box being typed
  // in, which would make the preview claim a name nobody has saved.
  const shownName = org.name

  return (
    <div className="card pad">
      <div className="card-title">Branding</div>
      <p className="draft-hint">
        {isAdmin
          ? 'What candidates see on the assessment header, and what every new assessment is pre-filled with.'
          : 'What candidates see on the assessment header when they open one of your organisation’s assessments.'}
      </p>

      <div className="stack">
        {isAdmin && (
          <div className="field org-name-field">
            <label htmlFor={nameId}>Organization name</label>
            <input
              id={nameId}
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setSaved(false)
              }}
            />
            <p className="field-hint">
              Also names this workspace on the Team page and in organisation invitations.
            </p>
          </div>
        )}

        <div>
          <span className="field-label">Logo</span>
          <div className="logo-row">
            <div className={logo ? 'logo-tile' : 'logo-tile empty'}>
              {logo ? <img src={logo} alt={`${shownName} logo`} /> : <span>No logo</span>}
            </div>
            <div className="logo-meta">
              {isAdmin && (
                <div className="logo-actions">
                  <span className="file-pick">
                    <input
                      ref={fileInput}
                      id={fileId}
                      type="file"
                      accept="image/png,image/jpeg,image/webp"
                      disabled={busy}
                      onChange={(e) => void handlePick(e.target.files?.[0])}
                    />
                    <label htmlFor={fileId} className="btn sec">
                      {busy ? 'Working…' : logo ? 'Replace logo' : 'Upload logo'}
                    </label>
                  </span>
                  {logo && (
                    <button
                      type="button"
                      className="btn danger sm"
                      onClick={() => void handleRemove()}
                      disabled={busy}
                    >
                      Remove
                    </button>
                  )}
                </div>
              )}
              {isAdmin && (
                <p className="field-hint">
                  PNG, JPEG or WebP, up to {MAX_KB}&nbsp;KB. Larger images are scaled to 512&nbsp;px.
                  SVG isn&rsquo;t accepted. The file is re-encoded on upload, which strips any camera
                  or location data it carried.
                </p>
              )}
            </div>
          </div>
        </div>

        <div>
          <span className="field-label">What the candidate sees</span>
          <div className="ide-title-preview">
            {logo && <img src={logo} alt="" className="ide-brand-logo" />}
            <span>{shownName} &mdash; Coding assessment</span>
          </div>
        </div>
      </div>

      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {saved && <p className="form-success">Saved.</p>}
      {isAdmin && (
        <div className="card-actions">
          <button
            type="button"
            className="btn accent"
            onClick={() => void handleSaveName()}
            disabled={saving || !name.trim() || name.trim() === org.name}
          >
            {saving ? 'Saving…' : 'Save name'}
          </button>
          <span className="field-hint">The logo saves as soon as you pick it.</span>
        </div>
      )}
    </div>
  )
}
