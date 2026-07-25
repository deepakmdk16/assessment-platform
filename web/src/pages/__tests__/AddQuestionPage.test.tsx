import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AddQuestionPage } from '../AddQuestionPage'
import { api, ApiError } from '../../api'
import type { QuestionDraftOut, QuestionOut } from '../../types'

const navigateMock = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    api: { createQuestion: vi.fn(), draftQuestion: vi.fn() },
    ApiError,
  }
})

describe('AddQuestionPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  const next = (user: ReturnType<typeof userEvent.setup>) =>
    user.click(screen.getByRole('button', { name: /^next$/i }))

  it('walks the wizard and submits basics, one test case, and the worked example', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createQuestion).mockResolvedValue({ id: 'two-sum' } as QuestionOut)

    render(
      <MemoryRouter>
        <AddQuestionPage />
      </MemoryRouter>,
    )

    // Step 1: Basics
    await user.type(screen.getByLabelText(/^title$/i), 'Two Sum')
    await user.type(screen.getByLabelText(/^prompt$/i), 'Return indices of two numbers that add up to target.')
    await next(user)

    // Step 2: Grading
    await user.type(screen.getByLabelText(/^constraints$/i), '1 <= n <= 1000')
    await user.clear(screen.getByLabelText(/time limit/i))
    await user.type(screen.getByLabelText(/time limit/i), '3')
    await user.clear(screen.getByLabelText(/pass threshold/i))
    await user.type(screen.getByLabelText(/pass threshold/i), '80')
    await next(user)

    // Step 3: Test cases
    await user.type(screen.getByLabelText(/test case 1 name/i), 'basic')
    await user.type(screen.getByLabelText(/test case 1 stdin/i), '2 7 11 15\n9')
    await user.type(screen.getByLabelText(/test case 1 expected/i), '0 1')
    await next(user)

    // Step 4: Worked example
    await user.type(screen.getByLabelText(/example input/i), '2 7 11 15\n9')
    await user.type(screen.getByLabelText(/example output/i), '0 1')
    await next(user)

    // Step 5: Review → create
    await user.click(screen.getByRole('button', { name: /create question/i }))

    await waitFor(() => expect(api.createQuestion).toHaveBeenCalledTimes(1))
    const payload = vi.mocked(api.createQuestion).mock.calls[0][0]
    // The id is no longer entered here — the server generates it (A6).
    expect(payload.id).toBeUndefined()
    expect(payload.title).toBe('Two Sum')
    expect(payload.time_limit_s).toBe(3)
    // Wizard shows 80%; the API receives the 0..1 fraction.
    expect(payload.pass_threshold).toBe(0.8)
    expect(payload.test_cases).toHaveLength(1)
    expect(payload.test_cases[0]).toMatchObject({
      name: 'basic',
      category: 'correctness',
      weight: 1,
    })

    // `justCreated` makes the question page offer the invite dialog once.
    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith('/questions/two-sum', {
        state: { justCreated: true },
      }),
    )
  })

  const draftFixture = (): QuestionDraftOut => ({
    question: {
      id: 'longest-run',
      title: 'Longest increasing run',
      prompt: 'Print the longest strictly increasing run.',
      constraints: '1 <= n <= 1e5',
      time_limit_s: 2,
      pass_threshold: 0.9,
      required_complexity: 'O(n)',
      example_input: '4\n1 2 1 3\n',
      example_output: '2',
      test_cases: [
        { name: 't1', stdin: '4\n1 2 1 3\n', expected: '2', category: 'correctness', weight: 1 },
      ],
    },
    warnings: ['Dropped case edge: reference timed out.'],
    reference_solution: 'print("ref")',
    reference_language: 'python',
    engine: 'claude-sonnet-4-6',
    cost_usd: 0.02,
  })

  it('drafts with AI and pre-fills the wizard fields', async () => {
    const user = userEvent.setup()
    vi.mocked(api.draftQuestion).mockResolvedValue(draftFixture())

    render(
      <MemoryRouter>
        <AddQuestionPage />
      </MemoryRouter>,
    )

    // Expand the collapsed "Draft with AI" panel (only the toggle has aria-expanded).
    await user.click(screen.getByRole('button', { expanded: false }))
    await user.type(screen.getByLabelText(/^brief$/i), 'Longest increasing run')
    await user.click(screen.getByRole('button', { name: /^draft with ai$/i }))

    await waitFor(() => expect(api.draftQuestion).toHaveBeenCalledTimes(1))
    // Fields populated from the draft.
    expect(screen.getByLabelText(/^title$/i)).toHaveValue('Longest increasing run')
    expect(screen.getByLabelText(/^prompt$/i)).toHaveValue('Print the longest strictly increasing run.')
    // Warning surfaced.
    expect(screen.getByText(/reference timed out/i)).toBeInTheDocument()
  })

  /** Open the Draft panel and attempt a draft. */
  async function attemptDraft(user: ReturnType<typeof userEvent.setup>) {
    render(
      <MemoryRouter>
        <AddQuestionPage />
      </MemoryRouter>,
    )
    await user.click(screen.getByRole('button', { expanded: false }))
    await user.type(screen.getByLabelText(/^brief$/i), 'Longest increasing run')
    await user.click(screen.getByRole('button', { name: /^draft with ai$/i }))
  }

  it('offers a retry when drafting fails for a reason a retry could fix', async () => {
    const user = userEvent.setup()
    vi.mocked(api.draftQuestion).mockRejectedValue(new ApiError(502, 'agent unreachable'))

    await attemptDraft(user)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/couldn’t reach the ai drafting service/i)

    // Retrying actually re-calls the API — the dead end is gone.
    vi.mocked(api.draftQuestion).mockResolvedValue(draftFixture())
    await user.click(screen.getByRole('button', { name: /try again/i }))
    await waitFor(() => expect(api.draftQuestion).toHaveBeenCalledTimes(2))
    expect(screen.getByLabelText(/^title$/i)).toHaveValue('Longest increasing run')
  })

  it('does not offer a retry when the server has no model key (503)', async () => {
    const user = userEvent.setup()
    vi.mocked(api.draftQuestion).mockRejectedValue(new ApiError(503, 'needs a live model'))

    await attemptDraft(user)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/no model api key/i)
    // Retrying can't fix config, so don't invite the interviewer to try.
    expect(screen.queryByRole('button', { name: /try again/i })).not.toBeInTheDocument()
  })

  it('explains an unusable draft (422) and shows the agent’s reason', async () => {
    const user = userEvent.setup()
    vi.mocked(api.draftQuestion).mockRejectedValue(
      new ApiError(422, 'Reference solution failed to compile: missing header'),
    )

    await attemptDraft(user)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/couldn’t turn this brief into a working question/i)
    expect(alert).toHaveTextContent(/failed to compile/i)
    // A different brief might work, so a retry is still offered.
    expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument()
  })

  it('adds and removes test case rows', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <AddQuestionPage />
      </MemoryRouter>,
    )

    // Advance to the Test cases step (Basics → Grading → Test cases).
    await user.type(screen.getByLabelText(/^title$/i), 'Two Sum')
    await user.type(screen.getByLabelText(/^prompt$/i), 'Prompt text.')
    await next(user)
    await next(user)

    expect(screen.getAllByLabelText(/test case \d+ name/i)).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: /add test case/i }))
    expect(screen.getAllByLabelText(/test case \d+ name/i)).toHaveLength(2)

    await user.click(screen.getAllByRole('button', { name: /remove/i })[0])
    expect(screen.getAllByLabelText(/test case \d+ name/i)).toHaveLength(1)
  })
})
