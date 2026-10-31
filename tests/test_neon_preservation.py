"""Source-preservation proof distinguishes legitimate newer Neon scans from data loss."""
from sqlalchemy import create_engine, insert, update
from careerhunter.database import jobs, metadata, runs
from careerhunter.neon_reconcile import _source_preserved


def _job(i, seen="2026-10-30T10:00:00+00:00"):
    return {
        "source": "ashby", "job_id": str(i), "company": "Test",
        "title": "Python", "location": "Remote",
        "job_url": "https://example.test/" + str(i),
        "payload": "{}", "content_hash": "a"*64,
        "first_seen_at": "2026-10-29T10:00:00+00:00",
        "last_seen_at": seen, "last_verified_at": seen,
        "status": "new", "closed_at": None,
    }


def _run(i):
    return {
        "id": i, "slot": "jobs",
        "started_at": "2026-10-30T10:00:00+00:00",
        "finished_at": "2026-10-30T10:10:00+00:00",
        "jobs_processed": 1, "jobs_new": 1, "jobs_closed": 0,
        "llm_calls": 0, "llm_tokens": 0, "llm_cost_usd": 0,
        "status": "success", "error": None,
    }


def _pair():
    old = create_engine("sqlite:///:memory:")
    new = create_engine("sqlite:///:memory:")
    metadata.create_all(old)
    metadata.create_all(new)
    with old.begin() as connection:
        connection.execute(insert(jobs), [_job(1)])
        connection.execute(insert(runs), [_run(1)])
    with new.begin() as connection:
        connection.execute(insert(jobs), [_job(1, "2026-10-31T10:00:00+00:00"), _job(2)])
        connection.execute(insert(runs), [_run(1), _run(2)])
    return old, new


def test_original_jobs_and_history_survive_newer_neon_scan():
    old, new = _pair()
    try:
        with old.connect() as a, new.connect() as b:
            assert _source_preserved(a, b, {"jobs": 1, "runs": 1}, {"jobs": 2, "runs": 2})
    finally:
        old.dispose()
        new.dispose()


def test_modified_first_observation_is_not_valid_preservation():
    old, new = _pair()
    try:
        with new.begin() as b:
            b.execute(update(jobs).where(jobs.c.job_id == "1").values(
                first_seen_at="2026-10-31T10:00:00+00:00"))
        with old.connect() as a, new.connect() as b:
            assert not _source_preserved(a, b, {"jobs": 1, "runs": 1}, {"jobs": 2, "runs": 2})
    finally:
        old.dispose()
        new.dispose()


def test_historical_run_tampering_is_detected():
    old, new = _pair()
    try:
        with new.begin() as b:
            b.execute(update(runs).where(runs.c.id == 1).values(status="failed"))
        with old.connect() as a, new.connect() as b:
            assert not _source_preserved(a, b, {"jobs": 1, "runs": 1}, {"jobs": 2, "runs": 2})
    finally:
        old.dispose()
        new.dispose()
