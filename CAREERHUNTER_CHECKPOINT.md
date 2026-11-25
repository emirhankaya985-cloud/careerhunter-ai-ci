# CareerHunter AI Checkpoint

Last checked: 2026-11-25 (Europe/Istanbul; Task 6.4)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`
PR: #74, branch `task-6-3`; application currently running on Render: `3759cc43cbfb8353dbfc9bca4e1e21cddcd1dea7`.

## Verified

- New Neon project `hidden-fog-42701810` (`careerhunter-ai-free`, organization `org-icy-cake-74628211`) was created 2026-11-25. Default branch: `br-autumn-cell-bb1fk9d1`; PostgreSQL 18.7. It contains only database `neondb`; table inventory is empty, and `careerhunter_live` does not exist. It is not a usable CareerHunter target yet.
- Previous project `quiet-art-74335461` and branch `br-young-sky-b9whr2a6` did not appear in Neon search or the connected organization's recoverable-project list. No export/backup is available through the Neon connector. The historical 5,454-job count has not been transferred or remeasured.
- GitHub Actions no-send Gmail preflight #45640117261 succeeded. `gmail.send` scope verified; current mail writer connects to `careerhunter_live` as `careerhunter_mail_sender`, with approval table present. Send gate false, approved recipients 0, automatic dispatch/template approval false, messages sent 0. This confirms the old connection is reachable, but not which Neon project it targets or the Gmail token's account identity.
- GitHub Actions has the user-listed OAuth and self-test secret names. Values were not read. The database URL secrets were last updated 2026-11-24, so their target cannot be inferred. `CAREERHUNTER_CV_VAULT_KEY` and `CAREERHUNTER_APPLICATION_REPLY_TO` are absent.
- Local CV files were verified on 2026-11-25: EN 715,894 bytes, SHA-256 `EAF05155147FEFAB4E6F984690917D0E2BFE5A2625BCD32D8B405F1DAD3D36C6`; TR 717,586 bytes, SHA-256 `EA34F21B18C92F876191F41C90056AD61C844CC6F82A13C94949EBD8467AC585`. Both are one-page, unencrypted PDFs with extractable text and matching language labels. They have not been uploaded.
- Hourly collector's latest observed successful scheduled run: #45548241184 (2026-11-25 04:39 UTC). Telegram approval worker: #45585129497 (2026-11-25 09:24 UTC). Both workflows are active, but no newer scheduled runs appeared in the history checked at 14:59 UTC.
- Render read-only check reported `/healthz` 200, `/readyz` 200, `/versionz` `3759cc43`. No database URLs or Render settings were changed.
- PR #74 remains open. Tests and PostgreSQL integration checks passed on `c053d66`; local full suite: 499 passed, 2 skipped; final Gmail self-test suite: 13 passed; Ruff passed. No Gmail messages or employer applications were sent.

## Task 6.3 code

- Added an owner-only manual Gmail test that fixes the recipient to a protected secret, verifies OAuth `email_verified` identity before sending, attaches only the selected vault CV, and records a one-shot `sent_self_test` receipt.
- Added least-privilege mail-receipt schema migration; the worker checks schema and does no runtime PostgreSQL DDL.
- Test workflow requires owner actor, main branch, explicit dispatch confirmation, selected language, CV key, Gmail OAuth and database secrets. Employer dispatch remains disabled.
- Task 6.4 review found the migration's unconditional grant failed if `careerhunter_mail_sender` did not exist. The branch now conditionally grants only when the role exists; rerunning after role provisioning applies the grants. This updated patch still needs CI.

## Pending

1. Lossless transfer: source project and full export are not visible in Neon connector. Existing GitHub secrets reach a database named `careerhunter_live`, but the source project identity and full table/key inventory have not been verified. Do not switch production URLs to the empty project.
2. Prepare a verified `careerhunter_live` database and least-privilege application/mail roles in the new project, then transfer and compare every table/row/key before any cutover.
3. After cutover, apply migrations and verify application read/write. The receipt migration is not applied to any production database.
4. Upload EN/TR CVs after the correct vault exists. Vault key is not in GitHub Actions; adding it would allow the gated workflow to decrypt CVs and needs explicit approval.
5. No-send preflight proves the token has `gmail.send` scope, not that GitHub's refresh token belongs to the intended sender. Owner-only test will verify identity before sending, but needs a populated vault and correct target DB.
6. `CAREERHUNTER_APPLICATION_REPLY_TO` is absent. Employer dispatch/template gates remain off and there are zero approved employer recipients.
7. Resolve Google's OAuth Testing-mode refresh token expiry compliantly (publish/verify External app, or use Internal only if eligible); do not work around the limit by repeatedly rotating tokens.
8. The last observed scheduled scan/Telegram runs are several hours old, despite workflows being active. Recheck natural schedules after database target is verified.

## Next steps

Review and merge PR #74 only after the corrected migration CI passes and schema/cutover risk is understood. Use the currently reachable source connection to perform a read-only full inventory and verified export; restore into the new project only after its `careerhunter_live` database and roles are prepared. Compare table counts, keys, and data before switching GitHub or Render URLs. Then upload the two verified CVs, confirm OAuth identity with a no-send check, run one owner-only CV test, and verify Gmail receipt plus Telegram notification. Keep employer dispatch off until recipient, template, and limits are approved.
