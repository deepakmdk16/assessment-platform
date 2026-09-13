import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import Editor from '@monaco-editor/react'
import { api, ApiError } from '../api'
import { parseServerDate } from '../invites'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { IntegrityNotice, IntegrityOverlay } from '../components/IntegrityGate'
import { fullscreenSupported, useIntegrity } from '../integrity'
import { useLeaveGuard } from '../leaveGuard'
import { ThemeCycleButton } from '../components/ThemeToggle'
import { useTheme } from '../theme/ThemeContext'
import { monacoTheme } from '../theme/theme'
import type {
  CandidateDraft as ServerDraft,
  InviteStartResponse,
  InviteStatusResponse,
  Language,
  RunResponse,
  RunTestsResponse,
} from '../types'
import { AssessmentFlow } from './AssessmentFlow'
import { CandidateNotice } from './CandidateNotice'
import { ConsoleResult } from './ConsoleResult'
import { CRIT_MS, formatRemaining, WARN_MS } from './candidateTimer'

type Stage =
  | 'loading'
  | 'invalid'
  | 'expired'
  | 'error'
  | 'gate'
  | 'editor'
  | 'submitted'
  | 'already_submitted'
  | 'timed_out'

// Autosave the in-progress solution to localStorage so a reload (or the
// ErrorBoundary catching a render throw) doesn't lose the candidate's work.
// Cleared once the attempt is recorded.
interface Draft {
  code: string
  language: string
  /** When this copy was written, so it can be compared against the server's. */
  saved_at?: string
}

const DRAFT_PREFIX = 'assessment-draft:'

/** A short, stable digest of the address (32-bit FNV-1a, 8 hex chars). Not
 *  cryptographic and not meant to be: the key is already scoped by invite
 *  token, so it only has to tell candidates apart without spelling their
 *  address out in localStorage, where anyone at a shared machine can read it
 *  (P2a). Synchronous on purpose — the restore runs inside the start click,
 *  and `crypto.subtle` is async. */
function digest(text: string): string {
  let h = 0x811c9dc5
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h.toString(16).padStart(8, '0')
}

/** Keyed by invite AND candidate. Keying on the token alone meant that on a
 *  shared machine the next candidate to open the same link was seeded with the
 *  previous one's unsubmitted code. */
function draftKey(token: string, candidateEmail: string): string {
  return `${DRAFT_PREFIX}${token}:${digest(candidateEmail.trim().toLowerCase())}`
}

/** The key before P2a spelled the address out. Move a draft saved under it to
 *  the hashed key, once, at the start of the sitting — so nobody mid-sitting
 *  across that deploy loses work. One place to delete when it is retired. */
function migrateLegacyDraft(token: string, candidateEmail: string): void {
  try {
    const legacyKey = `${DRAFT_PREFIX}${token}:${candidateEmail.trim().toLowerCase()}`
    const old = localStorage.getItem(legacyKey)
    if (old === null) return
    if (localStorage.getItem(draftKey(token, candidateEmail)) === null) {
      localStorage.setItem(draftKey(token, candidateEmail), old)
    }
    localStorage.removeItem(legacyKey)
  } catch {
    // ignore
  }
}

function loadDraft(token: string, candidateEmail: string): Draft | null {
  try {
    const raw = localStorage.getItem(draftKey(token, candidateEmail))
    return raw ? (JSON.parse(raw) as Draft) : null
  } catch {
    return null
  }
}

function saveDraft(token: string, candidateEmail: string, draft: Draft): void {
  try {
    localStorage.setItem(draftKey(token, candidateEmail), JSON.stringify(draft))
  } catch {
    // Private mode / quota exceeded — autosave is best-effort, so drop it silently.
  }
}

/** Whichever copy is newer, when both exist. Falls back to whichever is present.
 *  An undated local draft (written before this shipped) loses to a dated server
 *  copy — the server timestamp is the only one we can trust in that case. */
function pickDraft(local: Draft | null, server: ServerDraft | null): Draft | null {
  if (!local?.code) return server?.code ? server : null
  if (!server?.code) return local
  // `saved_at` is a real ISO instant from this browser; `updated_at` comes from
  // the API with no offset and would otherwise be read as local time, making
  // "newest wins" wrong by the viewer's UTC offset.
  const localAt = local.saved_at ? new Date(local.saved_at).getTime() : 0
  const serverAt = parseServerDate(server.updated_at).getTime()
  return serverAt > localAt ? server : local
}

