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
  },
  ApiError: class ApiError extends Error {},
}))

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
