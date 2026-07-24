import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NewAssessmentPage } from '../NewAssessmentPage'
import { api } from '../../api'
import type { AssessmentOut, Page, QuestionOut } from '../../types'

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
    api: { listQuestions: vi.fn(), createAssessment: vi.fn() },
    ApiError,
  }
})

const q = (id: string, title: string): QuestionOut =>
  ({ id, title, difficulty: 'easy' }) as QuestionOut

function libraryPage(items: QuestionOut[]): Page<QuestionOut> {
  return { items, total: items.length, limit: 200, offset: 0 }
}

/** Render and wait for the library to load. */
async function renderLoaded(items: QuestionOut[]) {
  vi.mocked(api.listQuestions).mockResolvedValue(libraryPage(items))
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
  })

  it('adds questions, preserves order, and creates the assessment', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'week-1' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum'), q('islands', 'Count Islands')])

    await user.type(screen.getByLabelText(/id \(slug\)/i), 'week-1')
    await user.type(screen.getByLabelText(/^title$/i), 'Week 1 Screen')

    // Add both, in library order.
    await user.click(addButtons()[0])
    await user.click(addButtons()[0]) // the second question shifts into slot 0

    await user.click(screen.getByRole('button', { name: /create assessment/i }))

    await waitFor(() => expect(api.createAssessment).toHaveBeenCalledTimes(1))
    const payload = vi.mocked(api.createAssessment).mock.calls[0][0]
    expect(payload).toMatchObject({
      id: 'week-1',
      title: 'Week 1 Screen',
      duration_minutes: 60,
      question_ids: ['two-sum', 'islands'],
    })
    await waitFor(() =>
      expect(navigateMock).toHaveBeenCalledWith('/assessments/week-1', {
        state: { justCreated: true },
      }),
    )
  })

  it('reorders and removes selected questions before create', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'a' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum'), q('islands', 'Count Islands'), q('bfs', 'BFS')])

    await user.type(screen.getByLabelText(/id \(slug\)/i), 'a')
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
    expect(vi.mocked(api.createAssessment).mock.calls[0][0].question_ids).toEqual([
      'islands',
      'two-sum',
    ])
  })

  it('sends null duration when marked indefinite', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createAssessment).mockResolvedValue({ id: 'a' } as AssessmentOut)
    await renderLoaded([q('two-sum', 'Two Sum')])

    await user.type(screen.getByLabelText(/id \(slug\)/i), 'a')
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

    await user.type(screen.getByLabelText(/id \(slug\)/i), 'a')
    await user.type(screen.getByLabelText(/^title$/i), 'A')
    await user.click(screen.getByRole('button', { name: /create assessment/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/at least one question/i)
    expect(api.createAssessment).not.toHaveBeenCalled()
  })
})
