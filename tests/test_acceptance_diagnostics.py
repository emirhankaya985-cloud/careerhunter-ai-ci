"""Signed acceptance workflows never echo OAuth values or modify data."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / ".github/workflows"


def test_gmail_acceptance_names_only():
    content = (ROOT / "gmail-acceptance.yml").read_text(encoding="utf-8")
    assert "GitHub Gmail read-only OAuth secrets are incomplete" in content
    assert "GMAIL_READONLY_REFRESH_TOKEN" in content
    assert "secrets.GMAIL_READONLY_REFRESH_TOKEN" in content
    assert "careerhunter.render_scan_client" not in content


def test_reconciliation_is_read_only_and_exact_legacy_source():
    content = (ROOT / "neon-reconcile.yml").read_text(encoding="utf-8")
    assert "Compare every Render and Neon row without writing" in content
    assert 'call("/internal/neon-cutover/preflight")' in content
    assert 'call("/internal/neon-cutover/state")' in content
    assert "Source was never written" in content
