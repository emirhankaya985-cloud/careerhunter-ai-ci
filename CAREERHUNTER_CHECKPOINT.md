# CareerHunter AI Checkpoint

Last updated: 2026-11-26 (Europe/Istanbul)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`
Production main SHA: `637c83507dae3c9856f0d9c49af31e9a214fe6de`

## Verified in this continuation

- GitHub access recovered. The Actions `DATABASE_URL` secret was updated on 2026-11-25 19:41 UTC to the `careerhunter_actions` role on the new Neon target. Its value was not printed.
- Manual Hourly Career Intelligence run [#45687710676](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45687710676) completed successfully at 19:44 UTC. It processed and saved 2,726 jobs. Neon SQL on project `hidden-fog-42701810`, branch `br-autumn-cell-bb1fk9d1`, database `careerhunter_live`, returned 2,726 `jobs`, 1 `runs`, and 0 CV rows. Database has unique `(source, job_id)` and `(source, job_url)` constraints.
- New Neon project is `careerhunter-ai-free`, project ID `hidden-fog-42701810`; default branch is ready. Core schema version is 4. The old Render PostgreSQL is not used for this scan.
- Render `/healthz` and `/readyz` returned `ok` and `ready`; `/versionz` returned `637c83507dae3c9856f0d9c49af31e9a214fe6de`.
- The Render `CAREERHUNTER_CRM_DATABASE_URL` value was corrected to the restricted `careerhunter_cv_writer` role on `careerhunter_live`. Render `/internal/owner/cv/status` then returned `ready`; its readiness included a valid encryption key and reachable vault. The vault still has 0 rows because PDFs have not been uploaded.
- The new database contains `careerhunter_cv_vault`; `careerhunter_cv_writer` can SELECT/INSERT the vault and cannot SELECT `jobs`.
- GitHub secret `NTFY_TOPIC` is absent; NTFY delivery is disabled until the user supplies the intended topic. No other NTFY destination was created.
- Gmail preflight #45684257217 succeeded without sending mail. No self-test or employer email was sent in this continuation.
- Created the new Neon `careerhunter_mail_sender` login role and applied idempotent Telegram approval / Gmail receipt table migrations. It has SELECT/INSERT/UPDATE only on those two tables; it cannot read `jobs` or the CV vault.
- GitHub `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` was updated to the new restricted role. Worker run [#45712865126](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45712865126) succeeded against it with an empty queue; Neon shows 0 approvals and 0 receipts. Render's matching `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` still needs user update, so the app queue and worker are not yet proven on the same database.
- No natural hourly run has occurred after the target change. Cron `0 * * * *` remains configured; the one successful new-target scan was a manual dispatch.
- NTFY is disabled: repository `NTFY_TOPIC` secret is absent.

## Local changes not yet pushed

- `src/careerhunter/notifications/ntfy.py`: identifies partial source failures in successful run alerts and adds a deterministic `X-Sequence-ID` so ntfy updates the same run notification on retry.
- `tests/test_ntfy.py`: verifies partial scan reporting and stable run sequence IDs.
- Focused checks passed: `pytest -q tests/test_ntfy.py` (4 passed), `ruff check src/careerhunter/notifications/ntfy.py tests/test_ntfy.py`.
- Full suite, commit, push, PR, and CI for these changes are still pending.

## Remaining work

1. Restore the Codex-Brave browser control; then upload the local English and Turkish PDFs and verify encrypted storage plus byte-for-byte readback without exposing contents.
2. Review `CAREERHUNTER_PROFILE_JSON` privately before treating score output as candidate-accurate. The current rule matcher scores skills, role, seniority, freshness, and location/eligibility; education, language, and actual candidate experience are not scored. Public `config/profile.yaml` is only a sample.
3. Confirm the next naturally scheduled hourly run writes to the new Neon target.
4. Update Render `CAREERHUNTER_GMAIL_SEND_DATABASE_URL` to new Neon role `careerhunter_mail_sender` so Render queue writes and Actions worker reads share the same database.
5. User must add the intended `NTFY_TOPIC` secret if NTFY reports are required.
6. Verify the owner-only Gmail self-test only after CV storage/readback is verified. Do not send employer applications without recipient, template, and automation approval.
7. PR #76 is open and has successful CI, but its change includes a CV deletion path that also deletes history; review that data-loss behavior before any merge. PR #75 is a stale checkpoint-only PR.

See [`USER_ACTION_REQUIRED.md`](USER_ACTION_REQUIRED.md) for the single remaining user setup item and direct links.
