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
    await screen.findByRole('button', { name: /send invite/i })
    expect(screen.queryByLabelText(/candidate emails/i)).not.toBeVisible()

    await user.click(screen.getByRole('button', { name: /send invite/i }))
    expect(screen.getByLabelText(/candidate emails/i)).toBeVisible()
  })

  it('cancels without creating anything', async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole('button', { name: /send invite/i }))
    await user.click(screen.getByRole('button', { name: /cancel/i }))

    expect(api.createInvite).not.toHaveBeenCalled()
    expect(screen.getByLabelText(/candidate emails/i)).not.toBeVisible()
  })

  /** Click the card's "Send invite" and return a scope for the dialog — both the
   *  card button and the dialog's submit are called "Send invite". */
  async function openInviteDialog(user: ReturnType<typeof userEvent.setup>) {
    await user.click(await screen.findByRole('button', { name: /send invite/i }))
    return within(screen.getByRole('dialog'))
  }

  it('refuses to create an invite with no recipients', async () => {
    const user = userEvent.setup()
    renderPage()

    const dialog = await openInviteDialog(user)
    await user.click(dialog.getByRole('button', { name: /send invite/i }))

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
    await user.click(dialog.getByRole('button', { name: /send invite/i }))

    await waitFor(() =>
      expect(api.createInvite).toHaveBeenCalledWith('two-sum', {
        recipients: ['alice@example.com', 'bob@example.com'],
      }),
    )
    // Dialog closes and the interviewer is told it went out.
    expect(await screen.findByRole('status')).toHaveTextContent(
      /invite sent to alice@example.com, bob@example.com/i,
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
    await user.click(dialog.getByRole('button', { name: /send invite/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/couldn’t be sent to candidate@example.com/i)
    expect(alert).toHaveTextContent('SMTP connection refused')
    // No false "sent" confirmation alongside the failure.
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
