# CareerHunter AI — Automated Reports and Four-Country Source Health

## Safe production schedules (UTC; Türkiye +3)

- Daily collector: 06:17 UTC (09:17 TRT). GitHub OIDC -> protected Render collector.
- Recovery guard: 08:40 and 15:20 UTC (11:40, 18:20 TRT). At most one extra recovery.
- Four-country public ATS source check: 08:55 UTC (11:55 TRT). Country codes US, GB, AU and TR; this is a source health check, NOT verification of the private database's country counts.
- Private dashboard readiness: 07:30 UTC (10:30 TRT).
- Seven-day digest: Sundays 18:30 UTC (21:30 TRT). Uses read-only GitHub Actions API and Telegram. Counts only jobs confirmed in successful collector log messages.

## Security

The seven-day job uses scoped GitHub actions:read with only the bot/chat secrets needed for Telegram; no DATABASE_URL, no candidate CV, no personal CRM data. GitHub-signed logfile URLs are downloaded without the GitHub bearer token being forwarded to the log storage host. Alerts never include credentials or private records. The four-country source check uses public ATS endpoints; failure alerts use a separate read-only job holding Telegram secrets.

## Proof requirements

CI tests verify weekly aggregation, missing-log truthfulness, recovery deduplication and Telegram acceptance conditions. After merge check the first real scheduled 4-country workflow and the first Sunday weekly Telegram report (or perform a permitted manual workflow dispatch) before labeling them fully live-verified. GitHub cron can be delayed.

## Remaining blockers

Render Free Postgres expiry 23 Nov 2026: independent restorable backup then safe Neon cutover and a new daily collector write/read check. Existing four-country deep verification and Weekly Career Strategy workflows remain manual until migrated from old database-secret execution. CV personalization remains an owner-triggered path. Production-grade fallback if the whole GitHub scheduling service is unavailable is not provided by this code.
