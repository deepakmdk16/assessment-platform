---
version: 2026-09-08
status: DRAFT TEMPLATE — NOT LEGAL ADVICE, NOT YET REVIEWED
---

> **Template, not an executable DPA.** A data processing addendum is the document
> a customer's legal team reads most closely, and the one where a wrong clause
> creates real liability. Have it reviewed and, for EU/UK transfers, attach the
> current Standard Contractual Clauses / UK Addendum — **do not draft those from
> scratch, use the official texts**. Replace every `[BRACKETED]` value.

# Data Processing Addendum

Between **[COMPANY LEGAL NAME]** ("Processor") and the customer identified in the
Terms ("Controller"). Forms part of the [Terms of Service](TERMS.md).

## 1. Roles

The Controller determines why and how Candidate personal data is processed. The
Processor processes it only on the Controller's documented instructions — which
include the Controller's use of the platform's features — except where law
requires otherwise, in which case the Processor notifies the Controller unless
that law forbids it.

## 2. Subject matter and duration

Running coding assessments: issuing invitations, receiving submissions, executing
and grading them, recording results and, where the Controller enables it,
recording integrity signals. Processing lasts for the term of the Terms, plus any
retention window the Controller configures.

## 3. Categories of data subject and personal data

**Data subjects:** the Controller's candidates, and its Authorised Users.

**Candidate personal data:** name; email address; submitted code and autosaved
drafts; assessment results including verdict, score, written summary and
per-test-case output; timing of the sitting; and, for a monitored sitting,
integrity signals (tab switches, fullscreen exits, developer-tools use, size of
externally-pasted text). **No special-category data is requested.** No camera,
microphone, screen or keystroke content is captured. The Controller must not put
special-category data into question text or invitation fields.

## 4. Sub-processors

The Controller authorises the sub-processors below. The Processor gives
[N] days' notice of any addition, during which the Controller may object and, if
unresolved, terminate.

| Sub-processor | Purpose | Location |
|---|---|---|
| [LLM PROVIDER] | Written assessment summary and question drafting | [REGION] |
| [EMAIL PROVIDER] | Invitation and notification delivery | [REGION] |
| Stripe | Payment processing (Authorised User billing data only) | [REGION] |
| [HOSTING PROVIDER] | Application and database hosting | [REGION] |
| [ERROR REPORTING PROVIDER] | Crash and error reports, when `SENTRY_DSN` is configured (X08). Submitted code, request bodies, cookies, query strings and invite tokens are stripped before an event is sent; a report can still carry the URL path and the timing of a candidate's request. Omit this row if error reporting is not enabled. | [REGION] |

Each is engaged under written terms imposing obligations no less protective than
these. The Processor remains liable for their performance.

## 5. Security

[DESCRIBE THE ACTUAL MEASURES — this must be true, not aspirational.] Currently
implemented: bcrypt password hashing with breach-corpus checking; short-lived
access tokens with server-side revocation; per-organisation scoping of every
authenticated query; token-gated candidate links bound to their recipients;
execution of submitted code in an OS-level sandbox, run by an unprivileged worker
with no system capabilities, with egress blocked, a system-call filter, memory,
process and CPU limits, and no access to other candidates' submissions;
encrypted transport; secrets supplied by environment only.

**Known gaps at the time of writing** — disclose or fix before signing: see
[STATUS.md](../STATUS.md) for the open hardening items, in particular the
absence of monitoring and alerting.

## 6. Assistance to the Controller

The Processor provides, through the platform:

- **Erasure** — `DELETE /candidates/{email}` anonymises a candidate everywhere in
  the Controller's organisation, destroying identifiers, submitted code, drafts
  and grading detail while leaving an anonymous statistical record.
- **Retention** — a Controller-configured window after which sittings are
  anonymised automatically. **No window is applied unless the Controller sets
  one.**
- **Deletion on termination** — deleting the organisation removes every row
  belonging to it.
- **Access and portability** — CSV export of submissions and results.

The Processor assists with data protection impact assessments and with
supervisory authority enquiries, and notifies the Controller **without undue
delay and in any event within [24/48/72] hours** of becoming aware of a personal
data breach, with the information available at that time.

## 7. International transfers

[STATE THE HOSTING REGION AND THE TRANSFER MECHANISM. Attach the EU SCCs
(Commission Decision 2021/914) with modules and annexes completed, and the UK
International Data Transfer Addendum where relevant. Do not paraphrase them.]

## 8. Audit

The Processor makes available the information needed to demonstrate compliance
and allows audits by the Controller or its auditor, no more than [once a year]
except after a breach, on [N] days' notice and subject to confidentiality.

## 9. Return and deletion

On termination the Processor deletes Candidate personal data within [N] days,
except where law requires retention, and confirms deletion in writing on request.

**Annex I (parties, processing description) and Annex II (technical and
organisational measures) to be completed from sections 3 and 5 above.**
