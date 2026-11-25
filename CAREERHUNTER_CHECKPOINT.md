# CareerHunter AI Checkpoint

Last checked: 2026-11-25 (Europe/Istanbul; Task 6.4 follow-up)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`

## Verified

- PR #74 merged into `main` as `637c83507dae3c9856f0d9c49af31e9a214fe6de`. The merged code adds a gated owner-only Gmail CV self-test and a durable receipt migration. Post-merge CI run #45641771212 and controlled E2E/Live ATS run #45641771278 passed. The migration conditionally grants the worker only if `careerhunter_mail_sender` already exists; otherwise it emits a notice and can be rerun after role provisioning.
- Local full suite: 499 passed, 2 skipped; Gmail-focused tests: 13 passed; Ruff passed. No message was sent by these tests.
- New Neon project `hidden-fog-42701810` (`careerhunter-ai-free`, organization `org-icy-cake-74628211`), branch `br-autumn-cell-bb1fk9d1`, was verified. An empty `careerhunter_live` database has now been created, but its table inventory is still empty. No old-project data, schema, or CVs have been copied there.
- The old source project `quiet-art-74335461` / branch `br-young-sky-b9whr2a6` is not visible in connected Neon project search/recovery. The existing `DATABASE_URL` and mail DB connection reach a database named `careerhunter_live`, but their Neon project identity and complete inventory have not been established. Historical 5,454-job data is not proven transferred.
- Latest scheduled hourly scan #45641397546 succeeded: processed 2,978 jobs and recorded 16 new jobs using the existing, not project-identified database connection. This does not prove the new Neon project is receiving scans.
- Gmail no-send preflight #45640117261 succeeded: `gmail.send` scope verified, mail database reachable as `careerhunter_mail_sender`, approval table present; send gate false, approved contacts 0, automatic dispatch/template approval false, and messages sent 0. GitHub OAuth refresh-token account identity is still unverified. No employer or self-test email was sent.
- Telegram approval worker run #45642529228 succeeded.
- Render `/healthz` and `/readyz` returned HTTP 200. `/versionz` remains `3759cc43cbfb8353dbfc9bca4e1e21cddcd1dea7`; production Render has not been verified on the merged commit.
- The provided CVs are valid, extractable one-page PDFs. EN: 715,894 bytes, SHA-256 `EAF05155147FEFAB4E6F984690917D0E2BFE5A2625BCD32D8B405F1DAD3D36C6`. TR: 717,586 bytes, SHA-256 `EA34F21B18C92F876191F41C90056AD61C844CC6F82A13C94949EBD8467AC585`. Neither has been uploaded. The new DB has no vault schema and `CAREERHUNTER_CV_VAULT_KEY` is not configured in GitHub Actions.
- `CAREERHUNTER_APPLICATION_REPLY_TO` is absent from GitHub Actions secrets. Employer outreach remains disabled with zero approved recipients.
- Google's official OAuth guidance states refresh tokens for External apps in Testing expire after seven days when non-basic scopes such as `gmail.send` are requested. Compliant durable options are publishing/verifying the External app or using an Internal app only when eligible: https://developers.google.com/identity/protocols/oauth2#expiration

## Pending / safety gates

1. Identify and gain read access to the original source Neon project (or provide a verified export). Until then, do not run the Render-only 11-table copy workflow, restore blindly, or point production at the empty new database.
2. Produce a full source inventory and backup, restore to the new Neon `careerhunter_live`, and compare every table, primary key, and row before changing GitHub/Render connection settings.
3. Provision the required application/mail roles and apply migrations only after the complete restore; verify all schema and permissions.
4. Upload the verified EN/TR PDFs only after the correct encrypted vault and key are in place. Do not print extracted CV content or add CVs/keys to source control.
5. Verify the GitHub OAuth token identity with the merged owner-only no-send identity gate; send the owner CV test only after vault setup and an explicit test-send approval. Keep employer dispatch off until recipient, template, and limits are explicitly approved.
6. Configure the intended Reply-To address after confirming the sender settings. Recheck Render version and scheduled Actions after database cutover.

## User action needed

Restore access to the original Neon source project in the connected Neon account, or provide an authorized full PostgreSQL export. Reopening the GitHub browser tab is not required; repository access remains available through the connected GitHub integration.
