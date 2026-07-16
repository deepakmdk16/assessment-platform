import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Editor from '@monaco-editor/react'
import { api, ApiError } from '../api'
import { badgeClass } from '../badges'
import type { QuestionOut, SubmissionDetail } from '../types'

/** Best-effort: pull a per-test-case array out of the agent's stored full_result.
 *  Backend shape is finalised in the next pass; until then we render whatever is
 *  present and fall back to a placeholder. */
function extractCases(full: Record<string, unknown> | undefined): Record<string, unknown>[] | null {
  if (!full) return null
  for (const key of ['test_results', 'tests', 'results', 'cases', 'checks']) {
    const v = full[key]
    if (Array.isArray(v) && v.length > 0) return v as Record<string, unknown>[]
  }
  return null
}

function str(v: unknown): string {
  if (v == null) return ''
  return typeof v === 'string' ? v : JSON.stringify(v)
}

export function SubmissionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [sub, setSub] = useState<SubmissionDetail | null>(null)
  const [question, setQuestion] = useState<QuestionOut | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    api
      .getSubmission(id)
      .then((s) => {
        setSub(s)
        api.getQuestion(s.question_id).then(setQuestion).catch(() => undefined)
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : 'Failed to load submission'))
  }, [id])

  if (error) return <p className="form-error">{error}</p>
  if (!sub) return <p className="page-loading">Loading…</p>

  const result = sub.result
  const cases = extractCases(result?.full_result)

  return (
    <div className="ide">
      <header className="ide-top">
        <Link to={`/questions/${sub.question_id}`} className="ide-back">
          ← Back
        </Link>
        <span className="ide-title">{question?.title ?? sub.question_id}</span>
        <div className="ide-top-right">
          <span className="muted">
            {sub.candidate} · {sub.language}
          </span>
          {result && <span className={badgeClass(result.verdict)}>{result.verdict}</span>}
          {result && <span className="score">{result.score_pct}%</span>}
        </div>
      </header>

      <div className="ide-split">
        <section className="panel">
          <div className="tabs">
            <span className="tab on">Problem</span>
          </div>
          <div className="panel-body prose">
            {question ? (
              <>
                <p className="pre-text">{question.prompt}</p>
                {question.constraints && (
                  <>
                    <h3>Constraints</h3>
                    <p className="pre-text">{question.constraints}</p>
                  </>
                )}
                {(question.example_input || question.example_output) && (
                  <div className="example-block">
                    <h3>Example</h3>
                    {question.example_input && (
                      <div className="io">
                        <span className="io-label">Input</span>
                        <pre className="code">{question.example_input}</pre>
                      </div>
                    )}
                    {question.example_output && (
                      <div className="io">
                        <span className="io-label">Output</span>
                        <pre className="code">{question.example_output}</pre>
                      </div>
                    )}
                  </div>
                )}
              </>
            ) : (
              <p className="muted">Loading problem…</p>
            )}
          </div>
        </section>

        <section className="panel">
          <div className="tabs">
            <span className="tab on">Candidate solution</span>
            <span className="tab-meta">{sub.language}</span>
          </div>
          <div className="editor-wrapper editor-wrapper-review">
            <Editor
              height="100%"
              language={sub.language || undefined}
              value={sub.code}
              theme="vs-dark"
              options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13 }}
            />
          </div>

          <div className="ide-review">
            <h3>AI summary</h3>
            <p className="review-summary">
              {result?.reason || str(result?.full_result?.summary) || 'No summary available yet.'}
            </p>

            <h3>Test cases</h3>
            {cases ? (
              <div className="card tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Case</th>
                      <th>Result</th>
                      <th>Output</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cases.map((c, i) => {
                      const passed = c.passed ?? c.ok ?? c.status
                      const label =
                        passed === true || String(passed).toLowerCase() === 'pass' ? 'pass' : 'fail'
                      return (
                        <tr key={i}>
                          <td>{str(c.name ?? c.id ?? `Case ${i + 1}`)}</td>
                          <td>
                            <span className={badgeClass(label)}>{label}</span>
                          </td>
                          <td className="mono-cell">{str(c.output ?? c.actual ?? c.stdout)}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">
                Per-test-case output isn’t wired yet — it lands in the next (backend) pass. Verdict
                and score above come from the agent’s stored result.
              </p>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
