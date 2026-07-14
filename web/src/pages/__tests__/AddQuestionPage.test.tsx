import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AddQuestionPage } from '../AddQuestionPage'
import { api } from '../../api'
import type { QuestionOut } from '../../types'

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
    api: { createQuestion: vi.fn() },
    ApiError,
  }
})

describe('AddQuestionPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('submits the form with basics, one test case, and the worked example', async () => {
    const user = userEvent.setup()
    vi.mocked(api.createQuestion).mockResolvedValue({ id: 'two-sum' } as QuestionOut)

    render(
      <MemoryRouter>
        <AddQuestionPage />
      </MemoryRouter>,
    )

    await user.type(screen.getByLabelText(/id \(slug\)/i), 'two-sum')
    await user.type(screen.getByLabelText(/^title$/i), 'Two Sum')
    await user.type(screen.getByLabelText(/^prompt$/i), 'Return indices of two numbers that add up to target.')

    await user.type(screen.getByLabelText(/^constraints$/i), '1 <= n <= 1000')
    await user.clear(screen.getByLabelText(/time limit/i))
    await user.type(screen.getByLabelText(/time limit/i), '3')
    await user.clear(screen.getByLabelText(/pass threshold/i))
    await user.type(screen.getByLabelText(/pass threshold/i), '80')

    await user.type(screen.getByLabelText(/test case 1 name/i), 'basic')
    await user.type(screen.getByLabelText(/test case 1 stdin/i), '2 7 11 15\n9')
    await user.type(screen.getByLabelText(/test case 1 expected/i), '0 1')

    await user.type(screen.getByLabelText(/example input/i), '2 7 11 15\n9')
    await user.type(screen.getByLabelText(/example output/i), '0 1')

    await user.click(screen.getByRole('button', { name: /create question/i }))

    await waitFor(() => expect(api.createQuestion).toHaveBeenCalledTimes(1))
    const payload = vi.mocked(api.createQuestion).mock.calls[0][0]
    expect(payload.id).toBe('two-sum')
    expect(payload.title).toBe('Two Sum')
    expect(payload.time_limit_s).toBe(3)
    expect(payload.pass_threshold).toBe(80)
    expect(payload.test_cases).toHaveLength(1)
    expect(payload.test_cases[0]).toMatchObject({
      name: 'basic',
      category: 'correctness',
      weight: 1,
    })

    await waitFor(() => expect(navigateMock).toHaveBeenCalledWith('/questions/two-sum'))
  })

  it('adds and removes test case rows', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <AddQuestionPage />
      </MemoryRouter>,
    )

    expect(screen.getAllByLabelText(/test case \d+ name/i)).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: /add test case/i }))
    expect(screen.getAllByLabelText(/test case \d+ name/i)).toHaveLength(2)

    await user.click(screen.getAllByRole('button', { name: /remove/i })[0])
    expect(screen.getAllByLabelText(/test case \d+ name/i)).toHaveLength(1)
  })
})
