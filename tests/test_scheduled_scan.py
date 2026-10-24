"""Regression tests for the no-secret GitHub OIDC collector endpoint."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from careerhunter.database import SQLiteRepository
from careerhunter.private_site import app
from careerhunter import scheduled_scan as scan


@pytest.fixture
def client(tmp_path, monkeypatch):
    db = tmp_path / "production-fixture.db"
    fixture = SQLiteRepository(db)
    fixture.engine.dispose()
    monkeypatch.setenv("DASHBOARD_PASSWORD", "fake-local-test-passphrase-123")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "fake-test-session-secret-1234567890abcdefgh")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "sqlite:///" + str(db))
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.delenv("DASHBOARD_BOOTSTRAP_SCHEMA", raising=False)
    with scan._lock:
        scan._state.clear()
        scan._state["status"] = "idle"
    with TestClient(app, base_url="https://testserver") as test:
        yield test


def claims():
    return {
        "sub": "repo:" + scan.REPO + ":ref:refs/heads/main",
        "repository": scan.REPO,
        "repository_id": scan.REPO_ID,
        "workflow_ref": scan.WORKFLOW,
        "ref": "refs/heads/main",
        "event_name": "schedule",
    }


def test_runner_disabled_without_render_opt_in(client, monkeypatch):
    monkeypatch.delenv("CAREERHUNTER_OIDC_COLLECTOR", raising=False)
    response = client.post("/internal/scan")
    assert response.status_code == 404


def test_no_anonymous_workflow_trigger_or_data_leak(client, monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    assert client.post("/internal/scan").status_code == 401
    assert client.get("/internal/scan/status").status_code == 401
    assert client.post("/internal/scan", headers={
        "Authorization": "Bearer fake.fake.fake"}).status_code == 401


def test_github_signature_identity_and_workflow_are_all_required(client, monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key="fixture-public-key"))
    identity = claims()
    monkeypatch.setattr(scan.jwt, "decode", lambda *args, **kwargs: dict(identity))
    headers = {"Authorization": "Bearer head.payload.signature"}

    for name, invalid in (
        ("repository_id", "123456"),
        ("repository", "attacker/other-repo"),
        ("ref", "refs/heads/untrusted"),
        ("sub", ""),
        ("workflow_ref", scan.REPO + "/.github/workflows/tests.yml@refs/heads/main"),
        ("event_name", "pull_request"),
    ):
        identity[name] = invalid
        assert client.post("/internal/scan", headers=headers).status_code == 403
        identity = claims()

    # Valid immutable/customized subject formats remain safe because all
    # independent signed repository and workflow claims are exact matches.
    identity["sub"] = "repository_id:" + scan.REPO_ID + ":ref:refs/heads/main"
    called = []
    monkeypatch.setattr(scan, "threading", SimpleNamespace(
        Thread=lambda **kwargs: SimpleNamespace(start=lambda: called.append(1))))
    first = client.post("/internal/scan", headers=headers)
    second = client.post("/internal/scan", headers=headers)
    assert first.status_code == 200 and first.json()["status"] == "running"
    assert second.status_code == 200 and len(called) == 1
    assert client.get("/internal/scan/status", headers=headers).json()["status"] == "running"


def test_invalid_signed_token_never_reaches_collector(client, monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    def fail(token):
        raise scan.jwt.InvalidSignatureError("bad signature")
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt", fail)
    response = client.post("/internal/scan", headers={
        "Authorization": "Bearer head.payload.signature"})
    assert response.status_code == 401


def test_nvidia_enrichment_requires_exact_backfill_workflow(client, monkeypatch):
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key="fixture-public-key"))
    identity = claims()
    monkeypatch.setattr(scan.jwt, "decode", lambda *args, **kwargs: dict(identity))
    headers = {"Authorization": "Bearer head.payload.signature"}
    assert client.post("/internal/ai-rescore", headers=headers).status_code == 403
    assert client.post("/internal/ai-rescore").status_code == 401
    identity["workflow_ref"] = scan.RESCORE_WORKFLOW
    identity["event_name"] = "workflow_dispatch"
    started = []
    monkeypatch.setattr(scan, "threading", SimpleNamespace(
        Thread=lambda **kwargs: SimpleNamespace(start=lambda: started.append(1))))
    result = client.post("/internal/ai-rescore", headers=headers)
    assert result.status_code == 200
    assert result.json()["mode"] == "ai"
    assert len(started) == 1
