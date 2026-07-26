---
name: ui-mockup
description: >-
  Building a new UI page, panel, or non-trivial visual change for the
  assessment-platform web app (web/), and producing the mockup-first artifact
  the project requires. Loads this repo's design-token vocabulary + component
  class inventory so you don't re-read the CSS every time. Complements the
  built-in artifact-design skill (fundamentals) with THIS app's specifics.
  Triggers: "mockup", "new UI page", "design a screen/panel", "restyle",
  "build a page for X".
---

# Building a platform UI mockup

The platform's appearance is **100% token-driven** — `web/src/styles/tokens.css`
is the single source of truth, and every component is styled by semantic class,
never inline. Your job when mocking a new screen is to reuse that vocabulary, not
reinvent it. Read [references/design-tokens.md](references/design-tokens.md) for
the full token + class map; the workflow below is the process.

## Workflow

1. **Load fundamentals first.** Invoke the built-in **`artifact-design`** skill —
   it calibrates design investment and gives the base method. This skill only adds
   the platform-specific vocabulary on top.

2. **Pull the live token block into the mockup — never hand-type hex.** Copy the
   `:root { … }` block (and both dark-theme blocks) verbatim from
   `web/src/styles/tokens.css` into the mockup's `<style>`. This is what makes the
   mockup drift-proof and exactly on-palette: values come from source at mockup
   time, so a re-theme upstream is one re-copy, not a repaint. Then reference every
   colour/space/radius/shadow as `var(--token)` — same discipline as the real app.

3. **Reuse the semantic class vocabulary.** Before inventing a class, check the
   inventory in [references/design-tokens.md](references/design-tokens.md) — the app
   already has `.card`, `.btn`, `.chip.chip-good`, `.sidebar`, `.tbl`, `.field`,
   `.wizard`, `.modal`, and ~150 more. Match existing names so the mockup maps 1:1
   onto real CSS and the eventual `.tsx` needs no new styling.

4. **Honor the dark-theme contract.** The palette flips via two triggers kept in
   lockstep — `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`
   **and** `:root[data-theme="dark"]`. If you touch theme values, change both
   blocks. Mockups should look correct in light and dark.

5. **Get sign-off before touching `.tsx`.** Per CLAUDE.md, a new UI feature is
   mockup → approval → implementation. Don't iterate live in the running app.

## The one hard rule when it becomes real code

When the mockup graduates to `.tsx`: **no inline `style={}` and no hex/rgb
literals in components** — both are lint-enforced (`no-restricted-syntax` +
`scripts/check-no-hex.mjs`). Semantic class in JSX, every visual rule in
`web/src/styles/components.css` keyed off it; conditional variants go through a
helper (e.g. `badges.ts`), not inline logic. Full rules:
[CONVENTIONS.md](../../../CONVENTIONS.md) → "Styling — a restyle must not touch
`.tsx`".
