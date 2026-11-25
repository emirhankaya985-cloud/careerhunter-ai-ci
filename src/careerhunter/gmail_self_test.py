"""Manual, owner-only Gmail delivery smoke test using the encrypted CV vault."""
from __future__ import annotations

import json
import os
import sys

from careerhunter.cv_vault import load_cv_attachment
from careerhunter.gmail_send import GmailSendError, send_owner_self_test_once
from careerhunter.telegram_github import send as send_telegram


def main() -> int:
    language = os.getenv("CAREERHUNTER_SELF_TEST_LANGUAGE", "").strip().lower()
    if language not in {"en", "tr"}:
        print(json.dumps({"ok": False, "error": "invalid_language"}))
        return 2
    try:
        attachment, _filename = load_cv_attachment(language)
        database_url = os.getenv("CAREERHUNTER_GMAIL_SEND_DATABASE_URL", "").strip()
        if not database_url:
            raise GmailSendError("mail_database_url_missing")
        message_id = send_owner_self_test_once(language, attachment,
                                               database_url=database_url)
    except GmailSendError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    except Exception:
        print(json.dumps({"ok": False, "error": "cv_vault_unavailable"}))
        return 1

    notification_sent = False
    try:
        notification_sent = send_telegram(
            f"CareerHunter owner Gmail self-test succeeded ({language.upper()}); "
            f"message ID: {message_id}"
        )
    except Exception:
        pass
    print(json.dumps({"ok": True, "language": language,
                      "message_id": message_id,
                      "telegram_notification_sent": notification_sent}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
