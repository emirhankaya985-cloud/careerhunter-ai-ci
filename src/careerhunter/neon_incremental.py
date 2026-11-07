"""Explicit source-preserving Render -> Neon incremental synchronization.

Read-only preflight is the default. Production apply requires a separately
verified restorable backup, owner opt-in and a dedicated authorized workflow.
No source writes, no source deletes, no automatic production cutover.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, make_url

from .database import jobs, metadata, runs
from .pg_transfer import _check_urls, _fingerprint, _row_digest, _source_counts, _start_snapshot


def _utc(value: str) -> datetime:
    value = str(value).replace("Z", "+00:00")
    result = datetime.fromisoformat(value)
    return result if result.tzinfo else result.replace(tzinfo=timezone.utc)


def _rowmap(connection: Connection, table) -> dict[tuple, dict]:
    keys = tuple(column.name for column in table.primary_key.columns)
    if not keys:
        raise RuntimeError("Unkeyed table blocks incremental transfer")
    records = [dict(row) for row in connection.execute(select(table)).mappings()]
    indexed = {tuple(record[key] for key in keys): record for record in records}
    if len(indexed) != len(records):
        raise RuntimeError("Duplicate primary key blocks incremental transfer")
    return indexed


def _changes(reader: Connection, target: Connection) -> tuple[dict, dict]:
    source_counts = _source_counts(reader)
    target_counts = _source_counts(target)
    changes = {}
    for table in metadata.sorted_tables:
        source_rows = _rowmap(reader, table)
        target_rows = _rowmap(target, table)
        if set(target_rows) - set(source_rows):
            raise RuntimeError("Neon contains identities absent in the original source")
        new = [row for key, row in source_rows.items() if key not in target_rows]
        altered = []
        for key, latest in source_rows.items():
            older = target_rows.get(key)
            if older is None or _row_digest(latest) == _row_digest(older):
                continue
            if table.name == "jobs":
                if (older["first_seen_at"] != latest["first_seen_at"]
                        or _utc(latest["last_seen_at"]) < _utc(older["last_seen_at"])):
                    raise RuntimeError("Job identity or timestamp regression")
            elif table.name == "company_signals":
                if (older["company_id"], older["company"], older["signal_type"]) != (
                        latest["company_id"], latest["company"], latest["signal_type"]):
                    raise RuntimeError("Company signal identity changed")
                if _utc(latest["observed_at"]) < _utc(older["observed_at"]):
                    raise RuntimeError("Company signal observation regressed")
            else:
                # Historical scans and private CRM records must never be silently
                # overwritten by a recurring sync.
                raise RuntimeError("Immutable history or CRM conflict")
            altered.append(latest)
        changes[table.name] = {"new": new, "changed": altered}
    return changes, {"source_counts": source_counts, "target_counts": target_counts}


def _apply(writer: Connection, changes: dict) -> None:
    backend = writer.dialect.name
    if backend not in {"sqlite", "postgresql"}:
        raise RuntimeError("Unsupported transfer database")
    for table in metadata.sorted_tables:
        rows = changes[table.name]["new"] + changes[table.name]["changed"]
        if not rows:
            continue
        stmt = (pg_insert(table) if backend == "postgresql" else sqlite_insert(table))
        stmt = stmt.values(rows)
        primary = [column.name for column in table.primary_key.columns]
        non_key = [column.name for column in table.columns if column.name not in primary]
        if changes[table.name]["changed"]:
            statement = stmt.on_conflict_do_update(
                index_elements=primary,
                set_={name: getattr(stmt.excluded, name) for name in non_key},
            )
        else:
            statement = stmt.on_conflict_do_nothing(index_elements=primary)
        writer.execute(statement)
    if backend == "postgresql":
        seq = writer.execute(text("SELECT pg_get_serial_sequence('runs', 'id')")).scalar_one_or_none()
        maximum = writer.execute(select(func.max(runs.c.id))).scalar_one()
        if seq and maximum is not None:
            writer.execute(text("SELECT setval(CAST(:seq AS regclass), :value, true)"),
                           {"seq": seq, "value": int(maximum)})


def synchronize(
    source_url: str,
    target_url: str,
    *,
    apply: bool = False,
    backup_confirmed: bool = False,
    allow_sqlite_tests: bool = False,
) -> dict:
    source_url, target_url = _check_urls(source_url, target_url, allow_sqlite_tests)
    source_id = make_url(source_url)
    target_id = make_url(target_url)
    if not allow_sqlite_tests:
        if (source_id.get_backend_name() != "postgresql"
                or (source_id.host or "").lower().endswith(".neon.tech")
                or target_id.get_backend_name() != "postgresql"
                or not (target_id.host or "").lower().endswith(".neon.tech")
                or target_id.database != "careerhunter_live"):
            raise RuntimeError("Verified original Render and dedicated Neon identities required")
    if apply and not backup_confirmed:
        raise RuntimeError("Independent tested backup required before incremental apply")
    options = ({"connect_args": {"options": "-c default_transaction_read_only=on"}}
               if source_id.get_backend_name() == "postgresql" else {})
    source = create_engine(source_url, pool_pre_ping=True, **options)
    target = create_engine(target_url, pool_pre_ping=True)
    try:
        with source.connect() as reader:
            _start_snapshot(reader)
            with target.begin() as writer:
                if apply and writer.dialect.name == "postgresql":
                    writer.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                changes, counts = _changes(reader, writer)
                report = {
                    "status": "ready",
                    "mode": "applied" if apply else "preflight",
                    "source_counts": counts["source_counts"],
                    "old_target_counts": counts["target_counts"],
                    "insert_counts": {key: len(value["new"]) for key, value in changes.items()},
                    "update_counts": {key: len(value["changed"]) for key, value in changes.items()},
                    "source_modified": False,
                    "production_cutover_performed": False,
                    "requires_final_reconciliation": True,
                }
                if apply:
                    _apply(writer, changes)
                    for table in metadata.sorted_tables:
                        if _fingerprint(writer, table) != _fingerprint(reader, table):
                            raise RuntimeError("Incremental row digest mismatch; rollback")
                    report["status"] = "copied-and-verified"
                return report
    finally:
        source.dispose()
        target.dispose()
