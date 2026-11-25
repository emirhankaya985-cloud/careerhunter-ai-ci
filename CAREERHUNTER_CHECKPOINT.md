# CareerHunter AI Checkpoint

Last checked: 2026-11-25 (Europe/Istanbul; Task 6.3 code work)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`
Branch: `main` (see GitHub for current documentation checkpoint SHA); application commit: `3759cc43cbfb8353dbfc9bca4e1e21cddcd1dea7`

## Verified
- Main contains a documentation-only checkpoint commit (`3d358aaf`); application source remains at `3759cc43`.
- Latest Render `/healthz` and `/readyz` returned HTTP 200; `/versionz` returned `3759cc43`. It is expected to differ from the documentation-only main commit; no app code changed.
- GitHub `Hourly Career Intelligence` scheduled runs #45493357820 (2026-11-24 21:39 UTC) and #45548241184 (2026-11-25 04:39 UTC) succeeded with event=`schedule`; scan workflow does not depend on Render.
- Scheduled Telegram HR email approval worker #45585129497 completed successfully. Telegram report workflow #45548646268 completed successfully.
- Existing code CI run #45380854892 succeeded on the app commit. No code changes were made in this continuation; no new tests were run for documentation-only updates.
- GitHub Actions secret names currently include `DATABASE_URL`, `CAREERHUNTER_PROFILE_JSON`, `CAREERHUNTER_GMAIL_SEND_DATABASE_URL`, Telegram token/chat ID. No Gmail send OAuth secrets (`GMAIL_SEND_CLIENT_ID`, `GMAIL_SEND_CLIENT_SECRET`, `GMAIL_SEND_REFRESH_TOKEN`) are present.
- Gmail preflight #45463259099 reported blocked: send disabled, OAuth scope unverified, zero approved contacts, no messages sent.\n- Current Gmail connector profile did not match the previously identified sender account; no worker test was sent to avoid sending a CV to the wrong mailbox. No dedicated self-recipient worker test path exists in current code.
- Files `Emirhan_Kaya_CV_EN.pdf` (715894 bytes; SHA-256 `EAF05155147FEFAB4E6F984690917D0E2BFE5A2625BCD32D8B405F1DAD3D36C6`) and `Emirhan_Kaya_CV (1).pdf` (717586 bytes; SHA-256 `EA34F21B18C92F876191F41C90056AD61C844CC6F82A13C94949EBD8467AC585`) are present in local Downloads. Do not put CVs or their contents in this public repository.
- Latest successful direct Neon read (2026-11-24): 5,454 jobs; source/job-key duplicates 0; duplicate URLs 0; CV vault 0; approvals 0; mail receipts 0; applied opportunities 0. A fresh read on 2026-11-25 failed because the current Neon connector returned `project not found`; updated database counts are therefore unverified.
- No employer applications were sent. Previous self-email #1a20ec741f4c778e was sent outside the CareerHunter worker and is not worker evidence.
- Old suspended Render Postgres recovery remains unverified; do not upgrade or delete it.

## Changes in checkpoint
- Task 6.3 added an owner-only, manual GitHub Actions Gmail self-test path. It fixes the recipient to a protected secret, verifies the OAuth identity with OpenID `email` before the Gmail send call, attaches only the selected vault CV, uses an idempotent durable receipt, and does not require enabling employer dispatch.
- Added a least-privilege mail receipt migration; the sender now checks PostgreSQL schema presence and performs no runtime DDL. The migration has not been applied to production because the original Neon project is not visible to the connected Neon account.
- Added mock coverage for successful owner-only send, verified identity mismatch, deduplication, independent self-test gate, and PDF/language validation.
- Verification: full `pytest -q` (499 passed, 2 skipped); Ruff on changed Python files passed. One initial regression command used a nonexistent test filename and was rerun with the repository's actual filenames.
- No production database, GitHub secrets, Gmail messages, CV data, or Render configuration were changed. Changes are local on branch `task-6-3`; PR/CI status pending.

## Pending / action required
1. Neon connector currently exposes a newly created Free organization (`Emirhan`), but searches for the original `careerhunter-ai-free` project and known project ID `quiet-art-74335461` returned no results. Reconnect/select the original Neon account/project; do not create a replacement. Fresh counts remain unverified.
2. Owner must sign in to the CareerHunter panel and upload EN and TR PDFs through the owner-only form. Latest verified vault count remains 0; browser authentication and CSRF must not be bypassed.
3. Confirm intended Gmail sender. The connected Gmail profile did not match the prior sender identity. Complete OAuth through Google's official flow with `gmail.send` and `openid email`; securely configure `GMAIL_SEND_CLIENT_ID`, `GMAIL_SEND_CLIENT_SECRET`, `GMAIL_SEND_REFRESH_TOKEN`, `CAREERHUNTER_GMAIL_SELF_TEST_ACCOUNT`, and `CAREERHUNTER_GMAIL_SELF_TEST_ENABLED` in GitHub Secrets. Do not paste secrets in chat.
4. Before the self-test can run, owner must upload both CVs and explicitly decide whether to expose `CAREERHUNTER_CV_VAULT_KEY` to this narrowly gated GitHub Actions workflow. That expands the workflow's ability to decrypt stored CVs; no secret was copied or added.
5. Apply `migrations/20261125_gmail_mail_receipts.sql` as the authorized Neon schema owner after reconnecting to the correct project. The worker intentionally fails closed until the table/columns exist.
6. There are zero approved employer contacts and no enabled template/automation approval. Keep employer dispatch off until these are explicitly established. No job applications or Gmail messages were sent.
7. Open PR and CI status pending; Render still runs application commit `3759cc43` until an authorized deployment occurs.

## Next continuation
Create PR for branch `task-6-3` and verify CI. Restore Neon connector access to the original project, inspect the production receipt schema, then apply the idempotent migration with the schema owner. Owner signs into the panel and uploads both PDFs. Confirm the intended Gmail sender and OAuth grant; decide whether the CV key may be stored as a GitHub secret for this workflow. Only then manually run the owner-only test and verify message ID, Neon receipt, attachment and Telegram notification. Keep employer sending disabled until its separate policy/recipient authorization is complete.


