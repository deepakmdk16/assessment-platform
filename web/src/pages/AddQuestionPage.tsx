import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError } from '../api'
import type { TestCaseCategory, TestCaseIn } from '../types'

function emptyTestCase(): TestCaseIn {
  return { name: '', stdin: '', expected: '', category: 'correctness', weight: 1 }
}

export function AddQuestionPage() {
  const navigate = useNavigate()

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

  function updateTestCase(index: number, patch: Partial<TestCaseIn>) {
    setTestCases((rows) => rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  }

  function addTestCase() {
    setTestCases((rows) => [...rows, emptyTestCase()])
  }

  function removeTestCase(index: number) {
    setTestCases((rows) => rows.filter((_, i) => i !== index))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
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
      <form className="question-form" onSubmit={handleSubmit}>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}

        <fieldset>
          <legend>Basics</legend>
          <label htmlFor="id">Id (slug)</label>
          <input id="id" value={id} onChange={(e) => setId(e.target.value)} required />
          <label htmlFor="title">Title</label>
          <input id="title" value={title} onChange={(e) => setTitle(e.target.value)} required />
          <label htmlFor="prompt">Prompt</label>
          <textarea
            id="prompt"
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            required
          />
        </fieldset>

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
            required
          />
          <label htmlFor="pass_threshold">Pass threshold (%)</label>
          <input
            id="pass_threshold"
            type="number"
            min={0}
            max={100}
            value={passThreshold}
            onChange={(e) => setPassThreshold(Number(e.target.value))}
            required
          />
          <label htmlFor="required_complexity">Required complexity</label>
          <input
            id="required_complexity"
            placeholder="e.g. O(n log n)"
            value={requiredComplexity}
            onChange={(e) => setRequiredComplexity(e.target.value)}
          />
        </fieldset>

        <fieldset>
          <legend>Test cases</legend>
          {testCases.map((tc, i) => (
            <div className="test-case-row" key={i}>
              <input
                aria-label={`Test case ${i + 1} name`}
                placeholder="name"
                value={tc.name}
                onChange={(e) => updateTestCase(i, { name: e.target.value })}
                required
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

        <button type="submit" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create question'}
        </button>
      </form>
    </div>
  )
}
