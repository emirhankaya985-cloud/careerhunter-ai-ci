"""Positive Telegram server receipt without leaking chat or token."""
import io
import json

import pytest

from careerhunter import telegram_github as tg


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@pytest.mark.parametrize(("message_id", "expected"), [
    (125, True), (0, False), (-7, False), (True, False), ("125", False),
])
def test_positive_receipt_only(monkeypatch, capsys, message_id, expected):
    token = "123456789:" + "a" * 35
    chat = "123456789"
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", chat)

    def fake_api(request, timeout):
        body = json.loads(request.data)
        assert body["chat_id"] == chat
        assert body["protect_content"] is True
        assert timeout == 22
        return Response(json.dumps({"ok": True, "result": {"message_id": message_id}}).encode())

    monkeypatch.setattr(tg, "urlopen", fake_api)
    assert tg.send("Safe notification") is expected
    output = capsys.readouterr().out
    assert ("message_id=125" in output) is (message_id == 125 and type(message_id) is int)
    assert token not in output
    assert chat not in output
