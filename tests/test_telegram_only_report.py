"""Telegram-only job report: never needs an owner's dashboard password."""
import pytest

from careerhunter import telegram_only_report as report


def job(index: int, *, score: int = 44, eligibility: str = "needs_review"):
    return {
        "title": f"Python Engineer <{index}>",
        "company": "Cloud & Inc",
        "location": "Remote",
        "url": f"https://example.org/job/{index}",
        "score": score,
        "eligibility": eligibility,
        "level": "junior",
    }


def test_five_weak_jobs_go_to_telegram_not_site():
    data = {"status": "ready", "jobs_new": 5, "strong_count": 0,
            "listed_count": 5, "threshold": 75,
            "items": [job(i) for i in range(5)]}
    batches = report.make_messages(data)
    assert len(batches) == 1
    message, buttons = batches[0]
    assert "Taranan yeni ilan: <b>5</b>" in message
    assert message.count("Düşük/orta uyum") == 5
    assert "&lt;1&gt;" in message
    assert "<1>" not in message
    assert len(buttons) == 5
    assert all(x["url"].startswith("https://") for x in buttons)
    assert "dashboard" not in message.lower()
    assert "kariyer paneli" not in message.lower()


def test_all_12_are_sent_in_three_batches(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DAILY_ITEM_LIMIT", "20")
    data = {"status": "ready", "jobs_new": 12, "strong_count": 0,
            "listed_count": 12, "items": [job(i) for i in range(12)]}
    chunks = report.make_messages(data)
    assert len(chunks) == 3
    assert [len(b) for _, b in chunks] == [5, 5, 2]
    assert "12." in chunks[2][0]


def test_ineligible_high_score_is_marked_as_unsuitable():
    data = {"status": "ready", "jobs_new": 1,
            "items": [job(1, score=90, eligibility="ineligible")]}
    result = report.make_messages(data)
    assert "Uygun görünmüyor" in result[0][0]
    assert "Türkiye'den uygun değil" in result[0][0]


def test_no_jobs_still_delivers_daily_health_confirmation():
    result = report.make_messages({"status": "ready", "jobs_new": 0, "items": []})
    assert len(result) == 1
    assert "Bugün yeni ilan yok" in result[0][0]
    assert result[0][1] == []


def test_invalid_job_url_is_rejected():
    with pytest.raises(ValueError):
        report.make_messages({"status": "ready", "jobs_new": 1,
                              "items": [{**job(1), "url": "http://unsafe"}]})


def test_cannot_announce_failed_collector():
    with pytest.raises(RuntimeError):
        report.make_messages({"status": "no_successful_scan", "items": []})


def test_main_sends_all_batches_and_fails_when_telegram_declines(monkeypatch):
    data = {"status": "ready", "jobs_new": 6,
            "items": [job(i) for i in range(6)]}
    monkeypatch.setattr(report, "configured", lambda: True)
    monkeypatch.setattr(report, "call", lambda path: data)
    monkeypatch.setattr(report.time, "sleep", lambda seconds: None)
    calls = []
    monkeypatch.setattr(report, "send", lambda *args: calls.append(args) or True)
    assert report.main() == 0
    assert len(calls) == 2
    monkeypatch.setattr(report, "send", lambda *args: False)
    assert report.main() == 1


def test_default_daily_limit_prevents_message_flood(monkeypatch):
    monkeypatch.delenv("TELEGRAM_DAILY_ITEM_LIMIT", raising=False)
    data = {"status": "ready", "jobs_new": 25,
            "listed_count": 25,
            "items": [job(i, score=61) for i in range(25)]}
    batches = report.make_messages(data)
    assert len(batches) == 2
    assert sum(len(buttons) for _, buttons in batches) == 10
    assert "15 ek ilan" in batches[-1][0]
    assert "İncelenecek: <b>25</b>" in batches[0][0]


def test_priority_jobs_come_before_ambiguous_high_scores(monkeypatch):
    monkeypatch.delenv("TELEGRAM_DAILY_ITEM_LIMIT", raising=False)
    ambiguous = {**job(1, score=98), "level": "unknown",
                 "eligibility": "needs_review"}
    actionable = {**job(2, score=81), "level": "junior",
                  "eligibility": "eligible"}
    result = report.make_messages({
        "status": "ready", "jobs_new": 2, "strong_count": 2,
        "threshold": 75, "items": [ambiguous, actionable],
    })
    text, buttons = result[0]
    assert buttons[0]["url"].endswith("/2")
    assert "✅ Öncelikli eşleşme" in text
    assert "🔎 Yüksek puan; koşullar teyit edilmeli" in text
    assert "Öncelikli (junior + Türkiye kanıtı): <b>1</b>" in text
    assert text.index("Python Engineer &lt;2&gt;") < text.index("Python Engineer &lt;1&gt;")


def test_invalid_daily_limit_falls_back_and_boundaries_are_clamped(monkeypatch):
    monkeypatch.setenv("TELEGRAM_DAILY_ITEM_LIMIT", "oops")
    assert report._daily_limit() == 10
    monkeypatch.setenv("TELEGRAM_DAILY_ITEM_LIMIT", "50000")
    assert report._daily_limit() == 20
    monkeypatch.setenv("TELEGRAM_DAILY_ITEM_LIMIT", "-100")
    assert report._daily_limit() == 1


def test_rerun_never_replays_previous_daily_digest(monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setattr(report, "configured", lambda: True)
    monkeypatch.setattr(report, "call", lambda _path: pytest.fail("API should not be called"))
    monkeypatch.setattr(report, "send", lambda *_args: pytest.fail("Would duplicate notification"))
    assert report.main() == 0
