/** R2-041 — one sitting, one tab. Two tabs on one sitting used to double-record
 *  every focus change and race each other's autosaves. */

import { cleanup, render, screen } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSittingLock } from '../sittingLock'

function Tab({ sitting }: { sitting: string | null }) {
  const held = useSittingLock(sitting)
  return <span data-testid="held">{String(held)}</span>
}

/** Both "tabs" are components in one jsdom, which is exactly the shared
 *  localStorage two real tabs have. */
function held(index = 0) {
  return screen.getAllByTestId('held')[index].textContent
}

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('the sitting lock', () => {
  it('gives the sitting to the tab that claimed it first', () => {
    render(<Tab sitting="tok:jane" />)
    expect(held()).toBe('true')

    render(<Tab sitting="tok:jane" />)
    // The second tab finds a live claim and stands down.
    expect(held(1)).toBe('false')
    // ...and the first one keeps it.
    expect(held(0)).toBe('true')
  })

  it('does not arbitrate between different sittings', () => {
    render(<Tab sitting="tok:jane" />)
    render(<Tab sitting="other:sam" />)
    expect(held(0)).toBe('true')
    expect(held(1)).toBe('true')
  })

  it('owns the sitting before the candidate has identified themselves', () => {
    render(<Tab sitting={null} />)
    expect(held()).toBe('true')
  })

  it('hands the sitting on when the holder stops beating', () => {
    // A crashed or force-closed tab leaves its claim behind. Waiting it out is
    // the difference between a stale claim and a candidate locked out of their
    // own assessment.
    localStorage.setItem(
      'assessment-sitting:tok:jane',
      JSON.stringify({ tab: 'a-tab-that-is-gone', at: Date.now() - 30_000 }),
    )
    render(<Tab sitting="tok:jane" />)
    expect(held()).toBe('true')
  })

  it('takes the sitting back after the holder unmounts', () => {
    const first = render(<Tab sitting="tok:jane" />)
    render(<Tab sitting="tok:jane" />)
    expect(held(1)).toBe('false')

    first.unmount()
    act(() => {
      vi.advanceTimersByTime(2_500)
    })
    // Released on unmount, so the survivor takes over on its next beat rather
    // than waiting out the staleness window.
    expect(held(0)).toBe('true')
  })

  it('ignores a claim stamped in the future', () => {
    // A candidate whose system clock jumps backwards would otherwise be locked
    // out until real time caught up.
    localStorage.setItem(
      'assessment-sitting:tok:jane',
      JSON.stringify({ tab: 'someone', at: Date.now() + 60 * 60_000 }),
    )
    render(<Tab sitting="tok:jane" />)
    expect(held()).toBe('true')
  })
})

describe('the lock survives the things a candidate actually does', () => {
  it('releases on unload, so a reload is not mistaken for a second tab', () => {
    render(<Tab sitting="tok:jane" />)
    expect(held()).toBe('true')

    // A reload tears the page down without running React cleanup. Without a
    // pagehide release the tab comes back, finds its own claim still inside the
    // staleness window, and tells the candidate their sitting is open elsewhere.
    act(() => {
      window.dispatchEvent(new Event('pagehide'))
    })
    expect(localStorage.getItem('assessment-sitting:tok:jane')).toBeNull()

    cleanup()
    render(<Tab sitting="tok:jane" />)
    expect(held()).toBe('true')
  })

  it('does not let a stood-down tab release the holder\'s claim', () => {
    render(<Tab sitting="tok:jane" />)
    const second = render(<Tab sitting="tok:jane" />)
    expect(held(1)).toBe('false')

    second.unmount()

    // The survivor still holds it: the loser never owned the claim, so its
    // teardown must not remove one.
    const claim = localStorage.getItem('assessment-sitting:tok:jane')
    expect(claim).not.toBeNull()
    expect(held(0)).toBe('true')
  })
})
