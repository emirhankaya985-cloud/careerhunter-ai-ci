"""Reconciliation must be authorized, read-only and fail-closed."""
from __future__ import annotations

from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from careerhunter import neon_reconcile, scheduled_scan as scan
from careerhunter.database import SQLiteRepository
from careerhunter.private_site import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    repo = SQLiteRepository(tmp_path / "fixture.db")
    repo.engine.dispose()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "safe-local-testing-password-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "fixture-session-secret-for-oidc-testing-12345")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", f"sqlite:///{tmp_path / 'fixture.db'}")
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    with TestClient(app, base_url="https://testserver") as http:
        yield http


def signed(monkeypatch):
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt", lambda token: SimpleNamespace(key="test"))
    claims = {
        "sub": "repo:" + scan.REPO + ":ref:refs/heads/main",
        "repository": scan.REPO,
        "repository_id": scan.REPO_ID,
        "workflow_ref": neon_reconcile.WORKFLOW,
        "ref": "refs/heads/main",
        "event_name": "push",
    }
    monkeypatch.setattr(scan.jwt, "decode", lambda *args, **kwargs: dict(claims))
    return claims, {"Authorization": "Bearer header.body.signature"}


def test_anonymous_cannot_reconcile(client):
    assert client.get("/internal/neon-cutover/preflight").status_code == 401


def test_wrong_workflow_cannot_reconcile(client, monkeypatch):
    claims, headers = signed(monkeypatch)
    claims["workflow_ref"] = scan.WORKFLOW
    assert client.get("/internal/neon-cutover/preflight", headers=headers).status_code == 403


def test_valid_workflow_receives_only_aggregate_counts(client, monkeypatch):
    _, headers = signed(monkeypatch)
    monkeypatch.setattr(neon_reconcile, "_connections", lambda: ("postgresql+psycopg://source", "postgresql+psycopg://target"))
    monkeypatch.setattr(neon_reconcile, "_compare", lambda *args: {
        "status": "match", "source_counts": {"jobs": 2166},
        "target_counts": {"jobs": 2166},
        "all_row_hashes_equal": True, "production_cutover_performed": False,
    })
    response = client.get("/internal/neon-cutover/preflight", headers=headers)
    assert response.status_code == 200
    assert response.json()["all_row_hashes_equal"] is True
    assert "password" not in response.text
    assert "postgresql" not in response.text


@pytest.mark.parametrize("invalid", [
    "",
    "not-a-url",
    "sqlite:///wrong.db",
    "postgresql://user:password@notneon.tech/careerhunter_live",
    "postgresql://user:password@ep-example.neon.tech/careerhunter",
])
def test_bad_url_is_not_accepted(client, monkeypatch, invalid):
    monkeypatch.setenv("CAREERHUNTER_NEON_DATABASE_URL", invalid)
    with pytest.raises(RuntimeError, match="verified Neon target"):
        neon_reconcile._connections()


def test_preflight_rejects_neon_primary(client, monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_DB_TARGET", "neon")
    with pytest.raises(RuntimeError, match="Render must remain primary"):
        neon_reconcile._connections()


def test_unavailable_database_does_not_leak_details(client, monkeypatch):
    _, headers = signed(monkeypatch)
    monkeypatch.setattr(neon_reconcile, "_connections", lambda: (_ for _ in ()).throw(RuntimeError("PASSWORD_SECRET")))
    response = client.get("/internal/neon-cutover/preflight", headers=headers)
    assert response.status_code == 503
    assert "PASSWORD_SECRET" not in response.text
