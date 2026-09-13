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
