import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
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
    api: { getInvite: vi.fn(), startInvite: vi.fn(), submitCandidate: vi.fn() },
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
