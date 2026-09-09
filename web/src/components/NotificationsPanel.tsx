/** Settings → Notifications (X23): where a finished sitting's result is sent.
 *
 *  The email to whoever sent the invitation is unconditional and needs no
 *  configuration, so it is described here rather than offered as a switch. What
 *  IS configurable is the organisation's own endpoint (X06's signed webhook).
 *
 *  The word "webhook" is deliberately absent from every string a user reads —
 *  the person in this panel is a hiring admin, not an integrator. The technical
 *  contract lives in the "What we send" block at the bottom, where whoever is
 *  actually wiring up the endpoint will look for it.
 *
 *  Admin-only, and it renders nothing at all for a plain member rather than
 *  showing disabled controls — the same choice PrivacyPanel and the Team tab
 *  make.
 */

import { useEffect, useState } from 'react'
import { api, ApiError } from '../api'

/** Mirrors the server's `Annotated[str, Field(max_length=2000)]`. Reported here
 *  before the round trip; the server refuses it either way. */
const MAX_URL = 2000

export function NotificationsPanel() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loaded, setLoaded] = useState(false)
  /** The URL as saved on the server — what "unchanged" is measured against. */
  const [savedUrl, setSavedUrl] = useState<string | null>(null)
  const [url, setUrl] = useState('')
  const [secret, setSecret] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void api
      .getOrg()
      .then((org) => {
        if (cancelled) return
        setIsAdmin(org.role === 'admin')
        setSavedUrl(org.results_webhook_url)
        setUrl(org.results_webhook_url ?? '')
        setLoaded(true)
      })
      .catch(() => {
        if (!cancelled) setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  function reset() {
    setError(null)
    setSaved(false)
    setCopied(false)
  }

  async function handleSave() {
    reset()
    const trimmed = url.trim()
    if (!trimmed) {
      setError('Enter the address results should be posted to, or press Stop sending.')
      return
    }
    if (trimmed.length > MAX_URL) {
      setError('That address is too long.')
      return
    }
    setBusy(true)
    try {
      const org = await api.setResultsWebhook(trimmed)
      setSavedUrl(org.results_webhook_url)
      setUrl(org.results_webhook_url ?? '')
      // Only ever REPLACE the shown secret, never clear it. Null here is not a
      // failure — it means this save minted nothing, so the secret already on
      // screen is still the live one. Overwriting it with null would wipe an
      // un-copied secret off the screen on a second Save, and getting it back
      // costs a rotation that breaks whatever endpoint is already configured.
      if (org.results_webhook_secret) setSecret(org.results_webhook_secret)
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save that address')
    } finally {
      setBusy(false)
    }
  }

  async function handleStop() {
    reset()
    setBusy(true)
    try {
      const org = await api.setResultsWebhook(null)
      setSavedUrl(org.results_webhook_url)
      setUrl('')
      setSecret(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not stop sending results')
    } finally {
      setBusy(false)
    }
  }

  async function handleCopy() {
    if (!secret) return
    try {
      await navigator.clipboard.writeText(secret)
      setCopied(true)
    } catch {
      // Clipboard access can be refused (permissions, an insecure origin). The
      // secret is on screen and selectable, so this is a missing convenience,
      // not a dead end — say so instead of claiming a copy that never happened.
      setCopied(false)
      setError('Could not copy automatically — select the secret and copy it.')
    }
  }

  if (!loaded) return <div className="card pad muted">Loading…</div>
  if (!isAdmin) return null

  const configured = savedUrl !== null

  return (
    <>
      <h2 className="section-title">Notifications</h2>
      <div className="card pad">
        <div className="card-title">Send results to another system</div>
        <p className="draft-hint">
          When a candidate finishes, we email whoever sent their invitation. You can also
          have each result posted to your own system — an applicant tracker, or a chat
          channel — the moment it&rsquo;s graded.
        </p>

        {saved && !secret && (
          <p className="form-success" role="status">
            Saved. Results will be posted from now on.
          </p>
        )}

        <div className="stack">
          <div className="field">
            <label htmlFor="results_webhook_url">Where should we post results?</label>
            <input
              id="results_webhook_url"
              type="url"
              placeholder="https://acme.example.com/hooks/assessments"
              value={url}
              onChange={(e) => {
                setUrl(e.target.value)
                reset()
              }}
            />
            <p className="hint-tight">An https address reachable on the public internet.</p>
          </div>

          {secret && (
            <div className="field">
              <label htmlFor="results_webhook_secret">Signing secret</label>
              <div className="secret">
                <code id="results_webhook_secret">{secret}</code>
                <button type="button" className="btn sec" onClick={handleCopy}>
                  {copied ? 'Copied' : 'Copy'}
                </button>
              </div>
              <div className="form-warning" role="alert">
                <p>
                  Copy this now — we won&rsquo;t show it again. Every request we send is
                  signed with it, and your endpoint should check that signature before
                  trusting the result.
                </p>
              </div>
            </div>
          )}

          {configured && !secret && (
            <div className="field">
              <span className="field-label">Signing secret</span>
              <div className="secret">
                <span className="secret-state">
                  <span className="dot on" /> Set — hidden since you saved it
                </span>
              </div>
              <p className="hint-tight">
                Lost it? Stop sending, then save the address again to issue a new one.
                Re-saving the same address on its own changes nothing.
              </p>
            </div>
          )}
        </div>

        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}

        <div className="card-actions">
          <button type="button" className="btn accent" onClick={handleSave} disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          {configured && (
            <button type="button" className="btn danger" onClick={handleStop} disabled={busy}>
              Stop sending
            </button>
          )}
        </div>
      </div>

      {configured && <WhatWeSend />}
    </>
  )
}

/** The contract, for whoever is wiring up the receiving end. Shown only once an
 *  endpoint exists — before that it is documentation for a decision nobody has
 *  made yet, and it would crowd out the one field that matters. */
function WhatWeSend() {
  return (
    <div className="card pad">
      <div className="card-title">What we send</div>
      <p className="draft-hint">
        One POST per finished sitting, signed{' '}
        <code>X-Assess-Signature: t=&lt;unix&gt;,v1=&lt;hmac-sha256&gt;</code> over the exact
        request body, using the secret above.
      </p>
      <pre className="code-sample">{`{
  "event": "results.ready",
  "organization_id": 1,
  "invite_id": 42,
  "title": "Backend Screen",
  "candidate": { "name": "Jane Doe", "email": "jane@example.com" },
  "results_url": "https://app.example.com/submissions/8f2c…",
  "results": [
    { "question_id": "sum_of_n", "verdict": "PASS", "score_pct": 100.0 }
  ]
}`}</pre>
    </div>
  )
}
