/** Settings → Privacy (X03): the organisation's retention window, and the
 *  erasure that answers a candidate's deletion request.
 *
 *  Both are admin-only. The panel renders nothing at all for a plain member
 *  rather than showing disabled controls — the same choice the Team tab makes,
 *  and it keeps a member from reading a policy they cannot act on as an
 *  invitation to ask.
 */

import { useEffect, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api'
import type { CandidateErasure } from '../types'

/** Matches `schemas.RetentionDays`. The floor of 1 is what stops a mis-typed 0
 *  reading as "delete everything now"; the server refuses out-of-range values
 *  either way, this only reports it before the round trip. */
const MIN_DAYS = 1
const MAX_DAYS = 3650

type Mode = 'keep' | 'window'

export function PrivacyPanel() {
  const [isAdmin, setIsAdmin] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [mode, setMode] = useState<Mode>('keep')
  const [days, setDays] = useState('365')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [eraseEmail, setEraseEmail] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [erasing, setErasing] = useState(false)
  const [erased, setErased] = useState<CandidateErasure | null>(null)
  const [eraseError, setEraseError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    void api
      .getOrg()
      .then((org) => {
        if (cancelled) return
        setIsAdmin(org.role === 'admin')
        if (org.retention_days !== null) {
          setMode('window')
          setDays(String(org.retention_days))
        }
        setLoaded(true)
      })
      .catch(() => {
        if (!cancelled) setLoaded(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleSave() {
    setError(null)
    setSaved(false)
    let value: number | null = null
    if (mode === 'window') {
      value = Number(days)
      if (!Number.isInteger(value) || value < MIN_DAYS || value > MAX_DAYS) {
        setError(`Enter a whole number of days between ${MIN_DAYS} and ${MAX_DAYS}.`)
        return
      }
    }
    setSaving(true)
    try {
      await api.setRetention(value)
      setSaved(true)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to save the retention policy')
    } finally {
      setSaving(false)
    }
  }

  async function handleErase(e: FormEvent) {
    e.preventDefault()
    setEraseError(null)
    setErased(null)
    // First submit arms the confirmation; the second one actually erases. A
    // destructive, irreversible action should take two deliberate acts, and the
    // address is right there to be re-read in between.
    if (!confirming) {
      setConfirming(true)
      return
    }
    setErasing(true)
    try {
      const result = await api.eraseCandidate(eraseEmail.trim())
      setErased(result)
      setEraseEmail('')
      setConfirming(false)
    } catch (err) {
      setEraseError(err instanceof ApiError ? err.message : 'Failed to erase candidate data')
    } finally {
      setErasing(false)
    }
  }

  if (!loaded) return <div className="card pad muted">Loading…</div>
  // Nothing at all for a plain member — including the section heading, which
  // would otherwise sit above empty space.
  if (!isAdmin) return null

  return (
    <>
      <h2 className="section-title">Privacy</h2>
      <div className="card pad">
        <div className="card-title">Data retention</div>
        <p className="draft-hint">
          How long this organisation keeps candidate data. Nothing is deleted on a schedule
          unless you set a window here.
        </p>
        <div className="stack">
          <div className="radio-set">
            <div className="radio-row">
              <input
                id="retention_keep"
                type="radio"
                name="retention"
                checked={mode === 'keep'}
                onChange={() => {
                  setMode('keep')
                  setSaved(false)
                }}
              />
              <label htmlFor="retention_keep">
                Keep until deleted
                <span className="radio-sub">
                  Sittings stay until someone erases them. This is the default.
                </span>
              </label>
            </div>
            <div className="radio-row">
              <input
                id="retention_window"
                type="radio"
                name="retention"
                checked={mode === 'window'}
                onChange={() => {
                  setMode('window')
                  setSaved(false)
                }}
              />
              <label htmlFor="retention_window">
                Delete automatically after a set period
                <span className="radio-sub">
                  Names, email addresses, submitted code, drafts and grading detail are
                  destroyed. Scores, verdicts and dates are kept, so your pass-rate history
                  doesn&rsquo;t change.
                </span>
              </label>
            </div>
          </div>
          {mode === 'window' && (
            <div className="retention-days">
              <input
                id="retention_days"
                type="number"
                min={MIN_DAYS}
                max={MAX_DAYS}
                value={days}
                aria-label="Retention period in days"
                onChange={(e) => {
                  setDays(e.target.value)
                  setSaved(false)
                }}
              />
              <span className="draft-hint">days after the candidate sits</span>
            </div>
          )}
          {mode === 'window' && (
            <div className="form-warning" role="status">
              <p>
                Turning this on applies to sittings you already hold. Anything already past the
                window is anonymised on the next sweep, within the hour.
              </p>
            </div>
          )}
        </div>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        {saved && <p className="form-success">Saved.</p>}
        <div className="card-actions">
          <button type="button" className="btn accent" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : 'Save retention policy'}
          </button>
        </div>
      </div>

      <div className="card pad danger">
        <div className="card-title">Erase a candidate</div>
        <p className="draft-hint">
          Answers a candidate&rsquo;s deletion request. Destroys their identifiers and their
          work everywhere they appear as an invited candidate — sittings, submissions, drafts
          and grading detail. This cannot be undone, and their invitation stops working, so
          reassessing them means sending a new one.
        </p>
        <form className="stack" onSubmit={handleErase}>
          <div className="field">
            <label htmlFor="erase_email">Candidate email address</label>
            <input
              id="erase_email"
              type="email"
              required
              placeholder="candidate@example.com"
              value={eraseEmail}
              onChange={(e) => {
                setEraseEmail(e.target.value)
                setConfirming(false)
                setErased(null)
              }}
            />
          </div>
          {eraseError && (
            <p role="alert" className="form-error">
              {eraseError}
            </p>
          )}
          {confirming && (
            <div className="form-warning" role="alert">
              <p>
                Erase everything for <b>{eraseEmail.trim()}</b>? Press again to confirm.
              </p>
            </div>
          )}
          <div className="card-actions">
            <button type="submit" className="btn danger" disabled={erasing}>
              {erasing ? 'Erasing…' : confirming ? 'Yes, erase permanently' : 'Erase candidate data'}
            </button>
          </div>
        </form>
        {erased && <ErasureReceipt result={erased} />}
      </div>
    </>
  )
}

/** What the erasure destroyed. Counts rather than a bare "done": the person
 *  answering the request has to be able to say what was done, and an address
 *  that held nothing would otherwise look exactly like a successful erasure. */
function ErasureReceipt({ result }: { result: CandidateErasure }) {
  if (!result.erased) {
    return (
      <p className="form-success" role="status">
        Nothing was held for {result.candidate_email}.
      </p>
    )
  }
  const counts: [number, string][] = [
    [result.submissions, result.submissions === 1 ? 'submission' : 'submissions'],
    [result.results, result.results === 1 ? 'result' : 'results'],
    [result.attempts, result.attempts === 1 ? 'sitting' : 'sittings'],
    [result.drafts_deleted, 'drafts deleted'],
    [result.integrity_events, 'integrity signals'],
    [result.invites_amended, result.invites_amended === 1 ? 'invitation amended' : 'invitations amended'],
  ]
  return (
    <div className="erasure-receipt" role="status">
      <h4>Erased {result.candidate_email}</h4>
      <dl className="erasure-counts">
        {counts.map(([value, label]) => (
          <div key={label}>
            <dt>{value}</dt>
            <dd>{label}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
