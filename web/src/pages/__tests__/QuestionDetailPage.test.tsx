import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { QuestionDetailPage } from '../QuestionDetailPage'
import { api, ApiError } from '../../api'
import type { Invite, QuestionOut } from '../../types'

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
      getQuestion: vi.fn(),
      listInvites: vi.fn(),
      listSubmissions: vi.fn(),
      revokeInvite: vi.fn(),
      createInvite: vi.fn(),
      deleteQuestion: vi.fn(),
    },
    ApiError,
  }
})

const question: QuestionOut = {
  id: 'two-sum',
  title: 'Two Sum',
  prompt: 'Find two numbers that add up to target.',
  constraints: '1 <= n <= 1000',
  time_limit_s: 60,
  pass_threshold: 80,
  required_complexity: 'O(n)',
  example_input: '2 7 11 15\n9',
  example_output: '0 1',
  status: 'active',
  test_cases: [],
  created_at: '2026-07-14T00:00:00Z',
  updated_at: '2026-07-14T00:00:00Z',
}

const activeInvite: Invite = {
  token: 'tok123',
  url: 'http://localhost:5173/t/tok123',
  question_id: 'two-sum',
  assessment_id: null,
  variant_set_id: null,
  variant_label: null,
  recipients: ['candidate@example.com'],
  expires_at: null,
  status: 'active',
  deliveries: [],
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/questions/two-sum']}>
      <Routes>
        <Route path="/questions/:id" element={<QuestionDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('QuestionDetailPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getQuestion).mockResolvedValue(question)
    vi.mocked(api.listInvites).mockResolvedValue([activeInvite])
    vi.mocked(api.listSubmissions).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 })
  })

  it('revokes an active invite and reflects the new status', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.revokeInvite).mockResolvedValue({ ...activeInvite, status: 'revoked' })

    renderPage()

    const revokeButton = await screen.findByRole('button', { name: /revoke/i })
    await user.click(revokeButton)

    await waitFor(() => {
      expect(api.revokeInvite).toHaveBeenCalledWith('two-sum', 'tok123')
    })

    // Status cell now shows revoked and the revoke button is gone.
    expect(await screen.findByText('revoked')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /revoke/i })).not.toBeInTheDocument()
  })

  it('does not revoke when the confirm dialog is dismissed', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    renderPage()

    await user.click(await screen.findByRole('button', { name: /revoke/i }))

    expect(api.revokeInvite).not.toHaveBeenCalled()
  })

  it('surfaces a revoke failure near the row and keeps the invite active', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.mocked(api.revokeInvite).mockRejectedValue(new ApiError(500, 'server exploded'))

    renderPage()

    await user.click(await screen.findByRole('button', { name: /revoke/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent('server exploded')
    // The invite is unchanged (still active, revoke button still present).
    expect(screen.getByText('active')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /revoke/i })).toBeInTheDocument()
  })

  it('keeps the email field out of the way until you ask to invite', async () => {
    const user = userEvent.setup()
    renderPage()

    // A question needs no invite, so nothing should imply one is required.
    await screen.findByRole('button', { name: /send quick screen/i })
    expect(screen.queryByLabelText(/candidate emails/i)).not.toBeVisible()

    await user.click(screen.getByRole('button', { name: /send quick screen/i }))
    expect(screen.getByLabelText(/candidate emails/i)).toBeVisible()
  })

  it('cancels without creating anything', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /send quick screen/i }))
    await user.click(screen.getByRole('button', { name: /cancel/i }))

    expect(api.createInvite).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/candidate emails/i)).not.toBeVisible()
  })

  /** Click the card's "Send quick screen" and return a scope for the dialog — both
   *  the card button and the dialog's submit are called "Send quick screen". */
  async function openInviteDialog(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: /send quick screen/i }))
    return within(screen.getByRole('dialog'))
  }

  it('refuses to create an invite with no recipients', async () => {
    const user = userEvent.setup()
    renderPage()

    const dialog = await openInviteDialog(user)
    await user.click(dialog.getByRole('button', { name: /send quick screen/i }))

    expect(await dialog.findByRole('alert')).toHaveTextContent(/at least one candidate email/i)
    expect(api.createInvite).not.toHaveBeenCalled()
  })

  it('accepts several comma-separated addresses and confirms the send', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createInvite).mockResolvedValue({
      ...activeInvite,
      token: 'tok997',
      recipients: ['alice@example.com', 'bob@example.com'],
      deliveries: [
        { recipient: 'alice@example.com', sent: true, error: null },
        { recipient: 'bob@example.com', sent: true, error: null },
      ],
    })

    renderPage()

    const dialog = await openInviteDialog(user)
    await user.type(dialog.getByLabelText(/candidate emails/i), 'alice@example.com, bob@example.com')
    await user.click(dialog.getByRole('button', { name: /send quick screen/i }))

    await waitFor(() =>
      expect(api.createInvite).toHaveBeenCalledWith('two-sum', {
        recipients: ['alice@example.com', 'bob@example.com'],
        // Default is "Never", matching every invite the product has sent so far.
        expires_at: null,
      }),
    )
    // Dialog closes and the interviewer is told it went out.
    expect(await screen.findByRole('status')).toHaveTextContent(
      /quick screen sent to alice@example.com, bob@example.com/i,
    )
    expect(screen.getByLabelText(/candidate emails/i)).not.toBeVisible()
  })

  it('warns when the invite was created but the email did not send', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createInvite).mockResolvedValue({
      ...activeInvite,
      token: 'tok999',
      deliveries: [
        { recipient: 'candidate@example.com', sent: false, error: 'SMTP connection refused' },
      ],
    })

    renderPage()

    const dialog = await openInviteDialog(user)
    await user.type(dialog.getByLabelText(/candidate emails/i), 'candidate@example.com')
    await user.click(dialog.getByRole('button', { name: /send quick screen/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/couldn’t be sent to candidate@example.com/i)
    expect(alert).toHaveTextContent('SMTP connection refused')
    // No false "sent" confirmation alongside the failure.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('shows each sitting integrity count in the quick-screen results table (I1)', async () => {
    vi.mocked(api.listSubmissions).mockResolvedValue({
      items: [
        {
          submission_id: 's1',
          candidate_name: 'Alice',
          candidate_email: 'alice@x.io',
          language: 'python',
          status: 'done',
          verdict: 'PASS',
          score_pct: 100,
          integrity_signals: 2,
          integrity_blocked: 0,
          created_at: '2026-07-28',
        },
        {
          submission_id: 's2',
          candidate_name: 'Bob',
          candidate_email: 'bob@x.io',
          language: 'python',
          status: 'done',
          verdict: 'PASS',
          score_pct: 100,
          integrity_signals: null,
          integrity_blocked: 0,
          created_at: '2026-07-28',
        },
      ],
      total: 2,
      limit: 100,
      offset: 0,
    })

    renderPage()

    const flagged = await screen.findByTitle('2 signals recorded during this sitting')
    expect(flagged).toHaveTextContent('2')
    expect(screen.getByText('Not monitored')).toBeInTheDocument() // null ≠ 0
  })
})

