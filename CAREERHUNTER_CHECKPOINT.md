# CareerHunter AI Checkpoint

Last checked: 2026-11-25 (Europe/Istanbul)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`
Branch/commit: `main` / `3759cc43cbfb8353dbfc9bca4e1e21cddcd1dea7`

## Verified
- GitHub `Hourly Career Intelligence` had successful scheduled runs #45493357820 (2026-11-24 21:39 UTC) and #45548241184 (2026-11-25 04:39 UTC); both event=`schedule`. Collector job and database-secret checks passed.
- Render `/healthz` and `/readyz` returned HTTP 200; `/versionz` returned the current main SHA above.
- Latest direct Neon read recorded during this session: 5,454 jobs; source/job-key duplicates 0; duplicate job URLs 0; CV vault 0; approvals 0; mail receipts 0; applied opportunities 0.
- Scheduled Telegram HR email approval workflow #45585129497 completed successfully. No application sends were observed or authorized.
- Existing CI Tests run #45380854892 succeeded on main SHA.
- Two original PDFs are present locally in Downloads and previously validated/hash-checked in session. Do not place CV files or their contents in this public repository.

## Changes in this checkpoint
- Added this status file only. No production data or secrets are included.

## Pending / action required
1. Owner must sign in to the CareerHunter panel and upload EN and TR CVs through the owner-only form. The live vault remains empty; browser authentication and CSRF must not be bypassed.
2. Gmail send OAuth secrets are absent from GitHub Actions: `GMAIL_SEND_CLIENT_ID`, `GMAIL_SEND_CLIENT_SECRET`, `GMAIL_SEND_REFRESH_TOKEN`; send/automation/template approval secrets are also not enabled. Configure via official Google OAuth and GitHub Secrets UI/secure CLI, never paste tokens into chat.
3. No approved employer contacts exist. Do not enable employer dispatch until verified recipients and template/automation approval are present.
4. Worker-originated self-test email with PDF attachment, message ID, Neon receipt, and inbox confirmation remains unverified.
5. No real job applications have been sent; no claims of completion should be made.
6. Old suspended Render Postgres recovery remains unverified; do not upgrade or delete it.

## Next continuation
After user completes panel sign-in, upload both local PDFs using the authenticated form, then verify encrypted vault readback and language selection. Separately complete Google OAuth through the official flow, store the three send credentials in GitHub Secrets, keep employer dispatch disabled until the owner approves a specific template/scope, then use a dedicated self-recipient test path and verify Gmail message/Neon receipt without contacting employers.
