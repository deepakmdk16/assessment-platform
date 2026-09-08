// Guards the "all appearance is token-driven" rule (see CONVENTIONS.md): fails
// if a hex colour literal appears in a component (.tsx) or in a stylesheet other
// than tokens.css. Colours are DEFINED in styles/tokens.css and referenced
// everywhere else as var(--token).
//
// components.css was outside this guard until 2026-09-08 and had accumulated 15
// literals — including a hardcoded editor background that showed through in
// light mode. Scanning .css is what stops that happening again.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = new URL('../src', import.meta.url).pathname
const HEX = /#[0-9a-fA-F]{3,8}\b/

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    // tokens.css is where hex belongs — it is the single source of truth.
    else if (name.endsWith('.tsx') || (name.endsWith('.css') && name !== 'tokens.css'))
      out.push(p)
  }
  return out
}

const violations = []
for (const file of walk(ROOT)) {
  readFileSync(file, 'utf8')
    .split('\n')
    .forEach((line, i) => {
      if (HEX.test(line)) violations.push(`${file}:${i + 1}: ${line.trim()}`)
    })
}

if (violations.length) {
  console.error('Hex colour literal(s) found — define them in styles/tokens.css and')
  console.error('reference them as var(--token):')
  for (const v of violations) console.error('  ' + v)
  process.exit(1)
}
console.log('check-no-hex: no hex colours outside tokens.css ✓')