describe('QuestionDetailPage — review and correction (UI-B)', () => {
  const withCases: QuestionOut = {
    ...question,
    duration_minutes: 30,
    test_cases: [
      {
        id: 'tc1',
        name: 'basic',
        stdin: '2 7 11 15\n9',
        expected: '0 1',
        category: 'correctness',
        weight: 1,
      },
      {
        id: 'tc2',
        name: 'big_case',
        stdin: 'huge-input',
        expected: 'huge-expected',
        category: 'performance',
        weight: 3,
      },
    ],
  }

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getQuestion).mockResolvedValue(withCases)
    vi.mocked(api.listInvites).mockResolvedValue([])
    vi.mocked(api.listSubmissions).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 })
  })

  it('shows the test cases and the time allowed, both already returned by the API', async () => {
    renderPage()

    // For an AI-drafted question this is the only way to review what the model
    // generated as expected output before a candidate is graded against it.
    expect(await screen.findByText('basic')).toBeInTheDocument()
    expect(screen.getByText('big_case')).toBeInTheDocument()
    expect(screen.getByText('performance')).toBeInTheDocument()
    expect(screen.getByText('30 min')).toBeInTheDocument()
    expect(screen.getByText(/never sent to the candidate/i)).toBeInTheDocument()
  })

  it('links Edit to the wizard seeded from this question', async () => {
    renderPage()
    expect(await screen.findByRole('link', { name: /^edit$/i })).toHaveAttribute(
      'href',
      '/questions/two-sum/edit',
    )
  })

  it("shows the server's own refusal when a question has submissions", async () => {
    vi.mocked(api.deleteQuestion).mockRejectedValue(
      new ApiError(409, "cannot delete question 'two-sum': 2 submission(s) are recorded against it."),
    )
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /^delete$/i }))
    await user.click(screen.getByRole('button', { name: /delete question/i }))

    // The rule lives server-side and its message names the count; paraphrasing
    // it here would let the two drift.
    expect(await screen.findByRole('alert')).toHaveTextContent(/2 submission\(s\) are recorded/i)
  })
})
