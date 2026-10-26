"""Regressions: 5 weak newly found jobs must still reach the owner by Telegram."""
import pytest

from careerhunter import daily_new_jobs as digest


def sample(i, score):
    return {
        "title": f"Entry Role <{i}>",
        "company": f"Studio & Co {i}",
        "location": "Remote",
        "url": f"https://example.org/jobs/{i}",
        "score": score,
        "method": "rules",
        "eligibility": "needs_review",
        "level": "junior",
    }


def test_five_new_jobs_even_if_no_strong_matches():
    payload = {
        "status": "ready", "jobs_new": 5, "strong_count": 0, "threshold": 75,
        "listed_count": 5,
        "items": [sample(i, 35 + i) for i in range(5)],
    }
    message, buttons = digest.compose(payload)
    assert "5" in message
    assert "Düşük/orta eşleşme" in message
    assert "&lt;0&gt;" in message
    assert "<0>" not in message
    assert len(buttons) == 6
    assert all(button["url"].startswith("https://") for button in buttons)


def test_ineligible_job_is_explicitly_labeled():
    record = sample(1, 96)
    record["eligibility"] = "ineligible"
    payload = {"status": "ready", "jobs_new": 1, "strong_count": 0,
               "items": [record]}
    message, _ = digest.compose(payload)
    assert "Uygun değil" in message
    assert "Türkiye'den çalışma uygun değil" in message


def test_no_new_jobs_means_no_notification():
    assert digest.compose({"status": "ready", "jobs_new": 0, "items": []}) is None


def test_counter_without_detail_still_returns_report():
    message, buttons = digest.compose({"status": "ready", "jobs_new": 5, "items": []})
    assert "5" in message and "panel" in message
    assert len(buttons) == 1


def test_non_https_job_link_blocked():
    with pytest.raises(ValueError):
        digest.compose({"status": "ready", "jobs_new": 1,
                        "items": [{**sample(1, 70), "url": "http://example.com"}]})


def test_main_calls_actual_send_and_requires_ack(monkeypatch):
    data = {"status": "ready", "jobs_new": 5, "strong_count": 0,
            "items": [sample(i, 20) for i in range(5)]}
    monkeypatch.setattr(digest, "configured", lambda: True)
    monkeypatch.setattr(digest, "call", lambda path: data)
    sent = []
    monkeypatch.setattr(digest, "send", lambda *args: sent.append(args) or True)
    assert digest.main() == 0
    assert len(sent) == 1 and len(sent[0][1]) == 6
    monkeypatch.setattr(digest, "send", lambda *args: False)
    assert digest.main() == 1
