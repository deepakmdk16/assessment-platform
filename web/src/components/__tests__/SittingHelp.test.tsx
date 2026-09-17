/** R2-039 — a way to ask for help without leaving the sitting. Before this, the
 *  support address reached the start gate and nowhere else, so a candidate who
 *  hit trouble after clicking Start had no address and no way back to one. */

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { SittingHelp } from '../SittingHelp'
import { IntegrityOverlay } from '../IntegrityGate'
import type { IntegrityState } from '../../integrity'

function outOfFullscreen(): IntegrityState {
  return {
    mustReturnToFullscreen: true,
    fullscreenExits: 1,
    pasteBlocked: null,
    dismissPasteBlock: vi.fn(),
    awayNotice: null,
    dismissAwayNotice: vi.fn(),
    enterFullscreen: vi.fn(async () => {}),
    flush: vi.fn(),
  }
}

describe('the help drawer', () => {
  it('opens from the top bar with the address to write to', async () => {
    const user = userEvent.setup()
    render(<SittingHelp supportEmail="hiring@northwind.example" proctored remainingLabel="24:13 left" />)

    // Shut at rest: the editor is the product, and this is one control on it.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: /help/i }))

    const drawer = screen.getByRole('dialog')
    expect(drawer.tagName).toBe('DIALOG')
    const link = screen.getByRole('link', { name: /hiring@northwind.example/ })
    expect(link).toHaveAttribute('href', 'mailto:hiring@northwind.example')
  })

  it('repeats what is being recorded, so re-reading it costs nothing', async () => {
    const user = userEvent.setup()
    render(<SittingHelp supportEmail="hiring@northwind.example" proctored />)
    await user.click(screen.getByRole('button', { name: /help/i }))

    expect(screen.getByText(/pasting code from outside this page is blocked/i)).toBeInTheDocument()
    expect(screen.getByText(/tab switches are recorded/i)).toBeInTheDocument()
    // No clock on an untimed sitting, rather than an empty line where one goes.
    expect(screen.getByText(/no time limit on this sitting/i)).toBeInTheDocument()
  })

  it('says nothing about monitoring on an unmonitored sitting', async () => {
    const user = userEvent.setup()
    render(<SittingHelp supportEmail="hiring@northwind.example" proctored={false} />)
    await user.click(screen.getByRole('button', { name: /help/i }))

    expect(screen.queryByText(/tab switches are recorded/i)).not.toBeInTheDocument()
    // The other blocks still earn the click.
    expect(screen.getByRole('link', { name: /hiring@northwind.example/ })).toBeInTheDocument()
  })

  it('omits the contact block rather than offering a dead link', async () => {
    const user = userEvent.setup()
    render(<SittingHelp supportEmail={null} proctored />)

    await user.click(screen.getByRole('button', { name: /help/i }))

    expect(screen.queryByText(/something not working/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /mailto/i })).not.toBeInTheDocument()
    // The button still opens: the monitoring rules are worth a click on their own.
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
})

describe('the fullscreen prompt carries its own address', () => {
  it('shows it, because the prompt covers the top bar and its Help button', () => {
    render(
      <IntegrityOverlay
        integrity={outOfFullscreen()}
        remainingLabel="24:13 left"
        supportEmail="hiring@northwind.example"
      />,
    )
    expect(screen.getByRole('link', { name: /hiring@northwind.example/ })).toHaveAttribute(
      'href',
      'mailto:hiring@northwind.example',
    )
  })

  it('shows no line at all when the deploy configures no address', () => {
    render(<IntegrityOverlay integrity={outOfFullscreen()} remainingLabel="24:13 left" />)
    expect(screen.queryByText(/need help\?/i)).not.toBeInTheDocument()
  })
})
