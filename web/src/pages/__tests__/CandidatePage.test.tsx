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
      postIntegrityEvents: vi.fn(() => Promise.resolve()),
      startInvite: vi.fn(),
      submitCandidate: vi.fn(),
      runCandidate: vi.fn(),
      runCandidateTests: vi.fn(),
      getCandidateDrafts: vi.fn(() => Promise.resolve({ drafts: [] })),
      saveCandidateDraft: vi.fn(() => Promise.resolve()),
    },
    ApiError,
  }
})

// The fullscreen gate is browser state the jsdom environment can't produce, so
// the hook is mocked and driven directly. Everything else stays real.
const integrityState = vi.hoisted(() => ({
  mustReturnToFullscreen: false,
}))
vi.mock('../../integrity', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../integrity')>()
  return {
    ...actual,
    useIntegrity: () => ({
      mustReturnToFullscreen: integrityState.mustReturnToFullscreen,
      fullscreenExits: integrityState.mustReturnToFullscreen ? 1 : 0,
      pasteBlocked: null,
      dismissPasteBlock: vi.fn(),
      enterFullscreen: vi.fn(async () => {}),
      flush: vi.fn(),
    }),
  }
})

vi.mock('@monaco-editor/react', () => ({
  default: ({
    value,
    onChange,
    options,
  }: {
    value?: string
    onChange?: (value: string | undefined) => void
    options?: { readOnly?: boolean }
  }) => (
    <textarea
      aria-label="code editor"
      value={value}
      readOnly={options?.readOnly}
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
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    await user.click(screen.getByRole('button', { name: /start/i }))

    await waitFor(() => {
      // The consent the candidate gave at the gate travels with the start (X04);
      // the server refuses a sitting that begins without it.
      expect(api.startInvite).toHaveBeenCalledWith(
        'tok123',
        'jane@example.com',
        'Jane Doe',
        true,
      )
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
        // Carried so a submit that is itself the start of the sitting still
        // records what the candidate agreed to (X04).
        consent: true,
      })
    })

    expect(await screen.findByRole('heading', { name: /submitted/i })).toBeInTheDocument()
  })

  it('cannot start until the candidate has consented', async () => {
    const user = userEvent.setup()
    renderCandidatePage()
    await user.type(await screen.findByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')

    // The server refuses this too (422). Disabling the button is only so the
    // candidate meets the requirement as a choice rather than as an error.
    expect(screen.getByRole('button', { name: /start/i })).toBeDisabled()
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    expect(screen.getByRole('button', { name: /start/i })).toBeEnabled()
    expect(api.startInvite).not.toHaveBeenCalled()
  })

  it('names the monitoring in what the candidate agrees to, when monitored', async () => {
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active', proctored: true })
    renderCandidatePage()
    expect(await screen.findByLabelText(/including the monitoring described above/i)).toBeInTheDocument()
  })

  it('does not claim monitoring in the consent for an unmonitored sitting', async () => {
    // Agreeing to monitoring that is not happening is a false record, and it is
    // the record that a lawful basis rests on.
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active', proctored: false })
    renderCandidatePage()
    expect(await screen.findByLabelText(/i agree to my assessment/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/including the monitoring/i)).not.toBeInTheDocument()
  })

  it('discloses monitoring on the gate before the candidate identifies themselves', async () => {
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active', proctored: true })
    renderCandidatePage()

    expect(await screen.findByText(/this sitting is monitored/i)).toBeInTheDocument()
    expect(screen.getByText(/pasting code from outside this page is blocked/i)).toBeInTheDocument()
    // Nothing has been recorded yet — the notice comes first.
    expect(api.postIntegrityEvents).not.toHaveBeenCalled()
  })

  it('says nothing about monitoring when the sitting is unmonitored', async () => {
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active', proctored: false })
    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    expect(screen.queryByText(/this sitting is monitored/i)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^start assessment$/i })).toBeInTheDocument()
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
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
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

  it('renders per-assessment branding on the IDE header when present (A12)', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue({
      ...multiStartResponse,
      assessment_title: 'Backend Screen',
      org_name: 'Acme Corp',
      logo_url: 'https://cdn.example.com/acme.png',
    })

    const { container } = renderCandidatePage()
    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    await user.click(screen.getByRole('button', { name: /start/i }))

    expect(await screen.findByText('Acme Corp — Backend Screen')).toBeInTheDocument()
    expect(screen.getByText(/powered by assess\.dev/i)).toBeInTheDocument()
    // The logo is decorative (empty alt) since the adjacent text already
    // carries the org name, so query it directly rather than by role="img".
    expect(container.querySelector('img.ide-brand-logo')).toHaveAttribute(
      'src',
      'https://cdn.example.com/acme.png',
    )
  })

  it('falls back to the generic header when an assessment has no branding', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(multiStartResponse)

    renderCandidatePage()
    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    await user.click(screen.getByRole('button', { name: /start/i }))

    await screen.findByRole('tab', { name: /Two Sum/i })
    expect(screen.getByText('Coding assessment')).toBeInTheDocument()
    expect(screen.queryByText(/powered by assess\.dev/i)).not.toBeInTheDocument()
  })

  it('shows a completion screen once every question is submitted manually (A5)', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(multiStartResponse)
    vi.mocked(api.submitCandidate).mockResolvedValue({ submission_id: 's', status: 'received' })

    renderCandidatePage()
    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    await user.click(screen.getByRole('button', { name: /start/i }))

    await screen.findByRole('tab', { name: /Two Sum/i })
    await user.type(screen.getByLabelText(/code editor/i), 'print(1)')
    await user.click(screen.getByRole('button', { name: /submit this question/i }))
    await waitFor(() => expect(api.submitCandidate).toHaveBeenCalledTimes(1))

    // Still on the IDE with one question left — no completion screen yet.
    expect(screen.queryByRole('heading', { name: /assessment complete/i })).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: /Merge Intervals/i }))
    await user.type(screen.getByLabelText(/code editor/i), 'print(2)')
    await user.click(screen.getByRole('button', { name: /submit this question/i }))
    await waitFor(() => expect(api.submitCandidate).toHaveBeenCalledTimes(2))

    expect(await screen.findByRole('heading', { name: /assessment complete/i })).toBeInTheDocument()
    expect(screen.getByText(/2 of 2 questions were submitted for grading/i)).toBeInTheDocument()
    // The IDE is gone entirely, not just disabled.
    expect(screen.queryByLabelText(/code editor/i)).not.toBeInTheDocument()
  })

  it('shows a completion screen when time runs out, even with an unanswered question (A5)', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue({
      ...multiStartResponse,
      deadline: new Date(Date.now() - 1000).toISOString(), // already expired
    })

    renderCandidatePage()
    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    await user.click(screen.getByRole('button', { name: /start/i }))

    // Neither question was ever answered, so nothing to auto-submit — the
    // terminal screen must still appear once the timeout pass settles, not
    // leave the candidate stuck on a locked IDE forever.
    expect(await screen.findByRole('heading', { name: /assessment complete/i })).toBeInTheDocument()
    expect(screen.getByText(/0 of 2 questions were submitted for grading/i)).toBeInTheDocument()
    expect(api.submitCandidate).not.toHaveBeenCalled()
  })

  it('lands on a terminal notice when time runs out with an empty editor (single question)', async () => {
    // Before: the auto-submit fired unconditionally, the server 422'd the empty
    // code, and the candidate sat on a locked IDE reading "submitting…" forever.
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue({
      ...startResponse,
      deadline: new Date(Date.now() - 1000).toISOString(), // already expired
    })

    renderCandidatePage()
    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    await user.click(screen.getByRole('button', { name: /start/i }))

    expect(await screen.findByRole('heading', { name: /time.s up/i })).toBeInTheDocument()
    expect(screen.getByText(/nothing was submitted/i)).toBeInTheDocument()
    expect(screen.queryByLabelText(/code editor/i)).not.toBeInTheDocument()
    expect(api.submitCandidate).not.toHaveBeenCalled()
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
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
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
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
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
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
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
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
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
      'assessment-draft:tok123:jane@example.com',
      JSON.stringify({ code: 'saved work', language: 'javascript' }),
    )
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: /coding assessment/i })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
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
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
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

