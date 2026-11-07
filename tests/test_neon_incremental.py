"""No external connections: incremental source preservation on SQLite fixtures."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select, update

from careerhunter.database import jobs, metadata, runs
from careerhunter.neon_incremental import synchronize


def url(path: Path) -> str:
    return "sqlite:///" + str(path)


def seed(database: str, *, old: bool):
    engine = create_engine(database)
    metadata.create_all(engine)
    baseline = {
        "source": "ashby", "job_id": "j1", "company": "Example",
        "title": "Junior Python", "location": "Türkiye",
        "job_url": "https://jobs.example.org/j1",
        "payload": "{}" if old else '{"score": 80}',
        "content_hash": "a" * 64 if old else "b" * 64,
        "first_seen_at": "2026-10-30T01:00:00+00:00",
        "last_seen_at": "2026-10-30T02:00:00+00:00" if old else "2026-11-07T03:00:00+00:00",
        "last_verified_at": "2026-10-30T02:00:00+00:00" if old else "2026-11-07T03:00:00+00:00",
        "status": "seen",
    }
    with engine.begin() as connection:
        connection.execute(insert(jobs).values(**baseline))
        connection.execute(insert(runs).values(
            id=1, slot="jobs", started_at="2026-10-30T01:00:00+00:00",
            finished_at="2026-10-30T01:02:00+00:00", status="success",
            jobs_processed=1, jobs_new=1))
        if not old:
            connection.execute(insert(jobs).values(**{
                **baseline, "job_id": "j2", "job_url": "https://jobs.example.org/j2",
                "first_seen_at": "2026-11-07T01:00:00+00:00",
            }))
            connection.execute(insert(runs).values(
                id=2, slot="jobs", started_at="2026-11-07T01:00:00+00:00",
                finished_at="2026-11-07T01:02:00+00:00", status="success",
                jobs_processed=2, jobs_new=1))
    engine.dispose()


def test_preflight_never_changes_older_target(tmp_path):
    source = url(tmp_path / "source.db")
    target = url(tmp_path / "target.db")
    seed(source, old=False)
    seed(target, old=True)
    report = synchronize(source, target, allow_sqlite_tests=True)
    assert report["status"] == "ready" and report["mode"] == "preflight"
    assert report["insert_counts"]["jobs"] == 1
    assert report["update_counts"]["jobs"] == 1
    assert report["insert_counts"]["runs"] == 1
    engine = create_engine(target)
    with engine.connect() as connection:
        assert connection.execute(select(jobs.c.job_id)).scalars().all() == ["j1"]
    engine.dispose()


def test_atomic_apply_preserves_source_and_yields_exact_copy(tmp_path):
    source = url(tmp_path / "source.db")
    target = url(tmp_path / "target.db")
    seed(source, old=False)
    seed(target, old=True)
    with pytest.raises(RuntimeError, match="backup"):
        synchronize(source, target, apply=True, allow_sqlite_tests=True)
    report = synchronize(source, target, apply=True, backup_confirmed=True,
                         allow_sqlite_tests=True)
    assert report["status"] == "copied-and-verified"
    assert report["source_modified"] is False
    assert report["production_cutover_performed"] is False
    assert report["requires_final_reconciliation"] is True
    assert synchronize(source, target, allow_sqlite_tests=True)["update_counts"]["jobs"] == 0


def test_rejects_target_only_records_before_any_write(tmp_path):
    source = url(tmp_path / "source.db")
    target = url(tmp_path / "target.db")
    seed(source, old=False)
    seed(target, old=True)
    engine = create_engine(target)
    with engine.begin() as connection:
        connection.execute(insert(runs).values(
            id=99, slot="jobs", started_at="2026-11-08T00:00:00+00:00",
            finished_at="2026-11-08T00:01:00+00:00", status="success"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="identities absent"):
        synchronize(source, target, allow_sqlite_tests=True)


def test_immutable_history_conflict_fails_closed(tmp_path):
    source = url(tmp_path / "source.db")
    target = url(tmp_path / "target.db")
    seed(source, old=False)
    seed(target, old=True)
    engine = create_engine(target)
    with engine.begin() as connection:
        connection.execute(update(runs).where(runs.c.id == 1).values(status="failed"))
    engine.dispose()
    with pytest.raises(RuntimeError, match="Immutable history"):
        synchronize(source, target, allow_sqlite_tests=True)


def test_same_database_is_rejected(tmp_path):
    source = url(tmp_path / "source.db")
    seed(source, old=True)
    with pytest.raises(ValueError, match="same database"):
        synchronize(source, source, allow_sqlite_tests=True)
