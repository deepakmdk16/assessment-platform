---
name: walkthrough
description: Drive the running product in a browser on an isolated stack and report what a real user would hit — every route at both viewports and both themes, with screenshots, overflow measurements and an axe pass. Use before signing off a mockup, after a UI branch is functionally done, or when asked to "walk through the product", "check how it looks", or "find what a user would hit".
---

# /walkthrough — look at the product, on a stack that is yours

The automated gate (`web/e2e/visual-gate.spec.ts`) asserts the two things a
machine can judge: no horizontal overflow, no serious/critical axe violation.
This is for everything else — whether the page is *good* — and for running that
same sweep ad hoc on a branch before a mockup is signed off.

## 1. Never use the dev stack

The dev stack on `:9000` / `:5173` has the developer's data, their session, their
`.env` and a real agent behind it. Findings from it are not reproducible and a
destructive step there costs real work. Bring up an isolated one instead — the
Playwright config already knows how, and every port is overridable:

```bash
cd web
E2E_PLATFORM_PORT=9100 E2E_FRONTEND_PORT=5273 E2E_AGENT_PORT=8200 \
  npx playwright test visual-gate --reporter=list
```

That starts the Node mock agent, a `platform-api` on a throwaway SQLite file
with `PLATFORM_TESTING=1` and rate limits off, and its own Vite — beside a
running dev stack, touching none of it. Screenshots land in
`web/test-results/visual-gate/`, four per route.

For a hands-on sweep rather than the spec, start the same three servers and drive
them yourself; `web/e2e/helpers.ts` has `registerInterviewer`, `createQuestion`
and `createInvite` so a populated account is three calls away.

## 2. What to cover

Both audiences, because they are different products: the **interviewer** app
(dashboard, question wizard and detail, assessments, submissions, settings) and
the **candidate** flow (`/t/:token` through consent, editor, run, submit). Then
the public shells: sign-in, register, the legal pages.

At **1280x800 and 390x844**, in **light and dark**. Most of the layout and theme
defects in the 2026-09-14 audit were only visible in one of those four.

## 3. Reading what you see

- **Wait past the transitions.** `.btn` transitions for 140 ms; a screenshot
  taken inside it produced a false "invisible button in dark mode" finding that
  a computed-style probe then refuted. `await page.waitForTimeout(250)` after
  `networkidle`, and **verify any visual claim with computed styles or a
  measurement**, never with the screenshot alone.
- **Measure overflow, don't eyeball it**: `documentElement.scrollWidth -
  clientWidth`, and name the outermost element sticking out.
- **Ask what the copy promises.** A sentence saying something is recorded,
  blocked, autosaved or monitored is a claim — check `docs/CLAIMS.md` has a row
  for it and that the row cites a test. The worst finding of the last round was
  a consent screen promising fullscreen that was never entered.
- **One noun per concept** — `docs/GLOSSARY.md`. Copy drift is most visible when
  you move between adjacent screens, which is exactly what a walkthrough does and
  a unit test never will.

## 4. Reporting

Findings go in the project's audit document with the round's ID namespace, each
with the consequence, the `file::symbol` evidence and a severity. A finding you
reproduced in the browser is `RT`; one you inferred from the screenshot is
`PLAUS` until you have checked the code.

If a defect is mechanical — it could be asserted — add it to the visual gate's
matrix or its `KNOWN_VIOLATIONS` list in the same change, so the next walkthrough
does not have to find it again.
