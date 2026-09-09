# Backups, recovery and data durability

What a customer's DPA review asks for, and what an on-call engineer needs at 3am.
Part of X03: an erasure and retention story is incomplete without saying where
else the data exists and how long it survives there.

> **Status: specification, not yet implemented.** No automated backup exists
> today — the platform runs from a single database with whatever durability the
> host provides. This file states the target so the gap is visible and costed
> rather than assumed away. **Do not quote the RPO/RTO below to a customer until
> the "Verifying" section has actually been run.**

## What has to survive

| Store | Contents | Loss means |
|---|---|---|
| Platform database (Postgres in production) | Everything: organisations, accounts, questions, invitations, submissions, results, integrity signals, usage counters | Total loss of the product's record. Unrecoverable by any other means — the agent is stateless and keeps nothing. |
| Object storage / uploads | None today | — |
| Stripe | Subscriptions and invoices | Recoverable from Stripe; it is the system of record for billing, not this platform. |
| Agent worker | Nothing durable | Nothing. It is stateless by design; a lost job is re-triggered by the reaper. |

The agent holding no state is what makes this a single-database problem.

## Targets

- **RPO (maximum data loss): 5 minutes.** Met by continuous WAL archiving /
  point-in-time recovery, not by nightly dumps — a nightly-only policy has an RPO
  of 24 hours, which for an in-progress sitting means a candidate's submitted
  work vanishing after they were told it was recorded.
- **RTO (maximum downtime): 4 hours** for restore into a working deployment.
- **Retention of backups: 30 days** of point-in-time recovery.

**Backup retention interacts with erasure and must be disclosed.** A candidate
erased today still exists in backups taken before the request, for up to the
backup retention period. That is normal and defensible under GDPR provided it is
(a) stated, (b) bounded, and (c) the erasure is re-applied if a backup is ever
restored. State it in [PRIVACY.md](PRIVACY.md) once the numbers here are real.

## Implementing

1. **Managed Postgres with PITR** ([HOSTING PROVIDER]) — the smallest correct
   answer; the provider does WAL archiving and retention. Set retention to 30
   days and confirm the plan actually includes PITR rather than daily snapshots.
2. **Encryption at rest** for backups, with keys not stored alongside them.
3. **A second, independent copy**: a weekly `pg_dump` to separate object storage
   in a different account, so a compromised or closed hosting account is not also
   the loss of every backup.
4. **Alerting** on backup failure — an unnoticed silent failure is the usual way
   backups turn out not to exist. Ties into X08 (no monitoring today).

## Restoring

1. Provision a new database; restore to the chosen timestamp.
2. Point `DATABASE_URL` at it and run `alembic upgrade head` — the restore may
   predate a migration.
3. Start the platform. The grading reaper re-triggers any submission left in
   `pending`/`running`, so grading resumes without manual intervention; results
   that arrived after the restore point are lost and their submissions re-graded.
4. **Re-apply every erasure and the retention sweep** performed since the restore
   point, or the restore silently resurrects data a person asked to have deleted.
   Until erasure requests are logged durably outside the database, this step
   depends on whatever record was kept by hand — a gap worth closing.

## Verifying

A backup that has never been restored is a hypothesis. Quarterly: restore into a
scratch environment, run `alembic upgrade head`, run the smoke suite against it,
record the wall-clock time, and compare it with the RTO above. Record the date
and result here.

| Date | Restore tested by | Time to restore | Result |
|---|---|---|---|
| _(none yet)_ | | | |
