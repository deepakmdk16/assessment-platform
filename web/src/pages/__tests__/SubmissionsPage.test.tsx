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
})
