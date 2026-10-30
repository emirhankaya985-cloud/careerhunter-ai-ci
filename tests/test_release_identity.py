"""Release identity proof does not disclose secrets or accept invalid SHAs."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from careerhunter.database import SQLiteRepository
from careerhunter.private_site import app, _get_engine


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    repo = SQLiteRepository(tmp_path / "private.db")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-password-only-for-release-tests")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "isolated-test-signing-secret-000000000000")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", f"sqlite:///{tmp_path / 'private.db'}")
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIE", "true")
    _get_engine.cache_clear()
    try:
        with TestClient(app, base_url="https://testserver") as client:
            yield client
    finally:
        _get_engine.cache_clear()
        repo.engine.dispose()


def test_render_version_endpoint_is_only_public_commit_identity(monkeypatch, app_client):
    sha = "9" * 40
    monkeypatch.setenv("RENDER_GIT_COMMIT", sha)
    response = app_client.get("/versionz")
    assert response.status_code == 200
    assert response.text == sha
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["x-frame-options"] == "DENY"
    assert "local-password" not in response.text
    assert "database" not in response.text


@pytest.mark.parametrize("raw", ["", "unknown", "x" * 40, "a" * 39, "a" * 41])
def test_invalid_render_version_refuses_production_acceptance(monkeypatch, app_client, raw):
    monkeypatch.setenv("RENDER_GIT_COMMIT", raw)
    response = app_client.get("/versionz")
    assert response.status_code == 503
    assert response.text == "unknown"


def test_production_acceptance_requires_exact_render_release():
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / ".github/workflows/v2-production-acceptance.yml"
    content = path.read_text(encoding="utf-8")
    assert 'code, deployed = get("/versionz")' in content
    assert 'deployed.strip().lower() != expected' in content
    assert 'get("/readyz")' in content
    assert 'code != 401' in content
