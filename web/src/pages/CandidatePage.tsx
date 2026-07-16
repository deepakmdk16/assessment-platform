import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import Editor from '@monaco-editor/react'
import { api, ApiError } from '../api'
import type { InviteGetResponse, Language } from '../types'

type Stage =
  | 'loading'
  | 'invalid'
  | 'expired'
  | 'error'
  | 'gate'
  | 'editor'
  | 'submitted'
  | 'already_submitted'

export function CandidatePage() {
  const { token } = useParams<{ token: string }>()
  const [stage, setStage] = useState<Stage>('loading')
  const [invite, setInvite] = useState<InviteGetResponse | null>(null)

  const [candidateName, setCandidateName] = useState('')
  const [candidateEmail, setCandidateEmail] = useState('')

  const [language, setLanguage] = useState<Language | ''>('')
  const [code, setCode] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const [consoleTab, setConsoleTab] = useState<'testcase' | 'result'>('testcase')
  const [runNote, setRunNote] = useState<string | null>(null)

  useEffect(() => {
    if (!token) return
    api
      .getInvite(token)
      .then((data) => {
        setInvite(data)
        setLanguage(data.languages[0] ?? '')
        setStage('gate')
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) setStage('invalid')
        else if (err instanceof ApiError && err.status === 410) setStage('expired')
        else setStage('error')
      })
  }, [token])

  function handleGateSubmit(e: FormEvent) {
    e.preventDefault()
    setStage('editor')
  }

  function handleRun() {
    setConsoleTab('result')
    setRunNote(
      'Running against the sample is coming soon. Use Submit to grade your solution against the full test suite.',
    )
  }

  async function handleSubmitCode(e: FormEvent) {
    e.preventDefault()
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
        title="Already submitted"
        body="A solution has already been submitted for this email address on this assessment."
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
            see the problem and a code editor on the next screen.
          </p>
          <div className="stack">
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
            <button type="submit" className="btn submit block">
              Start assessment
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
        <span className="chip chip-neutral">Time limit {q?.time_limit_s}s</span>
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
          </div>

          <div className="editor-wrapper">
            <Editor
              height="100%"
              language={language || undefined}
              value={code}
              onChange={(value) => setCode(value ?? '')}
              theme="vs-dark"
              options={{ minimap: { enabled: false }, fontSize: 13, scrollBeyondLastLine: false }}
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
                hasExample ? (
                  <>
                    <span className="io-label">Input</span>
                    <pre className="code">{q?.example_input}</pre>
                    <span className="io-label">Expected</span>
                    <pre className="code">{q?.example_output}</pre>
                  </>
                ) : (
                  <p className="muted">No sample test case provided for this problem.</p>
                )
              ) : (
                <p className="muted">{runNote ?? 'Run your code to see output here.'}</p>
              )}
            </div>
          </div>

          <form className="actionbar" onSubmit={handleSubmitCode}>
            {submitError && (
              <p role="alert" className="form-error">
                {submitError}
              </p>
            )}
            <button type="button" className="btn sec" onClick={handleRun}>
              Run
            </button>
            <button type="submit" className="btn submit" disabled={submitting}>
              {submitting ? 'Submitting…' : 'Submit'}
            </button>
          </form>
        </section>
      </div>
    </div>
  )
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
