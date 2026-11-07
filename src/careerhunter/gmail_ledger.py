"""Optional durable Gmail deduplication using opaque hashes only.

This is separate from the primary career data schema. It is created only
after the owner's explicit Gmail ledger opt-in, never at app startup.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import Column, MetaData, String, Table, create_engine
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url

from .inbox_review import InboxSignal

ledger_metadata = MetaData()
seen_mail = Table(
    "careerhunter_gmail_seen", ledger_metadata,
    Column("message_hash", String(64), primary_key=True),
    Column("thread_hash", String(64), nullable=True),
    Column("category", String(32), nullable=False),
    Column("first_processed_at", String(40), nullable=False),
)


def _digest(prefix: str, value: str) -> str:
    return hashlib.sha256((prefix + "\0" + value).encode("utf-8")).hexdigest()


def retain_unseen(
    url: str, items: list[tuple[str, str | None, InboxSignal]],
    *, allow_sqlite_tests: bool = False,
) -> list[InboxSignal]:
    """Atomically count every Gmail API message ID at most once across runs.

    Distinct messages in the same thread are counted separately. Store no raw
    identifiers, email content, addresses, or OAuth tokens. No remote Gmail
    write operation is performed. An unprepared database fails closed.
    """
    backend = make_url(url).get_backend_name()
    if backend != "postgresql" and not (allow_sqlite_tests and backend == "sqlite"):
        raise RuntimeError("Durable Gmail ledger requires an approved PostgreSQL database")
    engine = create_engine(url, pool_pre_ping=True)
    try:
        # Creating the dedicated table is deliberately restricted to the
        # feature's explicit opt-in path and is never done at process startup.
        ledger_metadata.create_all(engine)
        new: list[InboxSignal] = []
        with engine.begin() as conn:
            for message_id, thread_id, signal in items:
                values = {
                    "message_hash": _digest("gmail-message-v1", message_id),
                    "thread_hash": (
                        _digest("gmail-thread-v1", thread_id) if thread_id else None
                    ),
                    "category": signal.proposed_category,
                    "first_processed_at": datetime.now(timezone.utc).isoformat(),
                }
                if backend == "postgresql":
                    statement = pg_insert(seen_mail).values(**values).on_conflict_do_nothing(
                        index_elements=[seen_mail.c.message_hash])
                else:
                    statement = sqlite_insert(seen_mail).values(**values).on_conflict_do_nothing(
                        index_elements=[seen_mail.c.message_hash])
                result = conn.execute(statement)
                if result.rowcount == 1:
                    new.append(signal)
        return new
    finally:
        engine.dispose()
