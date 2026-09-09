import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from '../../theme/ThemeContext'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SubmissionDetailPage } from '../SubmissionDetailPage'
import { api, ApiError } from '../../api'
import type { AgentFullResult, QuestionOut, SubmissionDetail } from '../../types'

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    api: {
      getSubmission: vi.fn(),
      getQuestion: vi.fn(),
      // I1: the panel loads alongside the report; a clean sitting by default so
      // these cases stay about the report itself.
      retrySubmission: vi.fn(),
      getSubmissionIntegrity: vi.fn(() =>
        Promise.resolve({
          monitored: true,
          summary: {
            total: 0,
            focus_losses: 0,
            away_ms: 0,
            fullscreen_exits: 0,
            pastes_blocked: 0,
            devtools_opens: 0,
          },
          events: [],
        }),
      ),
    },
    ApiError,
  }
})

vi.mock('@monaco-editor/react', () => ({
  default: ({ value }: { value?: string }) => <textarea aria-label="code editor" readOnly value={value} />,
}))

const question: QuestionOut = {
  id: 'two-sum',
  title: 'Two Sum',
  prompt: 'Find two numbers that add up to target.',
  constraints: '1 <= n <= 1000',
  time_limit_s: 2,
  pass_threshold: 0.9,
  required_complexity: 'O(n)',
  example_input: '2 7',
  example_output: '0 1',
  status: 'active',
  test_cases: [],
  created_at: '2026-07-16T00:00:00Z',
  updated_at: '2026-07-16T00:00:00Z',
}

/** Shaped exactly like the agent's `result_to_dict` — the contract this page reads. */
const fullResult: AgentFullResult = {
  question_id: 'two-sum',
  question_title: 'Two Sum',
  language: 'python',
  verdict: 'FAIL',
  reason: 'Scored 50% (1/2 points), threshold 90% (wrong answer on big_case).',
  score_pct: 50,
  points_earned: 1,
  points_total: 2,
  pass_threshold_pct: 90,
  compile_error: null,
  infra_error: null,
  test_cases: [
    {
      name: 'basic',
      category: 'correctness',
      weight: 1,
      status: 'PASS',
      input: 'basic-case-input',
      expected: 'basic-expected',
      actual: 'basic-expected',
      duration_s: 0.012,
      timed_out: false,
      error: null,
    },
    {
      name: 'big_case',
      category: 'performance',
      weight: 1,
      status: 'TLE',
      input: 'big-case-input',
      expected: 'big-expected',
      actual: '',
      duration_s: 2.0,
      timed_out: true,
      error: 'timed out after 2.0s',
    },
  ],
  quality: {
    engine: 'claude-sonnet-5',
    time_complexity: 'O(n^2)',
    meets_time_constraints: false,
    overall_score: 6,
    criteria: [{ name: 'Readability', score: 8, comment: 'Clear naming throughout.' }],
    strengths: ['Handles the empty input edge case.'],
    weaknesses: ['Uses a nested loop where a hash map would be linear.'],
    summary: 'Correct on small inputs but quadratic, so it times out at scale.',
  },
  judge_cost_usd: 0.004,
  adversarial: null,
}

const submission: SubmissionDetail = {
  id: 'sub1',
  question_id: 'two-sum',
  candidate: 'Casey Candidate',
  erased: false,
  language: 'python',
  code: 'print("hi")',
  status: 'done',
  agent_job_id: 'job1',
  created_at: '2026-07-16T00:00:00Z',
  late: false,
  result: {
    verdict: 'FAIL',
    score_pct: 50,
    reason: fullResult.reason!,
    full_result: fullResult,
    received_at: '2026-07-16T00:01:00Z',
  },
}

