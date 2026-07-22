import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import Editor from '@monaco-editor/react'
import { api, ApiError } from '../api'
import { badgeClass } from '../badges'
import type { InviteStartResponse, Language, RunResponse, RunTestsResponse } from '../types'

type Stage =
  | 'loading'
  | 'invalid'
  | 'expired'
  | 'error'
  | 'gate'
  | 'editor'
  | 'submitted'
  | 'already_submitted'

// Autosave the in-progress solution to localStorage, keyed by the invite token,
// so a reload (or the ErrorBoundary catching a render throw) doesn't lose the
// candidate's work. Cleared once the attempt is recorded.
interface Draft {
  code: string
  language: string
}

const DRAFT_PREFIX = 'assessment-draft:'

// Countdown urgency thresholds (ms): amber under 5 min, red under 1 min.
const WARN_MS = 5 * 60 * 1000
const CRIT_MS = 60 * 1000

/** Remaining time as m:ss (or h:mm:ss past an hour), floored at zero. */
function formatRemaining(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

function loadDraft(token: string): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT_PREFIX + token)
    return raw ? (JSON.parse(raw) as Draft) : null
  } catch {
    return null
  }
}

function saveDraft(token: string, draft: Draft): void {
  try {
    localStorage.setItem(DRAFT_PREFIX + token, JSON.stringify(draft))
  } catch {
    // Private mode / quota exceeded — autosave is best-effort, so drop it silently.
  }
}

function clearDraft(token: string): void {
  try {
    localStorage.removeItem(DRAFT_PREFIX + token)
  } catch {
    // ignore
  }
}

