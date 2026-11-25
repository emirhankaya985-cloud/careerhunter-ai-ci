# CareerHunter AI Checkpoint

Last checked: 2026-11-25 (Europe/Istanbul)
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
- Added/updated this file only. No production data or secrets were changed.

## Pending / action required
1. Owner must sign in to the CareerHunter panel and upload EN and TR PDFs through the owner-only form. Current live vault count remains last measured at 0; browser authentication and CSRF must not be bypassed.
2. Confirm which Gmail account is the intended sender; the connected account did not match the prior sender identity. Complete Gmail send OAuth through Google's official flow and securely add the code-required `GMAIL_SEND_CLIENT_ID`, `GMAIL_SEND_CLIENT_SECRET`, and `GMAIL_SEND_REFRESH_TOKEN` values through GitHub Secrets. Do not paste secrets in chat.
3. There are zero approved employer contacts and no enabled template/automation approval. Keep employer dispatch off until these are explicitly established.
4. Worker-originated self-test email with PDF, Gmail message ID, Neon receipt, inbox confirmation, and Telegram confirmation remains unverified. Add or authorize a strictly self-recipient test path after the intended Gmail account is confirmed; do not turn on employer dispatch just to test.
5. Fresh Neon counts and table health await restored/authorized Neon connector access.
6. No real job applications have been sent.

## Next continuation
After owner login, upload both local PDFs via the existing owner form and verify encrypted readback and language selection. Configure Gmail OAuth securely; keep employer dispatch disabled until recipient and template scope are approved. Then use a dedicated self-recipient worker test and verify the message, attachment, Neon receipt, and notification. Recheck Neon data when authorized connector access is restored.


