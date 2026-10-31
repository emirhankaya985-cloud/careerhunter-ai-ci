"""Real archive test must never target production or accept an unsigned caller."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from careerhunter import pg_restore_acceptance as recovery
from careerhunter import scheduled_scan as scan
from careerhunter.database import SQLiteRepository
from careerhunter.private_site import app


def test_accepts_only_neon_live_as_source(monkeypatch):
    from careerhunter import private_site as site

    def configure(url):
        monkeypatch.setattr(site, "_settings", lambda: ("owner", "hidden", url))

    configure("postgresql+psycopg://owner:secret@some.neon.tech/careerhunter_live")
    source, scratch = recovery._urls()
    assert source.endswith("/careerhunter_live")
    assert scratch.endswith("/careerhunter_restore_probe_20261031")
    assert source != scratch

    for url in ("postgresql+psycopg://owner:secret@render.internal/careerhunter_live",
                "postgresql+psycopg://owner:secret@some.neon.tech/careerhunter",
                "postgresql+psycopg://owner:secret@some.neon.tech/"
                "careerhunter_restore_probe_20261031"):
        configure(url)
        with pytest.raises(ValueError):
            recovery._urls()


def test_recovery_routes_fail_closed_without_signed_identity(tmp_path, monkeypatch):
    path = tmp_path / "fixture.db"
    repository = SQLiteRepository(path)
    repository.engine.dispose()
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", "sqlite:///" + str(path))
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "private-placeholder-for-fixture")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "fixture-" + "1" * 60)
    monkeypatch.setenv("CAREERHUNTER_OIDC_COLLECTOR", "true")
    monkeypatch.delenv("CAREERHUNTER_PG_RESTORE_ENABLED", raising=False)
    monkeypatch.setattr(scan._jwks, "get_signing_key_from_jwt",
                        lambda token: SimpleNamespace(key="fixture"))
    claims = {
        "repository": scan.REPO, "repository_id": scan.REPO_ID,
        "workflow_ref": scan.WORKFLOW, "ref": "refs/heads/main",
        "sub": "repo:" + scan.REPO + ":ref:refs/heads/main",
        "event_name": "workflow_dispatch",
    }
    monkeypatch.setattr(scan.jwt, "decode", lambda *args, **kwargs: dict(claims))
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/internal/pg-restore/tooling").status_code == 401
        headers = {"Authorization": "Bearer header.payload.signature"}
        assert client.get("/internal/pg-restore/tooling", headers=headers).status_code == 403
        claims["workflow_ref"] = recovery.WORKFLOW
        monkeypatch.setattr(recovery.shutil, "which", lambda name: None)
        enabled = client.get("/internal/pg-restore/tooling", headers=headers)
        assert enabled.status_code == 200
        assert enabled.json() == {"installed": False, "enabled": False}
        assert client.post("/internal/pg-restore/start", headers=headers).status_code == 503


def test_postgres_commands_never_pass_credentials_in_argv():
    import inspect
    code = inspect.getsource(recovery._check)
    assert "PGPASSWORD" not in code
    assert '"pg_dump"' in code and '"pg_restore"' in code
    assert "stdout=subprocess.DEVNULL" in code
    assert "stderr=subprocess.DEVNULL" in code


def test_neon_postgres17_requires_matching_real_client_binaries(monkeypatch):
    from types import SimpleNamespace

    class NoPreferredBinary:
        def __init__(self, path):
            self.path = path

        def is_file(self):
            return False

    monkeypatch.setattr(recovery, "Path", NoPreferredBinary)
    monkeypatch.setattr(recovery.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(recovery.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(stdout="pg_dump (PostgreSQL) 17.11"))
    assert recovery._installed() is True

    monkeypatch.setattr(recovery.subprocess, "run", lambda *args, **kwargs:
                        SimpleNamespace(stdout="pg_restore (PostgreSQL) 15.4"))
    assert recovery._installed() is False
