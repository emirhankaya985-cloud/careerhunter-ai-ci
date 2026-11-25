# CareerHunter AI Checkpoint

Updated: 2026-11-26 (Europe/Istanbul)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`

## Verified production state

- Neon project `careerhunter-ai-free` (`hidden-fog-42701810`), branch `br-autumn-cell-bb1fk9d1`, database `careerhunter_live` is ready and remains the active collector target.
- Latest successful Hourly Career Intelligence run after merge: [#45714135543](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45714135543), manual dispatch on main SHA `4af28e6fc8b1f8aecf9c0ea00d294da74619e8d0`.
- Latest successful manual production scan: [#45722381870](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45722381870), completed in 2m32s on `main`; required PostgreSQL and private profile checks passed.
- Neon SQL after that run: 3,360 jobs, 56 jobs scored 60+, and 3,360 distinct `(source, job_id)` keys. The prior pre-run count was 3,118; the new scan completed without a database or profile configuration error.
- Hourly schedule remains `0 * * * *`. No natural scheduled run after the Neon cutover has yet been observed; the successful post-merge run was manual.
- Post-merge GitHub `Tests` and `Controlled E2E and Live ATS Health` checks passed; the post-merge collector run also succeeded.
- PR #77 merged as `4af28e6fc8b1f8aecf9c0ea00d294da74619e8d0`. It reports partial source failures in NTFY alerts and uses deterministic per-run ntfy sequence IDs to deduplicate retries.
- Render mail-writer environment now targets the new Neon `careerhunter_live` using the limited mail role. Environment deploy is Live at the same main commit. `/healthz`=`ok`, `/readyz`=`ready`, `/versionz`=`4af28e6fc8b1f8aecf9c0ea00d294da74619e8d0`.
- Neon role audit: `careerhunter_actions`, `careerhunter_cv_writer`, and `careerhunter_mail_sender` are non-admin login roles (no superuser, createdb, or createrole).
- CV upload is canceled by the owner. Do not ask for upload, request browser file permissions, or block automation on the vault. Both PDFs remain local and were not uploaded or modified.
- The GitHub Actions secret `CAREERHUNTER_PROFILE_JSON` was updated privately from skills and experience explicitly stated in the supplied CVs. It contains no contact details or PDF content. `daily.yml` and `personalize.yml` consume it; the successful run above confirms the production collector accepted the profile. Matching remains rule-based and does not require the CV vault.
- Gmail capability preflight [#45718928243](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45718928243) verified the send OAuth scope and `careerhunter_mail_sender` connectivity to `careerhunter_live`; `approval_table_exists=true`, `messages_sent=0`, automatic dispatch remains off.
- Telegram mail worker [#45718932859](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45718932859) succeeded after the Neon credential was corrected; SQL immediately before the run showed 0 pending approvals and 0 receipts. No email was sent.
- NTFY delivery remains disabled until the owner adds the intended `NTFY_TOPIC` GitHub Actions secret.
- PR #76 remains open and unmerged: its delete route removes archived CV history too. Do not merge until deletion preserves history or the data-loss behavior is explicitly changed and retested. PR #75 is stale checkpoint-only.
- Old Render PostgreSQL remains suspended; no old data migration was claimed or attempted.

## Matching limitations

- Rule matcher currently scores declared skills, target role, job seniority, location/eligibility, and freshness. It does not score education, candidate language, actual experience duration, or produce per-dimension breakdowns.
- The private production profile is intentionally not printed, committed, or logged. Do not replace it with the public sample profile.
- User screenshot showed `Invalid request origin` on a panel request. Origin/CSRF protections were not weakened. The exact route was not readable from the screenshot; because CV upload was canceled, no upload retry was made.
- Owner explicitly approved CV-less automatic email outreach using localized messages. PRs #79 and #80 are merged; full suite passed (501 passed, 2 skipped), with CI test, verify, and PostgreSQL integration checks green. Türkiye → Turkish; United States/UK/Australia → English; Germany → German. Unknown/ambiguous languages are skipped; instructions requiring a CV are excluded. 60+ score, verified eligibility, explicit ATS email-application evidence, idempotency, daily 5, and one-per-company/day limits remain enforced.
- GitHub Actions send/automatic/template gates are enabled for template v2. Gmail capability preflight [#45725040098](https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/actions/runs/45725040098) completed without sending; the database had 0 verified application email contacts at that check, so no employer messages were sent. The next collector run will send only if it finds eligible contacts.

## Next actions

1. Observe the next natural hourly scan and verify its Neon writes.
2. Observe whether the next collector run finds an eligible email-application address; no message is sent without that listing evidence.
3. Add `NTFY_TOPIC` only if the owner wants NTFY delivery.
4. Improve evidence-based profile dimensions and score breakdown without inferring uncertain CV fields.

See [`USER_ACTION_REQUIRED.md`](USER_ACTION_REQUIRED.md) for direct links and the required manual steps. No CV, secret, or token values are stored in this checkpoint.
