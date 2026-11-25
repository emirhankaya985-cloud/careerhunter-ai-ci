# CareerHunter AI Checkpoint

Updated: 2026-11-26 (Europe/Istanbul)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`

## Verified production state

- Neon project `careerhunter-ai-free` (`hidden-fog-42701810`), branch `br-autumn-cell-bb1fk9d1`, database `careerhunter_live` is ready and remains the active collector target.
- Latest successful Hourly Career Intelligence run after merge: [#45714135543](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45714135543), manual dispatch on main SHA `4af28e6fc8b1f8aecf9c0ea00d294da74619e8d0`.
- Neon SQL after that run: 3,118 jobs, 2 scan runs, 0 CV rows, 0 pending mail approvals, 0 Gmail receipts. Job source/id and source/URL distinct counts both equal 3,118.
- Hourly schedule remains `0 * * * *`. No natural scheduled run after the Neon cutover has yet been observed; the successful post-merge run was manual.
- Post-merge GitHub `Tests` and `Controlled E2E and Live ATS Health` checks passed; the post-merge collector run also succeeded.
- PR #77 merged as `4af28e6fc8b1f8aecf9c0ea00d294da74619e8d0`. It reports partial source failures in NTFY alerts and uses deterministic per-run ntfy sequence IDs to deduplicate retries.
- Render mail-writer environment now targets the new Neon `careerhunter_live` using the limited mail role. Environment deploy is Live at the same main commit. `/healthz`=`ok`, `/readyz`=`ready`, `/versionz`=`4af28e6fc8b1f8aecf9c0ea00d294da74619e8d0`.
- Neon role audit: `careerhunter_actions`, `careerhunter_cv_writer`, and `careerhunter_mail_sender` are non-admin login roles (no superuser, createdb, or createrole).
- `careerhunter_cv_writer` points to the new Neon and its owner-only CV vault readiness was previously confirmed. Vault still has 0 records. Two PDFs exist locally and were not modified.
- CV upload page is owner-authenticated at `/internal/owner/cv/manage`. Browser session is authenticated, but upload is blocked because the Brave extension lacks “Allow access to file URLs”. The browser policy prevents Codex from opening extension settings; do not work around it. User previously approved enabling this extension permission; they must toggle it manually.
- Gmail capability preflight [#45718928243](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45718928243) verified the send OAuth scope and `careerhunter_mail_sender` connectivity to `careerhunter_live`; `approval_table_exists=true`, `messages_sent=0`, automatic dispatch remains off.
- Telegram mail worker [#45718932859](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45718932859) succeeded after the Neon credential was corrected; SQL immediately before the run showed 0 pending approvals and 0 receipts. No email was sent.
- NTFY delivery remains disabled until the owner adds the intended `NTFY_TOPIC` GitHub Actions secret.
- PR #76 remains open and unmerged: its delete route removes archived CV history too. Do not merge until deletion preserves history or the data-loss behavior is explicitly changed and retested. PR #75 is stale checkpoint-only.
- Old Render PostgreSQL remains suspended; no old data migration was claimed or attempted.

## Matching limitations

- Rule matcher currently scores declared skills, target role, job seniority, location/eligibility, and freshness. It does not score education, candidate language, actual experience duration, or produce per-dimension breakdowns.
- The private production `CAREERHUNTER_PROFILE_JSON` value was not inspected; public sample profile must not be used as candidate truth.

## Next actions

1. Enable Brave extension “Allow access to file URLs”; then upload the existing English and Turkish PDFs and verify encrypted readback and correct language.
2. Observe the next natural hourly scan and verify its Neon writes.
3. Add `NTFY_TOPIC` only if the owner wants NTFY delivery.
4. Improve evidence-based profile dimensions and score breakdown without inferring uncertain CV fields.

See [`USER_ACTION_REQUIRED.md`](USER_ACTION_REQUIRED.md) for direct links and the required manual steps. No CV, secret, or token values are stored in this checkpoint.
