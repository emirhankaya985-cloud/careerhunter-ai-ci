"""Isolated migration safety tests (SQLite fixtures, never the production DB)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, insert, inspect, select

from careerhunter.database import contacts, jobs, metadata, runs
from careerhunter.pg_transfer import transfer


def urls(tmp_path):
    return f"sqlite:///{tmp_path / 'render.db'}", f"sqlite:///{tmp_path / 'neon.db'}"


def seed(url):
    engine = create_engine(url)
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(insert(jobs).values(
            source="fixture", job_id="1", company="Example", title="Python Developer",
            location="Remote", job_url="https://example.org/jobs/1",
            payload='{"private":"retain"}', content_hash="a" * 64,
            first_seen_at="2026-10-20T00:00:00+00:00",
            last_seen_at="2026-10-30T00:00:00+00:00",
            last_verified_at="2026-10-30T00:00:00+00:00",
            status="new",
        ))
        conn.execute(insert(contacts).values(
            person_id="private-person", payload='{"notes":"retain exactly"}',
            updated_at="2026-10-30T00:00:00+00:00",
        ))
        conn.execute(insert(runs).values(
            id=42, slot="jobs", started_at="2026-10-30T00:00:00+00:00",
            status="success", jobs_processed=1, jobs_new=1,
        ))
    engine.dispose()


def test_default_preflight_is_read_only(tmp_path):
    src, dst = urls(tmp_path)
    seed(src)
    result = transfer(src, dst, allow_sqlite_tests=True)
    assert result["mode"] == "preflight"
    assert result["source_counts"]["jobs"] == 1
    assert result["source_counts"]["contacts"] == 1
    assert result["data_copied"] is False
    target = create_engine(dst)
    assert inspect(target).get_table_names() == []
    target.dispose()


def test_copy_preserves_every_table_and_private_payload(tmp_path):
    src, dst = urls(tmp_path)
    seed(src)
    result = transfer(src, dst, apply=True, backup_confirmed=True,
                      allow_sqlite_tests=True)
    assert result["mode"] == "copied-and-verified"
    assert result["production_cutover_performed"] is False
    source, target = create_engine(src), create_engine(dst)
    for table in metadata.sorted_tables:
        with source.connect() as a, target.connect() as b:
            rows_a = [dict(row) for row in a.execute(select(table)).mappings()]
            rows_b = [dict(row) for row in b.execute(select(table)).mappings()]
            assert rows_a == rows_b
    with target.connect() as conn:
        assert conn.execute(select(func.max(runs.c.id))).scalar_one() == 42
        assert conn.execute(select(contacts.c.payload)).scalar_one() == (
            '{"notes":"retain exactly"}'
        )
    source.dispose()
    target.dispose()


def test_copy_refuses_existing_target(tmp_path):
    src, dst = urls(tmp_path)
    seed(src)
    seed(dst)
    with pytest.raises(RuntimeError, match="Target has tables"):
        transfer(src, dst, apply=True, backup_confirmed=True,
                 allow_sqlite_tests=True)
    engine = create_engine(dst)
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(jobs)).scalar_one() == 1
    engine.dispose()


def test_apply_requires_prior_verified_backup(tmp_path):
    src, dst = urls(tmp_path)
    seed(src)
    with pytest.raises(ValueError, match="backup"):
        transfer(src, dst, apply=True, allow_sqlite_tests=True)


def test_rejects_same_database_and_non_postgres_production(tmp_path):
    src, dst = urls(tmp_path)
    with pytest.raises(ValueError, match="same database"):
        transfer(src, src, allow_sqlite_tests=True)
    with pytest.raises(ValueError, match="PostgreSQL"):
        transfer(src, dst)