describe('server drafts (CX2)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active' })
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({ drafts: [] })
    vi.mocked(api.saveCandidateDraft).mockResolvedValue(undefined)
  })

  async function startSitting() {
    const user = userEvent.setup()
    renderCandidatePage()
    await user.type(await screen.findByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    await user.click(screen.getByRole('button', { name: /start/i }))
    return user
  }

  it('restores the server draft when localStorage has nothing (device switch)', async () => {
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({
      drafts: [
        { question_id: 'q1', code: 'server saved code', language: 'javascript', updated_at: 'x' },
      ],
    })

    await startSitting()

    expect(await screen.findByLabelText(/code editor/i)).toHaveValue('server saved code')
    expect(screen.getByLabelText(/language/i)).toHaveValue('javascript')
  })

  it('prefers the local draft when it is the newer of the two', async () => {
    localStorage.setItem(
      'assessment-draft:tok123:jane@example.com',
      JSON.stringify({
        code: 'local, freshest',
        language: 'python',
        saved_at: '2026-09-08T12:00:00Z',
      }),
    )
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({
      drafts: [
        {
          question_id: 'q1',
          code: 'older server copy',
          language: 'python',
          updated_at: '2026-09-08T11:00:00Z',
        },
      ],
    })

    await startSitting()

    expect(await screen.findByLabelText(/code editor/i)).toHaveValue('local, freshest')
  })

  it('prefers the server draft when it is newer, instead of hiding it behind a stale local copy', async () => {
    // The old rule was "local always wins", so work saved from another device
    // was silently invisible behind whatever this browser happened to hold.
    localStorage.setItem(
      'assessment-draft:tok123:jane@example.com',
      JSON.stringify({
        code: 'stale local copy',
        language: 'python',
        saved_at: '2026-09-08T10:00:00Z',
      }),
    )
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({
      drafts: [
        {
          question_id: 'q1',
          code: 'newer work from my laptop',
          language: 'python',
          updated_at: '2026-09-08T12:00:00Z',
        },
      ],
    })

    await startSitting()

    expect(await screen.findByLabelText(/code editor/i)).toHaveValue('newer work from my laptop')
    // And because the two genuinely differ, the candidate is told rather than
    // having one silently discarded.
    expect(screen.getByRole('dialog', { name: /two versions of your work/i })).toBeInTheDocument()
  })

  it('restores the chosen draft\'s language, not just its code', async () => {
    // Restoring code alone reopened a Java answer under Python, which then fails
    // to compile — the candidate's own work, sabotaged by the restore.
    localStorage.setItem(
      'assessment-draft:tok123:jane@example.com',
      JSON.stringify({
        code: 'local version',
        language: 'javascript',
        saved_at: '2026-09-08T12:00:00Z',
      }),
    )
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({
      drafts: [
        {
          question_id: 'q1',
          code: 'server version',
          language: 'python',
          updated_at: '2026-09-08T11:00:00',
        },
      ],
    })
    const user = await startSitting()

    await screen.findByRole('dialog', { name: /two versions of your work/i })
    await user.click(screen.getByRole('button', { name: /your account/i }))

    expect(await screen.findByLabelText(/code editor/i)).toHaveValue('server version')
    expect(screen.getByLabelText(/language/i)).toHaveValue('python')
  })

  it('compares draft ages as UTC, so the server copy is not mis-ranked', async () => {
    // updated_at arrives with no offset. Read as local time it lands hours away
    // from the instant the server meant, and "newest wins" picks the wrong one.
    localStorage.setItem(
      'assessment-draft:tok123:jane@example.com',
      JSON.stringify({
        code: 'local, one hour older',
        language: 'python',
        saved_at: '2026-09-08T11:00:00Z',
      }),
    )
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({
      drafts: [
        {
          question_id: 'q1',
          code: 'server, newer',
          language: 'python',
          updated_at: '2026-09-08T12:00:00',
        },
      ],
    })

    await startSitting()

    expect(await screen.findByLabelText(/code editor/i)).toHaveValue('server, newer')
  })

  it("does not seed a candidate with the previous candidate's work on a shared machine", async () => {
    // Keyed on the token alone, the next person to open the same link inherited
    // whatever the last one left unsent.
    localStorage.setItem(
      'assessment-draft:tok123:someone.else@example.com',
      JSON.stringify({ code: 'not my code', language: 'python' }),
    )
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({ drafts: [] })

    await startSitting()

    expect(await screen.findByLabelText(/code editor/i)).not.toHaveValue('not my code')
  })

  it('autosaves the code to the server while editing', async () => {
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    const user = await startSitting()

    await user.type(await screen.findByLabelText(/code editor/i), 'print(42)')
    // The server save is debounced (2s) behind the localStorage one.
    await waitFor(
      () =>
        expect(api.saveCandidateDraft).toHaveBeenCalledWith(
          'tok123',
          expect.objectContaining({ candidate_email: 'jane@example.com', code: 'print(42)' }),
        ),
      { timeout: 4000 },
    )
  })

  it('seeds each question of a multi-question sitting from its own draft', async () => {
    vi.mocked(api.startInvite).mockResolvedValue(multiStartResponse)
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({
      drafts: [
        { question_id: 'q2', code: 'draft for merge intervals', language: 'python', updated_at: 'x' },
      ],
    })

    const user = await startSitting()

    // q1 had no draft — blank editor.
    expect(await screen.findByLabelText(/code editor/i)).toHaveValue('')
    // q2 resumes from its server draft.
    await user.click(screen.getByRole('tab', { name: /merge intervals/i }))
    expect(screen.getByLabelText(/code editor/i)).toHaveValue('draft for merge intervals')
  })
})

describe('CandidatePage — the fullscreen block actually blocks (UI-D / W05)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    integrityState.mustReturnToFullscreen = false
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active', proctored: true })
    vi.mocked(api.startInvite).mockResolvedValue(startResponse)
    vi.mocked(api.getCandidateDrafts).mockResolvedValue({ drafts: [] })
  })

  async function start() {
    const user = userEvent.setup()
    renderCandidatePage()
    await user.type(await screen.findByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByLabelText(/i agree to my assessment/i))
    await user.click(screen.getByRole('button', { name: /start/i }))
    return user
  }

  it('leaves the editor writable while the candidate is in fullscreen', async () => {
    await start()
    expect(await screen.findByLabelText(/code editor/i)).not.toHaveAttribute('readonly')
  })

  it('locks the editor and every action when the gate is up', async () => {
    integrityState.mustReturnToFullscreen = true
    await start()

    // The scrim was a pointer overlay only, so the candidate kept typing behind
    // a screen that said they were blocked — while STATUS claimed otherwise.
    expect(await screen.findByLabelText(/code editor/i)).toHaveAttribute('readonly')
    expect(screen.getByRole('button', { name: /^run$/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /submit/i })).toBeDisabled()
  })
})
