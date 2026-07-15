import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import { LANGUAGES } from '../types'
import type { Language, TestCaseCategory, TestCaseIn } from '../types'

function emptyTestCase(): TestCaseIn {
  return { name: '', stdin: '', expected: '', category: 'correctness', weight: 1 }
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
  const [draftError, setDraftError] = useState<string | null>(null)
  const [draftWarnings, setDraftWarnings] = useState<string[]>([])
  const [referenceSolution, setReferenceSolution] = useState<string | null>(null)

  async function handleDraft() {
    if (!brief.trim()) {
      setDraftError('Enter a brief to draft from.')
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
      setPassThreshold(q.pass_threshold)
      setRequiredComplexity(q.required_complexity ?? '')
      setExampleInput(q.example_input ?? '')
      setExampleOutput(q.example_output ?? '')
      setTestCases(q.test_cases.length > 0 ? q.test_cases : [emptyTestCase()])
      setDraftWarnings(res.warnings)
      setReferenceSolution(res.reference_solution)
    } catch (err) {
      setDraftError(err instanceof ApiError ? err.message : 'Failed to draft question')
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
        pass_threshold: passThreshold,
        required_complexity: requiredComplexity,
        example_input: exampleInput,
        example_output: exampleOutput,
        test_cases: testCases,
      })
      navigate(`/questions/${created.id}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create question')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="page">
      <h1>Add question</h1>

      <ol className="wizard-steps">
        {STEPS.map((label, i) => (
          <li
            key={label}
            className={i === step ? 'current' : i < step ? 'done' : undefined}
            aria-current={i === step ? 'step' : undefined}
          >
            <span className="wizard-step-num">{i + 1}</span>
            {label}
          </li>
        ))}
      </ol>

      {/* No submit button lives in this form: the Create action is an explicit
          type="button" onClick below. That avoids a React footgun where clicking
          "Next" re-renders the same button position into a submit button mid-click
          and the browser then submits. preventDefault guards stray Enter presses. */}
      <form className="question-form" onSubmit={(e) => e.preventDefault()}>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}

        {step === 0 && (
          <fieldset className="draft-panel">
            <legend>
              <button
                type="button"
                className="button-link"
                aria-expanded={draftOpen}
                onClick={() => setDraftOpen((o) => !o)}
              >
                {draftOpen ? '▾' : '▸'} Draft with AI
              </button>
            </legend>
            {draftOpen && (
              <>
                <p className="draft-help">
                  Describe the problem; the agent drafts a full question you can review and edit
                  below before saving.
                </p>
                {draftError && (
                  <p role="alert" className="form-error">
                    {draftError}
                  </p>
                )}
                <label htmlFor="brief">Brief</label>
                <textarea
                  id="brief"
                  value={brief}
                  placeholder="e.g. Given N integers, print the length of the longest strictly increasing run."
                  onChange={(e) => setBrief(e.target.value)}
                />
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
                <label htmlFor="difficulty">Difficulty (optional)</label>
                <input
                  id="difficulty"
                  placeholder="e.g. medium"
                  value={difficulty}
                  onChange={(e) => setDifficulty(e.target.value)}
                />
                <label htmlFor="target_complexity">Target complexity (optional)</label>
                <input
                  id="target_complexity"
                  placeholder="e.g. O(n log n)"
                  value={targetComplexity}
                  onChange={(e) => setTargetComplexity(e.target.value)}
                />
                <button type="button" onClick={handleDraft} disabled={drafting}>
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
                    <pre>{referenceSolution}</pre>
                  </details>
                )}
              </>
            )}
          </fieldset>
        )}

        {step === 0 && (
          <fieldset>
            <legend>Basics</legend>
            <label htmlFor="id">Id (slug)</label>
            <input id="id" value={id} onChange={(e) => setId(e.target.value)} />
            <label htmlFor="title">Title</label>
            <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} />
            <label htmlFor="prompt">Prompt</label>
            <textarea id="prompt" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </fieldset>
        )}

        {step === 1 && (
          <fieldset>
            <legend>Constraints &amp; grading</legend>
            <label htmlFor="constraints">Constraints</label>
            <textarea
              id="constraints"
              value={constraints}
              onChange={(e) => setConstraints(e.target.value)}
            />
            <label htmlFor="time_limit_s">Time limit (s)</label>
            <input
              id="time_limit_s"
              type="number"
              min={0}
              value={timeLimitS}
              onChange={(e) => setTimeLimitS(Number(e.target.value))}
            />
            <label htmlFor="pass_threshold">Pass threshold (%)</label>
            <input
              id="pass_threshold"
              type="number"
              min={0}
              max={100}
              value={passThreshold}
              onChange={(e) => setPassThreshold(Number(e.target.value))}
            />
            <label htmlFor="required_complexity">Required complexity</label>
            <input
              id="required_complexity"
              placeholder="e.g. O(n log n)"
              value={requiredComplexity}
              onChange={(e) => setRequiredComplexity(e.target.value)}
            />
          </fieldset>
        )}

        {step === 2 && (
          <fieldset>
            <legend>Test cases</legend>
            {testCases.map((tc, i) => (
              <div className="test-case-row" key={i}>
                <input
                  aria-label={`Test case ${i + 1} name`}
                  placeholder="name"
                  value={tc.name}
                  onChange={(e) => updateTestCase(i, { name: e.target.value })}
                />
                <textarea
                  aria-label={`Test case ${i + 1} stdin`}
                  placeholder="stdin"
                  value={tc.stdin}
                  onChange={(e) => updateTestCase(i, { stdin: e.target.value })}
                />
                <textarea
                  aria-label={`Test case ${i + 1} expected`}
                  placeholder="expected"
                  value={tc.expected}
                  onChange={(e) => updateTestCase(i, { expected: e.target.value })}
                />
                <select
                  aria-label={`Test case ${i + 1} category`}
                  value={tc.category}
                  onChange={(e) =>
                    updateTestCase(i, { category: e.target.value as TestCaseCategory })
                  }
                >
                  <option value="correctness">correctness</option>
                  <option value="performance">performance</option>
                </select>
                <input
                  aria-label={`Test case ${i + 1} weight`}
                  type="number"
                  min={0}
                  value={tc.weight}
                  onChange={(e) => updateTestCase(i, { weight: Number(e.target.value) })}
                />
                <button
                  type="button"
                  className="button-link"
                  onClick={() => removeTestCase(i)}
                  disabled={testCases.length === 1}
                >
                  Remove
                </button>
              </div>
            ))}
            <button type="button" onClick={addTestCase}>
              Add test case
            </button>
          </fieldset>
        )}

        {step === 3 && (
          <fieldset>
            <legend>Worked example</legend>
            <label htmlFor="example_input">Example input</label>
            <textarea
              id="example_input"
              value={exampleInput}
              onChange={(e) => setExampleInput(e.target.value)}
            />
            <label htmlFor="example_output">Example output</label>
            <textarea
              id="example_output"
              value={exampleOutput}
              onChange={(e) => setExampleOutput(e.target.value)}
            />
          </fieldset>
        )}

        {step === LAST_STEP && (
          <fieldset>
            <legend>Review</legend>
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
          </fieldset>
        )}

        <div className="wizard-nav">
          {step > 0 && (
            <button type="button" onClick={goBack}>
              Back
            </button>
          )}
          {step < LAST_STEP ? (
            <button type="button" onClick={goNext}>
              Next
            </button>
          ) : (
            <button type="button" onClick={handleCreate} disabled={submitting}>
              {submitting ? 'Creating…' : 'Create question'}
            </button>
          )}
        </div>
      </form>
    </div>
  )
}
