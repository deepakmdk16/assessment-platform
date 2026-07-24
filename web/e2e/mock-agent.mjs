// Mock Assessment Agent for browser E2E — stands in for `../AssesmentAgent` so the
// suite runs fully offline (no live agent, no LLM key). It mirrors the real agent's
// two-step contract: accept `POST /assessments` (returning a job_id immediately),
// then POST the graded result back to the platform's callback_url.
//
// The callback is deferred slightly so the platform has committed `agent_job_id`
// (which it sets only AFTER trigger_assessment returns) before the callback tries
// to match the submission by that id.
import http from 'node:http'

const PORT = Number(process.env.MOCK_AGENT_PORT ?? 8000)
const CALLBACK_DELAY_MS = Number(process.env.MOCK_AGENT_DELAY_MS ?? 150)
// Optional shared secret, matching the platform's X-Assess-Token contract.
const CALLBACK_TOKEN = process.env.CALLBACK_TOKEN || null

// Per-process-unique prefix so job/question ids don't collide with rows left in a
// persisted E2E DB across runs (see the callback-matching note below).
const runId = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`
let jobCounter = 0

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = ''
    req.on('data', (chunk) => (data += chunk))
    req.on('end', () => resolve(data))
    req.on('error', reject)
  })
}

// Mirrors the real agent's `result_to_dict` (assessment_agent/agent.py) — the
// platform stores this verbatim as `full_result` and the interviewer's report
// card reads it field by field. Keep the SHAPE in step with the real agent: a
// thinner mock is what let a broken report card pass E2E once already.
async function fireCallback(callbackUrl, jobId) {
  const payload = {
    job_id: jobId,
    question_id: 'mock-question',
    question_title: 'Mock question',
    language: 'python',
    verdict: 'PASS',
    reason: 'mock agent: all tests passed',
    score_pct: 100.0,
    points_earned: 2,
    points_total: 2,
    pass_threshold_pct: 90.0,
    compile_error: null,
    infra_error: null,
    test_cases: [
      {
        name: 'basic',
        category: 'correctness',
        weight: 1.0,
        status: 'PASS',
        input: 'mock-input-1',
        expected: 'mock-expected-1',
        actual: 'mock-expected-1',
        duration_s: 0.01,
        timed_out: false,
        error: null,
      },
      {
        name: 'large',
        category: 'performance',
        weight: 1.0,
        status: 'PASS',
        input: 'mock-input-2',
        expected: 'mock-expected-2',
        actual: 'mock-expected-2',
        duration_s: 0.2,
        timed_out: false,
        error: null,
      },
    ],
    quality: {
      engine: 'mock-agent',
      time_complexity: 'O(n)',
      meets_time_constraints: true,
      overall_score: 9,
      criteria: [{ name: 'Readability', score: 9, comment: 'Mock criterion comment.' }],
      strengths: ['Mock strength: handles edge cases.'],
      weaknesses: ['Mock weakness: no input validation.'],
      summary: 'Mock grade for E2E.',
    },
    judge_cost_usd: null,
    adversarial: null,
  }
  const headers = { 'Content-Type': 'application/json' }
  if (CALLBACK_TOKEN) headers['X-Assess-Token'] = CALLBACK_TOKEN
  try {
    await fetch(callbackUrl, { method: 'POST', headers, body: JSON.stringify(payload) })
  } catch (err) {
    console.error('[mock-agent] callback POST failed:', err)
  }
}

const server = http.createServer(async (req, res) => {
  if (req.method === 'GET' && req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ status: 'ok' }))
    return
  }

  if (req.method === 'POST' && req.url === '/questions/draft') {
    // Deterministic stand-in for the agent's LLM-backed drafter. Returns a small
    // valid question so the "Draft with AI" browser flow works offline.
    const question = {
      id: `drafted-${runId}-${++jobCounter}`,
      title: 'Longest increasing run',
      prompt: 'Read N then N integers; print the length of the longest strictly increasing run.',
      constraints: '1 <= N <= 1e5',
      time_limit_s: 2.0,
      pass_threshold: 0.9,
      required_complexity: 'O(n)',
      example: { input: '4\n1 2 1 3\n', output: '2' },
      // Floor-compliant (A1): the platform now enforces ≥4 correctness + ≥1
      // performance case at save time, so a below-floor draft would 422 on Create.
      test_cases: [
        { name: 't1', stdin: '4\n1 2 1 3\n', expected: '2', category: 'correctness', weight: 1.0 },
        { name: 't2', stdin: '1\n5\n', expected: '1', category: 'correctness', weight: 1.0 },
        { name: 't3', stdin: '3\n3 2 1\n', expected: '1', category: 'correctness', weight: 1.0 },
        { name: 't4', stdin: '5\n1 2 3 4 5\n', expected: '5', category: 'correctness', weight: 1.0 },
        { name: 'large', stdin: '2\n1 2\n', expected: '2', category: 'performance', weight: 1.0 },
      ],
    }
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(
      JSON.stringify({
        engine: 'mock-agent',
        question,
        warnings: [],
        reference_solution: 'print("mock reference")',
        reference_language: 'python',
        cost_usd: null,
      }),
    )
    return
  }

  // Non-grading run paths (the candidate's editor). Deterministic stand-ins for
  // the real agent's execution: echo something plausible rather than running code.
  if (req.method === 'POST' && req.url === '/run') {
    let body = {}
    try {
      body = JSON.parse(await readBody(req))
    } catch {
      // tolerate a malformed body
    }
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(
      JSON.stringify({
        stdout: `mock-run-output for stdin: ${(body.stdin ?? '').trim() || '(empty)'}`,
        stderr: null,
        duration_s: 0.01,
        timed_out: false,
        compile_error: null,
        infra_error: null,
      }),
    )
    return
  }

  if (req.method === 'POST' && req.url === '/run/tests') {
    // Mirrors the real agent's redaction: status only, never input/expected/actual.
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(
      JSON.stringify({
        compile_error: null,
        infra_error: null,
        test_cases: [
          { name: 'basic', category: 'correctness', status: 'PASS', duration_s: 0.01 },
          { name: 'large', category: 'performance', status: 'FAIL', duration_s: 0.5 },
        ],
      }),
    )
    return
  }

  if (req.method === 'POST' && req.url === '/assessments') {
    let body = {}
    try {
      body = JSON.parse(await readBody(req))
    } catch {
      // tolerate a malformed body; we only need callback_url
    }
    // Include a per-process-unique prefix: the counter resets to 0 on every mock
    // restart, so a bare `mock-job-N` collides with rows left in a persisted E2E DB
    // (`e2e-platform.db` lives at the repo root and isn't reset between runs). On a
    // collision the callback's `.first()` match grades a stale submission and leaves
    // the current one stuck at "running". A unique run prefix keeps job_ids distinct.
    const jobId = `mock-job-${runId}-${++jobCounter}`
    if (body.callback_url) {
      setTimeout(() => fireCallback(body.callback_url, jobId), CALLBACK_DELAY_MS)
    }
    res.writeHead(202, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify({ job_id: jobId }))
    return
  }

  res.writeHead(404)
  res.end()
})

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[mock-agent] listening on http://127.0.0.1:${PORT}`)
})
