/** I1 stage 1 — the candidate-side capture engine and the interviewer's panel.
 *  jsdom has no real fullscreen or clipboard, so both are stubbed: what's under
 *  test is the classification (which signal, blocked or not) and the batching,
 *  not the browser's own behaviour. */

import { cleanup, render, screen, waitFor } from '@testing-library/react'
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
function Harness({
  enabled = true,
  questionId = 'q1',
  startedAtMs,
}: {
  enabled?: boolean
  questionId?: string
  startedAtMs?: number | null
}) {
  const integrity = useIntegrity({
    token: 'tok',
    candidateEmail: 'cand@x.io',
    questionId,
    enabled,
    startedAtMs,
  })
  return (
    <div>
      <span data-testid="must-return">{String(integrity.mustReturnToFullscreen)}</span>
      <span data-testid="exits">{integrity.fullscreenExits}</span>
      <span data-testid="blocked">{integrity.pasteBlocked?.size ?? ''}</span>
      <span data-testid="away">{integrity.awayNotice?.durationMs ?? ''}</span>
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
    // ...and tells the candidate it was seen (U05). A tab switch cannot be
    // blocked by any browser API, so acknowledging it is the whole response.
    expect(screen.getByTestId('away').textContent).not.toBe('')
    expect(Number(screen.getByTestId('away').textContent)).toBeGreaterThanOrEqual(4000)
    visibility.mockRestore()
  })

  it('records a momentary flicker but does not announce it', async () => {
    // A notification stealing focus or a screenshot is not a visit elsewhere;
    // nagging about those would train the candidate to ignore the notice.
    render(<Harness />)
    const visibility = vi.spyOn(document, 'visibilityState', 'get')

    visibility.mockReturnValue('hidden')
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await act(async () => {
      vi.advanceTimersByTime(300)
    })
    visibility.mockReturnValue('visible')
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })

    expect(screen.getByTestId('away')).toHaveTextContent('')
    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted().length).toBeGreaterThan(0))
    expect(posted().find((e) => e.kind === 'focus_loss')).toBeDefined()
    visibility.mockRestore()
  })

  it('says nothing about a tab switch in an unmonitored sitting', async () => {
    // Nothing is recorded without the monitoring consent, so there is nothing
    // to acknowledge either.
    render(<Harness enabled={false} />)
    const visibility = vi.spyOn(document, 'visibilityState', 'get')
    visibility.mockReturnValue('hidden')
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    await act(async () => {
      vi.advanceTimersByTime(9000)
    })
    visibility.mockReturnValue('visible')
    act(() => {
      document.dispatchEvent(new Event('visibilitychange'))
    })
    expect(screen.getByTestId('away')).toHaveTextContent('')
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

  it('tells a sitting with no consent record apart from a consented one', () => {
    // The panel's other states were covered; this one was not, so nothing
    // stopped it from silently disappearing (R2-003's other half). A sitting
    // that predates the consent record must not read as one that consented.
    render(<IntegrityPanel report={report({ consent_at: null })} />)
    expect(screen.getByText('No consent recorded')).toBeInTheDocument()
    expect(screen.queryByText('Consented')).not.toBeInTheDocument()

    cleanup()
    render(<IntegrityPanel report={report({ consent_at: '2026-09-15T10:00:00Z' })} />)
    expect(screen.getByText('Consented')).toBeInTheDocument()
    expect(screen.queryByText('No consent recorded')).not.toBeInTheDocument()
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

describe('offsets are anchored to the sitting, not to the page load (R2-036)', () => {
  it('places an event at its distance from the server-reported start', async () => {
    // A candidate 40 minutes in who reloads: the browser knows how long the
    // sitting has run because /start returned `started_at` and `server_now`, so
    // the first event of the NEW page load is still placed 40 minutes along.
    render(<Harness startedAtMs={Date.now() - 40 * 60_000} />)
    act(() => {
      document.dispatchEvent(clipboardEvent('paste', 'from somewhere else'))
    })
    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted()).toHaveLength(1))

    const offset = posted()[0].offset_ms
    expect(offset).toBeGreaterThan(39 * 60_000)
    expect(offset).toBeLessThan(41 * 60_000)
  })

  it('falls back to this page load when the server reported no start', async () => {
    // The pre-attempt case: nothing to anchor to, and measuring from now is the
    // most the browser can honestly say.
    render(<Harness startedAtMs={null} />)
    act(() => {
      document.dispatchEvent(clipboardEvent('paste', 'from somewhere else'))
    })
    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted()).toHaveLength(1))

    expect(posted()[0].offset_ms).toBeLessThan(1000)
  })
})

