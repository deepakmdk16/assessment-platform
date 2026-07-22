import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Editor from '@monaco-editor/react'
import { api, ApiError } from '../api'
import { badgeClass } from '../badges'
import { useTheme } from '../theme/ThemeContext'
import { monacoTheme } from '../theme/theme'
import type { QuestionOut, ResultTestCase, SubmissionDetail } from '../types'

/** The interviewer's report card. Unlike the candidate view this deliberately
 *  shows everything — inputs, expected vs actual, the answer key — because the
 *  whole point is judging the submission. */
export function SubmissionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { resolved } = useTheme()
  const [sub, setSub] = useState<SubmissionDetail | null>(null)
  const [question, setQuestion] = useState<QuestionOut | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<'report' | 'tests'>('report')
  const [pollTimedOut, setPollTimedOut] = useState(false)

  // Poll while the submission is still being graded so the report appears without
  // a manual refresh. Stops on a terminal state (result present or status=error),
  // on unmount, and after a cap so a wedged job doesn't poll forever.
  useEffect(() => {
    if (!id) return
    const sid = id
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let questionLoaded = false
    const startedAt = Date.now()
    const POLL_MS = 3000
    const MAX_MS = 120000

    async function tick() {
      try {
        const s = await api.getSubmission(sid)
        if (cancelled) return
        setSub(s)
        if (!questionLoaded) {
          questionLoaded = true
          api
            .getQuestion(s.question_id)
            .then((q) => {
              if (!cancelled) setQuestion(q)
            })
            .catch(() => undefined)
        }
        const pending = !s.result && (s.status === 'pending' || s.status === 'running')
        if (!pending) return
        if (Date.now() - startedAt >= MAX_MS) {
          setPollTimedOut(true)
          return
        }
        timer = setTimeout(tick, POLL_MS)
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? err.message : 'Failed to load submission')
      }
    }
    tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [id])

  if (error) return <p className="form-error">{error}</p>
  if (!sub) return <p className="page-loading">Loading…</p>

  const result = sub.result
  const full = result?.full_result
  const cases = full?.test_cases ?? []
  const quality = full?.quality
  const isPending = !result && (sub.status === 'pending' || sub.status === 'running') && !pollTimedOut

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
          {result ? (
            <>
              <span className={badgeClass(result.verdict)}>{result.verdict}</span>
              <span className="score">{result.score_pct}%</span>
            </>
          ) : (
            <span className={`${badgeClass(sub.status)}${isPending ? ' chip-live' : ''}`}>
              {sub.status}
            </span>
          )}
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
                {question.reference_solution && (
                  <details className="draft-reference">
                    <summary>
                      Show reference solution
                      {question.reference_language ? ` (${question.reference_language})` : ''}
                    </summary>
                    <pre className="code">{question.reference_solution}</pre>
                  </details>
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
              theme={monacoTheme(resolved)}
              options={{ readOnly: true, minimap: { enabled: false }, fontSize: 13 }}
            />
          </div>

          <div className="ide-review">
            <div className="tabs">
              <button
                type="button"
                className={tab === 'report' ? 'tab on' : 'tab'}
                onClick={() => setTab('report')}
              >
                Report
              </button>
              <button
                type="button"
                className={tab === 'tests' ? 'tab on' : 'tab'}
                onClick={() => setTab('tests')}
              >
                Test cases{cases.length > 0 && <span className="count">{cases.length}</span>}
              </button>
            </div>

            {!result ? (
              <GradingNotice status={sub.status} timedOut={pollTimedOut} />
            ) : tab === 'report' ? (
              <ReportTab
                reason={result.reason}
                compileError={full?.compile_error ?? null}
                infraError={full?.infra_error ?? null}
                agentError={full?.error ?? null}
                pointsEarned={full?.points_earned}
                pointsTotal={full?.points_total}
                passThresholdPct={full?.pass_threshold_pct}
                quality={quality ?? null}
              />
            ) : (
              <TestsTab cases={cases} />
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function GradingNotice({ status, timedOut }: { status: string; timedOut: boolean }) {
  if (status === 'error') {
    return (
      <div className="grading">
        <div className="grading-title">Grading couldn’t complete</div>
        <p className="grading-sub">
          The agent couldn’t be reached for this submission, so it was never graded. Retry it from
          the submissions list.
        </p>
      </div>
    )
  }
  if (timedOut) {
    return (
      <div className="grading">
        <div className="grading-title">Still grading</div>
        <p className="grading-sub">
          This is taking longer than usual. It’s still being processed — refresh to check again.
        </p>
      </div>
    )
  }
  return (
    <div className="grading">
      <div className="spinner" aria-hidden="true" />
      <div className="grading-title">Grading in progress</div>
      <p className="grading-sub">
        The agent is running the code and judging quality. This updates automatically — no need to
        refresh.
      </p>
      <div className="live-dot">Checking every few seconds</div>
    </div>
  )
}

function ReportTab({
  reason,
  compileError,
  infraError,
  agentError,
  pointsEarned,
  pointsTotal,
  passThresholdPct,
  quality,
}: {
  reason: string
  compileError: string | null
  infraError: string | null
  agentError: string | null
  pointsEarned?: number
  pointsTotal?: number
  passThresholdPct?: number
  quality: import('../types').ResultQuality | null
}) {
  return (
    <>
      <h3>Verdict</h3>
      <p className="review-summary">{reason}</p>

      {(pointsEarned != null || passThresholdPct != null) && (
        <div className="kv-row">
          {pointsEarned != null && pointsTotal != null && (
            <div className="kv">
              <span className="k">Points</span>
              <span className="num">
                {pointsEarned}/{pointsTotal}
              </span>
            </div>
          )}
          {passThresholdPct != null && (
            <div className="kv">
              <span className="k">Threshold</span>
              <span className="num">{passThresholdPct}%</span>
            </div>
          )}
          {quality?.time_complexity && (
            <div className="kv">
              <span className="k">Complexity</span>
              <span className="mono">{quality.time_complexity}</span>
            </div>
          )}
        </div>
      )}

      {compileError && (
        <div className="form-error">
          <strong>Did not compile</strong>
          <pre className="code">{compileError}</pre>
        </div>
      )}
      {infraError && (
        <div className="form-error">
          <strong>Could not evaluate</strong>
          <pre className="code">{infraError}</pre>
        </div>
      )}
      {agentError && (
        <div className="form-error">
          <strong>Agent error</strong>
          <pre className="code">{agentError}</pre>
        </div>
      )}

      {quality ? (
        <>
          <h3>AI summary</h3>
          <p className="review-summary">{quality.summary}</p>

          {quality.strengths.length > 0 && (
            <>
              <h3>Strengths</h3>
              <ul className="bullets">
                {quality.strengths.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </>
          )}

          {quality.weaknesses.length > 0 && (
            <>
              <h3>Weaknesses</h3>
              <ul className="bullets">
                {quality.weaknesses.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </>
          )}

          {quality.criteria.length > 0 && (
            <>
              <h3>Criteria</h3>
              <div className="card tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>Criterion</th>
                      <th>Score</th>
                      <th>Comment</th>
                    </tr>
                  </thead>
                  <tbody>
                    {quality.criteria.map((c) => (
                      <tr key={c.name}>
                        <td className="t-title">{c.name}</td>
                        <td className="score">{c.score}</td>
                        <td>{c.comment}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <p className="cellsub">
            Quality is advisory — it never affects the verdict or score. Engine: {quality.engine}.
          </p>
        </>
      ) : (
        <p className="muted">
          No AI summary for this submission — the judge is skipped when the code doesn’t run.
        </p>
      )}
    </>
  )
}

function TestsTab({ cases }: { cases: ResultTestCase[] }) {
  if (cases.length === 0) {
    return <p className="muted">No test cases ran for this submission.</p>
  }
  return (
    <div className="card tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th>Case</th>
            <th>Result</th>
            <th>Time</th>
            <th>Input</th>
            <th>Expected</th>
            <th>Actual</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((c) => (
            <tr key={c.name}>
              <td>
                <div className="t-title">{c.name}</div>
                <div className="cellsub">
                  {c.category} · weight {c.weight}
                </div>
              </td>
              <td>
                <span className={badgeClass(c.status)}>{c.status}</span>
              </td>
              <td className="score">{c.duration_s}s</td>
              <td>
                <pre className="code cell-pre">{c.input}</pre>
              </td>
              <td>
                <pre className="code cell-pre">{c.expected}</pre>
              </td>
              <td>
                <pre className="code cell-pre">{c.error ? c.error : c.actual}</pre>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
