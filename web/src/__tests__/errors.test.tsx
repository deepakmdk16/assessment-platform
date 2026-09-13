/** P3a — a spent allowance is the one refusal with somewhere to go, so it is
 *  the one that gets a link. Settings having a route per section is what makes
 *  that possible; before it, /settings could only be described. */

import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ApiError } from '../api'
import { apiMessage } from '../errors'

function show(err: unknown, fallback = 'Something went wrong') {
  return render(<MemoryRouter>{apiMessage(err, fallback)}</MemoryRouter>)
}

describe('apiMessage', () => {
  it('links a spent allowance straight to the plan', () => {
    show(new ApiError(402, 'the Free plan’s limit of 10 candidate sittings this month is used up.'))

    expect(screen.getByText(/limit of 10 candidate sittings/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /billing/i })).toHaveAttribute(
      'href',
      '/settings/billing',
    )
  })

  it('leaves every other refusal as the sentence it was', () => {
    show(new ApiError(403, 'you are not an admin of this organisation.'))

    expect(screen.getByText(/not an admin/i)).toBeInTheDocument()
    // A link on a refusal nothing in Settings can fix is a dead end.
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })

  it('falls back when the failure never reached the server', () => {
    show(new TypeError('Failed to fetch'), 'Check your connection and try again.')

    expect(screen.getByText(/check your connection/i)).toBeInTheDocument()
    expect(screen.queryByText(/failed to fetch/i)).not.toBeInTheDocument()
  })
})
