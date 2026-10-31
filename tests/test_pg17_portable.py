"""PG17 portable toolchain must fail closed before any executable runs."""
import hashlib
from io import BytesIO

import pytest

from careerhunter import pg17_portable as pg


class FakeResponse(BytesIO):
    def geturl(self):
        return pg.BASE + "postgresql-17/client.deb"


def test_sha256_mismatch_never_writes_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "urlopen", lambda request, timeout: FakeResponse(b"test-payload"))
    output = tmp_path / "pkg.deb"
    with pytest.raises(RuntimeError, match="checksum"):
        pg._fetch("postgresql-17/client.deb", "0" * 64, output)
    assert not output.exists()


def test_correct_sha256_only_accepts_official_https(tmp_path, monkeypatch):
    content = b"test-payload"
    monkeypatch.setattr(pg, "urlopen", lambda request, timeout: FakeResponse(content))
    output = tmp_path / "good.deb"
    pg._fetch("postgresql-17/client.deb", hashlib.sha256(content).hexdigest(), output)
    assert output.read_bytes() == content


def test_only_pg_utilities_and_isolated_library_env(tmp_path, monkeypatch):
    monkeypatch.setattr(pg, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        pg.binary_path("bash")
    assert pg.binary_path("pg_dump") is None
    assert pg.command_env({"ANOTHER": "untouched"}) == {"ANOTHER": "untouched"}
    lib = tmp_path / "usr/lib/x86_64-linux-gnu"
    lib.mkdir(parents=True)
    env = pg.command_env({"ANOTHER": "untouched", "LD_LIBRARY_PATH": "/before"})
    assert env["ANOTHER"] == "untouched"
    assert env["LD_LIBRARY_PATH"] == f"{lib}:/before"
