"""Verify scheduled health checks reject an old live Render release."""
from pathlib import Path


def test_scheduled_health_check_requires_exact_runtime_sha():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/site-smoke.yml").read_text(encoding="utf-8")
    assert 'get("/versionz")' in workflow
    assert 'os.environ.get("GITHUB_SHA"' in workflow
    assert 'deployed.strip().lower() != expected' in workflow
    assert 'FAIL: Render live commit differs from GitHub main' in workflow


def test_smoke_failure_retains_owner_notification_guard():
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/site-smoke.yml").read_text(encoding="utf-8")
    assert "needs: health" in workflow
    assert "needs.health.result == 'failure'" in workflow
    assert "site_health_alert" in workflow
