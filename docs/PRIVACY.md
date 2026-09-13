---
version: 2026-09-13
status: DRAFT TEMPLATE — NOT LEGAL ADVICE, NOT YET REVIEWED
---

> **This document is a template, not a reviewed privacy policy.** It was written
> from the system's actual data flows so that a lawyer has something accurate to
> work from, and it must be reviewed by one before this platform is sold to
> anyone. Every `[BRACKETED]` value must be replaced. Publishing it as-is
> misrepresents your obligations.
>
> The `version` above is stamped onto every candidate's consent record
> (`CandidateAttempt.consent_version`, via `config.PRIVACY_POLICY_VERSION`).
> **Bump both together** whenever this text changes materially — the stamp is the
> only evidence of which words a candidate actually agreed to.

# Privacy Notice

**Controller:** [COMPANY LEGAL NAME], [REGISTERED ADDRESS], [COMPANY NUMBER]
**Contact:** [PRIVACY CONTACT EMAIL] · **Data protection contact:** [DPO OR REP]
**Last updated:** [DATE]

## Who is responsible for what

This platform is used by employers ("customers") to run coding assessments.

- For **candidate** data, the customer who invited you is the **controller** —
  they decide to assess you and why. [COMPANY] is a **processor** acting on their
  instructions. The terms of that relationship are in [the DPA](DPA.md).
- For **interviewer account** data (the people who log in), [COMPANY] is the
  controller.

If you are a candidate and want your data erased, you may ask either party;
requests reaching [COMPANY] are passed to the customer who holds the record,
because only they can decide whether to keep it.

## What is collected

### From candidates

| Data | Where it comes from | Why |
|---|---|---|
| Name and email address | The invitation, and what you type on the start screen | To identify whose assessment this is and to bind the invite link to its recipients |
| Submitted code, and autosaved drafts | Your work in the editor | To assess it; drafts exist so a cleared cache or a device switch does not lose your work |
| Assessment results — verdict, score, per-test-case output | Produced by grading your code | The purpose of the assessment |
| Timing — when you started, when you submitted, whether it was late | Recorded by the server | To operate a timed assessment fairly |
| **Proctoring signals**, when the sitting is monitored: tab switches, leaving fullscreen, developer-tools use, and the size of text pasted from outside the page | Your browser, while the assessment is open | To let the interviewer see the circumstances of the sitting |

**Proctoring does not use your camera, microphone, or screen.** No video, audio,
screenshots, or keystroke content is captured. The signals are events and
durations, not recordings, and they are client-reported: they are a prompt for a
human to look more closely, never proof of anything and never an input to your
score.

### From interviewers

Name, email address, hashed password, organisation membership, and — for paying
customers — billing details. **Card details never reach this platform**; payment
is handled by Stripe on their own pages.

## Cookies and local storage

Only what the service needs in order to work. There are no analytics or
advertising cookies, and no third-party scripts on candidate pages.

| Name | Who | What it is | How long |
|---|---|---|---|
| `refresh_token` | Interviewers | An httpOnly cookie that keeps you signed in | 30 days, or until you sign out |
| `assessment-theme` | Anyone who picks a theme | Your light or dark choice, in your browser's local storage | Until you clear your browser data |
| `assessment-draft:…` | Candidates | An autosave of your unsent code for one sitting, in your browser's local storage. The key is derived from your address, not your address itself | Until you submit; cleared then |

Because nothing here is optional or used for tracking, there is no cookie
banner. That changes the day any analytics or marketing script is added — and
none may be added to candidate pages.

## Lawful basis

- **Candidates:** the customer's basis, typically their legitimate interest in
  assessing applicants, or steps taken at your request prior to a contract of
  employment. **Consent is additionally recorded for the proctoring signals**,
  because monitoring is not something you should be subject to without having
  been told and having agreed. You give it on the start screen, and it is stored
  with the version of this notice you were shown. Refusing it means the
  assessment does not start; ask the employer for an alternative.
- **Interviewers:** performance of the contract for the service, and legitimate
  interest in securing and operating it.

## Who it is shared with

- **The employer who invited you** — they see your submission, result and, for a
  monitored sitting, the integrity signals.
- **Sub-processors**, listed in [the DPA](DPA.md): the LLM provider that produces
  the written assessment summary, the email provider that delivers invitations,
  Stripe for payments, [HOSTING PROVIDER], and — where your employer has enabled
  error reporting — the provider that receives crash reports. Your code, the
  contents of your requests and your invite link are stripped from those reports
  before they are sent.
- **Nobody else.** Candidate data is never sold, never used to train models, and
  never used to advertise.

Your code is sent to a grading service to be executed and to an LLM provider to
be summarised. Both are operated under contract; neither uses the content for
their own purposes. See [the DPA](DPA.md) for the current list and locations.

## How long it is kept

Each customer sets their own retention window (their **Privacy** settings). When
one is set, sittings older than it are anonymised automatically: name, email,
submitted code, drafts, and the grading detail are destroyed, while the verdict,
score and timings survive as an anonymous record so the customer's aggregate
hiring statistics do not silently change.

**Where a customer has set no window, data is kept until they delete it or you
ask them to.** [COMPANY] does not impose a window, because doing so would delete
customers' hiring records without their instruction.

## Automated assessment

Your code is run against the question's test cases and scored automatically,
and an AI model writes a short summary of it for the interviewer. **The AI does
not decide anything about your application.** The score is deterministic and
the summary is advisory; a person at the employer reads both and makes any
decision, as Article 22 GDPR requires for decisions with legal or similarly
significant effects. To ask for a human review of your result, or to contest
it, contact the interviewer who invited you, or [PRIVACY CONTACT EMAIL]. The
same notice is shown on the start screen before you begin.

## Your rights

Access, rectification, **erasure**, restriction, objection, and portability;
where consent is the basis, the right to withdraw it. Exercising erasure destroys
your identifiers and your submitted work, and is not reversible.

Contact [PRIVACY CONTACT EMAIL], or the employer who invited you. You have the
right to complain to your supervisory authority — in the UK the ICO, in the EU
your national authority.

## Transfers, security, and changes

[DESCRIBE HOSTING REGION AND ANY INTERNATIONAL TRANSFER MECHANISM — SCCs, UK
addendum, adequacy.] Passwords are hashed with bcrypt and checked against known
breach corpora; access to a customer's data is scoped to their organisation;
transport is encrypted. [DESCRIBE BREACH NOTIFICATION COMMITMENT.]

Material changes are published here with a new version, and candidates are asked
to agree again at their next sitting.
