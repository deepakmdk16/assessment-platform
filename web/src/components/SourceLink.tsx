/** AGPL §13: the source of the version a user is talking to, offered to them.
 *
 *  The licence obligation is about the *running* code, so the commit is baked
 *  in at build time (`SOURCE_COMMIT` in web/Dockerfile, set on a deploy by
 *  docs/DEPLOY.md §2) rather than linking at a branch that moves underneath the
 *  deployment. A build that does not pass one — a working copy, `npm run dev` —
 *  links at the repository instead of at an empty `/tree/`.
 *
 *  Vite copies an empty environment value through verbatim rather than falling
 *  back to a `??` default, which is the trap branding.ts documents; `||` is
 *  deliberate here for that reason.
 */
const REPO = import.meta.env.VITE_SOURCE_URL || 'https://github.com/deepakmdk16/assessment-platform'
const COMMIT = import.meta.env.VITE_SOURCE_COMMIT || ''

export const SOURCE_URL = COMMIT ? `${REPO}/tree/${COMMIT}` : REPO

/** `showCommit` is for the interviewer sidebar, which has the width for a sha
 *  and is also where someone reporting a bug would go looking for a version. */
export function SourceLink({ showCommit = false }: { showCommit?: boolean }) {
  return (
    <a href={SOURCE_URL} target="_blank" rel="noreferrer">
      {showCommit && COMMIT ? `Source ${COMMIT.slice(0, 7)}` : 'Source'}
    </a>
  )
}
