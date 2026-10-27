"""Conservative one-shot PostgreSQL data migration for CareerHunter AI.

Source is read-only. Target writes are transactional, and never allowed when
any application table already contains records. No credentials/records logged.
Pause the collector before invoking --apply.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections.abc import Iterable

from sqlalchemy import create_engine, func, insert, inspect, select, text
from sqlalchemy.engine import Engine, make_url

from .database import metadata


class MigrationError(RuntimeError):
    pass


def _db_identity(engine: Engine) -> tuple:
    url = engine.url
    return (url.host, url.port, url.database)


def _table_digest(connection, table) -> tuple[int, str]:
    """Compare every row's content without printing or retaining row data."""
    digest = hashlib.sha256()
    total = 0
    query = select(table).order_by(*table.primary_key.columns)
    for row in connection.execute(query):
        digest.update(repr(tuple(row)).encode("utf-8"))
        digest.update(b"\n")
        total += 1
    return total, digest.hexdigest()


def transfer(source_engine: Engine, destination_engine: Engine, *, apply: bool = False) -> dict[str, int]:
    """Copy all application tables atomically; refuse dirty targets or mismatches."""
    if _db_identity(source_engine) == _db_identity(destination_engine):
        raise MigrationError("Source and destination point to the same database")
    if source_engine.dialect.name != destination_engine.dialect.name:
        raise MigrationError("Source and destination database dialects differ")

    tables = list(metadata.sorted_tables)
    names = {table.name for table in tables}
    existing_source = set(inspect(source_engine).get_table_names())
    if missing := (names - existing_source):
        raise MigrationError("Source is missing application tables: " + ", ".join(sorted(missing)))

    with source_engine.connect() as source:
        if source_engine.dialect.name == "postgresql":
            source.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        source_counts = {
            table.name: int(source.execute(select(func.count()).select_from(table)).scalar_one())
            for table in tables
        }
        existing_destination = set(inspect(destination_engine).get_table_names())
        with destination_engine.connect() as destination:
            dirty = [
                table.name for table in tables
                if table.name in existing_destination and
                destination.execute(select(func.count()).select_from(table)).scalar_one()
            ]
        if dirty:
            raise MigrationError("Target contains records; refusing to overwrite: " + ", ".join(dirty))
        if not apply:
            return source_counts

        # On PostgreSQL, any error rolls back table creation and copied records.
        with destination_engine.begin() as destination:
            metadata.create_all(destination, checkfirst=True)
            for table in tables:
                for batch in source.execute(select(table)).mappings().partitions(100):
                    destination.execute(insert(table), [dict(row) for row in batch])

            if destination_engine.dialect.name == "postgresql" and source_counts.get("runs", 0):
                destination.execute(text(
                    "SELECT setval(pg_get_serial_sequence('runs', 'id'), "
                    "(SELECT MAX(id) FROM runs), true)"
                ))

            for table in tables:
                src_total, src_hash = _table_digest(source, table)
                dst_total, dst_hash = _table_digest(destination, table)
                if (src_total, src_hash) != (dst_total, dst_hash):
                    raise MigrationError(
                        f"Verification failed for {table.name}: "
                        f"source={src_total}, target={dst_total}"
                    )
        return source_counts


def _url_from_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise MigrationError(f"Missing {name} environment variable")
    value = value.replace("postgres://", "postgresql+psycopg://", 1)
    value = value.replace("postgresql://", "postgresql+psycopg://", 1)
    if make_url(value).get_backend_name() != "postgresql":
        raise MigrationError(f"{name} must point to PostgreSQL")
    return value


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Copy data (otherwise preflight only)")
    args = parser.parse_args(argv)
    try:
        source = create_engine(_url_from_env("SOURCE_DATABASE_URL"), pool_pre_ping=True)
        destination = create_engine(_url_from_env("TARGET_DATABASE_URL"), pool_pre_ping=True)
        try:
            counts = transfer(source, destination, apply=args.apply)
        finally:
            source.dispose()
            destination.dispose()
    except Exception as exc:
        # Database driver exceptions may reveal secrets. Only print the exception class.
        print(f"Migration failed: {type(exc).__name__}; see protected operator logs", file=sys.stderr)
        return 1
    print("Mode:", "COPY AND VERIFY" if args.apply else "PREFLIGHT ONLY")
    print("Verified counts:", ", ".join(
        f"{name}={count}" for name, count in sorted(counts.items())
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
