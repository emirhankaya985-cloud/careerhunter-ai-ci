"""Production weekly automation reporting: pure, isolated, secret-free tests."""
from datetime import datetime, timedelta, timezone

import pytest

from careerhunter import automation_alerts, weekly_production_digest as weekly

NOW = datetime(2026, 10, 30, 19, 30, tzinfo=timezone.utc)


def run(*, days_ago=0, status="completed", conclusion="success",
        event="schedule", branch="main", id=1):
    # Use 10:00 UTC to ensure the local Turkish calendar date remains stable.
    created = (NOW.replace(hour=10, minute=0) -
               timedelta(days=days_ago)).isoformat()
    return {"created_at": created, "head_branch": branch, "event": event,
            "status": status, "conclusion": conclusion, "id": id}


def test_report_prefers_successful_recovery_and_counts_one_day_once():
    records = [
        run(days_ago=0, conclusion="failure", id=1),
        run(days_ago=0, event="workflow_dispatch", conclusion="success", id=2),
        run(days_ago=1, id=3),
        run(days_ago=2, branch="fork/feature", id=4),
    ]
    chosen, days = weekly.choose_days(records, NOW)
    assert len(chosen) == len(days) == 7
    assert chosen[-1]["id"] == 2
    assert chosen[-2]["id"] == 3
    assert chosen[-3] is None
    message = weekly.build_message(records, {
        2: "PASS: Collected 1984 job rows; 43 newly stored.",
        3: "PASS: Collected 120 job rows; 2 newly stored.",
    }, NOW)
    assert "Başarılı gün: <b>2/7</b>" in message
    assert "kaydedilen ilan toplamı: <b>45</b>" in message
    assert "İşlenen ilan satırı toplamı: <b>2104</b>" in message
    assert "Atlama: <b>5</b>" in message


def test_missing_logs_are_never_reported_as_zero_jobs():
    message = weekly.build_message([run()], {}, NOW)
    assert "DOĞRULANAMADI" in message
    assert "loglardan doğrulanamadı" in message
    assert "kaydedilen ilan toplamı" not in message


def test_failed_and_in_flight_days_are_distinct():
    message = weekly.build_message([
        run(days_ago=0, status="completed", conclusion="failure", id=1),
        run(days_ago=1, status="in_progress", conclusion=None, id=2),
    ], {}, NOW)
    assert "Başarısız: <b>1</b>" in message
    assert "Sürüyor: <b>1</b>" in message
    assert "Atlama: <b>5</b>" in message


@pytest.mark.parametrize(("value", "expected"), [
    ("PASS: Collected 1984 job rows; 43 newly stored.", (1984, 43)),
    ("new jobs maybe 17", None),
    ("PASS: Collected 10 job rows; 0 newly stored.", (10, 0)),
    ("", None),
])
def test_log_parser_requires_verified_collector_line(value, expected):
    assert weekly.counters(value) == expected


def test_weekly_rejects_untrusted_context_without_network(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "fixture-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "other/repo")
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(weekly, "_run_stats",
                        lambda *args: (_ for _ in ()).throw(
                            AssertionError("must not read API")))
    assert weekly.main() == 1


def test_weekly_send_receipt_required(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "fixture-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", weekly.REPO)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setattr(weekly, "_run_stats", lambda *args: ([run()], {
        1: "PASS: Collected 2 job rows; 1 newly stored."
    }))
    monkeypatch.setattr(weekly, "send", lambda *args: True)
    assert weekly.main() == 0
    monkeypatch.setattr(weekly, "send", lambda *args: False)
    assert weekly.main() == 1


@pytest.mark.parametrize("kind", ["weekly", "country"])
def test_failure_alerts_are_not_marked_successful_without_receipt(monkeypatch, kind):
    monkeypatch.setattr(automation_alerts, "send", lambda *args: True)
    assert automation_alerts.alert(kind)
    monkeypatch.setattr(automation_alerts, "send", lambda *args: False)
    assert not automation_alerts.alert(kind)
