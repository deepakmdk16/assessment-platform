import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NewAssessmentPage } from '../NewAssessmentPage'
import { api } from '../../api'
import type { AssessmentOut, Page, QuestionOut, User, VariantSetSummary } from '../../types'

const navigateMock = vi.fn()

// The page reads the interviewer's workspace default branding via useAuth (A12);
// mock it so the test controls the current user's defaults without a provider.
const authState = vi.hoisted(() => ({ user: null as User | null }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: authState.user }) }))

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
    api: { listQuestions: vi.fn(), listVariantSets: vi.fn(), createAssessment: vi.fn() },
    ApiError,
  }
})

const q = (id: string, title: string): QuestionOut =>
  ({ id, title, difficulty: 'easy' }) as QuestionOut

const vset = (id: string, title: string, variant_count = 3): VariantSetSummary =>
  ({ id, title, variant_count, difficulty: 'medium' }) as VariantSetSummary

function page<T>(items: T[]): Page<T> {
  return { items, total: items.length, limit: 200, offset: 0 }
}

/** Render and wait for the library + variant sets to load. */
async function renderLoaded(items: QuestionOut[], sets: VariantSetSummary[] = []) {
  vi.mocked(api.listQuestions).mockResolvedValue(page(items))
  vi.mocked(api.listVariantSets).mockResolvedValue(page(sets))
  render(
    <MemoryRouter>
      <NewAssessmentPage />
    </MemoryRouter>,
  )
  await screen.findAllByRole('button', { name: /^add$/i })
}

/** The library column shows an "Add" button per available question. */
const addButtons = () => screen.getAllByRole('button', { name: /^add$/i })

