"""Production CRM/CV writes must use the selected live Neon database."""
import pytest
from fastapi import HTTPException

from careerhunter.application_actions import _writer_url
from careerhunter import cv_vault


def _configure(monkeypatch, writer_url, neon_url):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("CAREERHUNTER_DB_TARGET", "neon")
    monkeypatch.setenv("CAREERHUNTER_CRM_DATABASE_URL", writer_url)
    monkeypatch.setenv("CAREERHUNTER_NEON_DATABASE_URL", neon_url)


def test_writer_accepts_same_neon_project_pooler_and_live_database(monkeypatch):
    _configure(
        monkeypatch,
        "postgresql://crm_writer:secret@ep-live-pooler.eu-central-1.aws.neon.tech/careerhunter_live",
        "postgresql://dashboard_reader:secret@ep-live.eu-central-1.aws.neon.tech/careerhunter_live",
    )

    assert _writer_url().startswith("postgresql+psycopg://crm_writer:")


@pytest.mark.parametrize("writer_url", [
    "postgresql://crm_writer:secret@render.internal/careerhunter_ai_db",
    "postgresql://crm_writer:secret@ep-other.eu-central-1.aws.neon.tech/careerhunter_live",
    "postgresql://crm_writer:secret@ep-live.eu-central-1.aws.neon.tech/other_db",
])
def test_writer_rejects_wrong_production_database_without_leaking_url(
        monkeypatch, writer_url):
    _configure(
        monkeypatch,
        writer_url,
        "postgresql://reader:secret@ep-live.eu-central-1.aws.neon.tech/careerhunter_live",
    )

    with pytest.raises(HTTPException) as error:
        _writer_url()

    assert error.value.status_code == 503
    assert "secret" not in error.value.detail
    assert "ep-" not in error.value.detail


def test_writer_fails_closed_when_selected_target_is_missing(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("CAREERHUNTER_DB_TARGET", raising=False)
    monkeypatch.setenv(
        "CAREERHUNTER_CRM_DATABASE_URL",
        "postgresql://writer:secret@ep-live.eu-central-1.aws.neon.tech/careerhunter_live",
    )
    monkeypatch.setenv(
        "CAREERHUNTER_NEON_DATABASE_URL",
        "postgresql://reader:secret@ep-live.eu-central-1.aws.neon.tech/careerhunter_live",
    )

    with pytest.raises(HTTPException) as error:
        _writer_url()

    assert error.value.status_code == 503
    assert "secret" not in error.value.detail


def test_oidc_preflight_reports_safe_target_facts_without_upload(monkeypatch):
    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execute(self, statement):
            assert str(statement) == "SELECT 1"

    class Engine:
        def connect(self):
            return Connection()

        def dispose(self):
            pass

    class Inspector:
        def has_table(self, name):
            assert name == "careerhunter_cv_vault"
            return True

    monkeypatch.setattr(
        "careerhunter.scheduled_scan._require_github_oidc", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("careerhunter.application_actions._writer_url", lambda: (
        "postgresql+psycopg://writer:private@ep-live.eu-central-1.aws.neon.tech/"
        "careerhunter_live"
    ))
    monkeypatch.setattr(cv_vault, "_key", lambda: b"x" * 32)
    monkeypatch.setattr(cv_vault, "create_engine", lambda *args, **kwargs: Engine())
    monkeypatch.setattr(cv_vault, "inspect", lambda connection: Inspector())

    result = cv_vault.cv_vault_preflight(object())

    assert result == {
        "status": "ready",
        "writer_database": "careerhunter_live",
        "writer_matches_selected_neon": True,
        "writer_reachable": True,
        "vault_table_exists": True,
        "encryption_key_configured": True,
        "cv_upload_performed": False,
    }
    assert "private" not in str(result)
    assert "ep-live" not in str(result)
