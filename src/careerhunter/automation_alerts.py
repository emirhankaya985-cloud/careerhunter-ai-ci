"""Clear, minimal Telegram alerts for failed automatic audit workflows."""
from __future__ import annotations

import sys

from .telegram_github import send

TEMPLATES = {
    "weekly": (
        "⚠️ <b>CareerHunter AI | Haftalık rapor başarısız</b>\n"
        "GitHub'daki haftalık otomasyon ve Telegram gönderim kayıtlarını kontrol et.",
        "weekly-production-report.yml",
    ),
    "personalize": (
        "⚠️ <b>CareerHunter AI | Kişisel ilan puanlama yenilemesi başarısız</b>\n"
        "Ücretsiz kural tabanlı geçmiş ilan puanlama görevini GitHub kayıtlarından incele.",
        "personalize.yml",
    ),
    "country": (
        "⚠️ <b>CareerHunter AI | Dört ülke kaynak denetimi başarısız</b>\n"
        "ABD, Birleşik Krallık, Avustralya veya Türkiye için kaynak doğrulaması "
        "tamamlanamadı. GitHub kayıtlarını kontrol et.",
        "e2e-verification.yml",
    ),
}


def alert(kind: str) -> bool:
    message, file = TEMPLATES[kind]
    return send(message, [{
        "text": "🔍 GitHub kontrol kayıtları",
        "url": ("https://github.com/emirhankaya985-cloud/careerhunter-ai-ci/"
                "actions/workflows/" + file),
    }])


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in TEMPLATES:
        print("FAIL: invalid alert type")
        return 2
    accepted = alert(sys.argv[1])
    print("PASS: alert accepted" if accepted else "FAIL: alert not accepted")
    return 0 if accepted else 1


if __name__ == "__main__":
    sys.exit(main())
