from __future__ import annotations

from careerhunter.llm.fallback import draft_message
from careerhunter.models import Contact


def prepare_drafts(contact: Contact) -> Contact:
    """No source-backed context means no message: manual research remains required."""
    if contact.do_not_contact:
        contact.message_variant_a = None
        contact.message_variant_b = None
        return contact
    if contact.research_confidence not in {"medium", "high"} or not contact.verified_context:
        return contact
    draft = draft_message(contact.name, contact.company, contact.verified_context)
    contact.message_variant_a = draft["draft_a"]
    contact.message_variant_b = draft["draft_b"]
    contact.message_variant_a_tr = draft.get("draft_a_tr")
    contact.message_variant_b_tr = draft.get("draft_b_tr")
    contact.status = "draft_ready"
    return contact
