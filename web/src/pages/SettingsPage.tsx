import { useState } from 'react'
import { api, ApiError } from '../api'
import { useAuth } from '../auth/AuthContext'

export function SettingsPage() {
  const { user, refresh } = useAuth()
  const [orgName, setOrgName] = useState(user?.default_org_name ?? '')
  const [logoUrl, setLogoUrl] = useState(user?.default_logo_url ?? '')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    setError(null)
    setSaved(false)
    setSaving(true)
    try {
      await api.updateMe({
        default_org_name: orgName.trim() || null,
        default_logo_url: logoUrl.trim() || null,
      })
      await refresh()
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="wizard">
      <div className="page-head">
        <div>
          <h1>Workspace</h1>
          <div className="sub">
            Defaults for everything you create. These aren&rsquo;t applied retroactively — they
            pre-fill each new assessment, where you can still change them per assessment.
          </div>
        </div>
      </div>

      {error && (
        <p role="alert" className="form-error">
          {error}
        </p>
      )}
      {saved && <p className="form-success">Saved.</p>}

      <div className="card pad">
        <div className="card-title">Default branding</div>
        <p className="draft-hint">
          Pre-fills the branding on every new assessment so you don&rsquo;t re-enter it each time.
          Candidates see it on their IDE header when they open the assessment. Leave blank to default
          to the generic &ldquo;Coding assessment&rdquo; header.
        </p>
        <div className="stack">
          <div className="grid2">
            <div className="field">
              <label htmlFor="default_org_name">Organization name</label>
              <input
                id="default_org_name"
                placeholder="e.g. Acme Corp"
                value={orgName}
                onChange={(e) => {
                  setOrgName(e.target.value)
                  setSaved(false)
                }}
              />
            </div>
            <div className="field">
              <label htmlFor="default_logo_url">Logo URL</label>
              <input
                id="default_logo_url"
                placeholder="https://…"
                value={logoUrl}
                onChange={(e) => {
                  setLogoUrl(e.target.value)
                  setSaved(false)
                }}
              />
            </div>
          </div>
          {(orgName.trim() || logoUrl.trim()) && (
            <div className="ide-title-preview">
              {logoUrl.trim() && <img src={logoUrl.trim()} alt="" className="ide-brand-logo" />}
              <span>
                {orgName.trim() && `${orgName.trim()} — `}
                Coding assessment
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="wizard-nav">
        <button type="button" className="btn accent" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save defaults'}
        </button>
      </div>
    </div>
  )
}
