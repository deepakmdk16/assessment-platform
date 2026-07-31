import { render, screen } from '@testing-library/react'
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
  api: { listAllSubmissions: vi.fn(), listQuestions: vi.fn() },
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
