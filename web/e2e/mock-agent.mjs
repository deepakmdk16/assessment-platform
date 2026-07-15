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

async function fireCallback(callbackUrl, jobId) {
  const payload = {
    job_id: jobId,
    verdict: 'PASS',
    score_pct: 100.0,
    reason: 'mock agent: all tests passed',
    summary: 'Mock grade for E2E.',
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
      test_cases: [
        { name: 't1', stdin: '4\n1 2 1 3\n', expected: '2', category: 'correctness', weight: 1.0 },
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
