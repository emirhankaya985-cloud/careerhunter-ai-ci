"""The Telegram live smoke test must not resend on a GitHub workflow rerun."""
import sys

from careerhunter import telegram_github


def test_smoke_rerun_skips_without_second_send(monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789:" + "a" * 35)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123456789")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "2")
    monkeypatch.setattr(sys, "argv", ["telegram_github.py", "--test"])

    def unexpected_send(*args, **kwargs):
        raise AssertionError("rerun must not send a second Telegram message")

    monkeypatch.setattr(telegram_github, "send", unexpected_send)

    assert telegram_github.main() == 0
    assert "SKIP: repeat workflow attempt" in capsys.readouterr().out
