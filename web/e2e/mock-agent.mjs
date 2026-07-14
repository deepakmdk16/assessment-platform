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

  if (req.method === 'POST' && req.url === '/assessments') {
    let body = {}
    try {
      body = JSON.parse(await readBody(req))
    } catch {
      // tolerate a malformed body; we only need callback_url
    }
    const jobId = `mock-job-${++jobCounter}`
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
