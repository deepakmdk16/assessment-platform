import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SubmissionDetailPage } from '../SubmissionDetailPage'
import { api } from '../../api'
import type { AgentFullResult, QuestionOut, SubmissionDetail } from '../../types'

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return { api: { getSubmission: vi.fn(), getQuestion: vi.fn() }, ApiError }
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
  language: 'python',
  code: 'print("hi")',
  status: 'done',
  agent_job_id: 'job1',
  created_at: '2026-07-16T00:00:00Z',
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
    <MemoryRouter initialEntries={['/submissions/sub1']}>
      <Routes>
        <Route path="/submissions/:id" element={<SubmissionDetailPage />} />
      </Routes>
    </MemoryRouter>,
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

  it('shows a pending notice when the agent has not called back yet', async () => {
    vi.mocked(api.getSubmission).mockResolvedValue({
      ...submission,
      status: 'running',
      result: null,
    })
    renderPage()

    expect(await screen.findByText(/hasn’t been graded yet/i)).toBeInTheDocument()
  })
})
