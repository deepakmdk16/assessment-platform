import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AnalyticsPanel } from '../AnalyticsPanel'
import { api } from '../../api'
import type { AssessmentAnalytics, OverviewAnalytics } from '../../types'

vi.mock('../../api', () => ({
  api: {
    analyticsOverview: vi.fn(),
    analyticsQuestions: vi.fn(),
    analyticsAssessment: vi.fn(),
    listAssessments: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}))

const overview: OverviewAnalytics = {
  questions: 12,
  submissions: 148,
  graded: 142,
  candidates: 63,
  passed: 82,
  pass_rate: 0.577,
  avg_score_pct: 71.4,
  trend: [
    { date: '2026-07-24', submissions: 8, graded: 8, passed: 5, pass_rate: 0.625 },
    { date: '2026-07-25', submissions: 14, graded: 13, passed: 9, pass_rate: 0.69 },
  ],
  score_distribution: [
    { low: 0, high: 20, count: 9 },
    { low: 20, high: 40, count: 14 },
    { low: 40, high: 60, count: 24 },
    { low: 60, high: 80, count: 41 },
    { low: 80, high: 100, count: 35 },
  ],
}

const xc: AssessmentAnalytics = {
  assessment_id: 'a1',
  title: 'Backend Screen',
  slot_count: 3,
  candidates_started: 2,
  candidates_completed: 1,
  avg_score_pct: 75,
  pass_rate: 0.6,
  score_distribution: [{ low: 60, high: 80, count: 1 }],
  candidates: [
    {
      candidate_name: 'Priya N.',
      candidate_email: 'priya@x.io',
      passed_count: 3,
      submitted_count: 3,
      total_count: 3,
      avg_score_pct: 94,
      rank: 1,
      percentile: 1,
      time_to_solve_s: 2460,
    },
    {
      candidate_name: 'Sam K.',
      candidate_email: 'sam@x.io',
      passed_count: 1,
      submitted_count: 2,
      total_count: 3,
      avg_score_pct: 58,
      rank: 2,
      percentile: 0.5,
      time_to_solve_s: null,
    },
  ],
}

describe('AnalyticsPanel (AR1)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.analyticsOverview).mockResolvedValue(overview)
    vi.mocked(api.listAssessments).mockResolvedValue({
      items: [{ id: 'a1', title: 'Backend Screen' }],
      total: 1,
      limit: 100,
      offset: 0,
    } as never)
    vi.mocked(api.analyticsAssessment).mockResolvedValue(xc)
  })

  it('renders KPI tiles from the overview', async () => {
    render(<AnalyticsPanel days={30} onDaysChange={() => {}} />)
    expect(await screen.findByText('148')).toBeInTheDocument() // submissions
    expect(screen.getByText('58%')).toBeInTheDocument() // pass rate (0.577 -> 58%)
    expect(screen.getByText('71.4')).toBeInTheDocument() // avg score
  })

  it('renders the cross-candidate table for the selected assessment', async () => {
    render(<AnalyticsPanel days={30} onDaysChange={() => {}} />)
    expect(await screen.findByText('Priya N.')).toBeInTheDocument()
    expect(screen.getByText('100th')).toBeInTheDocument() // top percentile
    expect(screen.getByText('Complete')).toBeInTheDocument() // 3/3 submitted
    expect(screen.getByText('2 / 3 submitted')).toBeInTheDocument() // Sam partial
  })

  it('changing the range calls onDaysChange', async () => {
    const onDaysChange = vi.fn()
    const user = userEvent.setup()
    render(<AnalyticsPanel days={30} onDaysChange={onDaysChange} />)
    await screen.findByText('148')
    await user.click(screen.getByRole('button', { name: '7d' }))
    expect(onDaysChange).toHaveBeenCalledWith(7)
    await user.click(screen.getByRole('button', { name: 'All' }))
    expect(onDaysChange).toHaveBeenCalledWith(undefined)
  })
})
