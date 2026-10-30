"""Prove private cloud backup requires the exact GitHub OIDC workflow."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from careerhunter import cloud_backup, scheduled_scan as scan
from careerhunter.database import SQLiteRepository
from careerhunter.private_site import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "private.db")
    repo.engine.dispose()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "safe-local-testing-password-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "fixture-session-secret-for-oidc-testing-12345")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", f"sqlite:///{tmp_path / 'private.db'}")
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    with cloud_backup._lock:
        cloud_backup._state.clear()
        cloud_backup._state["status"] = "idle"
    with TestClient(app, base_url="https://testserver") as http:
        yield http


def _signed_identity(monkeypatch):
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key="public-fixture"))
    claims = {
        "sub": "repo:" + scan.REPO + ":ref:refs/heads/main",
        "repository": scan.REPO,
        "repository_id": scan.REPO_ID,
        "workflow_ref": cloud_backup.WORKFLOW,
        "ref": "refs/heads/main",
        "event_name": "workflow_dispatch",
    }
    monkeypatch.setattr(scan.jwt, "decode", lambda *args, **kwargs: dict(claims))
    return claims, {"Authorization": "Bearer header.body.signature"}


@pytest.mark.parametrize("path,method", [
    ("/internal/cloud-backup/preflight", "get"),
    ("/internal/cloud-backup/start", "post"),
    ("/internal/cloud-backup/status", "get"),
])
def test_cloud_backup_is_not_anonymous(client, path, method):
    assert getattr(client, method)(path).status_code == 401


def test_migration_only_exact_signed_workflow_may_access(client, monkeypatch):
    claims, headers = _signed_identity(monkeypatch)
    for key, invalid in [
        ("repository_id", "999"),
        ("workflow_ref", scan.WORKFLOW),
        ("ref", "refs/heads/feature"),
        ("event_name", "pull_request"),
    ]:
        claims[key] = invalid
        assert client.get("/internal/cloud-backup/status", headers=headers).status_code == 403
        claims, _ = _signed_identity(monkeypatch)
    assert client.get("/internal/cloud-backup/status", headers=headers).json()["status"] == "idle"


def test_cloud_backup_disabled_without_opt_in_or_neon_secret(client, monkeypatch):
    _, headers = _signed_identity(monkeypatch)
    monkeypatch.delenv("CAREERHUNTER_NEON_CLOUD_COPY_ENABLED", raising=False)
    response = client.post("/internal/cloud-backup/start", headers=headers)
    assert response.status_code == 503
    monkeypatch.setenv("CAREERHUNTER_NEON_CLOUD_COPY_ENABLED", "true")
    monkeypatch.delenv("CAREERHUNTER_NEON_BACKUP_URL", raising=False)
    response = client.post("/internal/cloud-backup/start", headers=headers)
    assert response.status_code == 503


def test_cloud_backup_rejects_non_neon_target(client, monkeypatch):
    _, headers = _signed_identity(monkeypatch)
    monkeypatch.setenv("CAREERHUNTER_NEON_CLOUD_COPY_ENABLED", "true")
    monkeypatch.setenv("CAREERHUNTER_NEON_BACKUP_URL",
                       "postgresql://user:password@somewhere.example/db")
    assert client.post("/internal/cloud-backup/start", headers=headers).status_code == 503


def test_signed_start_is_once_only_and_returns_no_credentials(client, monkeypatch):
    _, headers = _signed_identity(monkeypatch)
    monkeypatch.setenv("CAREERHUNTER_NEON_CLOUD_COPY_ENABLED", "true")
    monkeypatch.setenv("CAREERHUNTER_NEON_BACKUP_URL",
                       "postgresql://user:PRIVATE_VALUE@ep-test.eu-central-1.aws.neon.tech/neondb")
    monkeypatch.setattr(cloud_backup.threading, "Thread",
                        lambda **kwargs: SimpleNamespace(start=lambda: None))
    first = client.post("/internal/cloud-backup/start", headers=headers)
    second = client.post("/internal/cloud-backup/start", headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["status"] == "running"
    assert "PRIVATE_VALUE" not in first.text
    assert "PRIVATE_VALUE" not in second.text
    assert first.json()["cutover"] is False
