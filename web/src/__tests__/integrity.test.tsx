/** I1 stage 1 — the candidate-side capture engine and the interviewer's panel.
 *  jsdom has no real fullscreen or clipboard, so both are stubbed: what's under
 *  test is the classification (which signal, blocked or not) and the batching,
 *  not the browser's own behaviour. */

import { render, screen, waitFor } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { IntegrityCell, IntegrityChip, IntegrityPanel } from '../components/IntegrityPanel'
import { normalizeClipboard, useIntegrity } from '../integrity'
import { api } from '../api'
import type { IntegrityReport } from '../types'

vi.mock('../api', () => ({
  api: { postIntegrityEvents: vi.fn(() => Promise.resolve()) },
  ApiError: class extends Error {},
}))

const postEvents = vi.mocked(api.postIntegrityEvents)

/** Mount the hook and expose its latest state to the test. */
function Harness({ enabled = true, questionId = 'q1' }: { enabled?: boolean; questionId?: string }) {
  const integrity = useIntegrity({
    token: 'tok',
    candidateEmail: 'cand@x.io',
    questionId,
    enabled,
  })
  return (
    <div>
      <span data-testid="must-return">{String(integrity.mustReturnToFullscreen)}</span>
      <span data-testid="exits">{integrity.fullscreenExits}</span>
      <span data-testid="blocked">{integrity.pasteBlocked?.size ?? ''}</span>
      <button type="button" onClick={integrity.flush}>
        flush
      </button>
      <textarea aria-label="editor" />
    </div>
  )
}

function clipboardEvent(type: 'copy' | 'paste' | 'cut', text: string): ClipboardEvent {
  const e = new Event(type, { bubbles: true, cancelable: true }) as ClipboardEvent
  Object.defineProperty(e, 'clipboardData', {
    value: { getData: () => text },
  })
  return e
}

/** The events posted so far, flattened across batches. */
function posted() {
  return postEvents.mock.calls.flatMap((c) => c[1].events)
}

beforeEach(() => {
  postEvents.mockClear()
  vi.useFakeTimers({ shouldAdvanceTime: true })
  // jsdom implements neither the Fullscreen API nor `document.fullscreenElement`;
  // stub the entry point so the enforcement path under test is reachable.
  document.documentElement.requestFullscreen = vi.fn(() => Promise.resolve())
  Object.defineProperty(document, 'fullscreenElement', { value: null, configurable: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('paste classification', () => {
  it('blocks text that was never copied inside the page', async () => {
    render(<Harness />)
    const event = clipboardEvent('paste', 'def solve(): pass')
    act(() => {
      document.dispatchEvent(event)
    })
    expect(event.defaultPrevented).toBe(true)
    expect(await screen.findByTestId('blocked')).toHaveTextContent('17')

    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted()).toHaveLength(1))
    expect(posted()[0]).toMatchObject({ kind: 'paste_external', blocked: true, size: 17 })
  })

  it('allows text copied within the page, and records it as context', async () => {
    render(<Harness />)
    act(() => {
      document.dispatchEvent(clipboardEvent('copy', 'helper(x)'))
    })
    const paste = clipboardEvent('paste', 'helper(x)')
    act(() => {
      document.dispatchEvent(paste)
    })
    expect(paste.defaultPrevented).toBe(false)
    expect(screen.getByTestId('blocked')).toHaveTextContent('')

    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted()).toHaveLength(1))
    expect(posted()[0]).toMatchObject({ kind: 'paste_internal' })
    expect(posted()[0].blocked).toBeUndefined()  // recorded as context, not as a block
  })

  it('treats re-indented in-page text as internal, not as an outside paste', () => {
    // The editor may re-wrap what it hands back; whitespace must not turn a
    // candidate's own copy into a false accusation.
    render(<Harness />)
    act(() => {
      document.dispatchEvent(clipboardEvent('copy', 'a = 1\n  b = 2'))
    })
    const paste = clipboardEvent('paste', 'a = 1    b = 2')
    act(() => {
      document.dispatchEvent(paste)
    })
    expect(paste.defaultPrevented).toBe(false)
  })

  it('normalizes whitespace when comparing clipboard text', () => {
    expect(normalizeClipboard('  a\n\t b  ')).toBe('a b')
    expect(normalizeClipboard('   ')).toBe('')
  })

  it('records nothing when the sitting is unmonitored', () => {
    render(<Harness enabled={false} />)
    const paste = clipboardEvent('paste', 'anything at all')
    act(() => {
      document.dispatchEvent(paste)
    })
    expect(paste.defaultPrevented).toBe(false)
    expect(screen.getByTestId('blocked')).toHaveTextContent('')
  })
})

