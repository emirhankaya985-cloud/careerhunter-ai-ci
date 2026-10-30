# CareerHunter — Exact Live Release Proof

## Why this is required

On 31 October 2026 the Render service reported autoDeploy=yes and autoDeployTrigger=commit, but the last real live deployment was commit 0a9c0056 from 27 October. The GitHub main branch already contained later automation and v2 changes. A passing GitHub CI or /readyz endpoint **does not prove** the latest application source is running on Render.

## New release checks

- /versionz exposes only Render's documented RENDER_GIT_COMMIT (40-character hexadecimal SHA). It returns 503 'unknown' when the environment cannot prove its identity. It never returns DB credentials, tokens, CVs or contacts.
- The manual v2 Production Acceptance GitHub Actions workflow requires the exact deployed SHA to match that workflow run's GITHUB_SHA, then checks /readyz and owner/OIDC routes. It fails closed when Render is stale, so no false production acceptance.
- Existing /healthz and /readyz keep their response contracts for the daily collector and the external smoke check.

## Operator checklist (no paid plan)

1. Check https://dashboard.render.com/web/srv-dbe3l1l9fdbs73975hog and compare the latest live deployed commit with GitHub main. Inspect Render Events for missing automatic deployments.
2. Verify the Render GitHub integration has access to emirhankaya985-cloud/careerhunter-ai-ci and its main branch. If access is missing, reconnect it in Render/GitHub integrations; do not share tokens or credentials in chat.
3. Deploy the reviewed and CI-green main commit once via Render's manual deploy controls if automatic deployment does not occur. **Do not delete or switch the production PostgreSQL database as part of this repair.**
4. Before claiming v2 live, trigger CareerHunter v2 Production Acceptance (read-only) and require all checks green, including /versionz == GITHUB_SHA. Run the existing live dashboard smoke and verify next scheduled Telegram flow.
5. Keep the old database unchanged and continue backup-first Neon migration independently. The free Render PostgreSQL expires on 23 November 2026.

**Scope:** The release proof endpoint and CI check are a detection/acceptance safeguard. They do not autonomously configure Render deploy permissions or execute a forced production deployment.
