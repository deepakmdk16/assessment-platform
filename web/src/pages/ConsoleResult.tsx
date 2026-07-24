import { badgeClass } from '../badges'
import type { RunResponse, RunTestsResponse } from '../types'

/** The console's Result tab: output from Run, or the pass/fail strip from
 *  Run-against-test-cases. The candidate sees counts and statuses only — never
 *  a case's input or expected output. Shared by both candidate flows. */
export function ConsoleResult({
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
