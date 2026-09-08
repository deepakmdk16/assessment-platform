/** The `email` claim of an emailed reset / verification link, for display only.
 *  The server re-checks the token; this never gates anything. Anything that is
 *  not a plausible address (a crafted link could carry any string) is dropped so
 *  the page can't be made to show arbitrary text. */
export function emailFromToken(token: string): string | null {
  try {
    const [, payload = ''] = token.split('.')
    const email: unknown = JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/'))).email
    return typeof email === 'string' && email.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
      ? email
      : null
  } catch {
    return null
  }
}
