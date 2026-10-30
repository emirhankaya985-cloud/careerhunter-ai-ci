# CareerHunter AI — Public CI

Sanitized source and automated tests copied from the private AFK repository with a new
Git history. No private contacts, credentials, or production exports belong in GitHub.

## Owner-only dashboard

Render: https://careerhunter-private-dashboard.onrender.com

- `/login`: owner-password-only, secure cookies
- `/readyz`: verifies PostgreSQL tables are queryable
- Website database transactions default to read-only mode.
- `DASHBOARD_PASSWORD`, `DASHBOARD_SESSION_SECRET`, `DASHBOARD_DATABASE_URL`
  must be defined as Render environment variables and **never committed**.

## Daily job collection

GitHub Actions [Daily Career Intelligence](.github/workflows/daily.yml) runs each day
at **09:17 Europe/Istanbul** (`06:17 UTC`), or through a manual workflow dispatch.

- The GitHub runner asks GitHub for a *short-lived signed OIDC identity token*.
- Render verifies the GitHub signing key, exact repository ID, workflow ref,
  main branch, event type, issuer, expiry, and custom audience.
- Render (not GitHub) fetches jobs from configured, publicly available company ATS
  feeds and persists snapshots to PostgreSQL. No automated job applications or
  outreach are sent.
- The Render environment variable `CAREERHUNTER_OIDC_COLLECTOR=true` enables
  the secured scan endpoint.
- The collector uses the database connection already configured privately in
  Render; if the DB user has no write permission the scan fails transparently.
- CI treats no new jobs as fine *only if listings were actually processed*;
  empty collection and source failures don't count as successful daily scans.
- Legacy weekly and four-country verification workflows remain manual-only
  until their separate CI secrets are configured; they do not silently fall
  back to ephemeral SQLite.

## Tests

```bash
python -m pip install -e '.[dev]'
ruff check .
pytest -q
```

## Remaining configuration and limits

The example `config/profile.yaml` is **not** a user's private career profile.
Customize it privately to obtain meaningful personal match scores. The free Render
Postgres instance created October 24, 2026 expires November 23, 2026; migrate or
upgrade the database before then to retain persistent data. Free Render services
may sleep when idle and restart on demand.


## CareerHunter v2 (in-progress, not deployed)

This branch adds a **local-only owner workflow** on top of the existing ATS
collector, matching engine, Telegram digest, and private dashboard:

- Successful configured ATS fetch marks the job `ATS_LISTED` (one source, no
  independent employer-site verification). Optional rechecks distinguish
  source outages from absent listings.
- `python -m careerhunter.v2_workflow --db <EXISTING_LOCAL_SQLITE> verify ...`
  persists conservative source evidence without falsely closing jobs.
- `... cv ...` drafts a job-specific factual Markdown CV using a PRIVATE
  JSON profile and writes it outside this public repository.
- `... track --status applied --confirm-manual-event` only records a
  manually completed application, stores the CV fingerprint and creates a
  single seven-day follow-up; it NEVER sends an application or message.
- The private read-only dashboard gains a job verification label and an
  applications/follow-ups page after the corresponding code is deployed.

Runbook: [V2 owner operations](docs/V2_OPERATOR_RUNBOOK.md).

**Not production-complete:** Gmail read integration, LinkedIn browser work,
application submission, DOCX/PDF exports, independently verified employer
career-site corroboration, and live persistent CRM writes are NOT implemented
by this branch. Production requires an explicitly approved merge/deployment
plus the expiring free-Postgres migration review. Existing scan schedule is
unchanged.