describe('NewAssessmentPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.user = null
    vi.mocked(api.listVariantSets).mockResolvedValue(page([]))
  })

  it('adds questions, preserves order, and creates the assessment', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'week-1' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum'), q('islands', 'Count Islands')])

    await user.type(screen.getByLabelText(/^title$/i), 'Week 1 Screen')

    // Add both, in library order.
    await user.click(addButtons()[0])
    await user.click(addButtons()[0]) // the second question shifts into slot 0

    await user.click(screen.getByRole('button', { name: /create assessment/i }))

    await waitFor(() => expect(api.createAssessment).toHaveBeenCalledTimes(1))
    const payload = vi.mocked(api.createAssessment).mock.calls[0][0]
    expect(payload).toMatchObject({
      title: 'Week 1 Screen',
      duration_minutes: 60,
      slots: [{ question_id: 'two-sum' }, { question_id: 'islands' }],
      org_name: null,
      logo_url: null,
    })
    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith('/assessments/week-1', {
        state: { justCreated: true },
      }),
    )
  })

  it('adds a variant set as a slot and creates a mixed assessment (VS2)', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'mixed' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum')], [vset('pairs', 'Two-pointer pairs', 4)])

    await user.type(screen.getByLabelText(/^title$/i), 'Mixed')

    // One Add per source group: the question, then the variant set.
    await user.click(screen.getByText('Two Sum').closest('.q-pick')!.querySelector('button')!)
    await user.click(
      screen.getByText('Two-pointer pairs').closest('.q-pick')!.querySelector('button')!,
    )

    // The set slot reads as a variant set with its variant count.
    expect(screen.getByText(/each candidate gets a random variant · 4 variants/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /create assessment/i }))
    await waitFor(() => expect(api.createAssessment).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.createAssessment).mock.calls[0][0].slots).toEqual([
      { question_id: 'two-sum' },
      { variant_set_id: 'pairs' },
    ])
  })

  it('prefills branding from the workspace default and sends it on create (A12)', async () => {
    const user = userEvent.setup()
    authState.user = {
      id: '1',
      email: 'o@test.io',
      name: 'Owner',
      default_org_name: 'Acme Corp',
      default_logo_url: 'https://acme/logo.png',
    }
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'week-1' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum')])

    // The branding inputs start from the workspace default.
    expect(screen.getByLabelText(/organization name/i)).toHaveValue('Acme Corp')
    expect(screen.getByLabelText(/logo url/i)).toHaveValue('https://acme/logo.png')

    await user.type(screen.getByLabelText(/^title$/i), 'Week 1 Screen')
    await user.click(addButtons()[0])
    await user.click(screen.getByRole('button', { name: /create assessment/i }))

    await waitFor(() => expect(api.createAssessment).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.createAssessment).mock.calls[0][0]).toMatchObject({
      org_name: 'Acme Corp',
      logo_url: 'https://acme/logo.png',
    })
  })

  it('pre-populates the selection from router state (A8), dropping stale ids', async () => {
    vi.mocked(api.listQuestions).mockResolvedValue(
      page([q('two-sum', 'Two Sum'), q('islands', 'Count Islands')]),
    )
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: '/assessments/new', state: { preselected: ['islands', 'deleted-one'] } },
        ]}
      >
        <NewAssessmentPage />
      </MemoryRouter>,
    )

    // "islands" was preselected and is in the library — shows in "In this
    // assessment"; "deleted-one" doesn't exist in the library, so it's
    // silently dropped rather than lingering invisible in the payload.
    expect(await screen.findByText(/in this assessment \(1\)/i)).toBeInTheDocument()
    expect(screen.getByText('Count Islands')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^add$/i })).toBeInTheDocument() // Two Sum still pickable
  })

  it('sends branding fields when set, and null when left blank (A12)', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'week-1' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum')])

    await user.type(screen.getByLabelText(/^title$/i), 'Week 1 Screen')
    await user.type(screen.getByLabelText(/organization name/i), 'Acme Corp')
    await user.type(screen.getByLabelText(/logo url/i), 'https://cdn.example.com/acme.png')
    expect(screen.getByText(/Acme Corp — Week 1 Screen/)).toBeInTheDocument()

    await user.click(addButtons()[0])
    await user.click(screen.getByRole('button', { name: /create assessment/i }))

    await waitFor(() => expect(api.createAssessment).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.createAssessment).mock.calls[0][0]).toMatchObject({
      org_name: 'Acme Corp',
      logo_url: 'https://cdn.example.com/acme.png',
    })
  })

  it('reorders and removes selected questions before create', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'a' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum'), q('islands', 'Count Islands'), q('bfs', 'BFS')])

    await user.type(screen.getByLabelText(/^title$/i), 'A')

    // Add all three (each Add click removes that item from the library column).
    await user.click(addButtons()[0])
    await user.click(addButtons()[0])
    await user.click(addButtons()[0])

    // Move Two Sum down one, then remove BFS. (The ↑/↓/✕ buttons carry a title,
    // not text, so query by title.)
    await user.click(screen.getAllByTitle('Move down')[0]) // → islands, two-sum, bfs
    await user.click(screen.getAllByTitle('Remove')[2]) // drop bfs

    await user.click(screen.getByRole('button', { name: /create assessment/i }))

    await waitFor(() => expect(api.createAssessment).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.createAssessment).mock.calls[0][0].slots).toEqual([
      { question_id: 'islands' },
      { question_id: 'two-sum' },
    ])
  })

  it('sends null duration when marked indefinite', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'a' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum')])

    await user.type(screen.getByLabelText(/^title$/i), 'A')
    await user.click(addButtons()[0])
    await user.click(screen.getByLabelText(/indefinite/i))

    await user.click(screen.getByRole('button', { name: /create assessment/i }))

    await waitFor(() => expect(api.createAssessment).toHaveBeenCalledTimes(1))
    expect(vi.mocked(api.createAssessment).mock.calls[0][0].duration_minutes).toBeNull()
  })

  it('refuses to create with no questions', async () => {
    const user = userEvent.setup()
    await renderLoaded([q('two-sum', 'Two Sum')])

    await user.type(screen.getByLabelText(/^title$/i), 'A')
    await user.click(screen.getByRole('button', { name: /create assessment/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least one question/i)
    expect(api.createAssessment).not.toHaveBeenCalled()
  })

  it('offers a way to create a question when the library is empty (A14)', async () => {
    vi.mocked(api.listQuestions).mockResolvedValue(page([]))
    render(
      <MemoryRouter>
        <NewAssessmentPage />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/you have no questions yet/i)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /create your first question/i })
    expect(link).toHaveAttribute('href', '/questions/new')
  })
})
