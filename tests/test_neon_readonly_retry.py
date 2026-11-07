"""Transient DB failures may retry only a read-only reconciliation."""
from sqlalchemy.exc import OperationalError
import pytest

from careerhunter import neon_reconcile


def db_failure():
    return OperationalError("SELECT read_only", {}, RuntimeError("connection unavailable"))


def test_transient_failure_retries_with_new_snapshot(monkeypatch):
    attempts = []
    delays = []

    def compare(source, target):
        attempts.append((source, target))
        if len(attempts) < 3:
            raise db_failure()
        return {"status": "match"}

    monkeypatch.setattr(neon_reconcile, "_compare", compare)
    monkeypatch.setattr(neon_reconcile.time, "sleep", delays.append)
    assert neon_reconcile._compare_with_retry("old", "new") == {"status": "match"}
    assert len(attempts) == 3
    assert delays == [1, 2]


def test_repeated_failure_is_bounded_and_never_falsely_succeeds(monkeypatch):
    attempts = []
    monkeypatch.setattr(neon_reconcile.time, "sleep", lambda _: None)

    def fail(*args):
        attempts.append(args)
        raise db_failure()

    monkeypatch.setattr(neon_reconcile, "_compare", fail)
    with pytest.raises(OperationalError):
        neon_reconcile._compare_with_retry("old", "new")
    assert len(attempts) == 3


def test_nontransient_failures_fail_closed_without_retry(monkeypatch):
    attempts = []
    monkeypatch.setattr(neon_reconcile.time, "sleep", lambda _: pytest.fail("unexpected retry"))

    def fail(*args):
        attempts.append(args)
        raise ValueError("inconsistent data")

    monkeypatch.setattr(neon_reconcile, "_compare", fail)
    with pytest.raises(ValueError):
        neon_reconcile._compare_with_retry("old", "new")
    assert len(attempts) == 1
