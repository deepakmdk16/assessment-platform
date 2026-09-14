/** An address claim of an emailed reset / verification link, for display only.
 *  The server re-checks the token; this never gates anything. Anything that is
 *  not a plausible address (a crafted link could carry any string) is dropped so
 *  the page can't be made to show arbitrary text.
 *
 *  `claim` selects which address: `email` is the account's current one, `new`
 *  the address a change-of-address link moves it to (U08). */
export function emailFromToken(token: string, claim: 'email' | 'new' = 'email'): string | null {
  try {
    const [, payload = ''] = token.split('.')
    const email: unknown = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')))[claim]
    return typeof email === 'string' && email.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
      ? email
      : null
  } catch {
    return null
  }
}
