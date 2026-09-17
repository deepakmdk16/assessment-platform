/** The candidate page driving the REAL integrity hook (S04).
 *
 *  `CandidatePage.test.tsx` mocks `useIntegrity`, which is why R2-003 survived
 *  every green run: the bug was not in the hook and not in the page, but in the
 *  seam between them — the Start handler holds the hook object from the render
 *  where `enabled` was still false, so `enterFullscreen` returned early and the
 *  sitting ran in a normal window while the interviewer's panel read "Stayed in
 *  fullscreen". A test that stubs the hook cannot see that, so this file stubs
 *  only the browser APIs jsdom lacks and lets both modules be themselves.
 *
 *  Anything asserted here is a claim the product makes to a candidate on the
 *  consent screen — see docs/CLAIMS.md.
 */

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ThemeProvider } from '../../theme/ThemeContext'
import { CandidatePage } from '../CandidatePage'
import { api } from '../../api'
import type { InviteStartResponse } from '../../types'

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
      getInvite: vi.fn(),
      postIntegrityEvents: vi.fn(() => Promise.resolve()),
      startInvite: vi.fn(),
      submitCandidate: vi.fn(),
      runCandidate: vi.fn(),
      runCandidateTests: vi.fn(),
      getCandidateDrafts: vi.fn(() => Promise.resolve({ drafts: [] })),
      saveCandidateDraft: vi.fn(() => Promise.resolve()),
      sendCandidateFeedback: vi.fn(() => Promise.resolve()),
      publicConfig: vi.fn(() => Promise.resolve({ support_email: null })),
    },
    ApiError,
    logoSrc: (sha: string) => `/logos/${sha}`,
  }
})

vi.mock('@monaco-editor/react', () => ({
  default: ({
    value,
    onChange,
    options,
  }: {
    value?: string
    onChange?: (value: string | undefined) => void
    options?: { readOnly?: boolean }
  }) => (
    <textarea
      aria-label="code editor"
      value={value}
      readOnly={options?.readOnly}
      onChange={(e) => onChange?.(e.target.value)}
    />
  ),
}))

const startResponse: InviteStartResponse = {
  question: {
    title: 'Two Sum',
    prompt: 'Find two numbers that add up to target.',
    constraints: '1 <= n <= 1000',
    example_input: '2 7 11 15\n9',
    example_output: '0 1',
    time_limit_s: 60,
  },
  languages: ['python', 'javascript'],
  proctored: true,
}

function renderCandidatePage() {
  return render(
    <ThemeProvider>
      <MemoryRouter initialEntries={['/t/tok123']}>
        <Routes>
          <Route path="/t/:token" element={<CandidatePage />} />
        </Routes>
      </MemoryRouter>
    </ThemeProvider>,
  )
}

async function passGate(user: ReturnType<typeof userEvent.setup>) {
  await user.type(await screen.findByLabelText(/^name$/i), 'Jane Doe')
  await user.type(screen.getByLabelText(/^email$/i), 'jane@example.com')
  await user.click(screen.getByLabelText(/i agree to my assessment/i))
  await user.click(screen.getByRole('button', { name: /start/i }))
}

/** jsdom implements no Fullscreen API at all. Stub the two entry points the
 *  product uses and report what was asked for. */
function stubFullscreen({ grant = true }: { grant?: boolean } = {}) {
  const request = vi.fn(() =>
    grant ? Promise.resolve() : Promise.reject(new Error('denied by permissions policy')),
  )
  document.documentElement.requestFullscreen = request
  Object.defineProperty(document, 'fullscreenElement', { value: null, configurable: true })
  return request
}

beforeEach(() => {
  vi.clearAllMocks()
  localStorage.clear()
  vi.mocked(api.getInvite).mockResolvedValue({ status: 'active', proctored: true })
  vi.mocked(api.startInvite).mockResolvedValue(startResponse)
})

describe('a monitored sitting actually enters fullscreen (R2-003)', () => {
  it('requests fullscreen from the start click', async () => {
    const request = stubFullscreen()
    const user = userEvent.setup()
    renderCandidatePage()

    await passGate(user)

    // The claim on the consent screen is "Fullscreen, pasting blocked, tab
    // switches recorded". This is the half nothing asserted: the call itself.
    await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
  })

  it('records the denial when the browser refuses, and lets the sitting continue', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    try {
      const request = stubFullscreen({ grant: false })
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
      renderCandidatePage()

      await passGate(user)

      await waitFor(() => expect(request).toHaveBeenCalledTimes(1))
      // A refusal is context for the interviewer, not a dead end for the
      // candidate: the editor stays writable.
      expect(await screen.findByLabelText(/code editor/i)).not.toHaveAttribute('readonly')

      // And the signal actually leaves the browser. Queued before the first
      // render where monitoring is on, so this also pins that a denial raised
      // in that window survives to the next flush.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(11_000)
      })
      expect(
        vi
          .mocked(api.postIntegrityEvents)
          .mock.calls.flatMap((c) => c[1].events)
          .map((e) => e.kind),
      ).toContain('fullscreen_denied')
    } finally {
      vi.useRealTimers()
    }
  })

  it('asks for nothing when the sitting is unmonitored', async () => {
    const request = stubFullscreen()
    vi.mocked(api.getInvite).mockResolvedValue({ status: 'active', proctored: false })
    vi.mocked(api.startInvite).mockResolvedValue({ ...startResponse, proctored: false })
    const user = userEvent.setup()
    renderCandidatePage()

    await passGate(user)

    expect(await screen.findByLabelText(/code editor/i)).toBeInTheDocument()
    expect(request).not.toHaveBeenCalled()
  })
})

describe('a second tab on the same sitting stands down (R2-041)', () => {
  it('says so, and records nothing, when another tab already holds it', async () => {
    stubFullscreen()
    const user = userEvent.setup()
    renderCandidatePage()
    await passGate(user)
    await screen.findByLabelText(/code editor/i)

    // Another tab claimed this sitting a moment ago and is still beating. The
    // lock key is the invite token and the candidate's address.
    localStorage.setItem(
      'assessment-sitting:tok123:jane@example.com',
      JSON.stringify({ tab: 'the-other-tab', at: Date.now() }),
    )
    // Re-mount, which is what opening the link in a second tab actually is.
    cleanup()
    renderCandidatePage()
    await passGate(user)

    expect(await screen.findByText(/open in another tab/i)).toBeInTheDocument()
    // Nothing is recorded from here: the away total on the interviewer's panel
    // was being inflated by the candidate switching between their own two tabs.
    vi.mocked(api.postIntegrityEvents).mockClear()
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(api.postIntegrityEvents).not.toHaveBeenCalled()
  })

  it('does not warn the candidate against closing the tab it told them to close', async () => {
    stubFullscreen()
    localStorage.setItem(
      'assessment-sitting:tok123:jane@example.com',
      JSON.stringify({ tab: 'the-other-tab', at: Date.now() }),
    )
    const user = userEvent.setup()
    renderCandidatePage()
    await passGate(user)

    expect(await screen.findByText(/open in another tab/i)).toBeInTheDocument()
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    // The notice says "close the other tab"; a "Leave site?" prompt on top of it
    // is the product arguing with itself.
    expect(unload.defaultPrevented).toBe(false)
  })
})
