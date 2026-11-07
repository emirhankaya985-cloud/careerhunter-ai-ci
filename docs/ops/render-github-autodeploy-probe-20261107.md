# Render GitHub auto-deploy acceptance probe — 2026-11-07

This file is a no-runtime-change, one-time test of Render's On Commit connection
for the existing free CareerHunter dashboard.

- Before test, GitHub main and Render both pointed at
  `e55b68b71fce583feb70e9f6b07e1459445da2ab`.
- Render service: `srv-dbe3l1l9fdbs73975hog`, workspace
  `tea-dbbg02e7bikc738eg9vg`, linked branch `main`.
- Service metadata reports `autoDeploy=yes` and `autoDeployTrigger=commit`.
- Existing latest live deploy was `dep-dbnkaejl550s73ff55tg` and
  its trigger was `api`, not a Git provider auto-deploy.
- The acceptance condition is a *new* Render deployment with
  `trigger=auto_deploy` (or a provider-origin equivalent) and the exact
  GitHub squash merge SHA, followed by `status=live`.
- A passing GitHub Actions run, a manual/API deployment, or an accessible old
  `/healthz` endpoint does **not** satisfy this acceptance criterion.
- This document intentionally changes no application source, dependency,
  database schema, OAuth secret, or scheduled task.
- If no auto-deploy is observed, verify the Render GitHub App installation
  repository access and this service's Git Credentials in Render Settings.
  No production database or credential must be changed for this test.

**Result:** Not recorded in this source file. The authoritative result must
come from the Render Deploys/Events API and match the new merge SHA.
