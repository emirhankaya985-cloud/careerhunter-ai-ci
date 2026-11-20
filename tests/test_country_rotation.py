from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from careerhunter.country_rotation import (
    COUNTRIES, DISCOVERY_BOARDS, country_batch, discovery_companies,
    location_countries, rotation_report,
)


def test_every_country_covered_from_any_hour_within_eleven_runs():
    start = datetime(2026, 11, 20, tzinfo=timezone.utc)
    for offset in range(33):
        batches = [country_batch(start + timedelta(hours=offset+i)) for i in range(11)]
        assert all(len(set(batch)) == 6 and batch[:3] == ('US', 'DE', 'GB') for batch in batches)
        assert set().union(*map(set, batches)) == set(COUNTRIES)


def test_timezone_invariant_and_rejects_ambiguous_time():
    at = datetime(2026, 11, 20, 23, tzinfo=timezone.utc)
    assert country_batch(at) == country_batch(at.astimezone(timezone(timedelta(hours=3))))
    with pytest.raises(ValueError):
        country_batch(at.replace(tzinfo=None))


def test_all_verified_boards_revisited_with_bounded_budget():
    at = datetime(2026, 11, 20, tzinfo=timezone.utc)
    boards = [discovery_companies(at + timedelta(hours=i)) for i in range(4)]
    assert all(len(batch) == 2 for batch in boards)
    assert {c['greenhouse'] for batch in boards for c in batch} == {
        slug for _, slug in DISCOVERY_BOARDS}


def test_no_invented_country_evidence():
    assert location_countries('Remote - EMEA') == set()
    assert location_countries('London, United Kingdom') == {'GB'}
    assert location_countries('Berlin, Germany') == {'DE'}
    assert location_countries('Australia') == {'AU'}
    assert location_countries('Business Development') == set()


def test_report_distinguishes_inventory_from_personal_fit():
    at = datetime(2026, 11, 20, tzinfo=timezone.utc)
    jobs = [SimpleNamespace(location='Berlin', match_score=90, experience_level='senior'),
            SimpleNamespace(location='Berlin', match_score=75, experience_level='junior')]
    assert '| Germany | 2 | 1 |' in rotation_report(jobs, at)
