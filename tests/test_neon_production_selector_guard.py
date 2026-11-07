"""No implicit production rollback after the Neon cutover."""
import pytest

from careerhunter.private_site import _settings


def test_render_neon_config_requires_explicit_target(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-test-password-12345")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "local-test-secret-000000000000000")
    monkeypatch.setenv(
        "DASHBOARD_DATABASE_URL",
        "postgresql://reader:fixture@render.internal/careerhunter_ai_db",
    )
    monkeypatch.setenv(
        "CAREERHUNTER_NEON_DATABASE_URL",
        "postgresql://reader:fixture@ep-fixture.eu-central-1.aws.neon.tech/careerhunter_live",
    )
    monkeypatch.delenv("CAREERHUNTER_DB_TARGET", raising=False)

    with pytest.raises(RuntimeError, match="target must be explicit"):
        _settings()

    # A documented rollback must remain possible, but never implicit.
    monkeypatch.setenv("CAREERHUNTER_DB_TARGET", "render")
    assert "render.internal" in _settings()[2]

    monkeypatch.setenv("CAREERHUNTER_DB_TARGET", "neon")
    assert "neon.tech" in _settings()[2]


def test_render_without_neon_configuration_preserves_existing_default(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "local-test-password-12345")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "local-test-secret-000000000000000")
    monkeypatch.setenv(
        "DASHBOARD_DATABASE_URL",
        "postgresql://reader:fixture@render.internal/careerhunter_ai_db",
    )
    monkeypatch.delenv("CAREERHUNTER_NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("CAREERHUNTER_DB_TARGET", raising=False)
    assert "render.internal" in _settings()[2]
