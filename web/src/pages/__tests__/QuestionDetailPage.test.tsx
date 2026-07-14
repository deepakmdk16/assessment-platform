import { render, screen, waitFor } from '@testing-library/react'
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
    vi.mocked(api.listSubmissions).mockResolvedValue([])
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
})
