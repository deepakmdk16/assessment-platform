# Glossary — one word per concept

The 2026-09-14 audit found fifteen naming collisions in user-facing copy
(R2-107–R2-121): four nouns for the tenant inside a single form hint, three names
for one graded sitting on adjacent screens, "Sign in" as a heading above a "Log
in" button. Individually none is a bug; together they make one product read as
several.

This file is the canonical list. `web/scripts/check-copy.mjs` (part of
`npm run lint`) enforces the mechanical half — the variants where one spelling is
simply wrong. The rest is judgment, and this is what to judge against.

**Spelling is British** (organisation, cancelled, licence as a noun), with one
deliberate exception: **code identifiers stay as they are.** `Organization`,
`useLogin` and `/auth/login` are the code's vocabulary, and renaming a model to
match prose would be churn with a migration attached. The lint only reads prose —
JSX text and quoted strings containing a space — so the two vocabularies can
differ without either being wrong.

## The nouns

| Concept | Use | Never | Why |
|---|---|---|---|
| The person taking the assessment | **candidate** | applicant, user, test-taker | One word, and "applicant" implies a job application we do not model. |
| The person setting it | **interviewer** | hiring team, recruiter, hiring manager | The candidate deals with a person, not a department. `hiring team` also promises more people than may exist. |
| The tenant | **organisation** | Organization, workspace, team, company | Four nouns appeared in one hint (R2-108). The model is `Organization`; the copy says organisation. |
| One person's one go at an assessment | **sitting** | attempt, session, run | "Attempt" reads as "a try among several" when a sitting is normally the only one. `CandidateAttempt` is the table; the copy says sitting. |
| The thing being solved | **question** | problem, task, exercise | A "Problem" column under a "Questions" heading was the collision (R2-111). |
| A named, ordered set of questions | **assessment** | test, exam, question set | "Question set" collides with the first-class **variant set**. |
| Interchangeable per-candidate questions | **variant set** | question set, set of assessments | The object is called a variant set; nothing else may be called a set. |
| The link sent to a candidate | **invite** | invitation | Pick the short one and keep it: both appeared inside single surfaces (R2-113). The *email* is an invite email. |
| Getting into an account | **sign in** / **Sign in** | log in, Log in, Login, sign-on | The backend, the emails and the H1 already say sign in; only the buttons drifted (R2-112). "Sign-in" hyphenated is the noun. |
| A one-question assessment sent quickly | **quick screen** | quick test, screen, screener | It is one flow with one name. |
| What the agent returns | **result** (verdict + score) | grade, report, mark | "Grade" survives as the verb: the agent *grades* a submission and stores a result. |

## Sentence style

- **Sentence case** for headings, buttons and labels — not Title Case.
- **API error text**: lower case, ends with a full stop
  (`"question not found."`). A client that matches on text should not have to
  handle two styles (R2-120).
- **Never render a raw enum.** `active`, `done`, `PASS`, `trialing` are wire
  values; every one needs a human label before it reaches a screen (R2-115).
- **One word per state.** done *or* complete, not both (R2-116).
