from careerhunter.cli import main


def test_doctor(monkeypatch, tmp_path):
    monkeypatch.setenv("CAREERHUNTER_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("LLM_PROVIDER", "rules")
    assert main(["doctor"]) == 0

