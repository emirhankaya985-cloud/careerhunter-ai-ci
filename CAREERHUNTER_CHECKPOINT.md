# CareerHunter AI Checkpoint

Last checked: 2026-11-26 (Europe/Istanbul; Task 6.4 follow-up)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`

## Verified

- PR #74 merged into `main` as `637c83507dae3c9856f0d9c49af31e9a214fe6de`. The merged code adds a gated owner-only Gmail CV self-test and a durable receipt migration. Post-merge CI run #45641771212 and controlled E2E/Live ATS run #45641771278 passed. The migration conditionally grants the worker only if `careerhunter_mail_sender` already exists; otherwise it emits a notice and can be rerun after role provisioning.
- Local full suite: 499 passed, 2 skipped; Gmail-focused tests: 13 passed; Ruff passed. No message was sent by these tests.
- New Neon project `hidden-fog-42701810` (`careerhunter-ai-free`, organization `org-icy-cake-74628211`), branch `br-autumn-cell-bb1fk9d1`, was verified. On 2026-11-26, read-only SQL against `careerhunter_live` verified 14 public tables, 2,726 jobs, 1 scan run, 0 CV vault rows and 0 approved mail receipt rows. The vault, approvals and receipt tables exist. This does not establish a complete migration or verify that Render and Actions use this database.
- The old source project `quiet-art-74335461` / branch `br-young-sky-b9whr2a6` is not visible in connected Neon project search/recovery. The existing `DATABASE_URL` and mail DB connection reach a database named `careerhunter_live`, but their Neon project identity and complete inventory have not been established. Historical 5,454-job data is not proven transferred.
- Previously observed scheduled hourly scan #45641397546 succeeded: processed 2,978 jobs and recorded 16 new jobs using the existing, not project-identified database connection. This does not prove the new Neon project is receiving scans.
- Gmail no-send preflight #45640117261 succeeded: `gmail.send` scope verified, mail database reachable as `careerhunter_mail_sender`, approval table present; send gate false, approved contacts 0, automatic dispatch/template approval false, and messages sent 0. GitHub OAuth refresh-token account identity is still unverified. No employer or self-test email was sent.
- Previously observed Telegram approval worker run #45642529228 succeeded.
- On the previous 2026-11-25 probe, Render `/healthz` and `/readyz` returned HTTP 200. `/versionz` was `3759cc43cbfb8353dbfc9bca4e1e21cddcd1dea7`; production Render has not been verified on the merged commit.
- The two provided CVs were previously validated; no CV content or identifying file fingerprints are needed in this public checkpoint. The new vault contains zero rows. The vault key was previously reported missing in GitHub Actions; its current configuration has not been rechecked.
- `CAREERHUNTER_APPLICATION_REPLY_TO` was previously reported absent from GitHub Actions secrets; current configuration has not been rechecked. Employer outreach remains disabled with zero approved recipients.
- Google's official OAuth guidance states refresh tokens for External apps in Testing expire after seven days when non-basic scopes such as `gmail.send` are requested. Compliant durable options are publishing/verifying the External app or using an Internal app only when eligible: https://developers.google.com/identity/protocols/oauth2#expiration

## Pending / safety gates

1. Identify and gain read access to the original source Neon project (or provide a verified export). Until then, do not run the Render-only 11-table copy workflow, restore blindly, or switch production to the new database without checking source completeness and target identity.
2. Produce a full source inventory and backup, compare with the populated new Neon `careerhunter_live`, and plan a non-destructive reconciliation of every table, primary key, and row before changing GitHub/Render connection settings. Do not overwrite the new data blindly.
3. Verify the existing schema, application/mail roles and permissions; apply any remaining migrations only after reviewing the reconciliation plan.
4. Upload the verified EN/TR PDFs only after the correct encrypted vault and key are in place. Do not print extracted CV content or add CVs/keys to source control.
5. Verify the GitHub OAuth token identity with the merged owner-only no-send identity gate; send the owner CV test only after vault setup and an explicit test-send approval. Keep employer dispatch off until recipient, template, and limits are explicitly approved.
6. Configure the intended Reply-To address after confirming the sender settings. Recheck Render version and scheduled Actions after database cutover.

## User action needed

The connected free Neon organization currently lists three projects, and the recoverable project list is empty. Restore access to the original Neon source project, or provide an authorized full PostgreSQL export, to verify the historical job inventory. Reopening the GitHub browser tab is not required; repository access remains available through the connected GitHub integration.
