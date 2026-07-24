import { useEffect, useRef, useState } from 'react'
import Editor from '@monaco-editor/react'
import { api, ApiError } from '../api'
import { ThemeCycleButton } from '../components/ThemeToggle'
import { useTheme } from '../theme/ThemeContext'
import { monacoTheme } from '../theme/theme'
import type {
  CandidateQuestionPublic,
  Language,
  RunResponse,
  RunTestsResponse,
} from '../types'
import { ConsoleResult } from './ConsoleResult'
import { formatRemaining, timerClass } from './candidateTimer'

interface Answer {
  code: string
  language: Language
}

interface Props {
  token: string
  candidateName: string
  candidateEmail: string
  questions: CandidateQuestionPublic[]
  languages: Language[]
  deadline: string | null
  /** Bubble a 410/404 (expired/revoked) up so the page shows the shared notice. */
  onExpired: () => void
}

/**
 * The multi-question assessment flow (T4). One sitting, several questions the
 * candidate moves between freely, each submitted independently, under one shared
 * countdown (the assessment total). Rendered by CandidatePage when an invite
 * carries more than one question; the single-question flow is unchanged.
 */
export function AssessmentFlow({
  token,
  candidateName,
  candidateEmail,
  questions,
  languages,
  deadline,
  onExpired,
}: Props) {
  const { resolved } = useTheme()

  const [current, setCurrent] = useState(0)
  const [answers, setAnswers] = useState<Record<string, Answer>>(() =>
    Object.fromEntries(questions.map((q) => [q.id, { code: '', language: languages[0] ?? '' }])),
  )
  const [submitted, setSubmitted] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(questions.map((q) => [q.id, q.submitted])),
  )
  const [submittingId, setSubmittingId] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const [consoleTab, setConsoleTab] = useState<'testcase' | 'result'>('testcase')
  const [stdin, setStdin] = useState('')
  const [running, setRunning] = useState<'run' | 'tests' | null>(null)
  const [runResult, setRunResult] = useState<RunResponse | null>(null)
  const [testsResult, setTestsResult] = useState<RunTestsResponse | null>(null)
  const [runError, setRunError] = useState<string | null>(null)

  const [remainingMs, setRemainingMs] = useState<number | null>(null)
  const [timeUp, setTimeUp] = useState(false)
  const autoSubmitFired = useRef(false)

  const cq = questions[current]
  const answer = answers[cq.id]
  const isDone = submitted[cq.id]
  const locked = isDone || timeUp
  const submittedCount = questions.filter((q) => submitted[q.id]).length

  // Switch questions and reset the scratch console (its output belonged to the
  // previous question); code/language are kept per question in `answers`. Done in
  // the handler, not an effect, so there's no setState-in-effect cascade.
  function goToQuestion(i: number) {
    setCurrent(i)
    setConsoleTab('testcase')
    setStdin('')
    setRunResult(null)
    setTestsResult(null)
    setRunError(null)
    setRunning(null)
  }

  // Shared countdown to the assessment deadline (server-authoritative).
  useEffect(() => {
    if (!deadline) return
    const tick = () => {
      const ms = new Date(deadline).getTime() - Date.now()
      setRemainingMs(ms)
      if (ms <= 0) setTimeUp(true)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [deadline])

  // At zero, auto-submit every unanswered-but-written question once, so time
  // running out records work instead of losing it.
  useEffect(() => {
    if (!timeUp || autoSubmitFired.current) return
    autoSubmitFired.current = true
    void (async () => {
      for (const q of questions) {
        if (!submitted[q.id] && answers[q.id]?.code.trim()) {
          try {
            await api.submitCandidate(token, {
              candidate_name: candidateName,
              candidate_email: candidateEmail,
              language: answers[q.id].language,
              code: answers[q.id].code,
              question_id: q.id,
            })
            setSubmitted((s) => ({ ...s, [q.id]: true }))
          } catch {
            // best-effort at the deadline — a late/failed one is dropped silently
          }
        }
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeUp])

  function patchAnswer(patch: Partial<Answer>) {
    setAnswers((a) => ({ ...a, [cq.id]: { ...a[cq.id], ...patch } }))
  }

  async function submitOne(qid: string) {
    const ans = answers[qid]
    if (!ans?.code.trim() || submitted[qid]) return
    setSubmitError(null)
    setSubmittingId(qid)
    try {
      await api.submitCandidate(token, {
        candidate_name: candidateName,
        candidate_email: candidateEmail,
        language: ans.language,
        code: ans.code,
        question_id: qid,
      })
      setSubmitted((s) => ({ ...s, [qid]: true }))
    } catch (err) {
      if (err instanceof ApiError && (err.status === 410 || err.status === 404)) onExpired()
      // 409 = already recorded (e.g. a concurrent auto-submit) — treat as done.
      else if (err instanceof ApiError && err.status === 409) {
        setSubmitted((s) => ({ ...s, [qid]: true }))
      } else setSubmitError(err instanceof ApiError ? err.message : 'Failed to submit')
    } finally {
      setSubmittingId(null)
    }
  }

  async function doRun(which: 'run' | 'tests') {
    if (!answer?.language) return
    setRunError(null)
    setRunResult(null)
    setTestsResult(null)
    setConsoleTab('result')
    setRunning(which)
    try {
      if (which === 'run') {
        setRunResult(
          await api.runCandidate(token, {
            candidate_email: candidateEmail,
            language: answer.language,
            code: answer.code,
            stdin,
            question_id: cq.id,
          }),
        )
      } else {
        setTestsResult(
          await api.runCandidateTests(token, {
            candidate_email: candidateEmail,
            language: answer.language,
            code: answer.code,
            question_id: cq.id,
          }),
        )
      }
    } catch (err) {
      if (err instanceof ApiError && (err.status === 410 || err.status === 404)) onExpired()
      else if (err instanceof ApiError && err.status === 429)
        setRunError('Too many runs in a short time. Wait a moment and try again.')
      else setRunError(err instanceof ApiError ? err.message : 'Failed to run your code')
    } finally {
      setRunning(null)
    }
  }

  const hasExample = Boolean(cq.example_input || cq.example_output)

  return (
    <div className="ide">
      <header className="ide-top">
        <span className="ide-mark" aria-hidden="true" />
        <span className="ide-title">Coding assessment</span>
        <div className="ide-top-right">
          <span className="progress">
            {submittedCount} / {questions.length} submitted
          </span>
          {deadline && !timeUp && remainingMs !== null && (
            <span className={timerClass(remainingMs)} role="timer" title="Time remaining">
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
              Time&rsquo;s up
            </span>
          )}
          <ThemeCycleButton />
        </div>
      </header>

      <div className="q-strip" role="tablist" aria-label="Questions">
        {questions.map((q, i) => (
          <button
            key={q.id}
            type="button"
            role="tab"
            aria-selected={i === current}
            className={`q-tab${i === current ? ' on' : ''}${submitted[q.id] ? ' done' : ''}`}
            onClick={() => goToQuestion(i)}
          >
            <span className="n">{submitted[q.id] ? '✓' : i + 1}</span>
            {q.title}
          </button>
        ))}
      </div>

      <div className="ide-split">
        <section className="panel">
          <div className="tabs">
            <span className="tab on">Description</span>
          </div>
          <div className="panel-body prose">
            <p className="pre-text">{cq.prompt}</p>
            {cq.constraints && (
              <>
                <h3>Constraints</h3>
                <p className="pre-text">{cq.constraints}</p>
              </>
            )}
            {hasExample && (
              <div className="example-block">
                <h3>Example</h3>
                {cq.example_input && (
                  <div className="io">
                    <span className="io-label">Input</span>
                    <pre className="code">{cq.example_input}</pre>
                  </div>
                )}
                {cq.example_output && (
                  <div className="io">
                    <span className="io-label">Output</span>
                    <pre className="code">{cq.example_output}</pre>
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
              value={answer.language}
              disabled={locked}
              onChange={(e) => patchAnswer({ language: e.target.value as Language })}
            >
              {languages.map((lang) => (
                <option key={lang} value={lang}>
                  {lang}
                </option>
              ))}
            </select>
            {isDone && (
              <span className="editor-hint muted" role="status">
                Submitted ✓
              </span>
            )}
          </div>

          <div className="editor-wrapper">
            <Editor
              height="100%"
              language={answer.language || undefined}
              value={answer.code}
              onChange={(value) => patchAnswer({ code: value ?? '' })}
              theme={monacoTheme(resolved)}
              options={{
                readOnly: locked,
                minimap: { enabled: false },
                fontSize: 13,
                scrollBeyondLastLine: false,
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
                      <pre className="code">{cq.example_input}</pre>
                      <span className="io-label">Sample output</span>
                      <pre className="code">{cq.example_output}</pre>
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
                      placeholder={cq.example_input ?? 'Type the input your program reads…'}
                    />
                  </div>
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

          <div className="actionbar">
            {submitError && (
              <p role="alert" className="form-error">
                {submitError}
              </p>
            )}
            <button
              type="button"
              className="btn sec"
              onClick={() => doRun('run')}
              disabled={running !== null || locked || !answer.code}
            >
              {running === 'run' ? 'Running…' : 'Run'}
            </button>
            <button
              type="button"
              className="btn sec"
              onClick={() => doRun('tests')}
              disabled={running !== null || locked || !answer.code}
            >
              {running === 'tests' ? 'Running tests…' : 'Run against test cases'}
            </button>
            <button
              type="button"
              className="btn submit"
              onClick={() => submitOne(cq.id)}
              disabled={locked || submittingId !== null || running !== null || !answer.code}
            >
              {submittingId === cq.id ? 'Submitting…' : isDone ? 'Submitted' : 'Submit this question'}
            </button>
          </div>
        </section>
      </div>
    </div>
  )
}
