"""Alert functions have explicit Telegram acceptance checks, no network in tests."""
from careerhunter import daily_recovery_alert, site_health_alert


def test_recovery_failure_alert_needs_positive_telegram_receipt(monkeypatch):
    calls = []
    monkeypatch.setattr(daily_recovery_alert, "send",
                        lambda message, buttons: calls.append((message, buttons)) or True)
    assert daily_recovery_alert.main() == 0
    assert len(calls) == 1
    assert "Otomatik kurtarma" in calls[0][0]
    monkeypatch.setattr(daily_recovery_alert, "send",
                        lambda message, buttons: False)
    assert daily_recovery_alert.main() == 1


def test_dashboard_failure_alert_needs_positive_telegram_receipt(monkeypatch):
    calls = []
    monkeypatch.setattr(site_health_alert, "send",
                        lambda message, buttons: calls.append((message, buttons)) or True)
    assert site_health_alert.main() == 0
    assert len(calls) == 1
    assert "panel sağlık" in calls[0][0]
    monkeypatch.setattr(site_health_alert, "send",
                        lambda message, buttons: False)
    assert site_health_alert.main() == 1
