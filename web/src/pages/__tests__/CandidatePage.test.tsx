import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { ThemeProvider } from '../../theme/ThemeContext'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CandidatePage } from '../CandidatePage'
import { api } from '../../api'
import type { InviteStartResponse } from '../../types'

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
      getInvite: vi.fn(),
      startInvite: vi.fn(),
      submitCandidate: vi.fn(),
      runCandidate: vi.fn(),
      runCandidateTests: vi.fn(),
    },
    ApiError,
  }
})

vi.mock('@monaco-editor/react', () => ({
  default: ({
    value,
    onChange,
  }: {
    value?: string
    onChange?: (value: string | undefined) => void
  }) => (
    <textarea
      aria-label="code editor"
      value={value}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}))

const startResponse: InviteStartResponse = {
  question: {
    title: 'Two Sum',
    prompt: 'Find two numbers that add up to target.',
    constraints: '1 <= n <= 1000',
    example_input: '2 7 11 15\n9',
    example_output: '0 1',
    time_limit_s: 60,
  },
  languages: ['python', 'javascript'],
}

const multiStartResponse: InviteStartResponse = {
  question: startResponse.question,
  questions: [
    {
      id: 'q1', title: 'Two Sum', prompt: 'Find two numbers that add up to target.',
      constraints: '', example_input: '', example_output: '', time_limit_s: 2, submitted: false,
    },
    {
      id: 'q2', title: 'Merge Intervals', prompt: 'Merge overlapping intervals.',
      constraints: '', example_input: '', example_output: '', time_limit_s: 2, submitted: false,
    },
  ],
  languages: ['python', 'javascript'],
  deadline: null,
}

function renderCandidatePage() {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={['/t/tok123']}>
        <Routes>
          <Route path="/t/:token" element={<CandidatePage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

describe('CandidatePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Autosave persists to localStorage; isolate each test's drafts.
    localStorage.clear()
  })

  it('walks the candidate through gate -> editor -> submitted', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.submitCandidate).mockResolvedValue({
      submission_id: 'sub1',
      status: 'received',
    })

    renderCandidatePage()

    // Gate
    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))

    await waitFor(() => {
      expect(api.startInvite).toHaveBeenCalledWith('tok123', 'jane@example.com')
    })

    // Editor split view
    expect(await screen.findByText(/find two numbers/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/language/i)).toHaveValue('python')
    await user.type(screen.getByLabelText(/code editor/i), 'print("hi")')
    await user.click(screen.getByRole('button', { name: /^submit$/i }))

    await waitFor(() => {
      expect(api.submitCandidate).toHaveBeenCalledWith('tok123', {
        candidate_name: 'Jane Doe',
        candidate_email: 'jane@example.com',
        language: 'python',
        code: 'print("hi")',
      })
    })

    expect(await screen.findByRole('heading', { name: /submitted/i })).toBeInTheDocument()
  })

  it('multi-question assessment: shows the switcher, submits per question, and navigates', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(multiStartResponse)
    vi.mocked(api.submitCandidate).mockResolvedValue({ submission_id: 's', status: 'received' })

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))

    // Both questions appear as tabs; the first one's prompt is shown.
    expect(await screen.findByRole('tab', { name: /Two Sum/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /Merge Intervals/i })).toBeInTheDocument()
    expect(screen.getByText(/Find two numbers/i)).toBeInTheDocument()

    // Submit the current question — the call carries its question_id.
    await user.type(screen.getByLabelText(/code editor/i), 'print(1)')
    await user.click(screen.getByRole('button', { name: /submit this question/i }))
    await waitFor(() => {
      expect(api.submitCandidate).toHaveBeenCalledWith(
        'tok123',
        expect.objectContaining({ question_id: 'q1', code: 'print(1)' }),
      )
    })

    // Free navigation: clicking the second tab shows its prompt.
    await user.click(screen.getByRole('tab', { name: /Merge Intervals/i }))
    expect(screen.getByText(/Merge overlapping intervals/i)).toBeInTheDocument()
  })

  it('does not reveal the question until the gate is passed', async () => {
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    // The problem title/prompt must not be on the gate screen — it only arrives
    // with the /start response, after the email has been checked.
    expect(screen.queryByText(/two sum/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/find two numbers/i)).not.toBeInTheDocument()
  })

  it('turns away an uninvited email at the gate with no question data', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockRejectedValue(
      new ApiError(403, 'this assessment was not sent to that email address.'),
    )

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Mallory')
    await user.type(screen.getByLabelText(/^email$/i), 'mallory@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/wasn’t sent to that email/i)
    // Still on the gate; no problem leaked.
    expect(screen.queryByText(/find two numbers/i)).not.toBeInTheDocument()
  })

  it('shows "already recorded" when start returns 409', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockRejectedValue(
      new ApiError(409, 'your assessment has already been recorded for this email address.'),
    )

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))

    // Turned away before ever seeing the editor.
    expect(
      await screen.findByRole('heading', { name: /already recorded/i }),
    ).toBeInTheDocument()
    expect(screen.queryByLabelText(/code editor/i)).not.toBeInTheDocument()
  })

  it('shows an already-recorded message when submit returns 409', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.submitCandidate).mockRejectedValue(
      new ApiError(409, 'your assessment has already been recorded for this email address.'),
    )

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))

    await user.type(await screen.findByLabelText(/code editor/i), 'print("hi")')
    await user.click(screen.getByRole('button', { name: /^submit$/i }))

    expect(await screen.findByRole('heading', { name: /already recorded/i })).toBeInTheDocument()
  })

  /** Gate → editor, ready to exercise the in-editor actions. */
  async function reachEditor(user: ReturnType<typeof userEvent.setup>) {
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    renderCandidatePage()
    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))
    await user.type(await screen.findByLabelText(/code editor/i), 'print("hi")')
  }

  it('runs the code against the candidate’s own stdin and shows the output', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runCandidate).mockResolvedValue({
      stdout: '42',
      stderr: null,
      duration_s: 0.03,
      timed_out: false,
      compile_error: null,
    })

    await reachEditor(user)
    await user.type(screen.getByLabelText(/your input/i), '21')
    await user.click(screen.getByRole('button', { name: /^run$/i }))

    await waitFor(() => {
      expect(api.runCandidate).toHaveBeenCalledWith('tok123', {
        candidate_email: 'jane@example.com',
        language: 'python',
        code: 'print("hi")',
        stdin: '21',
      })
    })
    expect(await screen.findByText('42')).toBeInTheDocument()
  })

  it('shows a compile error from Run rather than an empty console', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runCandidate).mockResolvedValue({
      stdout: '',
      stderr: null,
      duration_s: 0,
      timed_out: false,
      compile_error: "line 1: expected ';'",
    })

    await reachEditor(user)
    await user.click(screen.getByRole('button', { name: /^run$/i }))

    expect(await screen.findByText(/expected ';'/)).toBeInTheDocument()
  })

  it('reports pass/fail per test case without revealing the cases', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runCandidateTests).mockResolvedValue({
      total: 3,
      passed: 2,
      compile_error: null,
      test_cases: [
        { index: 1, category: 'correctness', status: 'PASS', duration_s: 0.01 },
        { index: 2, category: 'correctness', status: 'FAIL', duration_s: 0.01 },
        { index: 3, category: 'performance', status: 'TLE', duration_s: 2 },
      ],
    })

    await reachEditor(user)
    await user.click(screen.getByRole('button', { name: /run against test cases/i }))

    expect(await screen.findByText(/2 of 3 test cases passed/i)).toBeInTheDocument()
    expect(screen.getByText('Test 1')).toBeInTheDocument()
    expect(screen.getByText('PASS')).toBeInTheDocument()
    expect(screen.getByText('FAIL')).toBeInTheDocument()
    expect(screen.getByText('TLE')).toBeInTheDocument()
  })

  it('does not submit when only running', async () => {
    const user = userEvent.setup()
    vi.mocked(api.runCandidateTests).mockResolvedValue({
      total: 1,
      passed: 1,
      compile_error: null,
      test_cases: [{ index: 1, category: 'correctness', status: 'PASS', duration_s: 0.01 }],
    })

    await reachEditor(user)
    await user.click(screen.getByRole('button', { name: /run against test cases/i }))
    await screen.findByText(/1 of 1 test cases passed/i)

    // Running is a rehearsal — the attempt is only spent on Submit.
    expect(api.submitCandidate).not.toHaveBeenCalled()
  })

  it('surfaces a rate-limit on Run without losing the candidate’s code', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.runCandidate).mockRejectedValue(new ApiError(429, 'too many requests'))

    await reachEditor(user)
    await user.click(screen.getByRole('button', { name: /^run$/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/too many runs/i)
    expect(screen.getByLabelText(/code editor/i)).toHaveValue('print("hi")')
  })

  it('restores an autosaved draft when the candidate returns', async () => {
    const user = userEvent.setup()
    localStorage.setItem(
      'assessment-draft:tok123',
      JSON.stringify({ code: 'saved work', language: 'javascript' }),
    )
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))

    const editor = await screen.findByLabelText(/code editor/i)
    expect(editor).toHaveValue('saved work')
    // The saved language is still offered, so it's the selected one.
    expect(screen.getByLabelText(/language/i)).toHaveValue('javascript')
    expect(screen.getByText(/draft restored/i)).toBeInTheDocument()
  })

  it('clears the saved draft once the attempt is recorded', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.submitCandidate).mockResolvedValue({ submission_id: 's', status: 'received' })

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))
    await user.type(await screen.findByLabelText(/code editor/i), 'print("hi")')
    await user.click(screen.getByRole('button', { name: /^submit$/i }))

    expect(await screen.findByRole('heading', { name: /submitted/i })).toBeInTheDocument()
    expect(localStorage.getItem('assessment-draft:tok123')).toBeNull()
  })

  it('shows an error for an expired invite', async () => {
    const { ApiError } = await import('../../api')
    vi.mocked(api.getInvite).mockRejectedValue(new ApiError(410, 'Expired'))

    renderCandidatePage()

    expect(await screen.findByText(/expired/i)).toBeInTheDocument()
  })

  it('shows an error for an invalid invite', async () => {
    const { ApiError } = await import('../../api')
    vi.mocked(api.getInvite).mockRejectedValue(new ApiError(404, 'Not found'))

    renderCandidatePage()

    expect(await screen.findByText(/invalid/i)).toBeInTheDocument()
  })
})
