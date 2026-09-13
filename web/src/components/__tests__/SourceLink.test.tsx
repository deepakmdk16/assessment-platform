import { render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

const REPO = 'https://github.com/deepakmdk16/assessment-platform'
const COMMIT = '0123456789abcdef0123456789abcdef01234567'

/** The commit is inlined by Vite at import time, so each case needs a fresh
 *  module with its own environment. */
async function load(commit: string) {
  vi.resetModules()
  vi.stubEnv('VITE_SOURCE_COMMIT', commit)
  return import('../SourceLink')
}

afterEach(() => {
  vi.unstubAllEnvs()
})

it('links at the exact version that is running, not at the branch head', async () => {
  // AGPL §13 offers the source of the software the user is interacting with.
  // A link to the default branch would name different code every time it moved.
  const { SOURCE_URL } = await load(COMMIT)
  expect(SOURCE_URL).toBe(`${REPO}/tree/${COMMIT}`)
})

it('still offers a link when no commit was baked into the build', async () => {
  // Vite copies an empty value through verbatim rather than falling back (see
  // branding.ts), so `/tree/` with nothing after it is the shape to avoid. The
  // obligation does not lapse just because the build forgot the sha.
  const { SOURCE_URL } = await load('')
  expect(SOURCE_URL).toBe(REPO)
})

it('renders an anchor that actually goes somewhere', async () => {
  const { SourceLink } = await load('')
  render(<SourceLink />)
  const link = screen.getByRole('link', { name: /source/i })
  expect(link.getAttribute('href')).toBeTruthy()
  expect(link).toHaveAttribute('rel', 'noreferrer')
})

it('names the short sha where the shell has room for it', async () => {
  const { SourceLink } = await load(COMMIT)
  render(<SourceLink showCommit />)
  expect(screen.getByRole('link', { name: `Source ${COMMIT.slice(0, 7)}` })).toBeInTheDocument()
})

it('says just "Source" when there is no sha to name', async () => {
  const { SourceLink } = await load('')
  render(<SourceLink showCommit />)
  expect(screen.getByRole('link', { name: 'Source' })).toBeInTheDocument()
})
