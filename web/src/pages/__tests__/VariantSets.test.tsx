import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { NewVariantSetPage } from '../NewVariantSetPage'
import { VariantSetsListPage } from '../VariantSetsListPage'
import { api } from '../../api'
import type { Page, QuestionIn, VariantDraftOut, VariantSetDraftOut, VariantSetSummary } from '../../types'

const navigateMock = vi.fn()

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return { ...actual, useNavigate: () => navigateMock }
})

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
      draftVariantSet: vi.fn(),
      createVariantSet: vi.fn(),
      listVariantSets: vi.fn(),
    },
    ApiError,
  }
})

beforeEach(() => {
  vi.clearAllMocks()
})

function variant(label: string, complexity = 'O(n)'): VariantDraftOut {
  return {
    label,
    question: {
      title: `Variant ${label}`,
      constraints: '1 <= N <= 10^5',
      required_complexity: complexity,
      test_cases: [{}, {}, {}, {}, {}],
    } as unknown as QuestionIn,
    reference_solution: 'print(1)',
    reference_language: 'python',
    warnings: [],
  }
}

function draftResult(warnings: string[] = []): VariantSetDraftOut {
  return { variants: [variant('A'), variant('B'), variant('C')], warnings, engine: 'test', cost_usd: 0.03 }
}

describe('NewVariantSetPage', () => {
  it('drafts, reviews, and saves a set', async () => {
    vi.mocked(api.draftVariantSet).mockResolvedValue(draftResult())
    vi.mocked(api.createVariantSet).mockResolvedValue({ id: 'set-1' } as never)

    render(
      <MemoryRouter>
        <NewVariantSetPage />
      </MemoryRouter>,
    )

    await userEvent.type(screen.getByLabelText(/brief/i), 'longest increasing run')
    await userEvent.click(screen.getByRole('button', { name: /draft 3 variants/i }))

    // Review step: the three variants + the parity-ok banner.
    expect(await screen.findByText('Variant A')).toBeInTheDocument()
    expect(screen.getByText(/parity checked/i)).toBeInTheDocument()
    expect(screen.getByText('Variant C')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /save variant set/i }))

    await waitFor(() => expect(api.createVariantSet).toHaveBeenCalled())
    const body = vi.mocked(api.createVariantSet).mock.calls[0][0]
    expect(body.variants).toHaveLength(3)
    expect(body.variants[0].label).toBe('A')
    expect(body.variants[0].reference_solution).toBe('print(1)')
    expect(navigateMock).toHaveBeenCalledWith('/variant-sets/set-1')
  })

  it('surfaces set-level parity warnings instead of the ok banner', async () => {
    vi.mocked(api.draftVariantSet).mockResolvedValue(
      draftResult(['Set parity: variants differ in required_complexity.']),
    )
    render(
      <MemoryRouter>
        <NewVariantSetPage />
      </MemoryRouter>,
    )
    await userEvent.type(screen.getByLabelText(/brief/i), 'x')
    await userEvent.click(screen.getByRole('button', { name: /draft 3 variants/i }))

    expect(await screen.findByText(/differ in required_complexity/i)).toBeInTheDocument()
    expect(screen.queryByText(/parity checked/i)).not.toBeInTheDocument()
  })
})

describe('VariantSetsListPage', () => {
  it('lists sets with their variant count', async () => {
    const row: VariantSetSummary = {
      id: 'set-1',
      title: 'Longest increasing run',
      language: 'python',
      difficulty: 'medium',
      variant_count: 3,
      status: 'active',
      created_at: '2026-07-26T00:00:00Z',
      updated_at: '2026-07-26T00:00:00Z',
    }
    const page: Page<VariantSetSummary> = { items: [row], total: 1, limit: 100, offset: 0 }
    vi.mocked(api.listVariantSets).mockResolvedValue(page)

    render(
      <MemoryRouter>
        <VariantSetsListPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText('Longest increasing run')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
    expect(screen.getByText('medium')).toBeInTheDocument()
  })

  it('shows an empty state when there are none', async () => {
    vi.mocked(api.listVariantSets).mockResolvedValue({ items: [], total: 0, limit: 100, offset: 0 })
    render(
      <MemoryRouter>
        <VariantSetsListPage />
      </MemoryRouter>,
    )
    expect(await screen.findByText(/no variant sets yet/i)).toBeInTheDocument()
  })
})