describe('focus and fullscreen', () => {
  it('records a tab switch with how long the candidate was away', async () => {
    render(<Harness />)
    const visibility = vi.spyOn(document, 'visibilityState', 'get')

    visibility.mockReturnValue('hidden')
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await act(async () => {
      vi.advanceTimersByTime(4000)
    })
    visibility.mockReturnValue('visible')
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })

    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted().length).toBeGreaterThan(0))
    const focus = posted().find((e) => e.kind === 'focus_loss')
    expect(focus?.duration_ms).toBeGreaterThanOrEqual(4000)
    visibility.mockRestore()
  })

  it('blocks the sitting while out of fullscreen and clears when it returns', async () => {
    render(<Harness />)
    // jsdom reports no fullscreen element, so a change event = an exit.
    act(() => {
      document.dispatchEvent(new Event('fullscreenchange'))
    })
    expect(screen.getByTestId('must-return')).toHaveTextContent('true')
    expect(screen.getByTestId('exits')).toHaveTextContent('1')

    const el = document.createElement('div')
    Object.defineProperty(document, 'fullscreenElement', { value: el, configurable: true })
    act(() => {
      document.dispatchEvent(new Event('fullscreenchange'))
    })
    expect(screen.getByTestId('must-return')).toHaveTextContent('false')

    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted().some((e) => e.kind === 'fullscreen_exit')).toBe(true))
    Object.defineProperty(document, 'fullscreenElement', { value: null, configurable: true })
  })
})

describe('batching', () => {
  it('flushes on its own interval, tagged with the open question', async () => {
    render(<Harness questionId="q7" />)
    act(() => {
      document.dispatchEvent(clipboardEvent('paste', 'outside'))
    })
    expect(postEvents).not.toHaveBeenCalled()  // queued, not sent per event

    await act(async () => {
      vi.advanceTimersByTime(10_000)
    })
    await waitFor(() => expect(postEvents).toHaveBeenCalledTimes(1))
    expect(postEvents.mock.calls[0][1]).toMatchObject({
      candidate_email: 'cand@x.io',
      question_id: 'q7',
    })
  })

  it('never rejects into the page when the server is unreachable', async () => {
    postEvents.mockRejectedValueOnce(new Error('offline'))
    render(<Harness />)
    act(() => {
      document.dispatchEvent(clipboardEvent('paste', 'outside'))
    })
    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(postEvents).toHaveBeenCalled())
    // A failed flush must not resurface as an unhandled rejection or a visible
    // error — monitoring degrades quietly.
    expect(screen.getByTestId('blocked')).toHaveTextContent('7')
  })
})

describe('the interviewer panel', () => {
  const report = (over: Partial<IntegrityReport> = {}): IntegrityReport => ({
    monitored: true,
    summary: {
      total: 2,
      focus_losses: 1,
      away_ms: 231_000,
      fullscreen_exits: 0,
      pastes_blocked: 1,
      devtools_opens: 0,
    },
    events: [
      {
        kind: 'focus_loss',
        offset_ms: 42_000,
        duration_ms: 231_000,
        size: null,
        blocked: false,
        question_id: 'q1',
        question_title: 'Two Sum',
      },
      {
        kind: 'paste_external',
        offset_ms: 291_000,
        duration_ms: null,
        size: 1284,
        blocked: true,
        question_id: 'q1',
        question_title: 'Two Sum',
      },
    ],
    ...over,
  })

  it('leads with the counts and lists events at offsets from the start', () => {
    render(<IntegrityPanel report={report()} />)
    expect(screen.getByText('1 paste blocked')).toBeInTheDocument()
    expect(screen.getByText(/1 tab switch · 3m 51s away/)).toBeInTheDocument()
    expect(screen.getByText('+00:42')).toBeInTheDocument()
    expect(screen.getByText('+04:51')).toBeInTheDocument()
    expect(screen.getByText(/1,284 characters/)).toBeInTheDocument()
    expect(screen.getByText('blocked')).toBeInTheDocument()
  })

  it('says a clean sitting is clean', () => {
    render(
      <IntegrityPanel
        report={report({
          summary: {
            total: 0,
            focus_losses: 0,
            away_ms: 0,
            fullscreen_exits: 0,
            pastes_blocked: 0,
            devtools_opens: 0,
          },
          risk: { score: 0, level: 'none', reasons: [] },
          events: [],
        })}
      />,
    )
    expect(screen.getByText('No signals')).toBeInTheDocument()
    expect(screen.getByText('0 / 100')).toBeInTheDocument()
  })

  it('shows the risk banner with the reasons that drove the level', () => {
    render(
      <IntegrityPanel
        report={report({
          risk: {
            score: 45,
            level: 'elevated',
            reasons: [
              { label: '1 outside paste blocked', points: 30 },
              { label: 'devtools opened 1 time', points: 15 },
            ],
          },
        })}
      />,
    )
    expect(screen.getByText('Elevated')).toBeInTheDocument()
    expect(screen.getByText('45 / 100')).toBeInTheDocument()
    expect(screen.getByText('1 outside paste blocked')).toBeInTheDocument()
    expect(screen.getByText('+30')).toBeInTheDocument()
    // The not-proof disclaimer is part of the banner, always shown with it.
    expect(screen.getByText(/never part of the verdict/)).toBeInTheDocument()
  })

  it('does not let an unmonitored sitting read as a clean one', () => {
    // An unmonitored sitting records nothing, so this is the state that matters:
    // empty, and it must NOT render as "No signals — stayed in fullscreen…".
    render(
      <IntegrityPanel
        report={report({
          monitored: false,
          summary: {
            total: 0,
            focus_losses: 0,
            away_ms: 0,
            fullscreen_exits: 0,
            pastes_blocked: 0,
            devtools_opens: 0,
          },
          events: [],
        })}
      />,
    )
    expect(screen.getByText(/ran unmonitored/)).toBeInTheDocument()
    expect(screen.queryByText('No signals')).not.toBeInTheDocument()
  })
})

