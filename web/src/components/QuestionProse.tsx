import { Fragment, type ReactNode } from 'react'

/** Inline markdown the drafting model actually emits: `code` and **bold**.
 *  Both markers must open and close on one line, so nothing that merely contains
 *  a backtick or an asterisk (`a * b`, `max_subarray`) is touched. */
const INLINE_MARKDOWN = /`([^`\n]+)`|\*\*([^*\n]+)\*\*/g

function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = []
  let cut = 0
  for (const match of text.matchAll(INLINE_MARKDOWN)) {
    const at = match.index
    if (at > cut) nodes.push(text.slice(cut, at))
    nodes.push(
      match[1] !== undefined ? (
        <code key={at}>{match[1]}</code>
      ) : (
        <strong key={at}>{match[2]}</strong>
      ),
    )
    cut = at + match[0].length
  }
  if (cut < text.length) nodes.push(text.slice(cut))
  return nodes
}

/** A question's prompt or constraints, rendered the way they were written.
 *
 *  These were plain `pre-wrap` text, but the drafting model writes markdown —
 *  six of the ninety dev questions carry backticks or `**`, and the drafting
 *  prompt itself uses backticks in its instructions — so candidates read literal
 *  `` `-1` `` and `**Input**` (R2-142).
 *
 *  Inline only, deliberately, and not react-markdown (which this app does use,
 *  for the legal pages): a markdown block parser strips the leading whitespace
 *  of every line, and "Example:\n  Input:\n    9" — the shape of most prompts in
 *  the corpus, none of which are markdown — comes back flattened against the
 *  margin. Fixing six questions is not worth reformatting eighty-four. Text
 *  outside a marker is passed through verbatim, escaped by React as ever, and
 *  `.pre-text` keeps the line breaks.
 */
export function QuestionProse({ children }: { children: string }) {
  return (
    <p className="pre-text">
      {renderInline(children).map((node, i) => (
        <Fragment key={i}>{node}</Fragment>
      ))}
    </p>
  )
}
