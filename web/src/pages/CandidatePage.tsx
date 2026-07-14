import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router-dom'
import Editor from '@monaco-editor/react'
import { api, ApiError } from '../api'
import type { InviteGetResponse, Language } from '../types'

type Stage = 'loading' | 'invalid' | 'expired' | 'error' | 'gate' | 'editor' | 'submitted'

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
      setSubmitError(err instanceof ApiError ? err.message : 'Failed to submit')
    } finally {
      setSubmitting(false)
    }
  }

  if (stage === 'loading') return <p className="page-loading">Loading…</p>
  if (stage === 'invalid') return <p className="form-error">This invite link is invalid.</p>
  if (stage === 'expired') return <p className="form-error">This invite link has expired.</p>
  if (stage === 'error') return <p className="form-error">Something went wrong. Please try again later.</p>

  if (stage === 'submitted') {
    return (
      <div className="page">
        <h1>Submitted</h1>
        <p>Thanks, {candidateName}! Your solution has been submitted successfully.</p>
      </div>
    )
  }

  if (stage === 'gate') {
    return (
      <div className="auth-page">
        <form className="auth-form" onSubmit={handleGateSubmit}>
          <h1>{invite?.question.title}</h1>
          <p>Enter your details to begin the assessment.</p>
          <label htmlFor="candidate_name">Name</label>
          <input
            id="candidate_name"
            value={candidateName}
            onChange={(e) => setCandidateName(e.target.value)}
            required
          />
          <label htmlFor="candidate_email">Email</label>
          <input
            id="candidate_email"
            type="email"
            value={candidateEmail}
            onChange={(e) => setCandidateEmail(e.target.value)}
            required
          />
          <button type="submit">Start</button>
        </form>
      </div>
    )
  }

  // stage === 'editor'
  return (
    <div className="candidate-split">
      <section className="candidate-prompt">
        <h1>{invite?.question.title}</h1>
        <h2>Prompt</h2>
        <p className="pre-text">{invite?.question.prompt}</p>
        <h2>Constraints</h2>
        <p className="pre-text">{invite?.question.constraints}</p>
        <h2>Example</h2>
        <pre>{invite?.question.example_input}</pre>
        <pre>{invite?.question.example_output}</pre>
        <p>Time limit: {invite?.question.time_limit_s}s</p>
      </section>

      <section className="candidate-editor">
        <form className="editor-form" onSubmit={handleSubmitCode}>
          <label htmlFor="language">Language</label>
          <select
            id="language"
            value={language}
            onChange={(e) => setLanguage(e.target.value as Language)}
          >
            {invite?.languages.map((lang) => (
              <option key={lang} value={lang}>
                {lang}
              </option>
            ))}
          </select>

          <div className="editor-wrapper">
            <Editor
              height="100%"
              language={language || undefined}
              value={code}
              onChange={(value) => setCode(value ?? '')}
              theme="vs-dark"
            />
          </div>

          {submitError && (
            <p role="alert" className="form-error">
              {submitError}
            </p>
          )}
          <button type="submit" disabled={submitting}>
            {submitting ? 'Submitting…' : 'Submit'}
          </button>
        </form>
      </section>
    </div>
  )
}
