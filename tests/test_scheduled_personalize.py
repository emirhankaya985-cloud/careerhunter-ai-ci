"""Read-only CI checks for rules-only scheduled personal match refresh."""
from pathlib import Path

from careerhunter import automation_alerts

ROOT = Path(__file__).resolve().parents[1]


def test_scheduled_personalize_uses_rules_mode_and_shared_lock():
    workflow = (ROOT / ".github/workflows/personalize.yml").read_text()
    assert "cron: '50 15 * * 2,5'" in workflow
    assert "SCAN_MODE:" in workflow
    assert 'if [ "$SCAN_MODE" = "ai" ]; then' in workflow
    assert "python src/careerhunter/render_scan_client.py --rescore" in workflow
    assert "github.event_name == 'schedule'" in workflow
    assert "careerhunter-production-collector" in workflow
    assert "secrets.TELEGRAM_BOT_TOKEN" in workflow


def test_scheduled_personalize_alert_needs_positive_receipt(monkeypatch):
    calls = []
    monkeypatch.setattr(
        automation_alerts, "send",
        lambda message, buttons: calls.append((message, buttons)) or True,
    )
    assert automation_alerts.alert("personalize") is True
    assert len(calls) == 1
    assert "puanlama" in calls[0][0]
    monkeypatch.setattr(automation_alerts, "send", lambda *args: False)
    assert automation_alerts.alert("personalize") is False


def test_manual_selection_still_exists():
    workflow = (ROOT / ".github/workflows/personalize.yml").read_text()
    assert "options: [rules, ai]" in workflow
    assert "workflow_dispatch" in workflow
