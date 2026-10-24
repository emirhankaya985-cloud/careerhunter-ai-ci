# CareerHunter AI — Public CI

Sanitized application code and tests copied from the private AFK repository, with a clean independent Git history. No production database, private contacts, passwords or API tokens belong in this repository.

Install with `python -m pip install -e '.[dev]'`, then run `ruff check .` and `pytest -q`.

The owner-only dashboard requires secret environment variables in Render (`DASHBOARD_DATABASE_URL`, `DASHBOARD_PASSWORD`, `DASHBOARD_SESSION_SECRET`). Automated outreach is not enabled.
