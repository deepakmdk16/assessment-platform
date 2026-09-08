import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, setNoOrganizationHandler } from '../api'

/** A 422 body the backend really sends: pydantic returns a list of error objects,
 *  which used to reach the page as "[object Object]" (W08). */
function respond(status: number, body: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: false,
      status,
      statusText: 'Unprocessable Entity',
      json: async () => body,
    })),
  )
}

async function messageFrom(status: number, body: unknown): Promise<string> {
  respond(status, body)
  try {
    await api.forgotPassword('jane@acme.com')
    throw new Error('expected the call to reject')
  } catch (err) {
    expect(err).toBeInstanceOf(ApiError)
    return (err as ApiError).message
  }
}

describe('request() error messages', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('joins a list-shaped 422 detail into readable text', async () => {
    const message = await messageFrom(422, {
      detail: [
        { loc: ['body', 'new_password'], msg: 'Value error, password must be at least 12 characters.' },
      ],
    })
    expect(message).toBe('password must be at least 12 characters.')
  })

  it('keeps a string detail as-is', async () => {
    const message = await messageFrom(422, {
      detail: 'that password appears in a known data breach; please choose another.',
    })
    expect(message).toBe('that password appears in a known data breach; please choose another.')
  })

  it('falls back to the status text rather than blanking the alert', async () => {
    // An empty list (or entries with no msg) must not produce an empty message:
    // pages render `{error && <p role="alert">}`, so '' would show nothing at all.
    expect(await messageFrom(422, { detail: [] })).toBe('Unprocessable Entity')
    expect(await messageFrom(422, { detail: [{ loc: ['body'] }] })).toBe('Unprocessable Entity')
  })
})

describe('the no-organisation refusal', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    setNoOrganizationHandler(null)
  })

  it('is recognised centrally, so every page does not have to', async () => {
    // An admin can remove someone; that account is signed in and legitimate but
    // 403s on every data route. Handled here for the same reason a 401 is —
    // otherwise it surfaces as bare error text on each page, with nothing
    // pointing at /team where the recovery lives.
    const onNoOrg = vi.fn()
    setNoOrganizationHandler(onNoOrg)
    respond(403, { detail: 'account belongs to no organisation.' })

    await expect(api.forgotPassword('jane@acme.com')).rejects.toBeInstanceOf(ApiError)
    expect(onNoOrg).toHaveBeenCalledTimes(1)
  })

  it('does not fire for an ordinary 403', async () => {
    const onNoOrg = vi.fn()
    setNoOrganizationHandler(onNoOrg)
    respond(403, { detail: "not your organisation's question." })

    await expect(api.forgotPassword('jane@acme.com')).rejects.toBeInstanceOf(ApiError)
    expect(onNoOrg).not.toHaveBeenCalled()
  })
})
