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
| `Fullscreen, pasting blocked,` | IntegrityGate summary line | `CandidatePageIntegrity.test.tsx` — "requests fullscreen from the start click" drives the real page and the real hook and asserts the call count; "records the denial when the browser refuses" covers the other branch |
| `Pasting blocked,` | IntegrityGate summary line | `integrity.test.tsx` — "blocks text that was never copied inside the page" |
| `Pasting code from outside this page is blocked.` | IntegrityGate detail | `integrity.test.tsx` — "blocks text that was never copied inside the page", "allows text copied within the page, and records it as context" |
| `Tab switches are recorded and shared with the interviewer.` | IntegrityGate detail, and the help drawer (R2-039) | `integrity.test.tsx` — "records a tab switch with how long the candidate was away" |
| `Opening developer tools is recorded when the browser makes it visible to the page.` | IntegrityGate detail, and the help drawer | `integrity.test.tsx` — "records a gap that opens during the sitting", plus "ignores a gap that was already there" and "still sees devtools opened after the candidate closes a sidebar". The sentence is narrower than the one it replaced on purpose: S04 found the old claim covered cases the heuristic cannot see (R2-040) |
| `What is recorded` | Sitting help drawer heading | Heads the block that renders `IntegrityRules`, the same component the consent screen uses — so the rows above are its proof, and there is no second copy to drift |
| `Paste blocked.` | IntegrityGate inline toast | `integrity.test.tsx` — "blocks text that was never copied inside the page" |
| `Your work so far is autosaved.` | IntegrityGate leave dialog | **owed** — R2-030 → S08. The multi-question flow has no local fallback and swallows the save error |
| `No consent recorded` | IntegrityPanel, interviewer side | `integrity.test.tsx` — "tells a sitting with no consent record apart from a consented one", which pins both directions |
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
