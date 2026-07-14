import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CandidatePage } from '../CandidatePage'
import { api } from '../../api'
import type { InviteGetResponse } from '../../types'

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    api: { getInvite: vi.fn(), submitCandidate: vi.fn() },
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

const inviteResponse: InviteGetResponse = {
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

function renderCandidatePage() {
  return render(
    <MemoryRouter initialEntries={['/t/tok123']}>
      <Routes>
        <Route path="/t/:token" element={<CandidatePage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('CandidatePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('walks the candidate through gate -> editor -> submitted', async () => {
    const user = userEvent.setup()
    vi.mocked(api.getInvite).mockResolvedValue(inviteResponse)
    vi.mocked(api.submitCandidate).mockResolvedValue({
      submission_id: 'sub1',
      status: 'received',
    })

    renderCandidatePage()

    // Gate
    expect(await screen.findByRole('heading', { name: 'Two Sum' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))

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

  it('shows an already-submitted message when submit returns 409', async () => {
    const user = userEvent.setup()
    const { ApiError } = await import('../../api')
    vi.mocked(api.getInvite).mockResolvedValue(inviteResponse)
    vi.mocked(api.submitCandidate).mockRejectedValue(
      new ApiError(409, 'a submission for this email already exists on this invite.'),
    )

    renderCandidatePage()

    expect(await screen.findByRole('heading', { name: 'Two Sum' })).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^name$/i), 'Jane Doe')
    await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
    await user.click(screen.getByRole('button', { name: /start/i }))

    await user.type(screen.getByLabelText(/code editor/i), 'print("hi")')
    await user.click(screen.getByRole('button', { name: /^submit$/i }))

    expect(await screen.findByRole('heading', { name: /already submitted/i })).toBeInTheDocument()
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
