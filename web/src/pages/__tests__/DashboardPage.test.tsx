import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DashboardPage } from '../DashboardPage'
import { api } from '../../api'
import type { Page, QuestionOut } from '../../types'

const navigateMock = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

vi.mock('../../api', () => ({
  api: {
    listQuestions: vi.fn(),
    archiveQuestion: vi.fn(),
    unarchiveQuestion: vi.fn(),
    // AR1 — the folded-in analytics panel + per-question columns fetch these.
    analyticsQuestions: vi.fn(),
    analyticsOverview: vi.fn(),
    analyticsAssessment: vi.fn(),
    listAssessments: vi.fn(),
  },
  ApiError: class ApiError extends Error {},
}))

const overview = {
  questions: 0, submissions: 0, graded: 0, candidates: 0, passed: 0,
  pass_rate: null, avg_score_pct: null, trend: [],
  score_distribution: [{ low: 0, high: 20, count: 0 }],
}

const q = (id: string, title: string): QuestionOut =>
  ({
    id,
    title,
    status: 'active',
    test_cases: [],
    created_at: '2026-07-24T00:00:00Z',
  }) as unknown as QuestionOut

function page(items: QuestionOut[]): Page<QuestionOut> {
  return { items, total: items.length, limit: 100, offset: 0 }
}

function renderPage() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  )
}

describe('DashboardPage — build assessment from selection (A8)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.analyticsQuestions).mockResolvedValue(page([]) as never)
    vi.mocked(api.analyticsOverview).mockResolvedValue(overview as never)
    vi.mocked(api.listAssessments).mockResolvedValue(page([]) as never)
    vi.mocked(api.analyticsAssessment).mockResolvedValue({} as never)
  })

  it('selecting questions reveals a Build assessment button that navigates with the selection', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listQuestions).mockResolvedValue(
      page([q('two-sum', 'Two Sum'), q('islands', 'Count Islands')]),
    )
    renderPage()

    await screen.findByText('Two Sum')
    expect(screen.queryByRole('button', { name: /build assessment/i })).not.toBeInTheDocument()

    await user.click(screen.getByLabelText('Select Two Sum'))
    await user.click(screen.getByLabelText('Select Count Islands'))
    const buildButton = screen.getByRole('button', { name: /build assessment \(2\)/i })
    await user.click(buildButton)

    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith('/assessments/new', {
        state: { preselected: ['two-sum', 'islands'] },
      }),
    )
  })

  it('selecting a checkbox does not navigate to the question detail page', async () => {
    const user = userEvent.setup()
    vi.mocked(api.listQuestions).mockResolvedValue(page([q('two-sum', 'Two Sum')]))
    renderPage()

    await screen.findByText('Two Sum')
    await user.click(screen.getByLabelText('Select Two Sum'))

    expect(navigateMock).not.toHaveBeenCalled()
  })
})

describe('DashboardPage — lists that do not lie (UI-E)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.analyticsOverview).mockResolvedValue(overview as never)
    vi.mocked(api.listAssessments).mockResolvedValue(page([]) as never)
    vi.mocked(api.analyticsAssessment).mockResolvedValue({} as never)
    vi.mocked(api.listQuestions).mockResolvedValue(page([q('two-sum', 'Two Sum')]))
    vi.mocked(api.analyticsQuestions).mockResolvedValue(page([]) as never)
  })

  it('makes each row title a real link, so the list is reachable without a mouse', async () => {
    renderPage()
    // Rows were `<tr onClick>` with nothing focusable inside — invisible to the
    // keyboard and to a screen reader. This was the audit's only P1 web item.
    expect(await screen.findByRole('link', { name: 'Two Sum' })).toHaveAttribute(
      'href',
      '/questions/two-sum',
    )
  })

  it('asks analytics for the same window as the page it decorates', async () => {
    renderPage()
    // A fixed 200 meant rows past that point rendered a silent em-dash where
    // their stats should have been.
    await waitFor(() => expect(api.analyticsQuestions).toHaveBeenCalled())
    const [, offset, limit] = vi.mocked(api.analyticsQuestions).mock.calls[0]
    const [, , listLimit] = vi.mocked(api.listQuestions).mock.calls[0]
    expect(offset).toBe(0)
    expect(limit).toBe(listLimit)
  })

  it('shows the median and late columns the analytics rows already carried', async () => {
    vi.mocked(api.analyticsQuestions).mockResolvedValue(
      page([
        {
          question_id: 'two-sum',
          pass_rate: 0.5,
          avg_score_pct: 41,
          median_score_pct: 38,
          median_time_to_solve_s: 120,
          late: 6,
        },
      ] as never) as never,
    )
    renderPage()

    expect(await screen.findByRole('columnheader', { name: 'Median' })).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'Late' })).toBeInTheDocument()
    // A skewed question shows immediately when the mean and median disagree.
    expect(await screen.findByText('38')).toBeInTheDocument()
    expect(screen.getByText('6')).toBeInTheDocument()
  })
})
