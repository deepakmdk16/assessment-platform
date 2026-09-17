/** P2a — the way out of the fullscreen prompt. The prompt itself is exercised
 *  through CandidatePage; this covers the leave dialog it opens. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { IntegrityOverlay } from '../IntegrityGate'
import type { IntegrityState } from '../../integrity'

function outOfFullscreen(over: Partial<IntegrityState> = {}): IntegrityState {
  return {
    mustReturnToFullscreen: true,
    fullscreenExits: 2,
    pasteBlocked: null,
    dismissPasteBlock: vi.fn(),
    awayNotice: null,
    dismissAwayNotice: vi.fn(),
    enterFullscreen: vi.fn(async () => {}),
    flush: vi.fn(),
    ...over,
  }
}

describe('leaving a monitored sitting', () => {
  it('keeps the prompt as it was, plus a way to leave', () => {
    render(<IntegrityOverlay integrity={outOfFullscreen()} remainingLabel="24:18 left" />)
    expect(screen.getByRole('heading', { name: /return to fullscreen to continue/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /re-enter fullscreen/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /leave assessment/i })).toBeInTheDocument()
    expect(screen.getByText(/2 exits recorded/i)).toBeInTheDocument()
  })

  it('explains what leaving means, with the clock, before offering the two choices', async () => {
    const user = userEvent.setup()
    render(<IntegrityOverlay integrity={outOfFullscreen()} remainingLabel="24:18 left" onSubmitAndLeave={() => {}} />)

    await user.click(screen.getByRole('button', { name: /leave assessment/i }))

    expect(screen.getByRole('heading', { name: /leave the assessment\?/i })).toBeInTheDocument()
    expect(screen.getByText(/your work so far is autosaved/i)).toBeInTheDocument()
    expect(screen.getByText(/the clock keeps running: 24:18 left/i)).toBeInTheDocument()
    expect(screen.getByText(/works until time runs out/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /return to fullscreen/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /submit and leave/i })).toBeEnabled()
    // The prompt it replaced is gone until they choose.
    expect(screen.queryByRole('button', { name: /re-enter fullscreen/i })).not.toBeInTheDocument()
  })

  it('says there is no clock when the sitting is untimed', async () => {
    const user = userEvent.setup()
    render(<IntegrityOverlay integrity={outOfFullscreen()} remainingLabel={null} />)
    await user.click(screen.getByRole('button', { name: /leave assessment/i }))
    expect(screen.getByText(/there’s no time limit/i)).toBeInTheDocument()
    expect(screen.getByText(/stays open until you submit/i)).toBeInTheDocument()
  })

  it('returning asks the browser for fullscreen and restores the prompt', async () => {
    const user = userEvent.setup()
    const integrity = outOfFullscreen()
    render(<IntegrityOverlay integrity={integrity} remainingLabel={null} />)
    await user.click(screen.getByRole('button', { name: /leave assessment/i }))
    await user.click(screen.getByRole('button', { name: /return to fullscreen/i }))
    expect(integrity.enterFullscreen).toHaveBeenCalledTimes(1)
    // Still out of fullscreen (jsdom never grants it), so the prompt is back.
    expect(screen.getByRole('button', { name: /re-enter fullscreen/i })).toBeInTheDocument()
  })

  it('"Submit and leave" hands off to the parent, which owns the confirmation', async () => {
    const user = userEvent.setup()
    const onSubmitAndLeave = vi.fn()
    render(
      <IntegrityOverlay integrity={outOfFullscreen()} remainingLabel={null} onSubmitAndLeave={onSubmitAndLeave} />,
    )
    await user.click(screen.getByRole('button', { name: /leave assessment/i }))
    await user.click(screen.getByRole('button', { name: /submit and leave/i }))
    expect(onSubmitAndLeave).toHaveBeenCalledTimes(1)
    // The leave dialog stays underneath the parent's confirmation, so a Cancel
    // there lands back on these facts rather than on the prompt.
    expect(screen.getByRole('heading', { name: /leave the assessment\?/i })).toBeInTheDocument()
  })

  it('cannot submit and leave when nothing has been written', async () => {
    const user = userEvent.setup()
    render(<IntegrityOverlay integrity={outOfFullscreen()} remainingLabel={null} onSubmitAndLeave={null} />)
    await user.click(screen.getByRole('button', { name: /leave assessment/i }))
    expect(screen.getByRole('button', { name: /submit and leave/i })).toBeDisabled()
  })

  it('starts over from the prompt after a fresh exit', async () => {
    // Left the dialog open, re-entered fullscreen by keyboard, then exited
    // again: the new exit must show the prompt, not the stale leave dialog.
    const user = userEvent.setup()
    const { rerender } = render(<IntegrityOverlay integrity={outOfFullscreen({ fullscreenExits: 1 })} />)
    await user.click(screen.getByRole('button', { name: /leave assessment/i }))
    rerender(<IntegrityOverlay integrity={outOfFullscreen({ mustReturnToFullscreen: false })} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    rerender(<IntegrityOverlay integrity={outOfFullscreen({ fullscreenExits: 2 })} />)
    expect(screen.getByRole('button', { name: /re-enter fullscreen/i })).toBeInTheDocument()
  })
})

describe('coming back from another tab (U05)', () => {
  function idle(over: Partial<IntegrityState> = {}): IntegrityState {
    return { ...outOfFullscreen(), mustReturnToFullscreen: false, fullscreenExits: 0, ...over }
  }

  it('says the switch was seen, in seconds, and does not block the editor', async () => {
    // A tab switch is the one thing a browser gives a page no way to prevent,
    // so acknowledging it is the whole of what can be done — and silence left
    // the candidate believing nothing had happened.
    const dismissAwayNotice = vi.fn()
    const user = userEvent.setup()
    render(
      <IntegrityOverlay
        integrity={idle({ awayNotice: { durationMs: 42_000 }, dismissAwayNotice })}
      />,
    )

    const notice = screen.getByRole('status')
    expect(notice).toHaveTextContent('You left this tab for 42 seconds.')
    expect(notice).toHaveTextContent(/shared with the interviewer/i)
    expect(notice).toHaveTextContent(/clock kept running/i)
    // Recorded, not refused: nothing is covering the editor.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(dismissAwayNotice).toHaveBeenCalledTimes(1)
  })

  it('reads a longer absence in minutes', () => {
    render(<IntegrityOverlay integrity={idle({ awayNotice: { durationMs: 132_000 } })} />)
    expect(screen.getByRole('status')).toHaveTextContent('You left this tab for 2m 12s.')
  })

  it('renders nothing at all while the candidate is present', () => {
    const { container } = render(<IntegrityOverlay integrity={idle()} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('the fullscreen prompt is a real modal (R2-038)', () => {
  it('opens as a native dialog, so the browser traps focus instead of the app claiming to', () => {
    const showModal = vi.spyOn(HTMLDialogElement.prototype, 'showModal')
    render(<IntegrityOverlay integrity={outOfFullscreen()} remainingLabel="24:18 left" />)

    const dialog = screen.getByRole('dialog')
    expect(dialog.tagName).toBe('DIALOG')
    // showModal, not show(): only the modal form puts the dialog in the top
    // layer, which is what makes Tab stay inside it and the editor inert.
    expect(showModal).toHaveBeenCalled()
    showModal.mockRestore()
  })

  it('refuses Escape — the way on is back into fullscreen, not out of the prompt', () => {
    render(<IntegrityOverlay integrity={outOfFullscreen()} remainingLabel="24:18 left" />)

    const cancel = new Event('cancel', { cancelable: true })
    screen.getByRole('dialog').dispatchEvent(cancel)

    expect(cancel.defaultPrevented).toBe(true)
  })
})
