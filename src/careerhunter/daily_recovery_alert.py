"""Minimal Telegram alert if the independent daily recovery guard itself fails."""
from __future__ import annotations

import sys

from .telegram_github import send


def main() -> int:
    delivered = send(
        "⚠️ <b>CareerHunter AI | Otomatik kurtarma kontrolü başarısız</b>\n"
        "Günlük tarama kurtarma görevi çalışmadı. "
        "GitHub Actions içindeki Daily Recovery Guard kayıtlarını kontrol et.",
        [{
            "text": "🛠️ Kurtarma görevleri",
            "url": ("https://github.com/emirhankaya985-cloud/"
                    "careerhunter-ai-ci/actions/workflows/daily-recovery.yml"),
        }],
    )
    print("PASS: recovery guard failure alert accepted" if delivered else
          "FAIL: recovery guard failure alert not accepted")
    return 0 if delivered else 1


if __name__ == "__main__":
    sys.exit(main())
