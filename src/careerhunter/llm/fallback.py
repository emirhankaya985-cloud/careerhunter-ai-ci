from __future__ import annotations


def draft_message(name: str, company: str, verified_context: str | None) -> dict:
    """Create source-grounded bilingual drafts without an external API.

    This is deliberately conservative: a draft is never a send instruction and
    the caller must present it for human review first.
    """
    if not verified_context:
        return {"draft_a": None, "draft_b": None, "human_review_required": True,
                "reason": "Doğrulanmış bağlam bulunmadı"}
    first = name.split()[0]
    return {
        "draft_a": f"Hi {first}, I came across {verified_context} at {company}. What challenge in this area do early-career engineers most often underestimate?",
        "draft_b": f"Hi {first}, I’m learning more about {verified_context} and noticed your work at {company}. Which skill would you prioritize first for someone building practical experience?",
        "draft_a_tr": f"Merhaba {first}, {company} bünyesindeki {verified_context} çalışmanızı gördüm. Bu alanda kariyerine yeni başlayanların en çok hangi zorluğu gözden kaçırdığını düşünüyorsunuz?",
        "draft_b_tr": f"Merhaba {first}, {company} bünyesinde {verified_context} konusundaki deneyiminizi fark ettim. Uygulamalı deneyim kazanan birinin önce hangi beceriye odaklanmasını önerirsiniz?",
        "human_review_required": True,
        "send_allowed_automatically": False,
        "source_context": verified_context,
    }


def critique_message(draft: str | None, *, verified_context: str | None,
                     source_count: int = 0) -> dict:
    """Return deterministic quality gates for a human reviewer."""
    issues: list[str] = []
    if not draft:
        issues.append("Taslak boş")
    elif len(draft) > 700:
        issues.append("Taslak 700 karakteri aşıyor")
    if not verified_context:
        issues.append("Doğrulanmış bağlam yok")
    if source_count < 1:
        issues.append("Kaynak URL'si eklenmeli")
    if draft and any(token in draft.lower() for token in ("password", "api key", "şifre")):
        issues.append("Hassas bilgi içeriyor olabilir")
    return {"ok": not issues, "issues": issues,
            "human_review_required": True, "send_allowed_automatically": False}

