import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CandidateErrorFallback, ErrorBoundary } from '../ErrorBoundary'

function Boom(): never {
  throw new Error('kaboom')
}

describe('ErrorBoundary', () => {
  beforeEach(() => {
    // A boundary catch logs via componentDidCatch + React's own dev logging;
    // silence it so the caught-error output doesn't look like a test failure.
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <p>all good</p>
      </ErrorBoundary>,
    )
    expect(screen.getByText('all good')).toBeInTheDocument()
  })

  it('shows the app fallback when a child throws', () => {
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText('This page hit an unexpected error')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reload page/i })).toBeInTheDocument()
  })

  it('shows a custom fallback when provided', () => {
    render(
      <ErrorBoundary fallback={<CandidateErrorFallback />}>
        <Boom />
      </ErrorBoundary>,
    )
    expect(screen.getByText('Something went wrong on this page')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /reload & continue/i })).toBeInTheDocument()
  })

  it('reloads the page from the fallback action', async () => {
    const reload = vi.fn()
    Object.defineProperty(window, 'location', {
      value: { ...window.location, reload },
      writable: true,
    })
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    )
    await userEvent.click(screen.getByRole('button', { name: /reload page/i }))
    expect(reload).toHaveBeenCalledOnce()
  })
})
