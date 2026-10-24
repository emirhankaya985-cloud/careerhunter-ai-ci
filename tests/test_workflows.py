from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workflows_have_manual_trigger_and_istanbul_timezone():
    daily = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
    weekly = (ROOT / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in daily and "workflow_dispatch:" in weekly
    assert daily.count("timezone: Europe/Istanbul") == 1
    assert "timezone: Europe/Istanbul" in weekly
    assert "concurrency:" in daily
    assert "DATABASE_URL: ${{ secrets.DATABASE_URL }}" in daily
    assert "NTFY_TOPIC: ${{ secrets.NTFY_TOPIC }}" in daily
    assert "contents: read" in daily
    assert "git push" not in daily


def test_no_linkedin_automation_module_exists():
    python_files = list((ROOT / "src").rglob("*.py"))
    content = "\n".join(path.read_text(encoding="utf-8") for path in python_files)
    forbidden = ["linkedin_cookie", "selenium", "playwright", "send_connection_request"]
    assert not any(term in content.lower() for term in forbidden)
