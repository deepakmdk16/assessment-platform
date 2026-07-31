import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AssessmentDetailPage } from '../AssessmentDetailPage'
import { api } from '../../api'
import type { AssessmentAttempt, AssessmentOut, Invite } from '../../types'

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
      listAssessmentAttempts: vi.fn(),
      createAssessmentInvite: vi.fn(),
    },
    ApiError,
  }
})

const assessment: AssessmentOut = {
  id: 'week-1',
  title: 'Backend Screen',
  org_name: null,
  logo_url: null,
  proctored: true,
  duration_minutes: 90,
  status: 'active',
  created_at: '2026-07-14T00:00:00Z',
  updated_at: '2026-07-14T00:00:00Z',
  questions: [
    { question_id: 'two-sum', variant_set_id: null, variant_count: null, position: 0, title: 'Two Sum' },
  ],
}

function baseInvite(overrides: Partial<Invite>): Invite {
  return {
    token: 'tok123',
    url: 'http://localhost:5173/t/tok123',
    question_id: null,
    assessment_id: 'week-1',
    variant_set_id: null,
    variant_label: null,
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
        <Route path="/submissions/:id" element={<div>Submission detail page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('AssessmentDetailPage — invite delivery (A4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getAssessment).mockResolvedValue(assessment)
    vi.mocked(api.listAssessmentInvites).mockResolvedValue([])
    vi.mocked(api.listAssessmentAttempts).mockResolvedValue([])
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

describe('AssessmentDetailPage — attempts (A3/A11)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.getAssessment).mockResolvedValue(assessment)
    vi.mocked(api.listAssessmentInvites).mockResolvedValue([])
  })

  const attempt: AssessmentAttempt = {
    candidate_name: 'Jane Doe',
    candidate_email: 'jane@example.com',
    passed_count: 1,
    total_count: 1,
    avg_score_pct: 92,
    questions: [
      {
        question_id: 'two-sum',
        variant_set_id: null,
        variant_label: null,
        title: 'Two Sum',
        submitted: true,
        late: false,
        submission_id: 'sub-1',
        verdict: 'PASS',
        score_pct: 92,
      },
    ],
  }

  it('shows one row per candidate with the pass count and average score', async () => {
    vi.mocked(api.listAssessmentAttempts).mockResolvedValue([attempt])
    renderPage()

    await screen.findByText('Jane Doe')
    expect(screen.getByText('jane@example.com')).toBeInTheDocument()
    expect(screen.getByText('1 / 1')).toBeInTheDocument()
    expect(screen.getByText('92%')).toBeInTheDocument()
  })

  it('clicking a graded question chip opens its full submission', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listAssessmentAttempts).mockResolvedValue([attempt])
    renderPage()

    await screen.findByText('Jane Doe')
    await user.click(screen.getByTitle(/two sum: pass/i))

    expect(await screen.findByText('Submission detail page')).toBeInTheDocument()
  })

  it('renders no Attempts section when nobody has started yet', async () => {
    vi.mocked(api.listAssessmentAttempts).mockResolvedValue([])
    renderPage()

    await screen.findByRole('heading', { name: /backend screen/i })
    expect(screen.queryByRole('heading', { name: /attempts/i })).not.toBeInTheDocument()
  })

  it('shows a variant-set slot and each candidate’s assigned variant (VS2)', async () => {
    vi.mocked(api.getAssessment).mockResolvedValue({
      ...assessment,
      questions: [
        { question_id: null, variant_set_id: 's1', variant_count: 3, position: 0, title: 'Pairs' },
      ],
    })
    vi.mocked(api.listAssessmentAttempts).mockResolvedValue([
      {
        ...attempt,
        questions: [
          {
            question_id: 's1_b',
            variant_set_id: 's1',
            variant_label: 'B',
            title: 'Pairs',
            submitted: true,
            late: false,
            submission_id: 'sub-1',
            verdict: 'PASS',
            score_pct: 80,
          },
        ],
      },
    ])
    renderPage()

    // The questions table marks it as a variant set with its variant count.
    expect(await screen.findByText(/variant set · 3 variants/i)).toBeInTheDocument()
    // The attempt chip names the variant THIS candidate was handed.
    expect(screen.getByTitle(/pairs \(variant b\): pass/i)).toBeInTheDocument()
  })

  it('flags a submission that arrived after the timed window closed', async () => {
    vi.mocked(api.listAssessmentAttempts).mockResolvedValue([
      {
        ...attempt,
        questions: [{ ...attempt.questions[0], late: true }],
      },
    ])
    renderPage()

    await screen.findByText('Jane Doe')
    // The chip tooltip tells the interviewer the work came in late (and it keeps
    // its PASS verdict — a late submission is still recorded and graded).
    const chip = screen.getByTitle(/two sum · submitted late: pass/i)
    expect(chip).toHaveTextContent('1')
    expect(chip).toHaveClass('late')
  })
})
