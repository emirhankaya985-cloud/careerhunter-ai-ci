"""Reversible, fail-closed Neon cutover settings (no network or secrets)."""
import pytest

from careerhunter.private_site import _settings


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("DASHBOARD_PASSWORD", "only-local-test-password-123456")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "only-local-test-secret-000000000000000")
    monkeypatch.setenv(
        "DASHBOARD_DATABASE_URL",
        "postgresql://render_reader:placeholder@render.internal/careerhunter_ai_db",
    )
    monkeypatch.delenv("CAREERHUNTER_NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("CAREERHUNTER_DB_TARGET", raising=False)
    return monkeypatch


def test_defaults_to_existing_render_database(configured):
    assert "render.internal" in _settings()[2]
    assert "psycopg" in _settings()[2]


def test_neon_opt_in_uses_dedicated_database_without_mutating_rollback(configured):
    configured.setenv(
        "CAREERHUNTER_NEON_DATABASE_URL",
        "postgresql://neon_owner:placeholder@ep-example.eu-central-1.aws.neon.tech/careerhunter_live?sslmode=require",
    )
    configured.setenv("CAREERHUNTER_DB_TARGET", "neon")
    assert "neon.tech" in _settings()[2]
    assert _settings()[2].startswith("postgresql+psycopg://")
    assert "render.internal" in __import__("os").environ["DASHBOARD_DATABASE_URL"]
    configured.setenv("CAREERHUNTER_DB_TARGET", "render")
    assert "render.internal" in _settings()[2]


@pytest.mark.parametrize("invalid", [
    "",
    "garbage",
    "sqlite:///tmp/other.db",
    "postgresql://admin:p@wrong.example.com/careerhunter_live",
    "postgresql://admin:p@ep-example.neon.tech/postgres",
    "postgresql://admin:p@notneon.tech/careerhunter_live",
])
def test_bad_neon_configuration_blocks_cutover(configured, invalid):
    configured.setenv("CAREERHUNTER_DB_TARGET", "neon")
    configured.setenv("CAREERHUNTER_NEON_DATABASE_URL", invalid)
    with pytest.raises(RuntimeError, match="verified dedicated target"):
        _settings()


def test_unknown_target_never_falls_back_silently(configured):
    configured.setenv("CAREERHUNTER_DB_TARGET", "some-other-database")
    with pytest.raises(RuntimeError, match="Unknown CareerHunter database target"):
        _settings()


def test_neon_credential_alone_cannot_switch_production(configured):
    configured.setenv("CAREERHUNTER_NEON_DATABASE_URL",
                      "postgresql://n:p@ep-a.neon.tech/careerhunter_live")
    assert "render.internal" in _settings()[2]
