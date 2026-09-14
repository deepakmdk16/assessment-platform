// Gate G2: a sentence that asserts behaviour must be in docs/CLAIMS.md.
//
// R2-003 is why. The consent screen told candidates "Fullscreen, pasting blocked,
// tab switches recorded" while `requestFullscreen` was never called — call count
// 0 on a live proctored sitting — and the interviewer's panel reported "Stayed in
// fullscreen". Every test passed, because the tests asserted what the hook does
// once already out of fullscreen. Nothing connected the sentence to a proof.
//
// This does not try to verify a claim; a script cannot. It makes the claim
// IMPOSSIBLE TO ADD SILENTLY: new copy carrying one of the keywords below fails
// the lint until it has a row in docs/CLAIMS.md naming the test that proves it
// (or saying the proof is owed, with the session that owes it).
//
// Prose extraction is shared in spirit with check-copy.mjs: JSX text nodes, and
// quoted strings with a space in them, so identifiers never trip it.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

const WEB_SRC = 'src'
const EMAIL_TEMPLATES = '../assessment_platform/email_templates.py'
const REGISTER = '../docs/CLAIMS.md'

const PROSE_PATTERNS = [
  />([^<>{}]*[A-Za-z][^<>{}]*)</g,
  /'([^']*\s[^']*)'/g,
  /"([^"]*\s[^"]*)"/g,
  /`([^`]*\s[^`]*)`/g,
]

// `className="editor-hint blocked"` is markup, not copy, and reads exactly like a
// sentence to the patterns above. Strip class attributes before extracting.
const CLASS_ATTRIBUTE = /\bclass(Name)?=(\{`[^`]*`\}|"[^"]*"|'[^']*'|\{[^}]*\})/g

// Words that turn copy into a promise about behaviour.
const CLAIM_KEYWORDS =
  /\b(recorded|records|recording|blocked|blocks|prevented|prevents|autosaved|autosaves|saved automatically|monitored|monitors|only works for you|only you|never shared|cannot be|can't be|is not sent|deleted permanently|permanently deleted)\b/i

// Below this length a fragment is a label, not a sentence making a promise.
const MIN_CLAIM_CHARS = 12

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) {
      if (name !== '__tests__' && name !== 'test') out.push(...walk(p))
    } else if (/\.(tsx|ts)$/.test(name) && !/\.test\./.test(name)) out.push(p)
  }
  return out
}

// The register's first column, as written between backticks.
const registered = [
  ...readFileSync(REGISTER, 'utf8').matchAll(/^\|\s*`([^`]+)`\s*\|/gm),
]
  .map((m) => m[1])
  // Longest first: "blocked" must not swallow a sentence that a longer row owns.
  .sort((a, b) => b.length - a.length)

if (registered.length === 0) {
  console.error(`check-claims: no claims parsed out of ${REGISTER} — is the table intact?`)
  process.exit(1)
}

const unregistered = []
const used = new Set()

for (const file of [...walk(WEB_SRC), EMAIL_TEMPLATES]) {
  const key = file.startsWith('..') ? file : relative('.', file)
  readFileSync(file, 'utf8')
    .split('\n')
    .forEach((rawLine, i) => {
      const line = rawLine.replace(CLASS_ATTRIBUTE, '')
      for (const pattern of PROSE_PATTERNS) {
        pattern.lastIndex = 0
        let m
        while ((m = pattern.exec(line)) !== null) {
          const text = m[1].trim()
          if (text.length < MIN_CLAIM_CHARS || !CLAIM_KEYWORDS.test(text)) continue
          const row = registered.find((claim) => text.includes(claim))
          if (row) used.add(row)
          else unregistered.push(`${key}:${i + 1}: "${text.slice(0, 90)}"`)
        }
      }
    })
}

const unused = registered.filter((claim) => !used.has(claim))

let failed = false
if (unregistered.length) {
  failed = true
  console.error('These sentences claim behaviour and are not in docs/CLAIMS.md:')
  for (const u of unregistered) console.error('  ' + u)
  console.error(
    '\nAdd a row naming the test that proves each one. If no test proves it yet, say' +
      '\n**owed** and name the session that owes it — but do not ship the sentence silently.'
  )
}
if (unused.length) {
  failed = true
  console.error('\nThese registered claims no longer appear in any copy — delete their rows:')
  for (const u of unused) console.error(`  "${u}"`)
  console.error('\n(A register that describes copy nobody ships stops being read.)')
}
if (failed) process.exit(1)
console.log(`check-claims: ${used.size} user-facing claim(s), each with a row in docs/CLAIMS.md ✓`)
