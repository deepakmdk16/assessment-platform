import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AssessmentDetailPage } from '../AssessmentDetailPage'
import { api } from '../../api'
import type { AssessmentOut, Invite } from '../../types'

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
      getAssessment: vi.fn(),
      listAssessmentInvites: vi.fn(),
      createAssessmentInvite: vi.fn(),
    },
    ApiError,
  }
})

const assessment: AssessmentOut = {
  id: 'week-1',
  title: 'Backend Screen',
  duration_minutes: 90,
  status: 'active',
  created_at: '2026-07-14T00:00:00Z',
  updated_at: '2026-07-14T00:00:00Z',
  questions: [{ question_id: 'two-sum', position: 0, title: 'Two Sum' }],
}

function baseInvite(overrides: Partial<Invite>): Invite {
  return {
    token: 'tok123',
    url: 'http://localhost:5173/t/tok123',
    question_id: null,
    assessment_id: 'week-1',
    recipients: ['candidate@example.com'],
    expires_at: null,
    status: 'active',
    deliveries: [],
    ...overrides,
  }
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/assessments/week-1']}>
      <Routes>
        <Route path="/assessments/:id" element={<AssessmentDetailPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AssessmentDetailPage — invite delivery (A4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getAssessment).mockResolvedValue(assessment)
    vi.mocked(api.listAssessmentInvites).mockResolvedValue([])
  })

  it('confirms delivery only for recipients the email actually reached', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessmentInvite).mockResolvedValue(
      baseInvite({
        deliveries: [{ recipient: 'alice@example.com', sent: true, error: null }],
      }),
    )

    renderPage()
    await screen.findByRole('heading', { name: /backend screen/i })

    await user.type(screen.getByLabelText(/candidate emails/i), 'alice@example.com')
    await user.click(screen.getByRole('button', { name: /send invite/i }))

    expect(await screen.findByRole('status')).toHaveTextContent(/invite sent to alice@example.com/i)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('warns when the invite was created but the email did not send', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessmentInvite).mockResolvedValue(
      baseInvite({
        deliveries: [
          { recipient: 'candidate@example.com', sent: false, error: 'SMTP connection refused' },
        ],
      }),
    )

    renderPage()
    await screen.findByRole('heading', { name: /backend screen/i })

    await user.type(screen.getByLabelText(/candidate emails/i), 'candidate@example.com')
    await user.click(screen.getByRole('button', { name: /send invite/i }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/couldn’t be sent to candidate@example.com/i)
    expect(alert).toHaveTextContent('SMTP connection refused')
    // No false "sent" confirmation alongside the failure.
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })
})