export function CandidatePage() {
  const { token } = useParams<{ token: string }>()
  const [stage, setStage] = useState<Stage>('loading')
  const [invite, setInvite] = useState<InviteStartResponse | null>(null)

  const [candidateName, setCandidateName] = useState('')
  const [candidateEmail, setCandidateEmail] = useState('')
  const [gateError, setGateError] = useState<string | null>(null)
  const [starting, setStarting] = useState(false)

  const [language, setLanguage] = useState<Language | ''>('')
  const [code, setCode] = useState('')
  const [draftRestored, setDraftRestored] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

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

  // Probe the link only — the question isn't served until the gate below proves
  // the visitor is one of the invited recipients.
  useEffect(() => {
    if (!token) return
    api
      .getInvite(token)
      .then(() => setStage('gate'))
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
    if (stage !== 'editor' || !token) return
    const t = setTimeout(() => saveDraft(token, { code, language }), 500)
    return () => clearTimeout(t)
  }, [stage, token, code, language])

  useEffect(() => {
    if (token && (stage === 'submitted' || stage === 'already_submitted')) clearDraft(token)
  }, [stage, token])

  async function handleGateSubmit(e: FormEvent) {
    e.preventDefault()
    if (!token) return
    setGateError(null)
    setStarting(true)
    try {
      const data = await api.startInvite(token, candidateEmail)
      setInvite(data)
      setDeadline(data.deadline ?? null)
      // Restore an autosaved draft for this invite, if any; only keep a saved
      // language that's still offered, else fall back to the first choice.
      const saved = loadDraft(token)
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
      setStage('editor')
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
    setSubmitError(null)
    setSubmitting(true)
    try {
      await api.submitCandidate(token, {
        candidate_name: candidateName,
        candidate_email: candidateEmail,
        language,
        code,
      })
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
    void doSubmit()
  }

  // Tick the countdown once a second while the editor is open and the assessment
  // is timed. Reads the server deadline against the local clock — the server is
  // the real authority (it enforces the deadline on submit); this is the display.
  useEffect(() => {
    if (stage !== 'editor' || !deadline) return
    const tick = () => {
      const ms = new Date(deadline).getTime() - Date.now()
      setRemainingMs(ms)
      if (ms <= 0) setTimeUp(true)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [stage, deadline])

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

  if (stage === 'gate') {
    return (
      <div className="auth">
        <form className="auth-card" onSubmit={handleGateSubmit}>
          <span className="auth-eyebrow">Invitation</span>
          <h1>Coding assessment</h1>
          <p className="auth-lead">
            You’ve been invited to a timed coding assessment. Enter your details to begin — you’ll
            see the problem and a code editor on the next screen. Use the email address your invite
            was sent to.
          </p>
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
            <button type="submit" className="btn submit block" disabled={starting}>
              {starting ? 'Starting…' : 'Start assessment'}
            </button>
          </div>
        </form>
      </div>
    )
  }

  // stage === 'editor'
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

          <div className="editor-wrapper">
            <Editor
              height="100%"
              language={language || undefined}
              value={code}
              onChange={(value) => {
                setCode(value ?? '')
                if (draftRestored) setDraftRestored(false)
              }}
              theme="vs-dark"
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                scrollBeyondLastLine: false,
                readOnly: timeUp,
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
              disabled={running !== null || submitting || timeUp || !code}
            >
              {running === 'run' ? 'Running…' : 'Run'}
            </button>
            <button
              type="button"
              className="btn sec"
              onClick={() => doRun('tests')}
              disabled={running !== null || submitting || timeUp || !code}
            >
              {running === 'tests' ? 'Running tests…' : 'Run against test cases'}
            </button>
            <button
              type="submit"
              className="btn submit"
              disabled={submitting || running !== null || timeUp}
            >
              {submitting ? 'Submitting…' : 'Submit'}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
}

/** The console's Result tab: output from Run, or the pass/fail strip from
 *  Run-against-test-cases. The candidate sees counts and statuses only — never
 *  a case's input or expected output. */
function ConsoleResult({
  running,
  error,
  run,
  tests,
}: {
  running: 'run' | 'tests' | null
  error: string | null
  run: RunResponse | null
  tests: RunTestsResponse | null
}) {
  if (running) return <p className="muted">Running…</p>
  if (error)
    return (
      <p role="alert" className="form-error">
        {error}
      </p>
    )

  if (run) {
    if (run.compile_error)
      return (
        <>
          <span className="io-label">Compile error</span>
          <pre className="code">{run.compile_error}</pre>
        </>
      )
    if (run.timed_out)
      return (
        <p className="form-warning">
          Your program ran out of time before it finished. It may be stuck waiting for input, or
          too slow.
        </p>
      )
    return (
      <>
        <span className="io-label">Output</span>
        <pre className="code">{run.stdout || '(no output)'}</pre>
        {run.stderr && (
          <>
            <span className="io-label">Errors</span>
            <pre className="code">{run.stderr}</pre>
          </>
        )}
        <p className="cellsub">Finished in {run.duration_s}s</p>
      </>
    )
  }

  if (tests) {
    if (tests.compile_error)
      return (
        <>
          <span className="io-label">Compile error</span>
          <pre className="code">{tests.compile_error}</pre>
        </>
      )
    const allPassed = tests.passed === tests.total && tests.total > 0
    return (
      <>
        <p className={allPassed ? 'run-summary good' : 'run-summary'}>
          {tests.passed} of {tests.total} test cases passed
        </p>
        <ul className="test-strip">
          {tests.test_cases.map((c) => (
            <li key={c.index}>
              <span className="test-strip-name">
                Test {c.index}
                {c.category === 'performance' && <span className="cellsub"> · performance</span>}
              </span>
              <span className={badgeClass(c.status)}>{c.status}</span>
              <span className="cellsub">{c.duration_s}s</span>
            </li>
          ))}
        </ul>
        <p className="cellsub">
          These are the same tests used for grading. The inputs aren’t shown — Submit when you’re
          ready to record your attempt.
        </p>
      </>
    )
  }

  return <p className="muted">Run your code to see output here.</p>
}

function CandidateNotice({ title, body }: { title: string; body: string }) {
  return (
    <div className="auth">
      <div className="auth-card notice-card">
        <h1>{title}</h1>
        <p className="muted">{body}</p>
      </div>
    </div>
  )
}