function clearDraft(token: string, candidateEmail: string): void {
  try {
    localStorage.removeItem(draftKey(token, candidateEmail))
  } catch {
    // ignore
  }
}

/** What the candidate is walking into, in one sentence, before they identify
 *  themselves. "Timed" only when it is (P2a). */
function gateLead(info: InviteStatusResponse | null): string {
  const problems = (info?.question_count ?? 1) > 1 ? 'problems' : 'problem'
  const clock =
    info?.duration_minutes != null
      ? `This sitting is timed. A ${info.duration_minutes}-minute clock starts when you begin, and you’ll`
      : 'There’s no time limit. You’ll'
  return `${clock} see the ${problems} and a code editor on the next screen. Use the email address your invite was sent to.`
}

/** Questions / time / languages, from the pre-start probe (P2a). */
function GateFacts({ info }: { info: InviteStatusResponse }) {
  return (
    <dl className="gate-facts">
      <div>
        <dt>Questions</dt>
        <dd>{info.question_count ?? 1}</dd>
      </div>
      <div>
        <dt>Time</dt>
        <dd>{info.duration_minutes != null ? `${info.duration_minutes} min` : 'No limit'}</dd>
      </div>
      <div>
        <dt>Languages</dt>
        <dd>{(info.languages ?? []).join(', ')}</dd>
      </div>
    </dl>
  )
}

/** The AI-in-hiring notice (P2a): what the AI does, who decides, and how to ask
 *  for a human review. On every start screen, monitored or not. Mirrors the
 *  "Automated assessment" section of docs/PRIVACY.md — change both together. */
function AssessmentNotice({ orgName }: { orgName?: string | null }) {
  const who = orgName ? `A person at ${orgName}` : 'A person'
  return (
    <div className="gate-note" role="note">
      <span className="gate-note-title">How your work is assessed</span>
      <p>
        Your code is run against test cases and scored automatically, and an AI model writes a
        short summary of it for the interviewer. {who} makes any decision about your application,
        not the AI. To ask for a human review of your result, contact the interviewer who
        invited you.
      </p>
    </div>
  )
}

