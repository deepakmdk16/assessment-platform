import { useState } from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { ExpiryField } from '../ExpiryField'

/** Mirrors how the invite dialogs use it: the parent resets `value` to null
 *  after a successful send while the field stays mounted. */
function Harness() {
  const [value, setValue] = useState<string | null>(null)
  return (
    <>
      <ExpiryField value={value} onChange={setValue} idPrefix="t" />
      <button type="button" onClick={() => setValue(null)}>
        Send
      </button>
      <output>{value ?? 'null'}</output>
    </>
  )
}

describe('ExpiryField', () => {
  it('follows the parent when it resets the value after a send', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const select = screen.getByLabelText(/link expires/i)

    await user.selectOptions(select, '7 days')
    expect(screen.getByRole('status', { hidden: true }).textContent).not.toBe('null')

    // The parent clears the value on a successful send. The select used to keep
    // showing "7 days" while the value was null, so the NEXT invite went out
    // with no expiry — on surfaces that have no revoke, the only control there
    // is, silently not applied.
    await user.click(screen.getByRole('button', { name: 'Send' }))

    expect(select).toHaveValue('Never')
    expect(screen.getByRole('status', { hidden: true }).textContent).toBe('null')
  })

  it('emits null for Never and a future instant for a preset', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    const select = screen.getByLabelText(/link expires/i)
    const out = screen.getByRole('status', { hidden: true })

    expect(out.textContent).toBe('null')
    await user.selectOptions(select, '24 hours')
    expect(new Date(out.textContent!).getTime()).toBeGreaterThan(Date.now())
  })
})
