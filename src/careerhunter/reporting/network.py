from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from careerhunter.models import Contact


def render_network(contacts: list[Contact]) -> str:
    ready = [contact for contact in contacts if contact.status == "draft_ready"]
    needs_research = [contact for contact in contacts if contact.status in {"discovered", "research_needed"}]
    lines = ["# Daily Network Intelligence", "",
             f"_Üretim zamanı: {datetime.now(ZoneInfo('Europe/Istanbul')).isoformat(timespec='minutes')}_", "",
             f"**Kayıtlı kişi:** {len(contacts)}  ", f"**Taslak hazır:** {len(ready)}  ",
             f"**Manuel araştırma gerekli:** {len(needs_research)}", ""]
    if not contacts:
        lines += ["Henüz doğrulanmış kişi yok. LinkedIn üzerinden manuel arama için kişi adı/şirket doğrulandıktan sonra JSON import kullan.", ""]
    for contact in ready[:5]:
        lines += [f"## {contact.name} — {contact.role}, {contact.company}", "",
                  f"- Dayanak: {contact.verified_context}",
                  f"- Kaynaklar: {', '.join(map(str, contact.research_sources)) or 'unknown'}",
                  f"- Kamuya açık e-posta: {contact.email_public or 'yok'}",
                  f"- İletişim engeli: {'evet' if contact.do_not_contact else 'hayır'}",
                  f"- Taslak A: {contact.message_variant_a}",
                  f"- Taslak B: {contact.message_variant_b}",
                  f"- Türkçe A: {contact.message_variant_a_tr or 'unknown'}",
                  f"- Türkçe B: {contact.message_variant_b_tr or 'unknown'}",
                  "- İnsan incelemesi zorunlu; sistem mesaj göndermez.", ""]
    return "\n".join(lines)


def write_network_report(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path
