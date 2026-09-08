/** The published policy documents (X04).
 *
 *  These render `docs/*.md` directly rather than restating them in JSX. The
 *  version string in a document's frontmatter is the same one stamped onto every
 *  candidate's consent record (`PRIVACY_POLICY_VERSION`), so the words a
 *  candidate agreed to and the words in the repo have to be the same words —
 *  a second copy in a component is a copy that goes stale silently.
 *
 *  Public and unauthenticated: a candidate reads these before identifying
 *  themselves, from the link on the start gate.
 */

import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useParams } from 'react-router-dom'

import { DOCS, ROUTES, splitFrontmatter, type LegalDoc } from '../legal'

export function LegalPage({ doc }: { doc?: LegalDoc }) {
  // Rendered both as a fixed route (`<LegalPage doc="privacy" />`) and, for the
  // shared `/legal/:doc` form, from the URL.
  const params = useParams<{ doc?: string }>()
  const key = (doc ?? params.doc ?? 'privacy') as LegalDoc
  const { version, body } = splitFrontmatter(DOCS[key] ?? DOCS.privacy)

  return (
    <div className="legal-page">
      <article className="legal">
        {version && <p className="legal-version">Version {version}</p>}
        <Markdown
          remarkPlugins={[remarkGfm]}
          components={{
            // Tables in these documents are wide; give each its own scroller so
            // the page body never scrolls sideways on a phone.
            table: ({ children }) => (
              <div className="legal-table-scroll">
                <table>{children}</table>
              </div>
            ),
            a: ({ href, children }) => {
              if (!href) return <>{children}</>
              const mapped = ROUTES[href]
              if (mapped) return <a href={mapped}>{children}</a>
              // A cross-reference to a file with no published page.
              if (href.endsWith('.md')) return <>{children}</>
              return (
                <a href={href} target="_blank" rel="noreferrer">
                  {children}
                </a>
              )
            },
          }}
        >
          {body}
        </Markdown>
      </article>
      <p className="legal-foot">
        <a href="/privacy">Privacy</a>
        <span aria-hidden="true">·</span>
        <a href="/terms">Terms</a>
        <span aria-hidden="true">·</span>
        <a href="/dpa">Data processing</a>
      </p>
    </div>
  )
}
