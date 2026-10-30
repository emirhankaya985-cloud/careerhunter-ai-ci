"""Telegram failure notice for the scheduled Render dashboard smoke test."""
from __future__ import annotations

import sys

from .telegram_github import send


def main() -> int:
    delivered = send(
        "🚨 <b>CareerHunter AI | Canlı panel sağlık kontrolü başarısız</b>\n"
        "Render uygulaması, PostgreSQL hazır olma kontrolü veya "
        "özel oturum güvenliği doğrulanamadı. GitHub Actions kayıtlarını incele.",
        [{
            "text": "🩺 Dashboard sağlık kontrolü",
            "url": ("https://github.com/emirhankaya985-cloud/"
                    "careerhunter-ai-ci/actions/workflows/site-smoke.yml"),
        }],
    )
    print("PASS: dashboard failure alert accepted" if delivered else
          "FAIL: dashboard failure alert not accepted")
    return 0 if delivered else 1


if __name__ == "__main__":
    sys.exit(main())
