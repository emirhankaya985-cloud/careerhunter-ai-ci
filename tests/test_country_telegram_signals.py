"""Country signals in Telegram stay conservative and never imply visa rights."""
import pytest

from careerhunter.telegram_only_report import _country_line, make_messages


def test_country_counts_are_explicit_location_hints_only():
    value = {"jobs_new": 4, "country_signals": {"US": 2, "GB": 1, "AU": 1, "TR": 0}}
    line = _country_line(value)
    assert "ABD: 2" in line and "BK: 1" in line
    assert "Türkiye: 0" in line and "uygunluk kanıtı değil" in line


def test_empty_job_digest_still_summarizes_country_hints():
    batches = make_messages({
        "status": "ready", "jobs_new": 3, "strong_count": 0,
        "quality_rejected": 3, "listed_count": 0, "items": [],
        "country_signals": {"US": 1, "GB": 1, "AU": 1, "TR": 0},
    })
    assert len(batches) == 1
    assert "ABD: 1" in batches[0][0]
    assert not batches[0][1]


@pytest.mark.parametrize("invalid", [
    {"US": -1}, {"US": 4}, {"US": "2"}, {"US": True}, [],
])
def test_rejects_impossible_or_untyped_counts(invalid):
    with pytest.raises(ValueError, match="Invalid country-signal"):
        _country_line({"jobs_new": 3, "country_signals": invalid})
