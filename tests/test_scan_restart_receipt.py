"""Fail-closed recovery of Render's in-memory scan status."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from careerhunter import scheduled_scan as scan
from careerhunter.database import SQLiteRepository, runs
from careerhunter.private_site import app


def _client(tmp_path, monkeypatch):
    database = tmp_path / "durable_scan.db"
    repo = SQLiteRepository(database)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-private-password-123456")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "test-private-session-secret-" + "x" * 40)
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "sqlite:///" + str(database))
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key="fixture-key"))
    monkeypatch.setattr(scan.jwt, "decode", lambda *args, **kwargs: {
        "sub": "repo:" + scan.REPO + ":ref:refs/heads/main",
        "repository": scan.REPO,
        "repository_id": scan.REPO_ID,
        "workflow_ref": scan.WORKFLOW,
        "ref": "refs/heads/main",
        "event_name": "workflow_dispatch",
    })
    return repo, database


def _headers():
    return {"Authorization": "Bearer head.payload.signature"}


def test_receipt_requires_signed_collector_identity(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/internal/scan/receipt").status_code == 401
        assert client.get("/internal/scan/receipt?since=not-a-time", headers=_headers()).status_code == 400


def test_receipt_proves_only_a_new_successful_database_run(tmp_path, monkeypatch):
    repo, database = _client(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    previous = (now - timedelta(hours=1)).isoformat()
    fresh = (now - timedelta(seconds=20)).isoformat()
    with repo.engine.begin() as connection:
        connection.execute(insert(runs).values(
            slot="jobs", started_at=previous, finished_at=previous,
            jobs_processed=250, jobs_new=1, status="success",
        ))
    repo.engine.dispose()
    with TestClient(app, base_url="https://testserver") as client:
        response = client.get("/internal/scan/receipt",
                              params={"since": fresh}, headers=_headers())
        assert response.status_code == 200
        assert response.json()["status"] == "absent"
        with SQLiteRepository(database).engine.begin() as connection:
            connection.execute(insert(runs).values(
                slot="jobs", started_at=now.isoformat(), finished_at=now.isoformat(),
                jobs_processed=1997, jobs_new=0, status="success",
            ))
        found = client.get("/internal/scan/receipt",
                           params={"since": fresh}, headers=_headers()).json()
        assert found["status"] == "success"
        assert found["durable_receipt"] is True
        assert found["jobs_processed"] == 1997


def test_receipt_rejects_stale_or_future_timestamps(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)
    with TestClient(app, base_url="https://testserver") as client:
        for stamp in ((datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(),
                      (datetime.now(timezone.utc) + timedelta(minutes=3)).isoformat()):
            assert client.get("/internal/scan/receipt",
                              params={"since": stamp}, headers=_headers()).status_code == 400