describe('the devtools heuristic scores a change, not a size (R2-040)', () => {
  /** jsdom lets these be assigned; the hook only ever reads them. */
  function setWindow(outer: number, inner: number) {
    window.outerWidth = outer
    window.innerWidth = inner
    window.outerHeight = 900
    window.innerHeight = 900
  }

  it('ignores a gap that was already there when the sitting began', async () => {
    // Edge's vertical tabs and Firefox's sidebar both open a permanent gap of
    // this size. Scoring the absolute gap flagged every one of those candidates
    // as having opened developer tools.
    setWindow(1600, 1300)
    render(<Harness />)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    act(() => screen.getByText('flush').click())
    await act(async () => {
      vi.advanceTimersByTime(50)
    })
    expect(posted().find((e) => e.kind === 'devtools')).toBeUndefined()
  })

  it('records a gap that opens during the sitting', async () => {
    setWindow(1600, 1580)
    render(<Harness />)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    // Docked developer tools: the window is unchanged, the viewport shrinks.
    setWindow(1600, 1100)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })

    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted().find((e) => e.kind === 'devtools')).toBeDefined())
  })

  it('does not read leaving fullscreen as devtools opening', async () => {
    // Fullscreen removes the browser's chrome, so the gap collapses. Sharing one
    // baseline across that boundary made ~0 the sitting's minimum and turned
    // every later exit — the thing this sitting asks candidates NOT to do, and
    // therefore the thing they do — into a "devtools" signal on the report.
    setWindow(1600, 1350)
    render(<Harness />)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })

    // Into fullscreen: no chrome, no gap.
    Object.defineProperty(document, 'fullscreenElement', {
      value: document.documentElement,
      configurable: true,
    })
    setWindow(1600, 1600)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })

    // ...and back out, which restores exactly the gap we started with.
    Object.defineProperty(document, 'fullscreenElement', { value: null, configurable: true })
    setWindow(1600, 1350)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })

    act(() => screen.getByText('flush').click())
    await act(async () => {
      vi.advanceTimersByTime(50)
    })
    expect(posted().find((e) => e.kind === 'devtools')).toBeUndefined()
  })

  it('still sees devtools opened while the candidate is in fullscreen', async () => {
    Object.defineProperty(document, 'fullscreenElement', {
      value: document.documentElement,
      configurable: true,
    })
    setWindow(1600, 1600)
    render(<Harness />)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    setWindow(1600, 1150) // docked devtools inside the fullscreen window
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })

    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted().find((e) => e.kind === 'devtools')).toBeDefined())
    Object.defineProperty(document, 'fullscreenElement', { value: null, configurable: true })
  })

  it('still sees devtools opened after the candidate closes a sidebar', async () => {
    // The narrowest chrome seen so far is the baseline, not the first sample —
    // otherwise closing a sidebar and then opening devtools nets out to zero.
    setWindow(1600, 1300) // sidebar open at the start
    render(<Harness />)
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    setWindow(1600, 1580) // sidebar closed
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })
    setWindow(1600, 1300) // devtools opened, same gap as the old sidebar
    act(() => {
      window.dispatchEvent(new Event('resize'))
    })

    act(() => screen.getByText('flush').click())
    await waitFor(() => expect(posted().find((e) => e.kind === 'devtools')).toBeDefined())
  })
})
