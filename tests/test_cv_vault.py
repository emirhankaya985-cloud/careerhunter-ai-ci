"""CV vault is owner-only, encrypted at rest and integrity-checked."""
import base64
from sqlalchemy import select
from fastapi.testclient import TestClient

from careerhunter.cv_vault import vault
from careerhunter.database import SQLiteRepository
from careerhunter.private_site import app, _get_engine, failed_logins


def test_cv_vault_upload_read_delete_is_private_and_encrypted(tmp_path, monkeypatch):
    dbfile = tmp_path / "owner.sqlite"
    repo = SQLiteRepository(dbfile)
    repo.engine.dispose()
    db_url = "sqlite:///" + str(dbfile)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-owner-passphrase-123456")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "fake-session-secret-123456789012345")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", db_url)
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIE", "true")
    monkeypatch.setenv("CAREERHUNTER_CRM_DATABASE_URL", db_url)
    monkeypatch.setenv("CAREERHUNTER_CRM_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_CV_VAULT_KEY",
                       base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("="))
    _get_engine.cache_clear()
    failed_logins.clear()
    try:
        with TestClient(app, base_url="https://testserver") as client:
            assert client.get("/internal/owner/cv/status").status_code == 401
            assert client.post("/login", data={
                "password": "test-owner-passphrase-123456"
            }).status_code == 200
            csrf = client.get("/internal/owner/cv/csrf").json()["csrf_token"]
            headers = {"origin": "https://testserver", "x-csrf-token": csrf,
                       "content-type": "application/pdf"}
            pdf = b"%PDF-1.4\nprivate cv fixture\n%%EOF"
            upload = client.put("/internal/owner/cv/en", content=pdf, headers=headers)
            assert upload.status_code == 200
            assert upload.json()["encrypted_at_rest"] is True
            assert client.get("/internal/owner/cv/status").json()["cvs"]["en"]["uploaded"]

            repo = SQLiteRepository(dbfile)
            with repo.engine.connect() as conn:
                row = conn.execute(select(vault)).mappings().one()
            assert pdf not in row["ciphertext"]

            downloaded = client.get("/internal/owner/cv/en")
            assert downloaded.status_code == 200
            assert downloaded.content == pdf
            assert downloaded.headers["cache-control"] == "no-store, private"

            deleted = client.delete("/internal/owner/cv/en", headers={
                "origin": "https://testserver", "x-csrf-token": csrf,
            })
            assert deleted.status_code == 200
            assert not client.get("/internal/owner/cv/status").json()["cvs"]["en"]["uploaded"]
    finally:
        _get_engine.cache_clear()


def test_cv_upload_rejects_invalid_pdf_and_bad_csrf(tmp_path, monkeypatch):
    dbfile = tmp_path / "owner.sqlite"
    db_url = "sqlite:///" + str(dbfile)
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-owner-passphrase-123456")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "fake-session-secret-123456789012345")
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", db_url)
    monkeypatch.setenv("DASHBOARD_ALLOW_SQLITE_TEST", "true")
    monkeypatch.setenv("DASHBOARD_SECURE_COOKIE", "true")
    monkeypatch.setenv("CAREERHUNTER_CRM_DATABASE_URL", db_url)
    monkeypatch.setenv("CAREERHUNTER_CRM_SQLITE_TEST", "true")
    monkeypatch.setenv("CAREERHUNTER_CV_VAULT_KEY",
                       base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("="))
    _get_engine.cache_clear()
    try:
        with TestClient(app, base_url="https://testserver") as client:
            client.post("/login", data={"password": "test-owner-passphrase-123456"})
            headers = {"origin": "https://testserver", "x-csrf-token": "bad",
                       "content-type": "application/pdf"}
            assert client.put("/internal/owner/cv/en", content=b"%PDF-1.4\n%%EOF",
                              headers=headers).status_code == 403
            csrf = client.get("/internal/owner/cv/csrf").json()["csrf_token"]
            headers["x-csrf-token"] = csrf
            assert client.put("/internal/owner/cv/en", content=b"not a pdf",
                              headers=headers).status_code == 422
    finally:
        _get_engine.cache_clear()
