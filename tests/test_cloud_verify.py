from pathlib import Path

from careerhunter.cloud_verify import verify


def test_cloud_verification_is_idempotent(tmp_path: Path):
    first = verify(tmp_path / "verify.db")
    second = verify(tmp_path / "verify.db")
    assert first[2] == 1
    assert second[2] == 0
    assert second[1] == first[1]
