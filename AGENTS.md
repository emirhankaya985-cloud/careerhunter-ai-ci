# CareerHunter AI — Agent operating rules

These instructions apply to every source file, workflow, and document in this repository.

## Architecture: cloud-only, no personal computer dependency

- **Required production chain:** GitHub Actions (scheduler and signed workflow identity) -> Render (Python application, owner dashboard, collectors) -> Neon (durable PostgreSQL after an accepted cutover) -> Telegram (private reports and failure alerts).
- The owner's Windows PC, local scripts, home network, public IP, fixed IP, and continuous device uptime must **never** be a requirement for routine operation, deployment, database backups, recovery, or monitoring.
- Prefer GitHub OIDC -> protected Render API for operational actions. Production database passwords and private application data belong in Render secrets; never pass them through public GitHub Actions logs, public artifacts, prompts, code, or Telegram.
- Maintain the **0 TL policy**: no paid plan, paid database, API billing, or upgrade without an explicit cost warning and owner approval. Free-tier limits and expiration dates must be disclosed. Do not silently rely on free compute being continuously available.

## Render -> Neon migration and temporary network access

1. Confirm that the reviewed GitHub `main` release is **actually live** on Render (inspect deployed commit and live acceptance); GitHub CI success alone is not deployment proof.
2. Make a **source-read-only, transactionally verified cloud backup** of all CareerHunter data from Render's private PostgreSQL connection to a previously empty dedicated Neon database. Verify all table counts and cryptographic row digests. Never upload private DB credentials or records into GitHub.
3. Check Neon table inventory, record counts, backup workflow logs, and a genuinely independent recovery/restore test before claiming the backup is disaster-recovery ready. A Neon branch is a useful copy but, without a restore test, not proof of tested recoverability.
4. **Do not cut over production** while Render remains the only authoritative writer unless a maintenance window, final data reconciliation, authenticated dashboard test, fresh collector write/read test, and Telegram test are confirmed. Preserve the original Render source until rollback and retention are verified.
5. Remove any temporary personal-PC /32 access allowance from the Render PostgreSQL **database-specific inbound IP rules** once all cloud operations have been verified and it is no longer used. Do not mistake the service's general Inbound IP Restrictions for database ingress. Never use `0.0.0.0/0` for database ingress. Do not include any personal IP in public repository files.
6. Treat source deletion, untested database cutover, disabling an operational collector, broadening inbound network access, and changing external message sending as high-risk actions requiring explicit approval.

## Operational acceptance and observability

- Keep the daily collector, recovery guard, four-country ATS health checks, scoring, and Telegram reporting cloud-native, scoped to the intended repository and main branch.
- Protect privileged Render routes with validated signed GitHub OIDC claims (exact repository ID, workflow reference, branch and allowed event). Do not create anonymous, unauthenticated database or backup endpoints.
- Never claim **fully autonomous / 100% production** without separately verified CI tests, exact live deployed commit, PostgreSQL integrity, a successful scheduled collection, Telegram acceptance, backup recovery, and failure-handling evidence.
- Status reports should distinguish: code merged, CI green, Render live, Neon copy verified, restored backup tested, production cutover completed, and independently monitored. Unknown is not success.
- Do not automatically submit applications, send recruitment emails, fabricate resume claims, or change Gmail/LinkedIn data without explicitly authorized and tested workflows.
- Maintain confidentiality of personal profiles, employer contacts, CVs, private notes and authentication secrets. Logs and dashboard responses should be data-minimal.

## References

- `docs/RENDER_NEON_CLOUD_ONLY.md` — cloud-only source-preserving copy workflow.
- `docs/RENDER_DEPLOY_ACCEPTANCE.md` — release identity and live-acceptance proof.
- `.github/workflows/neon-cloud-backup.yml` — explicit one-time backup workflow.
- `src/careerhunter/cloud_backup.py` — signed Render-only backup API.
- `src/careerhunter/pg_transfer.py` — default read-only transfer and verified copy.
