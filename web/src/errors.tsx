import type { ReactElement } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from './api'

/** What `apiMessage` returns: a sentence, or a sentence carrying a link.
 *  Narrower than `ReactNode` on purpose — a state holding one of these is
 *  still something you can be sure renders as a message. */
export type ErrorMessage = string | ReactElement

/** A failed call, said in a way the interviewer can act on.
 *
 *  Every status but one is a sentence and nothing more. 402 is the exception:
 *  the plan's allowance is spent, the fix is a page in this app, and since
 *  Settings has a route per section (P3a) that page can be linked to instead of
 *  described. The server's message stays verbatim — it is the API's answer and
 *  has to stand on its own for a caller that is not a browser — and the link is
 *  added beside it.
 */
export function apiMessage(err: unknown, fallback: string): ErrorMessage {
  if (!(err instanceof ApiError)) return fallback
  if (err.status !== 402) return err.message
  return (
    <>
      {err.message}
      <Link className="quota-link" to="/settings/billing">
        Open Billing
      </Link>
    </>
  )
}
