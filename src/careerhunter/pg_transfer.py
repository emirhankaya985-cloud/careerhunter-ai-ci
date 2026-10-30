"""Explicit Render -> Neon PostgreSQL transfer; never switches live connections.

The default is a read-only preflight. --apply requires a separately verified
backup and an entirely empty target. No private records are emitted to logs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from sqlalchemy import create_engine, func, insert, inspect, select, text
from sqlalchemy.engine import Connection, make_url

from .database import jobs, metadata, runs


def _check_urls(source_url: str, target_url: str, allow_sqlite: bool) -> tuple[str, str]:
    def normalize(value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value[len("postgresql://"):]
        return value

    if not source_url or not target_url:
        raise ValueError("Both source and target database URLs are required")
    source_url, target_url = normalize(source_url), normalize(target_url)
    source, target = make_url(source_url), make_url(target_url)
    supported = {"postgresql"} | ({"sqlite"} if allow_sqlite else set())
    if source.get_backend_name() not in supported or target.get_backend_name() not in supported:
        raise ValueError("Production transfer requires two PostgreSQL connections")
    if ((source.host, source.port, source.database) ==
            (target.host, target.port, target.database)):
        raise ValueError("Source and target identify the same database")
    return source_url, target_url


def _start_snapshot(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )


def _source_counts(connection: Connection) -> dict[str, int]:
    existing = set(inspect(connection).get_table_names())
    if any(table.name not in existing for table in metadata.sorted_tables):
        raise RuntimeError("Source schema incomplete; refusing partial migration")
    counts = {
        table.name: int(connection.execute(select(func.count()).select_from(table)).scalar_one())
        for table in metadata.sorted_tables
    }
    if counts[jobs.name] < 1:
        raise RuntimeError("Source has zero job rows; refusing a false success")
    return counts


def _require_empty_target(connection: Connection) -> None:
    if inspect(connection).get_table_names():
        raise RuntimeError("Target has tables; no overwrite or second transfer allowed")


def _digest(records: list[bytes]) -> str:
    combined = hashlib.sha256()
    for digest in sorted(records):
        combined.update(digest)
    return combined.hexdigest()


def _row_digest(row: dict) -> bytes:
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).digest()


def _fingerprint(connection: Connection, table) -> tuple[int, str]:
    signatures = [_row_digest(dict(row))
                  for row in connection.execute(select(table)).mappings()]
    return len(signatures), _digest(signatures)


def transfer(source_url: str, target_url: str, *, apply: bool = False,
             backup_confirmed: bool = False, allow_sqlite_tests: bool = False) -> dict:
    """Preserve all tables; source SELECT-only, target writes only on explicit apply."""
    source_url, target_url = _check_urls(source_url, target_url, allow_sqlite_tests)
    if apply and not backup_confirmed:
        raise ValueError("A verified independent backup is required before --apply")
    source_options = (
        {"connect_args": {"options": "-c default_transaction_read_only=on"}}
        if make_url(source_url).get_backend_name() == "postgresql" else {}
    )
    source = create_engine(source_url, pool_pre_ping=True, **source_options)
    target = create_engine(target_url, pool_pre_ping=True)
    try:
        with source.connect() as reader:
            _start_snapshot(reader)
            counts = _source_counts(reader)
            with target.connect() as checker:
                _require_empty_target(checker)
            if not apply:
                return {"mode": "preflight", "source_counts": counts,
                        "target_empty": True, "data_copied": False}

            with target.begin() as writer:
                _require_empty_target(writer)
                metadata.create_all(writer)
                fingerprints: dict[str, tuple[int, str]] = {}
                for table in metadata.sorted_tables:
                    signatures: list[bytes] = []
                    result = reader.execute(select(table)).mappings()
                    while batch := result.fetchmany(200):
                        records = [dict(row) for row in batch]
                        signatures.extend(_row_digest(row) for row in records)
                        writer.execute(insert(table), records)
                    fingerprints[table.name] = (len(signatures), _digest(signatures))

                for table in metadata.sorted_tables:
                    if _fingerprint(writer, table) != fingerprints[table.name]:
                        raise RuntimeError("Verification mismatch; target transaction rolled back")
                # Explicitly imported runs.id values need a valid future sequence.
                if writer.dialect.name == "postgresql":
                    seq = writer.execute(
                        text("SELECT pg_get_serial_sequence('runs', 'id')")
                    ).scalar_one_or_none()
                    maximum = writer.execute(select(func.max(runs.c.id))).scalar_one()
                    if seq and maximum is not None:
                        writer.execute(
                            text("SELECT setval(CAST(:seq AS regclass), :value, true)"),
                            {"seq": seq, "value": int(maximum)},
                        )
            return {"mode": "copied-and-verified", "source_counts": counts,
                    "target_counts": {k: v[0] for k, v in fingerprints.items()},
                    "data_copied": True, "production_cutover_performed": False}
    finally:
        source.dispose()
        target.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only preflight by default")
    parser.add_argument("--apply", action="store_true",
                        help="Copy to an empty Neon database; does not switch production")
    parser.add_argument("--backup-confirmed", action="store_true",
                        help="Affirm an independent restorable backup has been verified")
    args = parser.parse_args()
    try:
        report = transfer(
            os.environ.get("DASHBOARD_DATABASE_URL", ""),
            os.environ.get("NEON_DATABASE_URL", ""),
            apply=args.apply, backup_confirmed=args.backup_confirmed,
        )
    except Exception as exc:
        # Never include exception detail; DB drivers can embed secret connection data.
        print(f"TRANSFER BLOCKED: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
