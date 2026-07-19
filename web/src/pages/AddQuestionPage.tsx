import { Fragment, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { LANGUAGES } from '../types'
import type { Language, TestCaseCategory, TestCaseIn } from '../types'

function emptyTestCase(): TestCaseIn {
  return { name: '', stdin: '', expected: '', category: 'correctness', weight: 1 }
}

interface DraftFailure {
  message: string
  /** Whether trying the same brief again could plausibly work. */
  canRetry: boolean
  /** The agent's own reason, when it's worth showing under the summary. */
  detail?: string
}

/**
 * Turn a draft failure into something an interviewer can act on.
 *
 * Drafting is an LLM call, so some failures are luck (retry) and some are not
 * (fix the config, or rewrite the brief). Saying which is the difference between
 * a useful message and a dead end.
 */
function describeDraftFailure(err: unknown): DraftFailure {
  if (!(err instanceof ApiError)) {
    return { message: 'Couldn’t draft the question. Check your connection and try again.', canRetry: true }
  }
  switch (err.status) {
    case 503:
      return {
        message:
          'AI drafting isn’t available: the server has no model API key configured. This needs an admin — retrying won’t help.',
        canRetry: false,
      }
    case 422:
      return {
        message:
          'The AI couldn’t turn this brief into a working question, even after retrying. Try making the brief more specific about the input format and what to compute — or write the question yourself below.',
        canRetry: true,
        detail: err.message,
      }
    case 429:
      return { message: 'Too many drafting requests right now. Wait a moment and try again.', canRetry: true }
    case 502:
      return {
        message: 'Couldn’t reach the AI drafting service. It may be restarting — try again in a moment.',
        canRetry: true,
      }
    case 400:
      return { message: err.message, canRetry: false }
    default:
      return { message: err.message || 'Couldn’t draft the question.', canRetry: true }
  }
}

const STEPS = ['Basics', 'Grading', 'Test cases', 'Example', 'Review'] as const
const LAST_STEP = STEPS.length - 1

export function AddQuestionPage() {
  const navigate = useNavigate()

  const [step, setStep] = useState(0)

  const [id, setId] = useState('')
  const [title, setTitle] = useState('')
  const [prompt, setPrompt] = useState('')

  const [constraints, setConstraints] = useState('')
  const [timeLimitS, setTimeLimitS] = useState(2)
  const [passThreshold, setPassThreshold] = useState(70)
  const [requiredComplexity, setRequiredComplexity] = useState('')

  const [testCases, setTestCases] = useState<TestCaseIn[]>([emptyTestCase()])

  const [exampleInput, setExampleInput] = useState('')
  const [exampleOutput, setExampleOutput] = useState('')

  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // "Draft with AI" panel (Basics step). Independent of the wizard's `error` slot
  // so a draft failure never blocks manual entry.
  const [draftOpen, setDraftOpen] = useState(false)
  const [brief, setBrief] = useState('')
  const [draftLanguage, setDraftLanguage] = useState<Language>('python')
  const [difficulty, setDifficulty] = useState('')
  const [targetComplexity, setTargetComplexity] = useState('')
  const [drafting, setDrafting] = useState(false)
  const [draftError, setDraftError] = useState<DraftFailure | null>(null)
  const [draftWarnings, setDraftWarnings] = useState<string[]>([])
  const [referenceSolution, setReferenceSolution] = useState<string | null>(null)

  async function handleDraft() {
    if (!brief.trim()) {
      setDraftError({ message: 'Enter a brief to draft from.', canRetry: false })
      return
    }
    setDraftError(null)
    // Clear any prior draft's output so a failed re-draft doesn't leave stale
    // warnings / reference solution on screen.
    setDraftWarnings([])
    setReferenceSolution(null)
    setDrafting(true)
    try {
      const res = await api.draftQuestion({
        brief,
        language: draftLanguage,
        difficulty: difficulty.trim() || undefined,
        target_complexity: targetComplexity.trim() || undefined,
      })
      const q = res.question
      setId(q.id)
      setTitle(q.title)
      setPrompt(q.prompt)
      setConstraints(q.constraints)
      setTimeLimitS(q.time_limit_s)
      // The API stores a 0..1 fraction; the wizard shows whole-number percent.
      setPassThreshold(Math.round(q.pass_threshold * 100))
      setRequiredComplexity(q.required_complexity ?? '')
      setExampleInput(q.example_input ?? '')
      setExampleOutput(q.example_output ?? '')
      setTestCases(q.test_cases.length > 0 ? q.test_cases : [emptyTestCase()])
      setDraftWarnings(res.warnings)
      setReferenceSolution(res.reference_solution)
    } catch (err) {
      setDraftError(describeDraftFailure(err))
    } finally {
      setDrafting(false)
    }
  }

  function updateTestCase(index: number, patch: Partial<TestCaseIn>) {
    setTestCases((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  function addTestCase() {
    setTestCases((rows) => [...rows, emptyTestCase()])
  }

  function removeTestCase(index: number) {
    setTestCases((rows) => rows.filter((_, i) => i !== index))
  }

  // Per-step validation (returns the first problem, or null). The wizard hides
  // later fields, so native `required` can't guard them — this does.
  function validateStep(s: number): string | null {
    if (s === 0) {
      if (!id.trim()) return 'Id is required.'
      if (!title.trim()) return 'Title is required.'
      if (!prompt.trim()) return 'Prompt is required.'
    }
    if (s === 1) {
      if (!Number.isFinite(timeLimitS) || timeLimitS < 0) return 'Time limit must be 0 or more.'
      if (passThreshold < 0 || passThreshold > 100) return 'Pass threshold must be between 0 and 100.'
    }
    if (s === 2 && testCases.some((tc) => !tc.name.trim())) {
      return 'Every test case needs a name.'
    }
    return null
  }

  function goNext() {
    const problem = validateStep(step)
    if (problem) {
      setError(problem)
      return
    }
    setError(null)
    setStep((s) => Math.min(s + 1, LAST_STEP))
  }

  function goBack() {
    setError(null)
    setStep((s) => Math.max(s - 1, 0))
  }

  async function handleCreate() {
    // Safety net: re-validate every step before the create call.
    for (let s = 0; s < LAST_STEP; s++) {
      const problem = validateStep(s)
      if (problem) {
        setError(problem)
        setStep(s)
        return
      }
    }
    setError(null)
    setSubmitting(true)
    try {
      const created = await api.createQuestion({
        id,
        title,
        prompt,
        constraints,
        time_limit_s: timeLimitS,
        // Wizard holds percent; the API/agent want a 0..1 fraction.
        pass_threshold: passThreshold / 100,
        required_complexity: requiredComplexity,
        example_input: exampleInput,
        example_output: exampleOutput,
        test_cases: testCases,
      })
      // `justCreated` opens the invite dialog once, as a nudge — inviting is
      // optional, so it offers "Skip for now" rather than blocking the page.
      navigate(`/questions/${created.id}`, { state: { justCreated: true } })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create question')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="wizard">
      <div className="page-head">
        <div>
          <h1>New question</h1>
          <div className="sub">Draft with AI or author by hand — review every step before it's saved.</div>
        </div>
      </div>

      <div className="stepper">
        {STEPS.map((label, i) => (
          <Fragment key={label}>
            {i > 0 && <div className={i <= step ? 'step-bar done' : 'step-bar'} />}
            <div
              className={i === step ? 'step on' : i < step ? 'step done' : 'step'}
              aria-current={i === step ? 'step' : undefined}
            >
              <span className="dot">{i < step ? '✓' : i + 1}</span>
              {label}
            </div>
          </Fragment>
        ))}
      </div>

      {/* No submit button lives in this form: the Create action is an explicit
          type="button" onClick below. That avoids a React footgun where clicking
          "Next" re-renders the same button position into a submit button mid-click
          and the browser then submits. preventDefault guards stray Enter presses. */}
      <form className="stack" onSubmit={(e) => e.preventDefault()}>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}

        {step === 0 && (
          <div className="draft-card">
            <button
              type="button"
              className="draft-toggle"
              aria-expanded={draftOpen}
              onClick={() => setDraftOpen((o) => !o)}
            >
              <span className="draft-hd">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
                </svg>
                Draft with AI
              </span>
              <span className="draft-caret">{draftOpen ? '▾' : '▸'}</span>
            </button>
            {draftOpen && (
              <div className="stack draft-body">
                <p className="draft-hint">
                  Describe the problem; the agent drafts a full question — prompt, constraints, a
                  reference solution and a validated test suite — you can review and edit below
                  before saving.
                </p>
                {draftError && (
                  <div role="alert" className="form-error">
                    <p>{draftError.message}</p>
                    {draftError.detail && <p className="cellsub">{draftError.detail}</p>}
                    {draftError.canRetry && (
                      <button
                        type="button"
                        className="btn sec sm"
                        onClick={handleDraft}
                        disabled={drafting}
                      >
                        {drafting ? 'Retrying…' : 'Try again'}
                      </button>
                    )}
                  </div>
                )}
                <div className="field">
                  <label htmlFor="brief">Brief</label>
                  <textarea
                    id="brief"
                    value={brief}
                    placeholder="e.g. Given N integers, print the length of the longest strictly increasing run."
                    onChange={(e) => setBrief(e.target.value)}
                  />
                </div>
                <div className="grid2">
                  <div className="field">
                    <label htmlFor="draft_language">Reference language</label>
                    <select
                      id="draft_language"
                      value={draftLanguage}
                      onChange={(e) => setDraftLanguage(e.target.value as Language)}
                    >
                      {LANGUAGES.map((lang) => (
                        <option key={lang} value={lang}>
                          {lang}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="difficulty">Difficulty (optional)</label>
                    <input
                      id="difficulty"
                      placeholder="e.g. medium"
                      value={difficulty}
                      onChange={(e) => setDifficulty(e.target.value)}
                    />
                  </div>
                </div>
                <div className="field">
                  <label htmlFor="target_complexity">Target complexity (optional)</label>
                  <input
                    id="target_complexity"
                    placeholder="e.g. O(n log n)"
                    value={targetComplexity}
                    onChange={(e) => setTargetComplexity(e.target.value)}
                  />
                </div>
                <button type="button" className="btn accent" onClick={handleDraft} disabled={drafting}>
                  {drafting ? 'Drafting…' : 'Draft with AI'}
                </button>
                {draftWarnings.length > 0 && (
                  <div role="alert" className="draft-warnings">
                    <strong>Warnings</strong>
                    <ul>
                      {draftWarnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {referenceSolution && (
                  <details className="draft-reference">
                    <summary>Reference solution (context only — not saved)</summary>
                    <pre className="code">{referenceSolution}</pre>
                  </details>
                )}
              </div>
            )}
          </div>
        )}

        {step === 0 && (
          <div className="card pad">
            <div className="card-title">Basics</div>
            <div className="stack">
              <div className="grid2">
                <div className="field">
                  <label htmlFor="id">Id (slug)</label>
                  <input id="id" className="mono" value={id} onChange={(e) => setId(e.target.value)} />
                </div>
                <div className="field">
                  <label htmlFor="title">Title</label>
                  <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
                </div>
              </div>
              <div className="field">
                <label htmlFor="prompt">Prompt</label>
                <textarea id="prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
              </div>
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="card pad">
            <div className="card-title">Constraints &amp; grading</div>
            <div className="stack">
              <div className="field">
                <label htmlFor="constraints">Constraints</label>
                <textarea
                  id="constraints"
                  value={constraints}
                  onChange={(e) => setConstraints(e.target.value)}
                />
              </div>
              <div className="grid2">
                <div className="field">
                  <label htmlFor="time_limit_s">Time limit (s)</label>
                  <input
                    id="time_limit_s"
                    type="number"
                    min={0}
                    value={timeLimitS}
                    onChange={(e) => setTimeLimitS(Number(e.target.value))}
                  />
                </div>
                <div className="field">
                  <label htmlFor="pass_threshold">Pass threshold (%)</label>
                  <input
                    id="pass_threshold"
                    type="number"
                    min={0}
                    max={100}
                    value={passThreshold}
                    onChange={(e) => setPassThreshold(Number(e.target.value))}
                  />
                </div>
              </div>
              <div className="field">
                <label htmlFor="required_complexity">Required complexity</label>
                <input
                  id="required_complexity"
                  placeholder="e.g. O(n log n)"
                  value={requiredComplexity}
                  onChange={(e) => setRequiredComplexity(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="card pad">
            <div className="card-title">Test cases</div>
            {testCases.map((tc, i) => (
              <div className="tc-card" key={i}>
                <div className="tc-head">
                  <input
                    className="tc-name"
                    aria-label={`Test case ${i + 1} name`}
                    placeholder="Case name"
                    value={tc.name}
                    onChange={(e) => updateTestCase(i, { name: e.target.value })}
                  />
                  <select
                    aria-label={`Test case ${i + 1} category`}
                    value={tc.category}
                    onChange={(e) => updateTestCase(i, { category: e.target.value as TestCaseCategory })}
                  >
                    <option value="correctness">correctness</option>
                    <option value="performance">performance</option>
                  </select>
                  <label className="tc-num">
                    Weight
                    <input
                      className="tc-weight"
                      aria-label={`Test case ${i + 1} weight`}
                      type="number"
                      min={0}
                      value={tc.weight}
                      onChange={(e) => updateTestCase(i, { weight: Number(e.target.value) })}
                    />
                  </label>
                  <button
                    type="button"
                    className="btn-link"
                    onClick={() => removeTestCase(i)}
                    disabled={testCases.length === 1}
                  >
                    Remove
                  </button>
                </div>
                <div className="tc-io">
                  <div>
                    <label>Input (stdin)</label>
                    <textarea
                      aria-label={`Test case ${i + 1} stdin`}
                      placeholder="stdin passed to the program"
                      value={tc.stdin}
                      onChange={(e) => updateTestCase(i, { stdin: e.target.value })}
                    />
                  </div>
                  <div>
                    <label>Expected output</label>
                    <textarea
                      aria-label={`Test case ${i + 1} expected`}
                      placeholder="exact expected stdout"
                      value={tc.expected}
                      onChange={(e) => updateTestCase(i, { expected: e.target.value })}
                    />
                  </div>
                </div>
              </div>
            ))}
            <button type="button" className="btn sec" onClick={addTestCase}>
              Add test case
            </button>
          </div>
        )}

        {step === 3 && (
          <div className="card pad">
            <div className="card-title">Worked example</div>
            <div className="stack">
              <div className="field">
                <label htmlFor="example_input">Example input</label>
                <textarea
                  id="example_input"
                  value={exampleInput}
                  onChange={(e) => setExampleInput(e.target.value)}
                />
              </div>
              <div className="field">
                <label htmlFor="example_output">Example output</label>
                <textarea
                  id="example_output"
                  value={exampleOutput}
                  onChange={(e) => setExampleOutput(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        {step === LAST_STEP && (
          <div className="card pad">
            <div className="card-title">Review</div>
            <dl className="review-list">
              <dt>Id</dt>
              <dd>{id}</dd>
              <dt>Title</dt>
              <dd>{title}</dd>
              <dt>Time limit</dt>
              <dd>{timeLimitS}s</dd>
              <dt>Pass threshold</dt>
              <dd>{passThreshold}%</dd>
              <dt>Test cases</dt>
              <dd>{testCases.length}</dd>
            </dl>
          </div>
        )}

        <div className="wizard-nav">
          {step > 0 && (
            <button type="button" className="btn sec" onClick={goBack}>
              Back
            </button>
          )}
          {step < LAST_STEP ? (
            <button type="button" className="btn" onClick={goNext}>
              Next
            </button>
          ) : (
            <button type="button" className="btn" onClick={handleCreate} disabled={submitting}>
              {submitting ? 'Creating…' : 'Create question'}
            </button>
          )}
        </div>
      </form>
    </div>
  )
}
