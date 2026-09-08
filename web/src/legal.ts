/** The published policy documents, and the frontmatter parser that reads them.
 *
 *  Kept apart from `LegalPage` so the parsing is unit-testable on its own and so
 *  the component module exports only a component.
 */

import dpaMd from '../../docs/DPA.md?raw'
import privacyMd from '../../docs/PRIVACY.md?raw'
import termsMd from '../../docs/TERMS.md?raw'

export type LegalDoc = 'privacy' | 'terms' | 'dpa'

export const DOCS: Record<LegalDoc, string> = {
  privacy: privacyMd,
  terms: termsMd,
  dpa: dpaMd,
}

/** Where a `.md` cross-reference in the documents points once published. Links
 *  to anything else (`../STATUS.md`) have no public page and are rendered as
 *  plain text rather than as a link that 404s. */
export const ROUTES: Record<string, string> = {
  'PRIVACY.md': '/privacy',
  'TERMS.md': '/terms',
  'DPA.md': '/dpa',
}

interface Frontmatter {
  version: string | null
  status: string | null
  body: string
}

/** Split the leading `---` block off the document.
 *
 *  Deliberately not a YAML parser: the frontmatter here is two flat string keys
 *  written by us, and the alternative is a dependency to read a file we control
 *  the shape of. A document without frontmatter still renders — it simply has no
 *  version to show. */
export function splitFrontmatter(source: string): Frontmatter {
  const match = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/.exec(source)
  if (!match) return { version: null, status: null, body: source }
  const fields = new Map<string, string>()
  for (const line of match[1].split(/\r?\n/)) {
    const at = line.indexOf(':')
    if (at === -1) continue
    fields.set(line.slice(0, at).trim(), line.slice(at + 1).trim().replace(/^["']|["']$/g, ''))
  }
  return {
    version: fields.get('version') ?? null,
    status: fields.get('status') ?? null,
    body: source.slice(match[0].length),
  }
}
