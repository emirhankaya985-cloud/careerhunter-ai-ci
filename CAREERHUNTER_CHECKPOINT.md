# CareerHunter AI Checkpoint

Last updated: 2026-11-25 (Europe/Istanbul; CV writer diagnosis)
Repository: `emirhankaya985-cloud/careerhunter-ai-ci`
Production code merge: PR #74, `637c83507dae3c9856f0d9c49af31e9a214fe6de`

## Current task result

- User chose to abandon old database data and start fresh on the new Neon project.
- GitHub is reported to be experiencing a service outage. Secret API attempts returned HTTP 500. Per user instruction, do not treat these as code defects or retry push/PR/CI operations during the outage.
- The user updated Render environment settings and triggered a deployment. Render now reports the service Live on `637c83507dae3c9856f0d9c49af31e9a214fe6de`.
- The GitHub Actions `DATABASE_URL` was not changed; scheduled scans are not proven to target the new Neon database. The latest secret update attempt failed before changing it. No further Render settings were changed by Codex.

## New Neon target prepared

- Project: `careerhunter-ai-free`, project ID `hidden-fog-42701810`, organization `org-icy-cake-74628211`.
- Branch: `br-autumn-cell-bb1fk9d1`; database: `careerhunter_live`; PostgreSQL 18.7.
- Installed the fresh core schema: 11 tables; `schema_versions` reports version 4. No legacy records were copied; jobs table is empty.
- Created `careerhunter_actions` with read/write privileges on the public schema. An insert/delete permission check on `runs` completed successfully within one transaction; no test row remains.
- Render `/healthz`, `/readyz`, and `/versionz` return HTTP 200/`ok`/`ready`/`637c83507dae3c9856f0d9c49af31e9a214fe6de`. The dashboard panel shows zero jobs, zero people, and no recent run; the Neon database independently shows zero jobs and zero runs. These results are consistent with the fresh target, but `/readyz` does not reveal the connected project ID.
- `CAREERHUNTER_DB_TARGET` on Render is `neon`. Render's selected `CAREERHUNTER_NEON_DATABASE_URL` points to the new US-region Neon host. `CAREERHUNTER_CRM_DATABASE_URL` points to a different EU-region Neon host, so the app's guarded CV writer rejects the mismatch.
- Created `careerhunter_cv_vault` on the new database and a separate `careerhunter_cv_writer` role. Verified it has SELECT/INSERT on the CV table and no SELECT on `jobs`. Its password/URL was not displayed or stored in logs.
- The CV page still reports “CV vault is not ready”; no CV was uploaded. The required manual repair is to set Render's `CAREERHUNTER_CRM_DATABASE_URL` to a connection URI for `careerhunter_cv_writer` on the new project. The Render CV key variable exists, but its validity was not disclosed or tested.
- GitHub Actions is not proven to use the new database. No new scan has written to it. Mail-approval and Gmail-receipt supporting tables are not provisioned on this target.

## Existing verification

- PR #74 was merged as `637c83507dae3c9856f0d9c49af31e9a214fe6de`; post-merge CI #45641771212 and controlled E2E/Live ATS run #45641771278 passed.
- Latest observed scheduled scan #45641397546 processed 2,978 jobs and recorded 16 new jobs against the previous, unverified database target.
- Gmail no-send preflight #45640117261 verified `gmail.send` scope and database reachability. Sending was disabled; approved recipient count was 0; no Gmail message was sent. Employer outreach remains disabled.
- Telegram worker run #45642529228 succeeded against its then-configured target.
- The preceding Render deployment used `3759cc43cbfb8353dbfc9cba4e1e21cddcd1dea7`; the user subsequently triggered the live deployment noted above.
- Provided EN/TR PDFs were previously verified locally; neither has been uploaded. `CAREERHUNTER_CV_VAULT_KEY` and `CAREERHUNTER_APPLICATION_REPLY_TO` were absent from the GitHub secret list last inspected.

## Local quality checks (2026-11-25)

- `pytest -q`: 499 passed, 2 skipped, 24 existing Pydantic serialization warnings.
- `ruff check`: passed.
- No source code was changed in this continuation; these checks confirm the current repository baseline.

## After GitHub recovers

1. After GitHub recovers, update Actions `DATABASE_URL` to the `careerhunter_actions` connection, then dispatch one scan and confirm Neon project ID `hidden-fog-42701810`, job inserts, and run receipt.
2. Add a safe authenticated target-identity diagnostic; `/readyz` proves readability but not project ID. Confirm Render resolves to project `hidden-fog-42701810`.
3. In Render, set `CAREERHUNTER_CRM_DATABASE_URL` to a connection URI for role `careerhunter_cv_writer` on `careerhunter_live`; redeploy and confirm the CV page is ready. Then upload/read back both CVs.
4. Verify Gmail OAuth identity, From, and Reply-To. Keep employer sends disabled; send only the owner test after explicit approval.
5. Confirm scheduled workflows operate against the fresh target. Do not claim that legacy records were copied.

## GitHub change state

- PR #75 (checkpoint-only) remains open from the preceding attempt. Its text predates this fresh-target setup. No further PR, push, or CI requests were made after the outage instruction.
- The latest checkpoint should be committed locally; do not push it until GitHub recovers.