export function CandidatePage() {
  const { token } = useParams<{ token: string }>()
  const { resolved } = useTheme()
  const [stage, setStage] = useState<Stage>('loading')
  const [invite, setInvite] = useState<InviteStartResponse | null>(null)
  // A multi-question assessment invite (T4) hands off entirely to AssessmentFlow,
  // which keeps its own deadline/timeout/auto-submit state. This page's OWN
  // deadline effect below must not also run in that case — it used to fire
  // unconditionally, auto-submitting this page's (unused, empty) top-level
  // `code`/`language` state at timeout and flipping to the single-question
  // 'submitted' stage, which pre-empted AssessmentFlow's own terminal screen.
  const isMultiQuestion = Boolean(invite?.questions && invite.questions.length > 1)

  const [candidateName, setCandidateName] = useState('')
  const [candidateEmail, setCandidateEmail] = useState('')
  const [gateError, setGateError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)
  // The liveness probe: monitored or not (I1) and, since P2a, the title,
  // organisation, question count, duration and languages — what the gate says
  // before the candidate identifies themselves.
  const [gateInfo, setGateInfo] = useState<InviteStatusResponse | null>(null)
  const gateProctored = gateInfo?.proctored !== false
  // Agreement to the privacy notice and terms (X04). The server refuses a
  // sitting that begins without it; this only stops the candidate discovering
  // that through an error message.
  const [consented, setConsented] = useState(false)

  const [language, setLanguage] = useState<Language | ''>('')
  const [code, setCode] = useState('')
  const [draftRestored, setDraftRestored] = useState(false)
  // Both copies exist and differ, so the candidate chooses rather than having
  // one silently win. Null when there is nothing to choose between.
  const [draftConflict, setDraftConflict] = useState<{
    local: Draft
    server: ServerDraft
  } | null>(null)
  // Server-side drafts for this sitting (CX2), fetched once at /start. The
  // single-question restore below uses them when localStorage has nothing
  // (cleared cache / device switch); AssessmentFlow seeds its answers from them.
  const [serverDrafts, setServerDrafts] = useState<ServerDraft[]>([])
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  // The one-shot submit asks first (P2a). Only the candidate's own click opens
  // this; the deadline auto-submit calls doSubmit directly and never asks.
  const [confirmOpen, setConfirmOpen] = useState(false)

  // Server-authoritative deadline (ISO) from /start; null = untimed. The
  // countdown ticks to it, and `timeUp` flips once when it passes, triggering the
  // one-shot auto-submit below.
  const [deadline, setDeadline] = useState<string | null>(null)
  const [remainingMs, setRemainingMs] = useState<number | null>(null)
  const [timeUp, setTimeUp] = useState(false)
  const autoSubmitFired = useRef(false)

  const [consoleTab, setConsoleTab] = useState<'testcase' | 'result'>('testcase')
  const [stdin, setStdin] = useState('')
  const [running, setRunning] = useState<'run' | 'tests' | null>(null)
  const [runResult, setRunResult] = useState<RunResponse | null>(null)
  const [testsResult, setTestsResult] = useState<RunTestsResponse | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  // Integrity monitoring (I1). Owned here for BOTH candidate flows — one hook,
  // one event queue — so a multi-question sitting can't double-record; the
  // AssessmentFlow reports which question is open and renders the same overlay.
  // `proctored` is the sitting's own setting; a legacy invite omits it and is
  // monitored.
  const proctored = invite?.proctored !== false
  const [activeQuestionId, setActiveQuestionId] = useState<string | null>(null)
  // AssessmentFlow renders its own terminal screen, so `stage` stays 'editor'
  // after a multi-question sitting ends. Tracking completion separately stops
  // monitoring without pre-empting that screen.
  const [sittingComplete, setSittingComplete] = useState(false)
  const integrity = useIntegrity({
    token: token ?? '',
    candidateEmail,
    questionId: activeQuestionId,
    enabled: stage === 'editor' && proctored && !sittingComplete,
  })
  // The sitting is suspended: the gate is up and the candidate must return to
  // fullscreen. Everything that could change or submit an answer is off.
  const blocked = integrity.mustReturnToFullscreen
  // Warn before the tab closes while an unsubmitted single-question editor is
  // open (P2a). The multi-question flow guards itself, since it knows when the
  // sitting is complete.
  useLeaveGuard(stage === 'editor' && !isMultiQuestion)

  // Probe the link only — the question isn't served until the gate below proves
  // the visitor is one of the invited recipients.
  useEffect(() => {
    if (!token) return
    api
      .getInvite(token)
      .then((status) => {
        setGateInfo(status)
        setStage('gate')
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setStage('invalid')
        else if (err instanceof ApiError && err.status === 410) setStage('expired')
        else setStage('error')
      })
  }, [token])

  // Autosave the draft while editing (debounced so keystrokes don't thrash
  // localStorage), and clear it once the attempt is recorded so a later invite
  // to the same browser starts clean.
  useEffect(() => {
    // Not while a draft choice is pending: the autosave would overwrite the local
    // copy with the pre-selected winner, so choosing "this device" would restore
    // the server's code instead.
    if (stage !== 'editor' || !token || draftConflict) return
    const t = setTimeout(
      () => saveDraft(token, candidateEmail, { code, language, saved_at: new Date().toISOString() }),
      500,
    )
    return () => clearTimeout(t)
  }, [stage, token, candidateEmail, code, language, draftConflict])

  // Server-side autosave (CX2), single-question flow only — AssessmentFlow
  // saves per question itself. Gentler cadence than the localStorage one, and
  // fire-and-forget: a lost save costs at most a few seconds of typing.
  useEffect(() => {
    if (stage !== 'editor' || !token || isMultiQuestion || !code) return
    const t = setTimeout(() => {
      void api
        .saveCandidateDraft(token, {
          candidate_email: candidateEmail,
          question_id: activeQuestionId,
          code,
          language,
        })
        .catch(() => {})
    }, 2000)
    return () => clearTimeout(t)
  }, [stage, token, isMultiQuestion, code, language, candidateEmail, activeQuestionId])

  useEffect(() => {
    if (token && (stage === 'submitted' || stage === 'already_submitted'))
      clearDraft(token, candidateEmail)
  }, [stage, token, candidateEmail])

  /** Restore a whole draft, not just its code. Both halves of a draft matter:
   *  a Java answer reopened under Python does not compile. The language is
   *  validated against what this invite still offers, exactly as the initial
   *  restore does. */
  function applyDraft(draft: { code: string; language: string }) {
    setCode(draft.code)
    const offered = invite?.languages ?? []
    setLanguage(
      offered.includes(draft.language as Language)
        ? (draft.language as Language)
        : ((offered[0] ?? '') as Language),
    )
    setDraftConflict(null)
  }

  async function handleGateSubmit(e: FormEvent) {
    e.preventDefault()
    if (!token) return
    setGateError(null)
    setStarting(true)
    try {
      const data = await api.startInvite(token, candidateEmail, candidateName, consented)
      setInvite(data)
      setDeadline(data.deadline ?? null)
      // Server-side drafts for the sitting (CX2). Best-effort: a failed fetch
      // restores nothing rather than blocking the start.
      let drafts: ServerDraft[] = []
      try {
        drafts = (await api.getCandidateDrafts(token, candidateEmail)).drafts
      } catch {
        // offline / rate-limited — the localStorage path below still works
      }
      setServerDrafts(drafts)
      // Restore an autosaved draft for this invite. localStorage no longer wins
      // unconditionally: it used to, so work saved from another device — or from
      // this one after the local copy went stale — was silently hidden behind an
      // older draft. When both exist and differ, the candidate is asked; the
      // server copy carries `updated_at` and the local one now carries
      // `saved_at`, so both sides of that choice can be dated.
      const server = drafts.find((d) => d.question_id === data.questions?.[0]?.id) ?? drafts[0]
      migrateLegacyDraft(token, candidateEmail)
      const local = loadDraft(token, candidateEmail)
      const serverDraft = server?.code ? server : null
      if (local?.code && serverDraft?.code && local.code !== serverDraft.code) {
        setDraftConflict({ local, server: serverDraft })
      }
      const saved = pickDraft(local, serverDraft)
      if (saved?.code) {
        setCode(saved.code)
        setLanguage(
          data.languages.includes(saved.language as Language)
            ? (saved.language as Language)
            : (data.languages[0] ?? ''),
        )
        setDraftRestored(true)
      } else {
        setLanguage(data.languages[0] ?? '')
      }
      setActiveQuestionId(data.questions?.[0]?.id ?? null)
      setStage('editor')
      // Ask for fullscreen off the back of this click. A browser only grants it
      // from a user gesture, and the start POST above is quick enough to stay
      // inside that window; a denial is recorded and the sitting continues
      // unlocked rather than trapping the candidate on a modal.
      if (data.proctored !== false) void integrity.enterFullscreen()
    } catch (err) {
      if (!(err instanceof ApiError)) {
        setGateError('Something went wrong. Please try again.')
      } else if (err.status === 403) {
        setGateError(
          'This assessment wasn’t sent to that email address. Please use the address your invite was sent to.',
        )
      } else if (err.status === 409) {
        setStage('already_submitted')
      } else if (err.status === 410 || err.status === 404) {
        setStage('expired')
      } else {
        setGateError(err.message)
      }
    } finally {
      setStarting(false)
    }
  }

  /** Shared plumbing for the two non-grading actions. Neither consumes the
   *  candidate's single submission attempt. */
  async function doRun(which: 'run' | 'tests') {
    if (!token || !language) return
    setRunError(null)
    setRunResult(null)
    setTestsResult(null)
    setConsoleTab('result')
    setRunning(which)
    try {
      if (which === 'run') {
        setRunResult(
          await api.runCandidate(token, { candidate_email: candidateEmail, language, code, stdin }),
        )
      } else {
        setTestsResult(
          await api.runCandidateTests(token, { candidate_email: candidateEmail, language, code }),
        )
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setStage('already_submitted')
      else if (err instanceof ApiError && (err.status === 410 || err.status === 404))
        setStage('expired')
      else if (err instanceof ApiError && err.status === 429)
        setRunError('Too many runs in a short time. Wait a moment and try again.')
      else setRunError(err instanceof ApiError ? err.message : 'Failed to run your code')
    } finally {
      setRunning(null)
    }
  }

  async function doSubmit() {
    if (!token || !language) return
    if (timeUp && !code.trim()) {
      // Time ran out with nothing to record. The server rejects an empty
      // submission (422), which used to leave the candidate on a locked IDE
      // reading "submitting…" forever. Land on a terminal notice instead, as
      // the multi-question flow already does.
      integrity.flush()
      setStage('timed_out')
      return
    }
    setSubmitError(null)
    setSubmitting(true)
    try {
      await api.submitCandidate(token, {
        candidate_name: candidateName,
        candidate_email: candidateEmail,
        language,
        code,
        // Carried so a submit that is itself the start of the sitting (a reload
        // that lost the attempt, say) still records what they agreed to.
        consent: consented,
      })
      integrity.flush()  // the sitting's last signals, before this page unmounts
      setStage('submitted')
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setStage('already_submitted')
      else if (err instanceof ApiError && (err.status === 410 || err.status === 404))
        setStage('expired')
      else setSubmitError(err instanceof ApiError ? err.message : 'Failed to submit')
    } finally {
      setSubmitting(false)
    }
  }

  function handleSubmitCode(e: FormEvent) {
    e.preventDefault()
    setConfirmOpen(true)
  }

  // Tick the countdown once a second while the editor is open and the assessment
  // is timed. Reads the server deadline against the local clock — the server is
  // the real authority (it enforces the deadline on submit); this is the display.
  useEffect(() => {
    if (stage !== 'editor' || !deadline || isMultiQuestion) return
    const tick = () => {
      const ms = new Date(deadline).getTime() - Date.now()
      setRemainingMs(ms)
      if (ms <= 0) setTimeUp(true)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [stage, deadline, isMultiQuestion])

  // At zero, auto-submit whatever's in the editor — exactly once — so time running
  // out records the attempt rather than losing it.
  useEffect(() => {
    if (!timeUp || autoSubmitFired.current) return
    autoSubmitFired.current = true
    void doSubmit()
    // doSubmit reads the latest code/language via closure at fire time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeUp])

  if (stage === 'loading') return <p className="page-loading">Loading…</p>
  if (stage === 'invalid')
    return (
      <CandidateNotice title="Invalid link" body="This invite link doesn’t exist or has been removed." />
    )
  if (stage === 'expired')
    return (
      <CandidateNotice
        title="No longer active"
        body="This invite link is no longer active — it may have been revoked or expired."
      />
    )
  if (stage === 'error')
    return <CandidateNotice title="Something went wrong" body="Please try again later." />
  if (stage === 'already_submitted')
    return (
      <CandidateNotice
        title="Assessment already recorded"
        body="Your assessment has already been recorded for this email address. You can’t take it a second time — please contact your interviewer if you think this is a mistake."
      />
    )
  if (stage === 'submitted')
    return (
      <CandidateNotice
        title="Submitted ✓"
        body={`Thanks, ${candidateName}! Your solution has been submitted and is being graded.`}
      />
    )
  if (stage === 'timed_out')
    return (
      <CandidateNotice
        title="Time’s up"
        body="The time limit passed before any code was entered, so nothing was submitted. Contact your interviewer if you think this is a mistake."
      />
    )

  if (stage === 'gate') {
    return (
      <div className="auth">
        <form className="auth-card" onSubmit={handleGateSubmit}>
          <span className="auth-eyebrow">{gateInfo?.org_name ?? 'Invitation'}</span>
          <h1>{gateInfo?.assessment_title ?? 'Coding assessment'}</h1>
          <p className="auth-lead">{gateLead(gateInfo)}</p>
          {gateInfo?.languages?.length ? <GateFacts info={gateInfo} /> : null}
          {gateProctored && <IntegrityNotice />}
          <AssessmentNotice orgName={gateInfo?.org_name} />
          <div className="stack">
            {gateError && (
              <p role="alert" className="form-error">
                {gateError}
              </p>
            )}
            <div className="field">
              <label htmlFor="candidate_name">Name</label>
              <input
                id="candidate_name"
                value={candidateName}
                onChange={(e) => setCandidateName(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="candidate_email">Email</label>
              <input
                id="candidate_email"
                type="email"
                value={candidateEmail}
                onChange={(e) => setCandidateEmail(e.target.value)}
                required
              />
            </div>
            <div className="consent-check">
              <input
                id="candidate_consent"
                type="checkbox"
                checked={consented}
                onChange={(e) => setConsented(e.target.checked)}
              />
              <label htmlFor="candidate_consent">
                I’ve read the{' '}
                <a href="/privacy" target="_blank" rel="noreferrer">
                  privacy notice
                </a>{' '}
                and{' '}
                <a href="/terms" target="_blank" rel="noreferrer">
                  terms
                </a>
                , and I agree to my assessment
                {gateProctored ? ' — including the monitoring described above — ' : ' '}
                being recorded and shared with the interviewer.
              </label>
            </div>
            <button type="submit" className="btn submit block" disabled={starting || !consented}>
              {starting
                ? 'Starting…'
                : gateProctored && fullscreenSupported()
                  ? 'Enter fullscreen & start'
                  : 'Start assessment'}
            </button>
            <p className="gate-legal">
              <a href="/privacy" target="_blank" rel="noreferrer">
                Privacy
              </a>
              <span aria-hidden="true">·</span>
              <a href="/terms" target="_blank" rel="noreferrer">
                Terms
              </a>
            </p>
          </div>
        </form>
      </div>
    )
  }

  // stage === 'editor'
  // A multi-question assessment invite (T4) uses the free-navigation flow; a
  // single-question invite keeps the original single-question IDE below unchanged.
  if (token && invite && isMultiQuestion && invite.questions) {
    return (
      <AssessmentFlow
        token={token}
        candidateName={candidateName}
        candidateEmail={candidateEmail}
        questions={invite.questions}
        languages={invite.languages}
        deadline={deadline}
        assessmentTitle={invite.assessment_title}
        orgName={invite.org_name}
        logoUrl={invite.logo_url}
        integrity={integrity}
        initialDrafts={serverDrafts}
        onQuestionChange={setActiveQuestionId}
        onExpired={() => setStage('expired')}
        onComplete={() => setSittingComplete(true)}
      />
    )
  }

  const q = invite?.question
  const hasExample = Boolean(q?.example_input || q?.example_output)
  return (
    <div className="ide">
      <header className="ide-top">
        <span className="ide-mark" aria-hidden="true" />
        <span className="ide-title">{q?.title}</span>
        <div className="ide-top-right">
          <span className="chip chip-neutral">Per-test limit {q?.time_limit_s}s</span>
          {deadline && !timeUp && remainingMs !== null && (
            <span
              className={
                remainingMs <= CRIT_MS ? 'timer crit' : remainingMs <= WARN_MS ? 'timer warn' : 'timer'
              }
              role="timer"
              title="Time remaining"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="13" r="8" />
                <path d="M12 9v4l2 2M9 2h6" />
              </svg>
              {formatRemaining(remainingMs)} left
            </span>
          )}
          {deadline && timeUp && (
            <span className="timer-done" role="status">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M20 6L9 17l-5-5" />
              </svg>
              Time&rsquo;s up — submitting…
            </span>
          )}
          <ThemeCycleButton />
        </div>
      </header>

      <div className="ide-split">
        <section className="panel">
          <div className="tabs">
            <span className="tab on">Description</span>
          </div>
          <div className="panel-body prose">
            <p className="pre-text">{q?.prompt}</p>
            {q?.constraints && (
              <>
                <h3>Constraints</h3>
                <p className="pre-text">{q.constraints}</p>
              </>
            )}
            {hasExample && (
              <div className="example-block">
                <h3>Example</h3>
                {q?.example_input && (
                  <div className="io">
                    <span className="io-label">Input</span>
                    <pre className="code">{q.example_input}</pre>
                  </div>
                )}
                {q?.example_output && (
                  <div className="io">
                    <span className="io-label">Output</span>
                    <pre className="code">{q.example_output}</pre>
                  </div>
                )}
              </div>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="editor-head">
            <select
              aria-label="Language"
              className="lang-select"
              value={language}
              onChange={(e) => setLanguage(e.target.value as Language)}
            >
              {invite?.languages.map((lang) => (
                <option key={lang} value={lang}>
                  {lang}
                </option>
              ))}
            </select>
            {draftRestored && (
              <span className="editor-hint muted" role="status">
                Draft restored
              </span>
            )}
          </div>

          {draftConflict && (
            <div className="modal-scrim" role="dialog" aria-modal="true" aria-labelledby="dc-title">
              <div className="modal">
                <div className="stack">
                  <h2 id="dc-title">Two versions of your work</h2>
                  <p>
                    We found unsent work saved on this device and a different version saved from
                    your account. Pick the one you want to carry on with — the other is discarded.
                  </p>
                  <div className="modal-actions">
                    <button
                      type="button"
                      className="btn sec"
                      onClick={() => applyDraft(draftConflict.local)}
                    >
                      This device
                      {draftConflict.local.saved_at
                        ? ` · ${new Date(draftConflict.local.saved_at).toLocaleString()}`
                        : ''}
                    </button>
                    <button
                      type="button"
                      className="btn"
                      onClick={() => applyDraft(draftConflict.server)}
                    >
                      Your account · {parseServerDate(draftConflict.server.updated_at).toLocaleString()}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          )}

          <IntegrityOverlay
            integrity={integrity}
            remainingLabel={
              remainingMs !== null && remainingMs > 0 ? `${formatRemaining(remainingMs)} left` : null
            }
            onSubmitAndLeave={code.trim() ? () => setConfirmOpen(true) : null}
          />
          <ConfirmDialog
            open={confirmOpen}
            title="Submit?"
            confirmLabel="Submit"
            onCancel={() => setConfirmOpen(false)}
            onConfirm={() => {
              setConfirmOpen(false)
              // Re-check what the button checked: the dialog outlives a
              // fullscreen exit or the deadline, and neither may submit twice.
              if (submitting || timeUp || blocked) return
              void doSubmit()
            }}
          >
            <p>You can’t change your code after this.</p>
          </ConfirmDialog>

          <div className="editor-wrapper">
            <Editor
              height="100%"
              language={language || undefined}
              value={code}
              onChange={(value) => {
                setCode(value ?? '')
                if (draftRestored) setDraftRestored(false)
              }}
              theme={monacoTheme(resolved)}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                scrollBeyondLastLine: false,
                // Locked while the fullscreen gate is up, not merely covered.
                // The scrim is a pointer overlay: it never stopped the keyboard,
                // so a candidate kept typing behind a screen that claimed to
                // have blocked them, and STATUS claimed the editor was blocked.
                readOnly: timeUp || integrity.mustReturnToFullscreen,
              }}
            />
          </div>

          <div className="console">
            <div className="tabs">
              <button
                type="button"
                className={consoleTab === 'testcase' ? 'tab on' : 'tab'}
                onClick={() => setConsoleTab('testcase')}
              >
                Testcase
              </button>
              <button
                type="button"
                className={consoleTab === 'result' ? 'tab on' : 'tab'}
                onClick={() => setConsoleTab('result')}
              >
                Result
              </button>
            </div>
            <div className="console-body">
              {consoleTab === 'testcase' ? (
                <>
                  {hasExample && (
                    <>
                      <span className="io-label">Sample input</span>
                      <pre className="code">{q?.example_input}</pre>
                      <span className="io-label">Sample output</span>
                      <pre className="code">{q?.example_output}</pre>
                    </>
                  )}
                  <div className="field">
                    <label htmlFor="stdin">Your input (stdin)</label>
                    <textarea
                      id="stdin"
                      className="mono"
                      rows={4}
                      value={stdin}
                      onChange={(e) => setStdin(e.target.value)}
                      placeholder={q?.example_input ?? 'Type the input your program reads…'}
                    />
                  </div>
                  <p className="cellsub">
                    Run feeds this to your program on standard input.
                  </p>
                </>
              ) : (
                <ConsoleResult
                  running={running}
                  error={runError}
                  run={runResult}
                  tests={testsResult}
                />
              )}
            </div>
          </div>

          <form className="actionbar" onSubmit={handleSubmitCode}>
            {submitError && (
              <p role="alert" className="form-error">
                {submitError}
              </p>
            )}
            <button
              type="button"
              className="btn sec"
              onClick={() => doRun('run')}
              disabled={running !== null || submitting || timeUp || blocked || !code}
            >
              {running === 'run' ? 'Running…' : 'Run'}
            </button>
            <button
              type="button"
              className="btn sec"
              onClick={() => doRun('tests')}
              disabled={running !== null || submitting || timeUp || blocked || !code}
            >
              {running === 'tests' ? 'Running tests…' : 'Run against test cases'}
            </button>
            <button
              type="submit"
              className="btn submit"
              disabled={submitting || running !== null || timeUp || blocked || !code.trim()}
            >
              {submitting ? 'Submitting…' : 'Submit'}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}

