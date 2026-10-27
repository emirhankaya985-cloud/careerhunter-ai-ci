"""No production access required: migration safety with isolated SQLite databases."""
import pytest
from sqlalchemy import create_engine, func, inspect, select

from careerhunter.database import DatabaseRepository, jobs, runs
from careerhunter.migrate_postgres import MigrationError, transfer
from careerhunter.models import Job, RunStats, utc_now


def _job():
    return Job(
        job_id="migration-check", source="greenhouse", company="Example",
        title="Backend", job_url="https://example.com/jobs/migration-check",
        source_url="https://example.com/jobs",
    )


def test_migrates_every_table_without_deleting_source(tmp_path):
    source = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    destination = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    repository = DatabaseRepository(str(source.url), engine=source)
    repository.upsert_jobs([_job()])
    repository.record_run(RunStats(slot="jobs", started_at=utc_now(), status="success"))
    preflight = transfer(source, destination)
    assert preflight["jobs"] == 1
    assert "jobs" not in set(inspect(destination).get_table_names())
    counts = transfer(source, destination, apply=True)
    assert counts["jobs"] == 1 and counts["runs"] == 1
    with destination.connect() as connection:
        assert connection.execute(select(func.count()).select_from(jobs)).scalar_one() == 1
        assert connection.execute(select(func.count()).select_from(runs)).scalar_one() == 1
    with source.connect() as connection:
        assert connection.execute(select(func.count()).select_from(jobs)).scalar_one() == 1
    with pytest.raises(MigrationError, match="Target contains records"):
        transfer(source, destination, apply=True)


def test_refuses_same_database(tmp_path):
    source = create_engine(f"sqlite:///{tmp_path / 'same.db'}")
    with pytest.raises(MigrationError, match="same database"):
        transfer(source, source, apply=True)


def test_refuses_nonempty_destination(tmp_path):
    source = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    destination = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    DatabaseRepository(str(source.url), engine=source)
    DatabaseRepository(str(destination.url), engine=destination).upsert_jobs([_job()])
    with pytest.raises(MigrationError, match="Target contains records"):
        transfer(source, destination, apply=True)
