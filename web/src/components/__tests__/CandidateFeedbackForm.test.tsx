/** P2b — the optional feedback a candidate can leave once a sitting is over.
 *  Where it is allowed to appear is covered by the CandidatePage tests; this
 *  covers what it sends and how it answers the server. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CandidateFeedbackForm } from '../CandidateFeedbackForm'
import { api, ApiError } from '../../api'

vi.mock('../../api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return { api: { sendCandidateFeedback: vi.fn() }, ApiError }
})

function renderForm() {
  return render(<CandidateFeedbackForm token="tok123" candidateEmail="jane@example.com" />)
}

describe('candidate feedback', () => {
  beforeEach(() => vi.clearAllMocks())

  it('cannot be sent until a rating is chosen, and never pre-fills one', async () => {
    const user = userEvent.setup()
    renderForm()

    // Nothing selected: a default would be recorded as an opinion nobody gave.
    for (const n of [1, 2, 3, 4, 5]) {
      expect(screen.getByRole('radio', { name: String(n) })).not.toBeChecked()
    }
    expect(screen.getByRole('button', { name: /send feedback/i })).toBeDisabled()
    expect(screen.getByText(/pick a rating to send/i)).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: '4' }))
    expect(screen.getByRole('button', { name: /send feedback/i })).toBeEnabled()
  })

  it('sends the rating, the difficulty and the trimmed comment, then thanks them', async () => {
    const user = userEvent.setup()
    vi.mocked(api.sendCandidateFeedback).mockResolvedValue(undefined)
    renderForm()

    await user.click(screen.getByRole('radio', { name: '5' }))
    await user.click(screen.getByRole('radio', { name: /too hard/i }))
    await user.type(screen.getByLabelText(/anything you want the team to know/i), '  Q2 was a stretch.  ')
    await user.click(screen.getByRole('button', { name: /send feedback/i }))

    expect(api.sendCandidateFeedback).toHaveBeenCalledWith('tok123', {
      candidate_email: 'jane@example.com',
      rating: 5,
      difficulty_fair: 'too_hard',
      comment: 'Q2 was a stretch.',
    })
    expect(await screen.findByText(/your feedback is with the hiring team/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /send feedback/i })).not.toBeInTheDocument()
  })

  it('defaults the difficulty to the neutral middle rather than an opinion', async () => {
    const user = userEvent.setup()
    vi.mocked(api.sendCandidateFeedback).mockResolvedValue(undefined)
    renderForm()

    expect(screen.getByRole('radio', { name: /about right/i })).toBeChecked()
    await user.click(screen.getByRole('radio', { name: '3' }))
    await user.click(screen.getByRole('button', { name: /send feedback/i }))

    expect(api.sendCandidateFeedback).toHaveBeenCalledWith(
      'tok123',
      expect.objectContaining({ difficulty_fair: 'fair', comment: '' }),
    )
  })

  it('treats "already recorded" as sent, so a reload never reads as a failure', async () => {
    const user = userEvent.setup()
    vi.mocked(api.sendCandidateFeedback).mockRejectedValue(new ApiError(409, 'already recorded'))
    renderForm()

    await user.click(screen.getByRole('radio', { name: '4' }))
    await user.click(screen.getByRole('button', { name: /send feedback/i }))

    expect(await screen.findByText(/your feedback is with the hiring team/i)).toBeInTheDocument()
  })

  it('says the link is closed on a permanent refusal instead of inviting a retry', async () => {
    // The interviewer revoked the invite (or it expired) while they were typing.
    const user = userEvent.setup()
    vi.mocked(api.sendCandidateFeedback).mockRejectedValue(new ApiError(410, 'gone'))
    renderForm()

    await user.click(screen.getByRole('radio', { name: '4' }))
    await user.click(screen.getByRole('button', { name: /send feedback/i }))

    expect(await screen.findByText(/can’t take feedback any more/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /send feedback/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('keeps the retry for a server error, which trying again can fix', async () => {
    const user = userEvent.setup()
    vi.mocked(api.sendCandidateFeedback).mockRejectedValue(new ApiError(503, 'down'))
    renderForm()
    await user.click(screen.getByRole('radio', { name: '4' }))
    await user.click(screen.getByRole('button', { name: /send feedback/i }))
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /send feedback/i })).toBeEnabled()
  })

  it('keeps what they wrote when the send fails', async () => {
    const user = userEvent.setup()
    vi.mocked(api.sendCandidateFeedback).mockRejectedValue(new ApiError(500, 'boom'))
    renderForm()

    await user.click(screen.getByRole('radio', { name: '2' }))
    await user.type(screen.getByLabelText(/anything you want the team to know/i), 'The timer was tight.')
    await user.click(screen.getByRole('button', { name: /send feedback/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/didn’t send/i)
    expect(screen.getByLabelText(/anything you want the team to know/i)).toHaveValue(
      'The timer was tight.',
    )
    // Still sendable — the button comes back rather than locking them out.
    expect(screen.getByRole('button', { name: /send feedback/i })).toBeEnabled()
  })

  it('counts the comment against the limit the server enforces', async () => {
    const user = userEvent.setup()
    renderForm()
    expect(screen.getByText('0 / 2000')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/anything you want the team to know/i), 'abc')
    expect(screen.getByText('3 / 2000')).toBeInTheDocument()
    expect(screen.getByLabelText(/anything you want the team to know/i)).toHaveAttribute(
      'maxlength',
      '2000',
    )
  })
})
