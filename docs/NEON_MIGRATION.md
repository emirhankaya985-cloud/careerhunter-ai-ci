# CareerHunter AI — 0 TL Neon migration

**Status (2026-10-27):** A Neon Free project `quiet-art-74335461` has been created
in Frankfurt. The legacy Render PostgreSQL **is still live**: no cutover or
data migration has occurred. This document is not a claim of a completed move.

## Why

Render Free PostgreSQL expires after 30 days. A paused Supabase Free project
is not evidence that the currently running Render app uses Supabase.
Neon Free removes the 30-day Render database expiry but still has monthly
compute/storage/transfer limits and no uptime SLA. Never enable paid services.

## Preflight (do not expose credentials)

1. Confirm the correct Render workspace and identify the CareerHunter production
   database and dashboard service.
2. Confirm which source `DATABASE_URL` is actually used by the collector and which
   `DASHBOARD_DATABASE_URL` the dashboard reads. Do not guess.
3. Check all nine app tables exist in the source; list counts, confirm available
   Neon storage and running capacity. Obtain a secure, private `pg_dump` of the
   source; never commit the dump or production environment values to GitHub.
4. Pause GitHub Actions Daily Career Intelligence and ensure no current scan is
   writing to the source. Keep the dashboard read-only during cutover.
5. Supply the source and new Neon *direct* PostgreSQL URLs as
   `SOURCE_DATABASE_URL` and `TARGET_DATABASE_URL` in a trusted operator
   environment (not in source code, public Actions logs, or this document).

## Transfer and verify

Run locally or in a protected execution environment where both databases are
reachable:

```bash
python -m careerhunter.migrate_postgres
python -m careerhunter.migrate_postgres --apply
```

The preflight command is read-only. `--apply` refuses identical databases or
non-empty targets, copies all SQLAlchemy-managed application tables transactionally,
verifies row counts **and per-row digests**, and resets the `runs.id` sequence.
The source database is never written or deleted. Do not restart scans between
copy completion and cutover, because writes after the source snapshot are not
included in the transfer.

## Cut over, verify, rollback

1. Create a dedicated SELECT-only role in Neon for the dashboard. Grant SELECT on
   the nine tables only. Do not give web dashboard write permissions.
2. Update Render service environment variables securely:
   `DATABASE_URL` (collector) and `DASHBOARD_DATABASE_URL` (read-only dashboard)
   to the appropriate Neon connection strings. **Keep the existing secrets**
   (`DASHBOARD_PASSWORD`, `DASHBOARD_SESSION_SECRET`, OIDC settings) intact.
   Use pooled URLs for the runtime and a direct URL for migration.
3. Redeploy Render. Confirm `/readyz` responds 200, private dashboard login
   works, dashboard rows match snapshot, and authenticated scan works.
4. Re-enable daily GitHub Actions only after all checks pass; confirm one
   successful scan that writes to Neon and subsequent dashboard reads it.
5. Keep the Render source database untouched until the cutover is verified.
   On failure, restore previous Render URLs, redeploy, and investigate; do not
   re-run migration on non-empty Neon without an explicit reconciled recovery plan.

## Zero-cost guardrails

Neon organization must remain `Free`. Monitor usage of compute, data size,
egress and branch count. Never add payment methods, upgrade tiers, or create
paid Render instances. Neon suspends inactive compute; this is not equivalent
to deletion. Monthly quotas may still pause or restrict service.
