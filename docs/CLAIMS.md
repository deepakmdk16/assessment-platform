# Claims register — every sentence that asserts behaviour cites its test

A claim is copy that tells a user what the software *does*: "recorded",
"blocked", "autosaved", "monitored", "cannot be undone". The user believes it and
acts on it; a candidate consents to monitoring on the strength of one.

The 2026-09-14 audit found claims with nothing behind them. The worst was R2-003:
the consent screen said "Fullscreen, pasting blocked, tab switches recorded", and
`requestFullscreen` was never called — call count 0 on a live proctored sitting,
while the interviewer's panel read "Stayed in fullscreen". The tests that existed
asserted the *blocking* the hook does once out of fullscreen, which is why every
run was green.

`web/scripts/check-claims.mjs` (part of `npm run lint`) extracts user-facing
sentences containing the claim keywords and fails on one that is not in the table
below. **Adding a claim means adding a row.** A row whose Proof column says
*owed* is a claim the product currently makes and cannot back — those are work
items, listed with the session that closes them.

Keep the Claim column's text short and stable: the lint matches a sentence
against it as a substring, so quote the distinctive middle of a sentence rather
than a whole paragraph.

| Claim | Where | Proof |
|---|---|---|
| `This sitting is monitored` | IntegrityGate consent screen | `integrity.test.tsx` — "records nothing when the sitting is unmonitored" pins the negative; the positive is the rows below |
| `Fullscreen, pasting blocked,` | IntegrityGate summary line | **owed** — R2-003 → S04. Fullscreen is never entered; no test asserts `requestFullscreen` is called |
| `Pasting blocked,` | IntegrityGate summary line | `integrity.test.tsx` — "blocks text that was never copied inside the page" |
| `Pasting code from outside this page is blocked.` | IntegrityGate detail | `integrity.test.tsx` — "blocks text that was never copied inside the page", "allows text copied within the page, and records it as context" |
| `Tab switches and developer-tools use are recorded and shared with the interviewer.` | IntegrityGate detail | `integrity.test.tsx` — "records a tab switch with how long the candidate was away"; the devtools half is **owed** — S04; `integrity.test.tsx` renders a `devtools_opens` count but nothing asserts one is ever detected |
| `Paste blocked.` | IntegrityGate inline toast | `integrity.test.tsx` — "blocks text that was never copied inside the page" |
| `Your work so far is autosaved.` | IntegrityGate leave dialog | **owed** — R2-030 → S08. The multi-question flow has no local fallback and swallows the save error |
| `No consent recorded` | IntegrityPanel, interviewer side | **owed** — R2-003 → S04. Nothing asserts this state renders; `integrity.test.tsx` covers *unmonitored* but not *consent absent* |
| `integrity signals recorded during this sitting` | IntegrityPanel banner | `test_integrity.py` + `integrity.test.tsx` — "leads with the counts and lists events at offsets from the start" |
| `Integrity signals recorded during this sitting` | IntegrityPanel heading | as above |
| `signals, including` | IntegrityPanel summary | `integrity.test.tsx` — "colours the grid chip by risk level, not only by blocked pastes" |
| `recorded during this sitting` | IntegrityPanel count line | `integrity.test.tsx` — "says a clean sitting is clean" |
| `Not monitored` | IntegrityPanel / AssessmentDetail chip | `integrity.test.tsx` — "does not let an unmonitored sitting read as a clean one", "tells an unmonitored sitting apart from one with no signals, in the grid" |
| `Not monitored` | AssessmentDetailPage row | as above |
| `couldn’t be recorded when time ran out` | AssessmentFlow buzzer failure | **owed** — R2-029 → S08. There is no retry after a failed buzzer submit, so the sentence is the whole remedy |
| `Assessment already recorded` | CandidatePage dead end | `test_slice9.py` — "start blocks a candidate who already submitted" |
| `Your assessment has already been recorded for this email address.` | CandidatePage dead end | `test_slice9.py`, as above — the server's own `_ALREADY_SUBMITTED_DETAIL` |
| `Name cannot be empty.` | AccountPanel validation | `test_account_lifecycle.py` — "blank name is refused" |