function renderPage() {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={['/submissions/sub1']}>
        <Routes>
          <Route path="/submissions/:id" element={<SubmissionDetailPage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

describe('SubmissionDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getQuestion).mockResolvedValue(question)
    vi.mocked(api.getSubmission).mockResolvedValue(submission)
  })

  it('shows the verdict, question, candidate code and AI summary', async () => {
    renderPage()

    expect(await screen.findByText('FAIL')).toBeInTheDocument()
    expect(screen.getByText('50%')).toBeInTheDocument()
    expect(await screen.findByText(/find two numbers/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/code editor/i)).toHaveValue('print("hi")')
    expect(screen.getByText(/quadratic, so it times out/i)).toBeInTheDocument()
    expect(screen.getByText(/handles the empty input edge case/i)).toBeInTheDocument()
    expect(screen.getByText(/nested loop where a hash map/i)).toBeInTheDocument()
    expect(screen.getByText('Readability')).toBeInTheDocument()
  })

  it('renders every test case with input, expected and actual', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /test cases/i }))

    expect(screen.getByText('basic')).toBeInTheDocument()
    expect(screen.getByText('big_case')).toBeInTheDocument()
    expect(screen.getByText('PASS')).toBeInTheDocument()
    expect(screen.getByText('TLE')).toBeInTheDocument()
    // The interviewer sees the answer key — inputs and expected outputs.
    expect(screen.getByText('basic-case-input')).toBeInTheDocument()
    expect(screen.getByText('big-case-input')).toBeInTheDocument()
    expect(screen.getByText('big-expected')).toBeInTheDocument()
    // The passing case matched, so expected and actual both show the same value.
    expect(screen.getAllByText('basic-expected')).toHaveLength(2)
    // A timed-out case surfaces its error in place of empty actual output.
    expect(screen.getByText(/timed out after 2.0s/i)).toBeInTheDocument()
  })

  it('explains a compile failure instead of an empty report', async () => {
    vi.mocked(api.getSubmission).mockResolvedValue({
      ...submission,
      result: {
        verdict: 'FAIL',
        score_pct: 0,
        reason: 'Submission did not compile — score 0%.',
        full_result: {
          verdict: 'FAIL',
          reason: 'Submission did not compile — score 0%.',
          compile_error: "main.cpp:3:1: error: expected ';'",
          test_cases: [],
          quality: null,
        },
        received_at: '2026-07-16T00:01:00Z',
      },
    })
    renderPage()

    // Exact match: the verdict line also contains "did not compile".
    expect(await screen.findByText('Did not compile')).toBeInTheDocument()
    expect(screen.getByText(/expected ';'/)).toBeInTheDocument()
    // No judge runs on code that doesn't execute — say so rather than blank.
    expect(screen.getByText(/judge is skipped/i)).toBeInTheDocument()
  })

  it('shows a live grading notice while the agent is still working', async () => {
    vi.mocked(api.getSubmission).mockResolvedValue({
      ...submission,
      status: 'running',
      result: null,
    })
    renderPage()

    expect(await screen.findByText(/grading in progress/i)).toBeInTheDocument()
    // The affordance that tells the interviewer not to refresh — the point of P5.
    expect(screen.getByText(/updates automatically/i)).toBeInTheDocument()
  })

  it('surfaces a terminal error instead of polling forever', async () => {
    vi.mocked(api.getSubmission).mockResolvedValue({
      ...submission,
      status: 'error',
      result: null,
    })
    renderPage()

    expect(await screen.findByText(/grading couldn’t complete/i)).toBeInTheDocument()
  })

  it('surfaces the grading details the API already returned', async () => {
    renderPage()

    // Both are on the payload today and were rendered nowhere. agent_job_id is
    // the only handle for correlating with the agent's own logs; received_at
    // answers "when was this graded", which created_at does not.
    expect(await screen.findByText('job1')).toBeInTheDocument()
    expect(screen.getByText('Grading details')).toBeInTheDocument()
  })

  it('offers a working retry when grading failed, instead of pointing elsewhere', async () => {
    const errored: SubmissionDetail = { ...submission, status: 'error', result: null }
    const pending: SubmissionDetail = { ...errored, status: 'pending' }
    vi.mocked(api.getSubmission).mockResolvedValue(errored)
    vi.mocked(api.retrySubmission).mockResolvedValue(pending)
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText(/grading couldn.t complete/i)).toBeInTheDocument()
    // The old copy sent the interviewer to a list that had no retry control.
    expect(screen.queryByText(/retry it from the submissions list/i)).not.toBeInTheDocument()

    // The restarted poll re-fetches, so the server is the source of truth from
    // here — mirror a backend that has accepted the retry.
    vi.mocked(api.getSubmission).mockResolvedValue(pending)
    await user.click(screen.getByRole('button', { name: /retry grading/i }))

    expect(api.retrySubmission).toHaveBeenCalledWith('sub1')
    expect(await screen.findByText(/grading in progress/i)).toBeInTheDocument()
  })

  it('restarts polling after a retry, so the grade actually appears', async () => {
    // The poll effect keys on [id, retryKey]. Without the retryKey bump it never
    // re-runs — its previous pass had already stopped, because the status was
    // `error` — and the page promises updates that never come.
    const errored: SubmissionDetail = { ...submission, status: 'error', result: null }
    vi.mocked(api.getSubmission).mockResolvedValue(errored)
    vi.mocked(api.retrySubmission).mockResolvedValue({ ...errored, status: 'pending' })
    const user = userEvent.setup()
    renderPage()

    await screen.findByText(/grading couldn.t complete/i)
    const before = vi.mocked(api.getSubmission).mock.calls.length

    // The grade lands between the retry and the next poll tick.
    vi.mocked(api.getSubmission).mockResolvedValue(submission)
    await user.click(screen.getByRole('button', { name: /retry grading/i }))

    expect(await screen.findByText('FAIL')).toBeInTheDocument()
    expect(vi.mocked(api.getSubmission).mock.calls.length).toBeGreaterThan(before)
  })

  it("shows the server's own words when a retry is refused", async () => {
    vi.mocked(api.getSubmission).mockResolvedValue({
      ...submission,
      status: 'error',
      result: null,
    })
    // 409: the status moved on. The server's wording beats a generic failure.
    vi.mocked(api.retrySubmission).mockRejectedValue(
      new ApiError(409, 'submission is not in an error state'),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /retry grading/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/not in an error state/i)
  })

  it('says the integrity report failed to load rather than spinning forever', async () => {
    vi.mocked(api.getSubmissionIntegrity).mockRejectedValueOnce(new Error('network'))
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /integrity/i }))

    expect(await screen.findByText(/couldn.t load the integrity report/i)).toBeInTheDocument()
    // Absence of evidence is the thing being judged on this screen, so a read
    // failure must never read as an empty timeline.
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()

    vi.mocked(api.getSubmissionIntegrity).mockResolvedValueOnce({
      monitored: true,
      summary: {
        total: 0,
        focus_losses: 0,
        away_ms: 0,
        fullscreen_exits: 0,
        pastes_blocked: 0,
        devtools_opens: 0,
      },
      events: [],
    })
    await user.click(screen.getByRole('button', { name: /^retry$/i }))

    expect(await screen.findByText(/stayed in fullscreen/i)).toBeInTheDocument()
  })

  it('says the code was destroyed for an erased candidate, rather than showing an empty editor', async () => {
    // An empty read-only editor reads as a candidate who submitted nothing —
    // a different and much worse thing to believe about them.
    vi.mocked(api.getSubmission).mockResolvedValue({
      ...submission,
      candidate: '[erased]',
      erased: true,
      code: '',
    })
    renderPage()

    expect(await screen.findByText(/data was erased/i)).toBeInTheDocument()
    expect(screen.getByText(/erased candidate/i)).toBeInTheDocument()
    expect(screen.queryByText('[erased]')).not.toBeInTheDocument()
  })

})
