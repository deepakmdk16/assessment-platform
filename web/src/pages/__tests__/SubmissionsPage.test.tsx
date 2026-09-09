import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SubmissionsPage } from '../SubmissionsPage'
import { api } from '../../api'
import type { Page, QuestionOut, SubmissionSummary } from '../../types'

const navigateMock = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../../api', () => ({
  api: { listAllSubmissions: vi.fn(), listQuestions: vi.fn(), retrySubmission: vi.fn() },
  ApiError: class ApiError extends Error {},
  exportSubmissionsCsv: vi.fn(),
}))

function page<T>(items: T[]): Page<T> {
  return { items, total: items.length, limit: 100, offset: 0 }
}

const sub = (overrides: Partial<SubmissionSummary>): SubmissionSummary => ({
  id: 's1',
  question_id: 'two-sum',
  candidate: 'Alice',
  candidate_email: null,
  erased: false,
  language: 'python',
  status: 'done',
  agent_job_id: 'job1',
  created_at: '2026-07-24T00:00:00Z',
  ...overrides,
})

describe('SubmissionsPage — assessment linkage (A3)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.listQuestions).mockResolvedValue(page<QuestionOut>([]))
  })

  it('tags an assessment-linked submission with the assessment title, and a direct one as Standalone', async () => {
    vi.mocked(api.listAllSubmissions).mockResolvedValue(
      page([
        sub({ id: 's1', candidate: 'Alice', assessment_id: 'a1', assessment_title: 'Backend Screen' }),
        sub({ id: 's2', candidate: 'Bob', assessment_id: null, assessment_title: null }),
      ]),
    )

    render(
      <MemoryRouter>
        <SubmissionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Backend Screen')).toBeInTheDocument()
    expect(screen.getByText('Standalone')).toBeInTheDocument()
  })

  it('shows each sitting integrity count, telling unmonitored apart from a clean zero (I1)', async () => {
    vi.mocked(api.listAllSubmissions).mockResolvedValue(
      page([
        sub({ id: 's1', candidate: 'Alice', integrity_signals: 3, integrity_blocked: 1 }),
        sub({ id: 's2', candidate: 'Bob', integrity_signals: 0, integrity_blocked: 0 }),
        sub({ id: 's3', candidate: 'Carol', integrity_signals: null }),
      ]),
    )

    render(
      <MemoryRouter>
        <SubmissionsPage />
      </MemoryRouter>,
    )

    const flagged = await screen.findByTitle('3 signals, including 1 blocked paste')
    expect(flagged).toHaveTextContent('3')
    expect(screen.getByText('Not monitored')).toBeInTheDocument() // null ≠ 0
  })
})

describe('SubmissionsPage — recovering a failed grading (UI-A)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.listQuestions).mockResolvedValue(page<QuestionOut>([]))
  })

  it('offers Retry only on the rows that failed, and updates that row in place', async () => {
    vi.mocked(api.listAllSubmissions).mockResolvedValue(
      page([
        sub({ id: 'ok', candidate: 'Alice', status: 'done' }),
        sub({ id: 'bad', candidate: 'Bo', status: 'error' }),
      ]),
    )
    vi.mocked(api.retrySubmission).mockResolvedValue({
      id: 'bad',
      question_id: 'two-sum',
      candidate: 'Bo',
      erased: false,
      language: 'python',
      code: '',
      status: 'pending',
      agent_job_id: null,
      created_at: '2026-07-24T00:00:00Z',
      late: false,
      result: null,
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <SubmissionsPage />
      </MemoryRouter>,
    )

    // One failed row => exactly one Retry button.
    const retry = await screen.findByRole('button', { name: /^retry$/i })
    await user.click(retry)

    expect(api.retrySubmission).toHaveBeenCalledWith('bad')
    // Row swapped in place rather than refetching: a reload would shuffle rows
    // under the pointer while another retry is still in flight.
    expect(await screen.findByText('pending')).toBeInTheDocument()
    expect(navigateMock).not.toHaveBeenCalled()
  })

  it('links the assessment chip to the assessment without navigating the row', async () => {
    vi.mocked(api.listAllSubmissions).mockResolvedValue(
      page([sub({ id: 's1', assessment_id: 'a1', assessment_title: 'Backend Screen' })]),
    )
    render(
      <MemoryRouter>
        <SubmissionsPage />
      </MemoryRouter>,
    )

    // assessment_id was returned and discarded; the chip is now the link it could always have been.
    expect(await screen.findByRole('link', { name: 'Backend Screen' })).toHaveAttribute(
      'href',
      '/assessments/a1',
    )
  })

  it('shows an erased candidate as erased, not as a contactable address', async () => {
    // The integration gap: without this the row read as a candidate named
    // "[erased]" beside erased-a3f9@erased.invalid — which looks like an address
    // an interviewer could write to, and is not one.
    vi.mocked(api.listAllSubmissions).mockResolvedValue(
      page([
        sub({
          candidate: '[erased]',
          candidate_email: 'erased-a3f9@erased.invalid',
          erased: true,
        }),
      ]),
    )
    render(
      <MemoryRouter>
        <SubmissionsPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/erased candidate/i)).toBeInTheDocument()
    expect(screen.getByText(/data erased/i)).toBeInTheDocument()
    expect(screen.queryByText(/erased\.invalid/)).not.toBeInTheDocument()
  })

})
