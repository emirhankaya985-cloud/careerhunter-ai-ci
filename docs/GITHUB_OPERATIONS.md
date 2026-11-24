# CareerHunter operations on GitHub Actions

GitHub Actions owns scheduled and manual background operations. The Render site
is an optional private dashboard for viewing jobs and manually managing records;
scheduled collection, scoring, database summaries, reminders, Gmail checks,
NVIDIA checks, and owner-approved mail callbacks run from GitHub Actions.

## Required repository secrets

Add these in **Settings → Secrets and variables → Actions**. Keep values private;
never put them in workflow files, issues, or pull requests. `DATABASE_URL`,
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and `NTFY_TOPIC` are already used by
the existing workflows when configured.

| Secret | Used for |
| --- | --- |
| `CAREERHUNTER_PROFILE_JSON` | Private profile used to score jobs; required by the hourly scan. |
| `NVIDIA_API_KEY` | Optional NVIDIA model scoring and the manual NVIDIA smoke check. |
| `GMAIL_READONLY_CLIENT_ID` | Gmail read-only OAuth client. |
| `GMAIL_READONLY_CLIENT_SECRET` | Gmail read-only OAuth client secret. |
| `GMAIL_READONLY_REFRESH_TOKEN` | Gmail read-only refresh token. |
| `CAREERHUNTER_GMAIL_READONLY_ENABLED` | Set to `true` only when read-only Gmail review is intended. |
| `CAREERHUNTER_GMAIL_LEDGER_ENABLED` | Optional hash-only deduplication ledger in PostgreSQL. |
| `GMAIL_SEND_CLIENT_ID` | Gmail send OAuth client for owner-approved drafts. |
| `GMAIL_SEND_CLIENT_SECRET` | Gmail send OAuth client secret. |
| `GMAIL_SEND_REFRESH_TOKEN` | Gmail send refresh token. |
| `CAREERHUNTER_GMAIL_SEND_ENABLED` | Explicit gate for messages after a private owner approves the Telegram draft. |
| `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` | Optional dedicated DB URL for the one-shot send ledger; defaults to `DATABASE_URL`. |
| `CAREERHUNTER_CV_VAULT_KEY` | Encryption key used by the manual CV-vault preflight. |

Automatic outreach remains disabled unless the existing independent outreach
gates are explicitly enabled. The approval workflow does not send mail merely
because a draft exists; it requires the owner’s Telegram approval button.

## Workflow ownership

- `daily.yml`: hourly ATS scan and direct PostgreSQL writes.
- `personalize.yml`: manual direct PostgreSQL rescore/enrichment.
- `telegram-report.yml`, `followup-reminder.yml`: owner notifications read from PostgreSQL.
- `gmail-review.yml`, `gmail-acceptance.yml`, `gmail-send-preflight.yml`: bounded Gmail checks from Actions.
- `telegram-mail-approvals.yml`: five-minute Telegram queue delivery and owner callback polling.
- `nvidia-smoke.yml`, `cv-vault-preflight.yml`: manual checks from Actions.
- `site-smoke.yml` and `v2-production-acceptance.yml`: viewer/site availability checks only; they do not run collection or write production records.

The old Neon backup, Render reconciliation, and isolated restore workflows are
legacy migration/recovery utilities. They remain manually invoked and must not
be treated as routine production operations.
