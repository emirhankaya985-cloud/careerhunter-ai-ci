from datetime import datetime, timezone

from careerhunter.models import Job
from careerhunter.reporting.countries import aggregate_country_report, classify_job_countries, render_country_report


def job(job_id, location, description="Remote - US; visa sponsorship available", score=80):
    return Job(job_id=job_id, source="greenhouse", company="Acme", title="Data Engineer",
               location=location, description=description, job_url=f"https://jobs.example/{job_id}",
               source_url="https://boards.greenhouse.io/acme", match_score=score,
               first_seen_at=datetime.now(timezone.utc), last_verified_at=datetime.now(timezone.utc))


def test_four_country_report_counts_and_deduplicates():
    report = aggregate_country_report([job("1", "Remote - US")], source_results={
        "United States": {"attempted": 2, "successful": 1, "new_jobs": 1},
        "Australia": {"attempted": 1, "successful": 0, "errors": ["timeout"]},
    })
    assert report["unique_jobs"] == 1
    assert report["countries"]["United States"]["active_jobs"] == 1
    assert report["countries"]["Australia"]["active_jobs"] == 0
    assert report["countries"]["Australia"]["source_errors"] == ["timeout"]
    assert "United Kingdom" in report["countries"]


def test_country_report_is_human_readable():
    text = render_country_report(aggregate_country_report([job("1", "Remote - US")]))
    assert "Dört ülke günlük özeti" in text
    assert "United States" in text
    assert "Acme" in text


def test_worldwide_remote_is_unknown_not_every_country():
    row = job("global", "Remote - Worldwide", "Work from anywhere globally")
    assert classify_job_countries(row) == set()
    report = aggregate_country_report([row])
    assert report["unknown_jobs"] == 1
    assert all(v["active_jobs"] == 0 for v in report["countries"].values())


def test_explicit_multi_country_scope_is_counted_in_each_country():
    row = job("multi", "Remote - US / UK", "Open to applicants in the US and United Kingdom")
    assert classify_job_countries(row) == {"United States", "United Kingdom"}
    report = aggregate_country_report([row])
    assert report["countries"]["United States"]["active_jobs"] == 1
    assert report["countries"]["United Kingdom"]["active_jobs"] == 1
    assert report["unique_jobs"] == 1


def test_negative_restriction_does_not_turn_location_into_unknown():
    row = job("us-only", "New York, NY", "US only; no sponsorship")
    assert classify_job_countries(row) == {"United States"}
    report = aggregate_country_report([row])
    assert report["countries"]["United States"]["active_jobs"] == 1
    assert report["countries"]["United States"]["profile_fit_jobs"] == 1
