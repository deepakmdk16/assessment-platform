# Platform design-token & component vocabulary

The map you need to build an on-palette mockup without re-reading the CSS.
**Values are NOT snapshotted here** (they'd rot) — this documents the *names and
roles*; pull live values from source at mockup time.

Source of truth (read for exact values):
- **Tokens** → `web/src/styles/tokens.css` — `:root` (light) + two dark blocks.
- **Component classes** → `web/src/styles/components.css`.
- **Base/reset + utilities** → `web/src/styles/base.css` (`.mono`, `.muted`, `h1–h3`, `pre`, focus ring).
- **Theme plumbing** → `web/src/theme/theme.ts` (`light|dark|auto`, stamps `data-theme` on `<html>`).

---

## Token vocabulary (by role → `var(--token)`)

Use the **role**, not a raw colour. Grouped as in `tokens.css`:

- **Surfaces & lines:** `--color-bg` (app bg), `--color-surface` (cards), `--color-surface-2`, `--color-surface-3`, `--color-border`, `--color-border-strong`.
- **Text:** `--color-text` (body), `--color-heading` (titles), `--color-muted` (secondary), `--color-faint` (tertiary/placeholder).
- **Brand / actions:** `--color-ink` = primary (graphite) button, `--color-ink-hover`; `--color-accent` = cobalt, **used sparingly** for emphasis, `--color-accent-soft` (tint bg), `--color-accent-ink` (accent text).
- **Semantic status:** `--color-good` / `--color-warn` / `--color-bad`, each with a `-soft` tint background (`--color-good-soft`, etc.).
- **Difficulty** (reused for verdict/status): `--color-easy`, `--color-medium`, `--color-hard`.
- **Left rail** (constant across light/dark): `--rail`, `--rail-2`, `--rail-border`, `--rail-text`, `--rail-muted`.
- **Shape (radius):** `--radius-sm`, `--radius`, `--radius-lg`, `--radius-pill`.
- **Elevation (shadow):** `--shadow-sm`, `--shadow`, `--shadow-lg`.
- **Type:** `--font-sans` (system stack), `--font-mono`.
- **Layout:** `--sidebar-w` (240px), `--content-max` (1300px).

**Dark theme:** every `--color-*`/`--rail*`/`--shadow*` above is redefined in two
blocks kept in lockstep — the `@media (prefers-color-scheme: dark)` one (gated by
`:not([data-theme="light"])`) and `:root[data-theme="dark"]`. Radius/type/layout
do **not** change across themes. Edit both dark blocks together.

---

## Component class inventory (semantic classes in `components.css`)

Reach for these before inventing a class. Grouped by purpose (representative, not
exhaustive — grep `components.css` for the full ~150):

- **Shell / layout:** `.app` `.main` `.content` `.side` `.sidebar` `.side-who` `.side-foot` `.side-logout` `.topbar` `.topbar-user` `.nav` `.nav-label` `.brand` `.brand-mark` `.brand-name` `.page-head` `.page-loading` `.actionbar` `.list-toolbar`
- **Cards / surfaces:** `.card` `.card-title` `.panel` `.panel-body` `.notice-card` `.tc-card` `.draft-card` `.variant-card` `.auth-card` `.modal` `.modal-actions`
- **Buttons / actions:** `.btn` `.btn-link` `.icon-btn` `.row-actions` `.form-actions`
- **Chips / badges / status:** `.chip` + variants `.chip-good` `.chip-warn` `.chip-bad` `.chip-easy` `.chip-medium` `.chip-hard` `.chip-accent` `.chip-neutral` `.chip-live`; `.variant-badge` `.live-dot` `.score` `.count` `.num` `.check`
- **Forms / fields:** `.field` `.inline-field` `.form-error` `.form-success` `.form-warning` `.lang-select` `.picker-label`
- **Auth screens:** `.auth` `.auth-alt` `.auth-card` `.auth-eyebrow` `.auth-lead`
- **IDE / editor / console:** `.ide` `.ide-split` `.ide-panels` `.ide-top` `.ide-title` `.ide-review` `.editor-wrapper` `.editor-head` `.editor-hint` `.console` `.console-body` `.code` `.io` `.io-label` `.cell-pre` `.mono-cell`
- **Tables / lists / grids:** `.tbl` `.tbl-wrap` `.grid2` `.grid3` `.detail-grid` `.kv` `.kv-row` `.stack` `.review-list` `.recip-list` `.variant-list` `.clickable-row` `.row-archived` `.rz` `.rz-row` `.rz-col`
- **Wizard / stepper / progress / pager:** `.wizard` `.wizard-nav` `.stepper` `.step` `.step-bar` `.pager` `.pager-controls` `.pager-page` `.pager-range` `.progress` `.attempt-progress` `.timer` `.timer-done` `.spinner`
- **Tabs:** `.tabs` `.tab` `.tab-meta` `.q-tab` `.theme-seg`
- **Test cases / results:** `.test-strip` `.test-strip-name` `.tc-head` `.tc-io` `.tc-num` `.parity-ok` `.run-summary` `.grading` `.grading-title`
- **Prose / misc:** `.prose` `.bullets` `.muted` `.mono` `.sect-title` `.empty-state` `.crumb` `.boundary` (+ `.boundary-*` error UI)

---

## Regenerate when the design system changes

This is a curated snapshot of *names*. If `tokens.css` gains/renames a token or
`components.css` gains a class family, re-run the survey and update this file.
(A quick check: `grep -oE '^\.[a-z][a-zA-Z0-9_-]*' web/src/styles/components.css |
sort -u` for classes; the `:root` block of `tokens.css` for tokens.)