describe('states that must not look alike', () => {
  const clean: IntegrityReport = {
    monitored: true,
    summary: {
      total: 0,
      focus_losses: 0,
      away_ms: 0,
      fullscreen_exits: 0,
      pastes_blocked: 0,
      devtools_opens: 0,
    },
    events: [],
  }

  it('still shows recorded events if the sitting is reported unmonitored', () => {
    // Belt and braces behind the Invite.proctored snapshot: recorded evidence
    // always wins over the flag, because suppressing it would hide the truth.
    render(
      <IntegrityPanel
        report={{
          ...clean,
          monitored: false,
          summary: { ...clean.summary, total: 1, fullscreen_exits: 1 },
          events: [
            {
              kind: 'fullscreen_exit',
              offset_ms: 1000,
              duration_ms: 4000,
              size: null,
              blocked: false,
              question_id: null,
              question_title: null,
            },
          ],
        }}
      />,
    )
    expect(screen.getByText('Exited fullscreen')).toBeInTheDocument()
    expect(screen.queryByText(/ran unmonitored/)).not.toBeInTheDocument()
  })

  it('tells an unmonitored sitting apart from one with no signals, in the grid', () => {
    const { rerender } = render(<IntegrityCell signals={null} blocked={0} />)
    expect(screen.getByText('Not monitored')).toBeInTheDocument()

    rerender(<IntegrityCell signals={0} blocked={0} />)
    expect(screen.queryByText('Not monitored')).not.toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()

    rerender(<IntegrityCell signals={4} blocked={1} />)
    expect(screen.getByText('4')).toHaveAttribute(
      'title',
      '4 signals, including 1 blocked paste',
    )
  })

  it('colours the grid chip by risk level, not only by blocked pastes', () => {
    const { rerender } = render(<IntegrityCell signals={2} blocked={2} risk="high" />)
    expect(screen.getByText('2')).toHaveClass('chip-bad')
    expect(screen.getByText('2')).toHaveAttribute(
      'title',
      'risk high — 2 signals, including 2 blocked pastes',
    )

    rerender(<IntegrityCell signals={3} blocked={0} risk="elevated" />)
    expect(screen.getByText('3')).toHaveClass('chip-warn')

    // Ambient-only signals no longer read amber: low risk is neutral.
    rerender(<IntegrityCell signals={2} blocked={0} risk="low" />)
    expect(screen.getByText('2')).toHaveClass('chip-neutral')
    expect(screen.getByText('2')).toHaveAttribute(
      'title',
      'risk low — 2 signals recorded during this sitting',
    )
  })

  it('colours the header chip by level, so it agrees with the banner', () => {
    const base = {
      monitored: true,
      summary: {
        total: 4,
        focus_losses: 3,
        away_ms: 400_000,
        fullscreen_exits: 0,
        pastes_blocked: 0,
        devtools_opens: 1,
      },
      events: [],
    }
    // "high" reached WITHOUT a blocked paste — the old blocked-pastes rule
    // showed this amber while the banner said High.
    const { rerender } = render(
      <IntegrityChip report={{ ...base, risk: { score: 51, level: 'high', reasons: [] } }} />,
    )
    expect(screen.getByText('Integrity · 4')).toHaveClass('chip-bad')

    rerender(
      <IntegrityChip report={{ ...base, risk: { score: 12, level: 'low', reasons: [] } }} />,
    )
    expect(screen.getByText('Integrity · 4')).toHaveClass('chip-neutral')
  })
})
