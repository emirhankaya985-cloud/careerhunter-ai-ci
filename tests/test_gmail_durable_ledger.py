"""Cross-run Gmail dedupe tests use only a disposable SQLite fixture."""
import base64
from email.message import EmailMessage

import httpx
import pytest
from sqlalchemy import create_engine, select

from careerhunter import gmail_ledger
from careerhunter.gmail_reader import read_readonly
from careerhunter.inbox_review import InboxSignal


def test_durable_message_ids_and_distinct_messages_in_same_thread(tmp_path):
    url = "sqlite:///" + str(tmp_path / "private-ledger.db")
    x = InboxSignal(id_hash="x", proposed_category="interview")
    y = InboxSignal(id_hash="y", proposed_category="assessment")
    assert gmail_ledger.retain_unseen(
        url, [("opaque-msg-001", "opaque-thread-777", x)], allow_sqlite_tests=True
    ) == [x]
    assert gmail_ledger.retain_unseen(
        url, [("opaque-msg-001", "opaque-thread-777", x)], allow_sqlite_tests=True
    ) == []
    assert gmail_ledger.retain_unseen(
        url, [("opaque-msg-002", "opaque-thread-777", y)], allow_sqlite_tests=True
    ) == [y]
    engine = create_engine(url)
    with engine.connect() as conn:
        rows = conn.execute(select(gmail_ledger.seen_mail)).mappings().all()
    engine.dispose()
    assert len(rows) == 2
    assert rows[0]["thread_hash"] == rows[1]["thread_hash"]
    assert all("opaque" not in str(dict(row)) for row in rows)


def test_prod_path_does_not_fallback_to_local_sqlite(tmp_path):
    url = "sqlite:///" + str(tmp_path / "must-not-be-created.db")
    with pytest.raises(RuntimeError, match="approved PostgreSQL"):
        gmail_ledger.retain_unseen(url, [])
    assert not (tmp_path / "must-not-be-created.db").exists()


def test_gmail_reader_uses_durable_ledger_twice(monkeypatch, tmp_path):
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_ID", "fixture")
    monkeypatch.setenv("GMAIL_READONLY_CLIENT_SECRET", "fixture")
    monkeypatch.setenv("GMAIL_READONLY_REFRESH_TOKEN", "fixture")
    url = "sqlite:///" + str(tmp_path / "reader-ledger.db")
    msg = EmailMessage()
    msg["Subject"] = "Interview invitation"
    msg["Message-ID"] = "<interview-123@example.org>"
    msg.set_content("Please schedule an interview.")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii").rstrip("=")

    def reply(request):
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "ephemeral"})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={
                "messages": [{"id": "msgAAA123", "threadId": "threadAAA123"}]})
        return httpx.Response(200, json={"raw": raw})

    # Test-only SQLite is passed via the explicit monkeypatch shim: the
    # production Gmail reader deliberately only permits PostgreSQL.
    original = gmail_ledger.retain_unseen

    def local(url, items):
        return original(url, items, allow_sqlite_tests=True)

    monkeypatch.setattr(gmail_ledger, "retain_unseen", local)
    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        first = read_readonly(max_results=5, client=client, ledger_url=url)
        second = read_readonly(max_results=5, client=client, ledger_url=url)
    assert first.scanned == 1 and first.categories == {"interview": 1}
    assert second.scanned == 0 and second.categories == {}
