# CareerHunter — Cloud-only Neon backup and migration

This implementation does NOT need the owner's PC, public Render PostgreSQL ingress, or a local backup.

## First backup (source remains online)

1. Render dashboard retains the source `DASHBOARD_DATABASE_URL`. Do not replace it yet.
2. Store the existing Neon Free project's PostgreSQL connection string as `CAREERHUNTER_NEON_BACKUP_URL` in Render **environment secrets only**; enable `CAREERHUNTER_NEON_CLOUD_COPY_ENABLED=true` only after verifying a dedicated empty Neon target. Never commit or print the URL.
3. The separate `neon-cloud-backup.yml` workflow runs only with main GitHub OIDC. It calls `/internal/cloud-backup/preflight` and `/internal/cloud-backup/start` in Render. No database credential or private record flows through GitHub.
4. Render uses its already configured source DB connection, takes a repeatable-read, SELECT-only snapshot, and inserts into the empty Neon target inside one PostgreSQL transaction. All ORM tables, payloads and row hashes are checked before commit. No source data is deleted or changed.
5. Failed or interrupted copies must NOT be called successful. If the target has any existing tables, copy is blocked instead of overwriting them. This process alone is a **first independent cloud copy**, not a completed production cutover, tested disaster recovery, or continuously synchronized replica.

## Required follow-through

- Check the actual independent Neon table counts and selected checksums with a read-only database connector, without disclosing contacts/CVs.
- Create a point-in-time Neon backup branch from the successfully copied snapshot (within Free limits), or another independently restorable encrypted backup.
- Freeze scans/writers for final synchronization, reconcile changes since the first snapshot, and verify private dashboard read/write and Telegram daily digest against Neon **before** changing `DASHBOARD_DATABASE_URL`.
- Only after all checks pass: explicitly cut over the Render application to the verified Neon connection and re-run live acceptance. Leave the original Render database intact for rollback until the backup and restoration test are verified.
- Remove the temporary Windows IP allowlist rule after cloud access is established; the cloud backup does not use it.

## Security and zero cost

- Requires exact GitHub `repository_id`, `workflow_ref`, `main`, signed OIDC and only `workflow_dispatch` or `push` events. No anonymous routes may start a copy.
- Only target hosts ending with `.neon.tech` are accepted in production, and existing Neon tables are never deleted.
- The first backup requires a new explicit opt-in environment flag; copy tool refuses all other writes by default.
- A free-tier Neon project may enforce quota limits. No upgrade or paid service is required by this code.

**Not yet verified in production:** external connectivity from Render to Neon, first live snapshot, restore test, and final migration. Never call these completed based on CI alone.
