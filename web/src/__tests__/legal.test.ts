import { describe, expect, it } from 'vitest'
import { DOCS, ROUTES, splitFrontmatter } from '../legal'

describe('splitFrontmatter', () => {
  it('lifts the version out and leaves the body', () => {
    const { version, status, body } = splitFrontmatter(
      '---\nversion: 2026-09-08\nstatus: DRAFT\n---\n# Privacy Notice\n\nHello.\n',
    )
    expect(version).toBe('2026-09-08')
    expect(status).toBe('DRAFT')
    expect(body).toBe('# Privacy Notice\n\nHello.\n')
  })

  it('renders a document that has no frontmatter rather than blanking it', () => {
    const { version, body } = splitFrontmatter('# Terms\n\nBody.\n')
    expect(version).toBeNull()
    expect(body).toBe('# Terms\n\nBody.\n')
  })

  it('does not mistake a horizontal rule further down for frontmatter', () => {
    const { version, body } = splitFrontmatter('# Terms\n\nOne.\n\n---\n\nTwo.\n')
    expect(version).toBeNull()
    expect(body).toContain('Two.')
  })

  it('strips surrounding quotes from a value', () => {
    expect(splitFrontmatter('---\nstatus: "DRAFT TEMPLATE"\n---\nx\n').status).toBe(
      'DRAFT TEMPLATE',
    )
  })
})

describe('the published documents', () => {
  it('every one carries a version, since consent is stamped with it', () => {
    for (const [name, source] of Object.entries(DOCS)) {
      expect(splitFrontmatter(source).version, `${name} has no version`).toBeTruthy()
    }
  })

  it('every one still says it is an unreviewed draft', () => {
    // The banner is what makes publishing a template honest. When a lawyer has
    // signed the text off (X19) this test is what has to be changed on purpose.
    for (const [name, source] of Object.entries(DOCS)) {
      expect(splitFrontmatter(source).status, `${name} lost its DRAFT status`).toMatch(/DRAFT/i)
    }
  })

  it('the privacy notice records what proctoring does NOT collect', () => {
    // The single most load-bearing sentence for a candidate: no camera, no
    // microphone, no screen. Losing it in an edit would change what people are
    // agreeing to.
    expect(DOCS.privacy).toMatch(/does not use your camera, microphone, or screen/i)
  })

  it('cross-references between the documents resolve to real routes', () => {
    for (const target of Object.keys(ROUTES)) {
      expect(ROUTES[target].startsWith('/')).toBe(true)
    }
    expect(Object.keys(ROUTES).sort()).toEqual(['DPA.md', 'PRIVACY.md', 'TERMS.md'])
  })
})
