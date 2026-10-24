from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_daily_scheduler_uses_github_oidc_instead_of_database_secrets():
    daily = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in daily
    assert "cron: '17 6 * * *'" in daily
    assert "concurrency:" in daily
    assert "id-token: write" in daily
    assert "contents: read" in daily
    assert "DATABASE_URL" not in daily
    assert "secrets." not in daily
    assert "python src/careerhunter/render_scan_client.py" in daily
    assert "git push" not in daily


def test_legacy_workflows_are_manual_only_without_collector_secrets():
    weekly = (ROOT / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
    four = (ROOT / ".github/workflows/four-country-verification.yml").read_text(
        encoding="utf-8")
    assert "workflow_dispatch:" in weekly
    assert "workflow_dispatch:" in four
    assert "schedule:" not in weekly
    assert "schedule:" not in four


def test_no_linkedin_automation_module_exists():
    python_files = list((ROOT / "src").rglob("*.py"))
    content = "\n".join(path.read_text(encoding="utf-8") for path in python_files)
    forbidden = ["linkedin_cookie", "send_connection_request",
                 "import selenium", "from selenium",
                 "import playwright", "from playwright"]
    # Mentioning Playwright as a CV skill does not mean browser automation is enabled.
    assert not any(term in content.lower() for term in forbidden)
