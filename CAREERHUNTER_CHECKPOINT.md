# CareerHunter AI Checkpoint

Last updated: 2026-11-25 (Europe/Istanbul; fresh Neon continuation)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`
Production code merge: PR #74, `637c83507dae3c9856f0d9c49af31e9a214fe6de`

## Current task result

- User chose to abandon old database data and start fresh on the new Neon project.
- GitHub is reported to be experiencing a service outage. Secret API attempts returned HTTP 500. Per user instruction, do not treat these as code defects, retry push/PR/CI operations, or change the current production configuration during the outage.
- No production GitHub secret, Render database URL, or Render setting was changed. The production app still points to its previous configuration.

## New Neon target prepared

- Project: `careerhunter-ai-free`, project ID `hidden-fog-42701810`, organization `org-icy-cake-74628211`.
- Branch: `br-autumn-cell-bb1fk9d1`; database: `careerhunter_live`; PostgreSQL 18.7.
- Installed the fresh core schema: 11 tables; `schema_versions` reports version 4. No legacy records were copied; jobs table is empty.
- Created `careerhunter_actions` with read/write privileges on the public schema. An insert/delete permission check on `runs` completed successfully within one transaction; no test row remains.
- This new database is not yet connected to GitHub Actions or Render. No new scan has written to it.
- CV vault, mail-approval, and Gmail-receipt supporting tables are not provisioned on this target. No new Neon connection string was saved to GitHub or Render.

## Existing verification

- PR #74 was merged as `637c83507dae3c9856f0d9c49af31e9a214fe6de`; post-merge CI #45641771212 and controlled E2E/Live ATS run #45641771278 passed.
- Latest observed scheduled scan #45641397546 processed 2,978 jobs and recorded 16 new jobs against the previous, unverified database target.
- Gmail no-send preflight #45640117261 verified `gmail.send` scope and database reachability. Sending was disabled; approved recipient count was 0; no Gmail message was sent. Employer outreach remains disabled.
- Telegram worker run #45642529228 succeeded against its then-configured target.
- Render `/healthz` and `/readyz` returned HTTP 200. `/versionz` reported `3759cc43cbfb8353dbfc9cba4e1e21cddcd1dea7`.
- Provided EN/TR PDFs were previously verified locally; neither has been uploaded. `CAREERHUNTER_CV_VAULT_KEY` and `CAREERHUNTER_APPLICATION_REPLY_TO` were absent from the GitHub secret list last inspected.

## Local quality checks (2026-11-25)

- `pytest -q`: 499 passed, 2 skipped, 24 existing Pydantic serialization warnings.
- `ruff check`: passed.
- No source code was changed in this continuation; these checks confirm the current repository baseline.

## After GitHub recovers

1. Update Actions `DATABASE_URL` to the `careerhunter_actions` connection, then dispatch one scan and confirm Neon project ID `hidden-fog-42701810`, job inserts, and run receipt.
2. Change Render's explicit Neon target and reader/writer URLs only after the Actions target is verified; deploy and check health, ready, version, and database identity.
3. Provision least-privilege dashboard, CV, and mail roles and their schemas; securely configure the CV encryption key, then upload/read back both CVs.
4. Verify Gmail OAuth identity, From, and Reply-To. Keep employer sends disabled; send only the owner test after explicit approval.
5. Confirm scheduled workflows operate against the fresh target. Do not claim that legacy records were copied.

## GitHub change state

- PR #75 (checkpoint-only) remains open from the preceding attempt. Its text predates this fresh-target setup. No further PR, push, or CI requests were made after the outage instruction.
- This checkpoint is intended to be committed locally now; do not push it until GitHub recovers.
