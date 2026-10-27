"""Owner-only Telegram pairing security tests with mocked Bot API."""
import io
import json

from careerhunter import telegram_github as client


TOKEN = "123456789:" + "x" * 35
OWNER = "123456789"


class Response(io.BytesIO):
    status = 200

    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
        return False


def setup(monkeypatch, updates, *, webhook=""):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", OWNER)
    calls = []
    acknowledged = {"offset": None}

    def fake_urlopen(request, timeout=20):
        import urllib.parse
        method = urllib.parse.urlsplit(request.full_url).path.rsplit("/", 1)[-1]
        params = json.loads(request.data)
        calls.append((method, params))
        if method == "getWebhookInfo":
            return Response({"ok": True, "result": {"url": webhook}})
        if method == "getUpdates":
            if params.get("offset") is not None:
                acknowledged["offset"] = params["offset"]
            pending = [entry for entry in updates if acknowledged["offset"] is None
                       or entry["update_id"] >= acknowledged["offset"]]
            return Response({"ok": True, "result": pending})
        if method == "sendMessage":
            return Response({"ok": True, "result": {"message_id": 125}})
        raise AssertionError("Unexpected Bot API method")

    monkeypatch.setattr(client, "urlopen", fake_urlopen)
    return calls


def message(chat_id, sender_id, text, update_id):
    return {
        "update_id": update_id,
        "message": {
            "chat": {"id": chat_id, "type": "private"},
            "from": {"id": sender_id, "is_bot": False},
            "text": text,
        },
    }


def test_owner_start_pairs_once_and_acknowledges(monkeypatch):
    calls = setup(monkeypatch, [
        message(111222333, 111222333, "/start", 17),
        message(123456789, 123456789, "/start careerhunter_verify", 21),
    ])
    assert client.pair_owner_from_start()
    assert [name for name, _ in calls] == [
        "getWebhookInfo", "getUpdates", "sendMessage", "getUpdates"]
    assert calls[-1][1]["offset"] == 22
    assert calls[2][1]["chat_id"] == OWNER
    assert calls[2][1]["protect_content"] is True
    assert not client.pair_owner_from_start()
    assert len([x for x in calls if x[0] == "sendMessage"]) == 1


def test_nonowner_start_or_mismatched_sender_cannot_pair(monkeypatch):
    calls = setup(monkeypatch, [
        message(123456789, 111111111, "/start", 12),
        message(111111111, 111111111, "/start", 13),
    ])
    assert not client.pair_owner_from_start()
    assert not any(name == "sendMessage" for name, _ in calls)


def test_webhook_is_not_overwritten_or_polled(monkeypatch):
    calls = setup(monkeypatch, [message(123456789, 123456789, "/start", 99)],
                  webhook="https://bot.example.com/webhook")
    assert not client.pair_owner_from_start()
    assert [name for name, _ in calls] == ["getWebhookInfo"]


def test_normal_chat_message_does_not_initiate_unsolicited_notification(monkeypatch):
    calls = setup(monkeypatch, [message(123456789, 123456789, "hello", 47)])
    assert not client.pair_owner_from_start()
    assert not any(name == "sendMessage" for name, _ in calls)


def test_pair_secret_is_required(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert not client.pair_owner_from_start()



def test_cli_pairing_is_not_falsely_green(monkeypatch):
    monkeypatch.setattr(client, "configured", lambda: True)
    monkeypatch.setattr(client, "pair_owner_from_start", lambda: False)
    monkeypatch.setattr(client.sys, "argv", ["careerhunter", "--pair"])
    assert client.main() == 1
    monkeypatch.setattr(client, "pair_owner_from_start", lambda: True)
    assert client.main() == 0


def test_cli_requires_credentials_for_all_modes(monkeypatch):
    monkeypatch.setattr(client, "configured", lambda: False)
    for mode in ("--pair", "--diagnose", "--digest", "--test"):
        monkeypatch.setattr(client.sys, "argv", ["careerhunter", mode])
        assert client.main() == 1


def test_diagnosis_requires_exact_private_chat(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", OWNER)
    from urllib.parse import urlsplit

    def run(type_, chat_id):
        def fake_urlopen(request, timeout=16):
            method = urlsplit(request.full_url).path.rsplit("/", 1)[-1]
            if method == "getMe":
                return Response({"ok": True, "result": {"username": "careerhunter_test"}})
            if method == "getChat":
                return Response({"ok": True, "result": {
                    "type": type_, "id": chat_id,
                }})
            raise AssertionError("Unexpected Telegram API call: " + method)

        monkeypatch.setattr(client, "urlopen", fake_urlopen)
        return client.diagnose_connection()

    assert run("private", int(OWNER))
    assert not run("group", int(OWNER))
    assert not run("private", int(OWNER) + 1)


def test_health_workflow_schedules_diagnosis_not_repeated_pairing():
    from pathlib import Path
    source = (Path(__file__).parents[1] /
              ".github/workflows/telegram-pairing.yml").read_text()
    assert "cron: '9 7 * * *'" in source
    assert "CHECK_MODE: ${{ inputs.mode || 'diagnose' }}" in source
    assert "--diagnose" in source
    assert "--pair" in source
    assert "if: github.event_name == 'push'" in source
