# CareerHunter AI - Autonomous daily scan recovery (0 TL)

## Production schedule

- Primary scan: 06:17 UTC / 09:17 Türkiye daily. GitHub Actions Daily Career Intelligence calls Render via signed OIDC; no database credentials are available on the runner.
- Independent checks: 08:40 UTC / 11:40 Türkiye and 15:20 UTC / 18:20 Türkiye.
- If today's primary scan succeeded: no retry.
- If a scan is still running or queued: no retry.
- If any manual or recovery workflow_dispatch occurred today: no retry.
- Otherwise dispatch one additional production scan via the GitHub API.
- The existing Telegram workflow_run notifier reports success/failure for scans.
- If the recovery checker itself fails, a separate least-privilege job sends a Telegram alert; the checker cannot read Telegram secrets.

## Scope and security

The recovery job has GitHub actions:write and contents:read. The alert job receives only contents:read and Telegram secrets. The checker hardcodes the exact repository and main branch. Forks and feature branches cannot trigger production scans. Its only write action is a workflow dispatch; it cannot directly access or modify PostgreSQL.

The recovery job never performs migrations, sends unsolicited job applications or chooses a paid service.

## Limitations and release acceptance

GitHub's scheduler can be delayed or disabled on an inactive repository. The recovery job is independent from the primary GitHub workflow but not independent from GitHub's overall scheduler. Do not claim guaranteed exact execution times.

After merging, verify that Actions lists CareerHunter Daily Recovery Guard; observe a fresh scheduled check and inspect the outcome (healthy, running, already_retried, recovery_dispatched). Check that a recovery dispatch runs once at most and that Telegram reports its final outcome. Preserve a way to manually dispatch Daily Career Intelligence.

Render Free PostgreSQL still expires 23 November 2026. A verified backup, safe migration to the existing Neon Free project, a cutover acceptance test, and a rollback plan remain separate release blockers.
