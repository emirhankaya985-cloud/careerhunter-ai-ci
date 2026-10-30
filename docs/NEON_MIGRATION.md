# CareerHunter — controlled Render PostgreSQL to Neon Free transfer

This is an operator-only preparation path, not a performed production migration.
There is NO automatic trigger, NO database credential in source control, and
NO automatic production cutover.

## Verified infrastructure — 30 October 2026

- Render web: careerhunter-private-dashboard, Free, Frankfurt.
- Render PostgreSQL: careerhunter-ai-db, Free, **expires 23 November 2026**.
- Neon: careerhunter-ai-free, Free, Frankfurt. At last inspection: no app tables.
- Hosted Render connector read-only SQL is blocked by the existing IP allowlist.
  **Do not change this to public access just to run the connector.**

## Safe operator procedure

1. Create and **restore-test** a complete backup of the Render source database
   (all tables, schema, private records and sequences). Store the backup only
   in a protected location outside GitHub, workflow artifacts and chat.
2. Select a maintenance window. Pause daily scans and ensure the active scan
   has completed. Otherwise changes made after the snapshot could be lost
   during cutover.
3. Use a trusted execution environment with private network access to the
   Render source and TLS access to Neon. The existing Render application
   environment is a possible location; this repository does not itself
   provide an authenticated remote shell or execute the transfer.
4. Provide two environment secrets privately:
   - DASHBOARD_DATABASE_URL: original Render PostgreSQL connection, with
     source reading restricted to a read-only transaction.
   - NEON_DATABASE_URL: Neon PostgreSQL connection with TLS.
5. Run read-only preflight:
   python -m careerhunter.pg_transfer
6. Check source table counts, verify that Neon has no app tables, and confirm
   the independent restorable backup from step 1.
7. In a maintenance window, execute the one-time copy:
   python -m careerhunter.pg_transfer --apply --backup-confirmed
8. The copier keeps the source read-only, creates the schema in an empty
   target, copies EVERY SQLAlchemy-defined table, verifies row counts and
   order-independent record fingerprints, and advances the historical runs
   sequence. It commits only after verification.
9. Validate the new database independently: check table counts, source
   freshness and records, inspect the private dashboard and 4-country counts,
   then run a controlled new scan and Telegram notification.
10. Only after separate cutover authorization update Render's
    DASHBOARD_DATABASE_URL and related scan connection settings. Keep the
    original database untouched until all acceptance checks pass.

## Strict constraints

- The copy module deliberately cannot overwrite a target that has tables.
- It cannot read from SQLite in production; SQLite is allowed only through
  an explicit internal test function flag.
- It never prints database passwords, job descriptions or contact details.
- It never sends outreach or triggers a production scan.
- A successful migration checksum is not an independent backup or proof of
  downstream readiness.
- Do not run --apply while the collector is writing.
- GitHub Actions CI tests use disposable SQLite fixtures only.

## Acceptance

Full production status is denied until backup/restore proof, target migration,
new-DB read/write smoke, daily scan persistence, secure dashboard, Telegram
report and a rollback plan are all demonstrated with fresh run references.
