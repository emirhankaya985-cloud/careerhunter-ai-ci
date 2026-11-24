# CareerHunter AI — Agent operating rules

These instructions apply to every source file, workflow, and document in this repository.

## Architecture: GitHub-operated, website optional

- **Required production chain:** GitHub Actions (scheduler, collector, scoring, reporting and notifications) -> Neon PostgreSQL (durable production data). Render hosts an optional owner dashboard/viewer only; routine operations must continue when the website is unavailable.
- The owner's Windows PC, local scripts, home network, public IP, fixed IP, and continuous device uptime must **never** be a requirement for routine operation, deployment, database backups, recovery, or monitoring.
- GitHub Actions workflows connect directly to the selected production database through Actions Secrets. Use a narrowly scoped production role where the app's upsert/schema needs allow it. Never pass database credentials or private application data through logs, public artifacts, prompts, code, or Telegram.
- The Render dashboard should use read-only database access wherever possible. It must not be a required proxy, scheduler, collector, or writer for routine production operations.
- Maintain the **0 TL policy**: no paid plan, paid database, API billing, or upgrade without an explicit cost warning and owner approval. Free-tier limits and expiration dates must be disclosed. Do not silently rely on free compute being continuously available.

## Production database and recovery

1. Keep Neon as the authoritative production database after the accepted cutover. GitHub Actions must read and write production data directly through the `DATABASE_URL` Actions secret; never fall back to local SQLite when it is absent.
2. Preserve the original Render PostgreSQL source until its retention and rollback value have been verified. Reconcile its retained records to Neon when required; never switch production based solely on a green CI run.
3. Keep backups source-read-only and transactionally verified. Verify table counts and cryptographic row digests, and perform an independent recovery/restore test before claiming disaster-recovery readiness.
4. Never broaden database ingress to `0.0.0.0/0` or include personal IP addresses in public repository files.
5. Treat source deletion, untested database cutover, broadening inbound network access, and changing external message sending as high-risk actions requiring explicit approval.

## Operational acceptance and observability

- Keep the scheduled collector, recovery guard, four-country ATS health checks, scoring, and reports in GitHub Actions, scoped to the intended repository and `main` branch.
- Do not make operational success depend on Render health, deployment status, or website availability. Report website/dashboard health separately from collector/database health.
- Never claim **fully autonomous / 100% production** without separately verified CI tests, a successful scheduled collection, PostgreSQL integrity, Telegram acceptance, backup recovery, and failure-handling evidence.
- Status reports should distinguish: code merged, CI green, scheduled collection accepted, database write/read confirmed, Telegram acceptance, backup restore tested, website live, and independently monitored. Unknown is not success.
- Do not automatically submit applications, send recruitment emails, fabricate resume claims, or change Gmail/LinkedIn data without explicitly authorized and tested workflows.
- Maintain confidentiality of personal profiles, employer contacts, CVs, private notes and authentication secrets. Logs and dashboard responses should be data-minimal.

## References

- `docs/RENDER_NEON_CLOUD_ONLY.md` — historical source-preserving Render-to-Neon copy workflow and rollback notes.
- `docs/RENDER_DEPLOY_ACCEPTANCE.md` — historical Render release acceptance notes; not a prerequisite for routine operations.
- `.github/workflows/neon-cloud-backup.yml` — explicit one-time backup workflow.
- `src/careerhunter/cloud_backup.py` — signed legacy backup API.
- `src/careerhunter/pg_transfer.py` — verified database copy and reconciliation helpers.
