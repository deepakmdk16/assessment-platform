// Guards the "styling lives in CSS, not TSX" rule (see CONVENTIONS.md):
// fails if a hex colour literal appears in a component (.tsx). Colours belong in
// styles/tokens.css, referenced via var(--token).
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'

const ROOT = new URL('../src', import.meta.url).pathname
const HEX = /#[0-9a-fA-F]{3,8}\b/

function walk(dir) {
  const out = []
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) out.push(...walk(p))
    else if (name.endsWith('.tsx')) out.push(p)
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
  console.error('Hex colour literal(s) found in .tsx — move colours to styles/tokens.css:')
  for (const v of violations) console.error('  ' + v)
  process.exit(1)
}
console.log('check-no-hex: no hex colours in .tsx ✓')
