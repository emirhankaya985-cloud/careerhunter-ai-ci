# Render → Neon Free: reversible production cutover checklist

This document is not permission to delete or close the source Render PostgreSQL database.

## Immutable rollback guarantee

- Keep Render's original `DASHBOARD_DATABASE_URL` environment value unchanged.
- Stage `CAREERHUNTER_NEON_DATABASE_URL` with the dedicated `careerhunter_live` database on Neon.
- `CAREERHUNTER_DB_TARGET=render` (or absent) uses the original Render database.
- **Only** `CAREERHUNTER_DB_TARGET=neon` selects Neon for the dashboard, OIDC scan, Telegram data reads and read-only followups. Bad URL, wrong database name or wrong hostname fails closed.
- Rollback is a merge-only Render environment update `CAREERHUNTER_DB_TARGET=render`, followed by the normal redeploy and `/readyz` + smoke checks. Do not delete Neon data during rollback.
- If the dashboard uses a separate `CAREERHUNTER_CRM_DATABASE_URL` writer, that writer is **not** switched by the general selector; configure and test it separately or leave manual write disabled. Never let writes continue on the old Render database after the Neon cutover.

## Database snapshot and preflight

1. Ensure no scan, rescore, manual CRM write or scheduled collector runs during the final snapshot. The backup and daily scan share GitHub Actions concurrency group `careerhunter-production-collector` but manually initiated Render writers must still be checked.
2. The previous verified snapshot in `careerhunter` remains unchanged, with a Neon backup branch `careerhunter-first-backup-2026-10-31`.
3. Use a **distinct empty** Neon database named `careerhunter_live`. Transfer all 10 SQLAlchemy tables from Render into it via Render-hosted source read-only transaction, using `neon-cloud-backup.yml` and short-lived GitHub OIDC. Target must be entirely empty before copying; no replace/overwrite.
4. Require the workflow's source and copied counts match and every table's row digest match before commit. Query Neon independently and compare all 10 counts. A record-count comparison alone is inadequate, hence hash validation occurs in the copy transaction.
5. Take a separate Neon branch snapshot *after* the final transfer and prove read-only query from that branch. Do not claim a full disaster-recovery/restore drill unless an actual isolated restore has been tested.

## Production switch and acceptance

6. Keep the original Render DSN; stage the Neon URL and verify the existing source remains reachable. Make sure `CAREERHUNTER_NEON_CLOUD_COPY_ENABLED=false` and remove temporary `CAREERHUNTER_NEON_BACKUP_URL`.
7. Flip only `CAREERHUNTER_DB_TARGET=neon`; wait for Render's **live** deploy. A green GitHub job alone is insufficient.
8. From an independent GitHub runner, require real HTTPS `/readyz` 200 with response `ready`, `/versionz` matching the live release, private route authentication checks. Inspect the actual Neon database for recent scan writes and ensure Render counts do not change during the Neon-only scan.
9. Trigger *one* actual `daily.yml` production scan and require `jobs_processed > 0`, persisted Neon `runs` increment and the normal Telegram workflow report. Check duplicates and unknown-source failures.
10. Gmail: `gmail.readonly` in ChatGPT is **not** by itself the Render server OAuth configuration. Require an actual completed, non-skipped `gmail-review.yml` run, Render OAuth feature flag, valid refresh-token configuration and a successful aggregate Telegram notification. Do not claim it works based only on connected Gmail profile.
11. On **any** failed release, scan, Gmail or credential check: set `CAREERHUNTER_DB_TARGET=render`, redeploy, verify source `/readyz` and smoke, and keep both databases intact. The Render source must remain available until every acceptance is proven, the retention window chosen and the next planned daily scan succeeds.

## 0 TL constraints

- Neon Free has compute/storage usage limits; keep temporary backup branch without a compute endpoint after verification.
- The original Render Free PostgreSQL expires 23 November 2026. Do not delete it before cutover acceptance and a verified rollback decision.
- No CV, mailbox text, PostgreSQL URL, tokens or passwords belong in PRs, logs, GitHub Actions output or Telegram messages.
